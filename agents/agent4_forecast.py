"""
Agent 4 - Forecast & Redistribution.

Runs independently of the per-patient pipeline (call it on a timer/cron in
production). Uses the seeded 30-day consumption history in `data_store` to
compute a real days-of-cover forecast per facility per medicine, rather than
comparing stock to a hardcoded number.

The forecast is arithmetic (mean daily draw -> days of cover), NOT a model
call. A time series is exactly the kind of thing an LLM is bad at and a
`DataFrame` is good at. The model has no business being asked how many days of
platelet stock remain.

Two corrections over the previous version:
  * It no longer reports "0 ICU beds" as a shortage at a PHC. A PHC having no
    ICU is correct by design (IPHS), so flagging it meant one facility
    alarmed permanently - an alert that can never clear trains people to
    ignore alerts. A facility that HAS ICU capacity and is full still alarms.
  * `redistribute` will not drain a donor below its own reorder point plus a
    buffer, so a transfer cannot re-trigger the alert it was raised to clear.

CONNECT LATER: replace the mean-draw estimate with a proper time-series model
once you have real consumption data. The output shape stays the same, so the
frontend does not change.
"""

import pandas as pd

from data_store import (
    hospitals, by_id, stock_of, give_back, take,
    medicines_catalog, consumption_history,
)

# Days of cover below which we call a facility critical. A reorder threshold is
# a stock level; this is a rate-of-burn measure, and the two answer different
# questions - a facility can be above threshold and still one bad weekend from
# running out.
CRITICAL_DAYS = 3.0
WARN_DAYS = 7.0
TRANSFER_BUFFER_DAYS = 3.0  # donor keeps this much cover after donating


def _history_frame() -> pd.DataFrame:
    """Long-format frame: one row per (hospital, medicine, day)."""
    rows = []
    for h in hospitals:
        per_med = consumption_history.get(h["id"], {})
        for med, series in per_med.items():
            for day, units in enumerate(series):
                rows.append({
                    "hospital_id": h["id"],
                    "medicine": med,
                    "day": day,
                    "units": units,
                })
    return pd.DataFrame(rows)


def _daily_draw() -> pd.DataFrame:
    """Mean and 7-day-trend daily draw per facility per medicine."""
    df = _history_frame()
    if df.empty:
        return pd.DataFrame(columns=["hospital_id", "medicine", "mean_daily",
                                    "recent_daily", "trend"])
    agg = df.groupby(["hospital_id", "medicine"])["units"].agg(["mean", "std"])
    recent = (df[df["day"] >= 23]
              .groupby(["hospital_id", "medicine"])["units"].mean()
              .rename("recent"))
    # Trend = recent week vs the 7 days before it. Positive means accelerating
    # draw, which matters more than the raw mean during an outbreak.
    prior = (df[(df["day"] >= 16) & (df["day"] < 23)]
             .groupby(["hospital_id", "medicine"])["units"].mean()
             .rename("prior"))
    out = agg.join(recent).join(prior)
    out["trend"] = out["recent"] - out["prior"]
    return out.rename(columns={"mean": "mean_daily"})[
        ["mean_daily", "recent", "trend"]].reset_index()


def _coverage(stock: int, mean_daily: float, recent_daily: float, trend: float) -> float:
    """Days of cover, using the higher of the long-run and recent draw rate.

    During an outbreak the recent week is the honest number; in steady state the
    long-run mean is less noisy. Taking the max is the conservative choice, and
    for a stock-out forecast conservative is the correct bias.
    """
    rate = max(mean_daily, recent_daily, 0.01)
    if trend > 0:
        rate = max(rate, recent_daily + trend)  # keep climbing to today's burn
    return stock / rate


def check_shortages():
    draw = _daily_draw()
    lookup = {}
    if not draw.empty:
        lookup = draw.set_index(["hospital_id", "medicine"]).to_dict("index")

    alerts = []
    for h in hospitals:
        factors = []
        # ICU: only a shortage if the facility HAS ICU capacity and it is full.
        # A PHC with icu_total == 0 is correctly equipped, not short of anything.
        if h["icu_total"] > 0 and h["icu"] == 0:
            factors.append({
                "kind": "icu",
                "critical": True,
                "message": f"all {h['icu_total']} ICU bed(s) occupied; no critical-care capacity",
            })

        for med, meta in medicines_catalog.items():
            stock = stock_of(h, med)
            stats = lookup.get((h["id"], med))
            if not stats:
                continue
            days = _coverage(stock, stats["mean_daily"], stats["recent"], stats["trend"])
            if days >= WARN_DAYS and stock >= meta["reorder_threshold"]:
                continue
            critical = days < CRITICAL_DAYS
            direction = "rising" if stats["trend"] > 0.05 else "steady"
            factors.append({
                "kind": "stock",
                "medicine": med,
                "medicine_name": meta["name"],
                "critical": critical,
                "days_of_cover": round(days, 1),
                "daily_draw": round(max(stats["mean_daily"], stats["recent"]), 1),
                "direction": direction,
                "message": (
                    f'{meta["name"]}: {stock} units left, '
                    f'{max(stats["mean_daily"], stats["recent"]):.1f}/day {direction} draw '
                    f'-> {days:.0f} day(s) of cover'
                ),
            })

        if not factors:
            continue

        donor = _find_donor(h, factors, lookup)
        alerts.append({
            "hospital_id": h["id"],
            "hospital": h["name"],
            "critical": any(f["critical"] for f in factors),
            "reasons": factors,
            "message": f'{h["name"]}: ' + " and ".join(f["message"] for f in factors),
            "donor_id": donor["id"] if donor else None,
            "donor": donor["name"] if donor else None,
            "transfer": (
                {"medicine": wanted_med, "amount": suggested}
                if donor and (wanted_med := _primary_shortage(factors))
                and (suggested := _suggested_amount(h, wanted_med, donor, lookup))
                else None
            ),
        })

    return alerts


def _primary_shortage(factors: list) -> str | None:
    stock_factors = [f for f in factors if f["kind"] == "stock"]
    if not stock_factors:
        return None
    worst = min(stock_factors, key=lambda f: f.get("days_of_cover", 999))
    return worst["medicine"]


def _suggested_amount(short: dict, medicine: str, donor: dict, lookup: dict) -> int:
    """How much the donor can safely give - the receiver's gap, capped by the
    donor's true surplus."""
    stats = lookup.get((donor["id"], medicine))
    if not stats:
        return 0
    surplus = max(0.0, stock_of(donor, medicine) - _min_keep(medicine, stats))
    threshold = medicines_catalog[medicine]["reorder_threshold"]
    gap = max(0.0, (threshold * 3) - stock_of(short, medicine))
    return int(min(surplus, gap))


def _min_keep(medicine: str, stats) -> float:
    """Lowest stock a donor may give down to: its reorder point, or whatever
    keeps TRANSFER_BUFFER_DAYS of cover at the current burn rate."""
    return max(
        medicines_catalog[medicine]["reorder_threshold"],
        _coverage(0, stats["mean_daily"], stats["recent"], stats["trend"]) * TRANSFER_BUFFER_DAYS,
    )


def _find_donor(short: dict, factors: list, lookup: dict) -> dict | None:
    """Best facility that could cover this shortage without harming itself."""
    wanted = [f["medicine"] for f in factors if f["kind"] == "stock"]
    best, best_surplus = None, 0.0

    for cand in hospitals:
        if cand["id"] == short["id"]:
            continue
        total_surplus = 0.0
        for med in wanted:
            stats = lookup.get((cand["id"], med))
            if not stats:
                continue
            total_surplus += max(0.0, stock_of(cand, med) - _min_keep(med, stats))
        if total_surplus > best_surplus:
            best, best_surplus = cand, total_surplus

    return best if best_surplus > 0 else None


def redistribute(donor_id: str, receiver_id: str, medicine: str = "platelet_concentrate",
                 amount: int = 5) -> int:
    """Move stock between facilities, never draining the donor.

    Returns units actually moved (0 if the donor has no surplus to give).
    Raises KeyError for unknown ids/medicines and ValueError for donor==receiver
    so the API can turn them into 404/400 instead of a bare 500.
    """
    if medicine not in medicines_catalog:
        raise KeyError(f"Unknown medicine: {medicine}")
    donor = by_id(donor_id)
    if donor is None:
        raise KeyError(f"Unknown donor: {donor_id}")
    receiver = by_id(receiver_id)
    if receiver is None:
        raise KeyError(f"Unknown receiver: {receiver_id}")
    if donor["id"] == receiver["id"]:
        raise ValueError("donor_id and receiver_id must differ")
    if amount <= 0:
        raise ValueError("amount must be positive")

    stats = _daily_draw().set_index(["hospital_id", "medicine"])
    row = stats.loc[(donor["id"], medicine)]
    surplus = stock_of(donor, medicine) - _min_keep(medicine, row)

    moved = int(max(0, min(amount, surplus)))
    if moved <= 0:
        return 0
    take(donor, medicine, moved)
    give_back(receiver, medicine, moved)
    return moved


def forecast_table() -> list:
    """Flattened coverage for the UI, one row per facility x medicine."""
    draw = _daily_draw()
    if draw.empty:
        return []
    rows = []
    for _, r in draw.iterrows():
        h = by_id(r["hospital_id"])
        meta = medicines_catalog[r["medicine"]]
        stock = stock_of(h, r["medicine"])
        rows.append({
            "hospital_id": h["id"],
            "hospital": h["name"],
            "medicine": r["medicine"],
            "medicine_name": meta["name"],
            "stock": stock,
            "reorder_threshold": meta["reorder_threshold"],
            "mean_daily": round(r["mean_daily"], 2),
            "recent_daily": round(r["recent"], 2),
            "days_of_cover": round(_coverage(stock, r["mean_daily"], r["recent"], r["trend"]), 1),
        })
    return sorted(rows, key=lambda r: r["days_of_cover"])
