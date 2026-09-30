"""
Eval harness for Agent 1.

Measures the LLM triage path against ground truth and, critically, against a
naive keyword baseline. Without the baseline you cannot show the model is doing
anything a `if "shock" in text` would not - the baseline is what makes the LLM
number mean something.

Reports:
  * severity accuracy, overall and per noise level (clean vs OCR-degraded)
  * a confusion matrix, because "never says Red" would also score well on a
    Green-heavy set and that is a dangerous failure for a triage tool
  * safety misses: Red cases downgraded to Yellow/Green are counted separately
    and weighted, since under-triage is the error that kills
  * specialist agreement
  * routing accuracy, by driving the real Agent 2 and Agent 3 rather than
    scoring Agent 1's opinion of where the case should go
  * how many cases were held for a clinician instead of auto-dispositioned
  * latency and token usage, with a cost estimate

Run:  python -m eval.run_eval [--limit N] [--out results.json]

Requires GOOGLE_API_KEY. It makes one API call per report, so run it with
--limit while iterating.

RATE LIMITS - read this before running the full set.
On the free tier a project gets ~20 generate_content calls per day PER MODEL.
The full 78-report set therefore cannot be run more than once a day on a free
key, and will return 429 RESOURCE_EXHAUSTED part-way through on the second run.
Options:
  * --limit 20 (a representative slice) while iterating
  * bill the project, which raises the ceiling substantially
  * rely on LLM_FALLBACK_MODELS: quota is counted per model, so when one model
    reports 429 the retry loop rotates to the next and keeps going
Anything measured under a partial run is still reported honestly - the harness
records how many reports it actually attempted, and a run cut short by a rate
limit is marked as such rather than quietly scored on the reports it got.
"""

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict

import llm
from agents import agent1_triage, agent2_allocator, agent3_routing
from data_store import hospitals, resolve_specialty

DATASET = os.path.join(os.path.dirname(__file__), "lab_reports.json")

SEVERITIES = ["Green", "Yellow", "Red"]
# Under-triage costs far more than over-triage in a rural referral pathway.
SEVERITY_PENALTY = {"Green": 0, "Yellow": 1, "Red": 2}

# Approximate Gemini per-1M-token rates. Override with LLM_IN_COST /
# LLM_OUT_COST (USD) if the model or pricing changes - do not trust these to be
# current.
COST_IN_PER_M = float(os.getenv("LLM_IN_COST", "0.30"))
COST_OUT_PER_M = float(os.getenv("LLM_OUT_COST", "2.50"))


# --------------------------------------------------------------------------
# Baseline: what a competent engineer writes first, before reaching for a model.
# Deliberately keyword/regex based, exactly as an early prototype would be.
# --------------------------------------------------------------------------
BASELINE_RULES = [
    # NOTE: this rule set is blind to negation. "Not in shock" matches the
    # `shock` keyword below and is scored Red, which is exactly the failure
    # mode that motivates a model here. The one concession is a word boundary
    # on "ccu" - without it the substring matches inside "occult" and the
    # baseline is just buggy rather than merely naive.
    ("Red",  r"\bshock|septic|haemorrhagic|hemorrhagic|STEMI|ST elevation|"
            r"infarct|unconscious|unresponsive|resuscitat|cardiogenic|"
            r"grunting|convulsion|flow-sheet|\bGCS\s*(?:[0-9]|1[0-2])\b"),
    ("Red",  r"platelets?\D{0,12}(?:9,?\d{3}|1[0-9],?\d{3}|[1-9]\d{3})(?!\d)|"
            r"platelets?\D{0,8}critically low"),
    ("Red",  r"\bHb\D{0,6}[0-6](?:\.\d)?\s*(?:g|d?l)"),
    ("Red",  r"\b(?:platelet_concentrate|ICU|CCU)\b"),
    ("Yellow", r"admit for observation|pneumonia|consolidation|dehydrat|"
               r"loose motions|vomit|weakness|giddiness|anaemia|anemia|"
               r"orch|:\s*POSITIVE|isolation|ward"),
    ("Green", r"stable|discharged|oral|outpatient|viral|no admission"),
]


def baseline_triage(text: str) -> str:
    low = text.lower()
    for severity, pattern in BASELINE_RULES:
        if re.search(pattern, low, re.IGNORECASE):
            return severity
    return "Yellow"  # unknown -> never auto-clear


# --------------------------------------------------------------------------
def _cost(tokens: dict) -> float:
    if not tokens:
        return 0.0
    p = (tokens.get("prompt") or 0) / 1e6 * COST_IN_PER_M
    c = (tokens.get("completion") or 0) / 1e6 * COST_OUT_PER_M
    return p + c


# --------------------------------------------------------------------------
# Routing check.
#
# §18 asks for correct / wrong routing, which cannot be measured by looking at
# Agent 1's output alone - severity accuracy says nothing about whether the case
# reached a doctor who could take it. So this drives the real Agent 2 and Agent 3
# with the model's triage and scores where it lands.
#
# Ground truth is the dataset's `expected_specialist`: a case that needs a
# haematologist has not been routed correctly if it ends up with a general duty
# doctor. "none" means no specialty-specific review is needed, so a general
# doctor is the right destination and any specialty is not a routing error.
#
# Agent 3 increments doctor load as a side effect of assigning, so loads are
# snapshotted and restored around the call. Without that, report 1's assignment
# would make report 2 look like a capacity failure and the numbers would drift
# with position in the run.
# --------------------------------------------------------------------------
def _score_routing(result, need: dict) -> dict:
    """Run the deterministic agents on one triage and judge the destination."""
    loads = {d["name"]: d["load"] for h in hospitals for d in h["doctors"]}
    try:
        eligible, _ = agent2_allocator.run(need)
        hospital, doctor, _step, _ = agent3_routing.run(eligible, need)
    finally:
        for h in hospitals:
            for d in h["doctors"]:
                d["load"] = loads[d["name"]]
        agent3_routing._reservations.clear()

    expected = resolve_specialty(need.get("_expected_specialist"))
    if doctor is None:
        # Nobody to take it. Not the model's mistake - the network was out of
        # capacity - so it is reported apart from a wrong destination.
        return {"outcome": "unassigned", "expected": expected,
                "routed_to": None, "correct": None}
    routed = resolve_specialty(doctor["specialty"])
    if expected == "general_medicine":
        correct = True          # any general duty doctor is a correct landing
    else:
        correct = routed == expected
    return {
        "outcome": "routed" if correct else "misrouted",
        "expected": expected,
        "routed_to": routed,
        "facility": hospital["name"] if hospital else None,
        "correct": correct,
    }


def _need_from(result) -> dict:
    """The subset of Agent 1's `need` that the deterministic agents read.

    Built here rather than by calling agent1 so the eval scores the model's own
    output. Running agent1 would re-apply its confidence floor and its
    fallback, and the harness would then be measuring the safety net it is
    supposed to be measuring the model against.
    """
    meds = result.medicine_map()
    if result.platelets_needed:
        meds["platelet_concentrate"] = max(
            meds.get("platelet_concentrate", 0), result.platelets_needed)
    return {
        "icu": result.icu_needed,
        "platelets": result.platelets_needed,
        "specialist": None if result.specialist == "none" else result.specialist,
        "medicines": {k: v for k, v in meds.items() if v > 0},
    }


def evaluate(reports: list, limit: int | None = None) -> dict:
    if limit:
        reports = reports[:limit]

    rows = []
    conf = defaultdict(Counter)
    by_noise = defaultdict(lambda: {"n": 0, "correct": 0})
    by_tpl = defaultdict(lambda: {"n": 0, "correct": 0})
    latencies, costs, tokens = [], [], Counter()
    llm_hits, base_hits = 0, 0
    # Queue-recommendation agreement. These are advisory only - no action is ever
    # taken on them without a doctor - but if the model cannot even *suggest*
    # sensibly, the recommendation shown beside every case is noise, and the
    # whole "AI recommends, doctor decides" framing collapses into a demo.
    visit_hits = esc_hits = 0
    # The dangerous direction: the model says a case does not need an in-person
    # review, and it does. Counted apart from plain inaccuracy because this is
    # the recommendation that could keep a sick patient at home.
    visit_misses = []
    # §18's remaining metrics. Routing is scored by driving the real Agents 2-3;
    # manual review is whatever the production confidence floor would flag.
    routing = Counter()
    misrouted_ids = []
    manual_review = 0

    print(f"{'id':<8}{'triage':<7}{'expected':<9}{'noise':<7}{'ok':<4}{'ms':<7}note")
    print("-" * 78)

    # A run stopped by quota is not a run that scored badly, and the two must
    # never look alike in the output. Attributed separately from the start.
    throttled = []

    for r in reports:
        started = time.perf_counter()
        result = llm.triage_report(r["report_text"])
        elapsed = (time.perf_counter() - started) * 1000

        if result is None:
            reason = (llm.trace()[0].get("reason", "") if llm.trace() else "")
            if "429" in reason or "RESOURCE_EXHAUSTED" in reason or "quota" in reason:
                throttled.append(r["id"])

        expected = r["expected_severity"]
        predicted = result.severity if result else None
        base = baseline_triage(r["report_text"])

        # Treat "model unavailable" as a miss, never as a pass.
        hit = predicted == expected
        base_hit = base == expected
        llm_hits += hit
        base_hits += base_hit

        # Ground truth for the visit recommendation, derived from severity so the
        # dataset does not need a hand-labelled field for every report. Red
        # essentially always needs to be seen; Green essentially never does.
        # The dataset's own ground truth is the thing being scored, so this
        # cannot flatter the model.
        expect_visit = r.get("expected_physical_visit")
        if expect_visit is None:
            expect_visit = expected == "Red"
        visit_hit = result is not None and result.physical_visit_recommended == expect_visit
        esc_hit = (result is not None
                   and result.specialist_escalation_recommended
                   == r.get("expected_escalation", expected == "Red"))
        visit_hits += visit_hit
        esc_hits += esc_hit
        if result is not None and not visit_hit and expect_visit:
            visit_misses.append(r["id"])

        if predicted:
            conf[expected][predicted] += 1
            by_noise[r["noise"]]["n"] += 1
            by_noise[r["noise"]]["correct"] += hit
            by_tpl[r["template"]]["n"] += 1
            by_tpl[r["template"]]["correct"] += hit
            latencies.append(elapsed)
            # Token/cost accounting reads the trace, but a result can arrive
            # without one (a cached call, a stubbed model in a test). Missing
            # trace must mean "no cost recorded", not an IndexError that loses
            # the whole run's results.
            last = llm.trace()[0] if llm.trace() else {}
            costs.append(_cost(last.get("tokens")))
            for k, v in (last.get("tokens") or {}).items():
                if v:
                    tokens[k] += v
        else:
            conf[expected]["ERROR"] += 1
            by_noise[r["noise"]]["n"] += 1
            by_tpl[r["template"]]["n"] += 1

        # Routing + manual review, from the model's own output. An unreadable
        # report has no routing to score; it counts as a manual-review case,
        # which is the honest outcome rather than a silent pass.
        if result is not None:
            need = _need_from(result)
            need["_expected_specialist"] = r.get("expected_specialist")
            route = _score_routing(result, need)
            routing[route["outcome"]] += 1
            if route["outcome"] == "misrouted":
                misrouted_ids.append(f'{r["id"]}({route["expected"]}->{route["routed_to"]})')
            if result.confidence < agent1_triage.MIN_CONFIDENCE:
                manual_review += 1
        else:
            manual_review += 1
            routing["unreadable"] += 1

        rows.append({
            "id": r["id"], "template": r["template"], "noise": r["noise"],
            "expected": expected, "predicted": predicted, "baseline": base,
            "correct": hit, "baseline_correct": base_hit,
            "expected_specialist": r["expected_specialist"],
            "predicted_specialist": (result.specialist if result else None),
            "expected_physical_visit": expect_visit,
            "predicted_physical_visit": (result.physical_visit_recommended
                                         if result else None),
            "expected_escalation": r.get("expected_escalation", expected == "Red"),
            "predicted_escalation": (result.specialist_escalation_recommended
                                     if result else None),
            "recommended_action": (result.recommended_action if result else None),
            "confidence": (result.confidence if result else None),
            "red_flags": (result.red_flags if result else None),
            "reasoning": (result.reasoning if result else None),
            "routing": route if result is not None else {"outcome": "unreadable"},
            "manual_review": (result is None
                              or result.confidence < agent1_triage.MIN_CONFIDENCE),
            "latency_ms": round(elapsed),
        })

        mark = "OK " if hit else ("ERR" if not predicted else "XX ")
        print(f'{r["id"]:<8}{str(predicted):<7}{expected:<9}{r["noise"]:<7}{mark:<4}'
              f'{elapsed:>6.0f}  {r["template"]}')

    n = len(rows)
    errors = sum(1 for r in rows if r["predicted"] is None)

    # Under-triage = model says something less severe than the truth.
    under = [r for r in rows if r["predicted"] and
             SEVERITY_PENALTY[r["predicted"]] < SEVERITY_PENALTY[r["expected"]]]
    # Over-triage is the mirror: more severe than the truth. Cheaper than
    # under-triage in a rural pathway - it burns a scarce doctor slot and can
    # push a genuinely routine case behind a real one - but it is a real cost,
    # and folding it into plain accuracy hides it. A model that called every
    # case Red would score well on under-triage and terribly on this.
    over = [r for r in rows if r["predicted"] and
            SEVERITY_PENALTY[r["predicted"]] > SEVERITY_PENALTY[r["expected"]]]

    # Routing is scored only over cases that produced a verdict, because an
    # unreadable report has no destination to judge. The denominator is stated
    # so the rate cannot be quietly flattered by excluding the hard cases.
    routed_n = routing["routed"] + routing["misrouted"]
    spec_ok = sum(1 for r in rows if r["predicted"]
                  and r["predicted_specialist"] == r["expected_specialist"])
    spec_n = sum(1 for r in rows if r["predicted"])

    return {
        "model": llm.MODEL,
        "n": n,
        "llm": {
            "accuracy": round(llm_hits / n, 4) if n else 0,
            "errors": errors,
            "throttled": throttled,
            "specialist_accuracy": round(spec_ok / spec_n, 4) if spec_n else None,
            "under_triage_count": len(under),
            "under_triage_rate": round(len(under) / n, 4) if n else 0,
            "over_triage_count": len(over),
            "over_triage_rate": round(len(over) / n, 4) if n else 0,
        },
        "baseline": {"accuracy": round(base_hits / n, 4) if n else 0},
        "routing": {
            "scored": routed_n,
            "correct": routing["routed"],
            "wrong": routing["misrouted"],
            "unassigned": routing["unassigned"],
            "unreadable": routing["unreadable"],
            "accuracy": round(routing["routed"] / routed_n, 4) if routed_n else None,
            "misrouted": misrouted_ids,
        },
        "manual_review": {
            "count": manual_review,
            "rate": round(manual_review / n, 4) if n else 0,
            "threshold": agent1_triage.MIN_CONFIDENCE,
        },
        "recommendations": {
            "physical_visit_accuracy": round(visit_hits / spec_n, 4) if spec_n else None,
            "escalation_accuracy": round(esc_hits / spec_n, 4) if spec_n else None,
            "visit_recommendation_misses": visit_misses,
        },
        "by_noise": {k: {"n": v["n"], "accuracy": round(v["correct"] / v["n"], 4)}
                     for k, v in by_noise.items()},
        "by_template": {k: {"n": v["n"], "accuracy": round(v["correct"] / v["n"], 4)}
                        for k, v in sorted(by_tpl.items())},
        "confusion": {exp: dict(counts) for exp, counts in conf.items()},
        "latency_ms": {
            "mean": round(statistics.mean(latencies)) if latencies else None,
            "p50": round(statistics.median(latencies)) if latencies else None,
            "p95": round(sorted(latencies)[int(len(latencies) * 0.95)]) if latencies else None,
        },
        "tokens": dict(tokens),
        "est_cost_usd": round(sum(costs), 4),
        "rows": rows,
    }


def print_report(res: dict) -> None:
    print("\n" + "=" * 78)
    print("SEVERITY CONFUSION (row = truth, col = prediction)")
    print("=" * 78)
    print(f'{"":<10}' + "".join(f"{s:>9}" for s in SEVERITIES) + f'{"ERR":>9}{"acc":>9}')
    for exp in SEVERITIES:
        counts = res["confusion"].get(exp, {})
        total = sum(counts.values())
        acc = counts.get(exp, 0) / total if total else 0
        print(f'{exp:<10}' + "".join(f'{counts.get(s, 0):>9}' for s in SEVERITIES)
              + f'{counts.get("ERROR", 0):>9}{acc:>8.0%}')

    print("\n" + "=" * 78)
    print(f'model            {res["model"]}')
    print(f'reports          {res["n"]}')
    print(f'LLM accuracy     {res["llm"]["accuracy"]:.1%}')
    print(f'baseline accuracy{res["baseline"]["accuracy"]:>8.1%}   '
          f'(keyword/regex, the thing a model has to beat)')
    print(f'lift over base   {res["llm"]["accuracy"] - res["baseline"]["accuracy"]:+.1%}')
    print(f'under-triage     {res["llm"]["under_triage_count"]} cases '
          f'({res["llm"]["under_triage_rate"]:.1%})  <-- the dangerous error')
    print(f'over-triage      {res["llm"]["over_triage_count"]} cases '
          f'({res["llm"]["over_triage_rate"]:.1%})  <-- burns a doctor slot')
    print(f'specialist acc   {res["llm"]["specialist_accuracy"]}')
    print(f'errors/retries   {res["llm"]["errors"]}')
    throttled = res["llm"].get("throttled") or []
    if throttled:
        # Loud, because otherwise these rows read as model failures and the
        # accuracy figure above silently means "accuracy until we ran out".
        print(f'\n!! RATE LIMITED: {len(throttled)} of {res["n"]} reports were '
              f'rejected by the API quota and scored as errors.')
        print(f'!! They are NOT model failures. ids: '
              f'{", ".join(throttled[:12])}{" ..." if len(throttled) > 12 else ""}')
        print('!! Free tier is ~20 calls/day/model. Use --limit, or bill the '
              'project, or widen LLM_FALLBACK_MODELS.')

    rt = res.get("routing") or {}
    if rt.get("scored"):
        print(f'\n--- routing (destination reached, not just severity) ---')
        print(f'correct routing  {rt["correct"]}/{rt["scored"]} '
              f'({rt["accuracy"]:.1%})')
        print(f'wrong routing    {rt["wrong"]}  '
              f'(unassigned for capacity: {rt["unassigned"]}, '
              f'unreadable: {rt["unreadable"]})')
        if rt.get("misrouted"):
            print(f'  misrouted: {", ".join(rt["misrouted"][:8])}')

    mr = res.get("manual_review") or {}
    if mr:
        print(f'\n--- held for a clinician rather than auto-dispositioned ---')
        print(f'manual review    {mr["count"]} cases ({mr["rate"]:.1%})  '
              f'(model confidence below {mr["threshold"]}, or unreadable)')

    rec = res.get("recommendations") or {}
    if rec.get("physical_visit_accuracy") is not None:
        misses = rec.get("visit_recommendation_misses") or []
        print(f'\n--- queue recommendations (advisory; a doctor decides) ---')
        print(f'visit recommended {rec["physical_visit_accuracy"]:.1%}')
        print(f'escalation rec.   {rec["escalation_accuracy"]:.1%}')
        if misses:
            print(f'"no visit needed" on cases that do  {len(misses)}: '
                  f'{", ".join(misses[:8])}   <-- the dangerous direction')

    print("\nby noise level:")
    for k, v in res["by_noise"].items():
        print(f'  {k:<8} n={v["n"]:<4} accuracy={v["accuracy"]:.1%}')

    worst = sorted(res["by_template"].items(), key=lambda kv: kv[1]["accuracy"])[:6]
    print("\nweakest templates:")
    for k, v in worst:
        print(f'  {k:<28} n={v["n"]:<4} accuracy={v["accuracy"]:.0%}')

    lat = res["latency_ms"]
    if lat["mean"]:
        print(f'\nlatency ms       mean={lat["mean"]} p50={lat["p50"]} p95={lat["p95"]}')
    print(f'tokens           {res["tokens"]}')
    print(f'est. cost        ${res["est_cost_usd"]} (approximate; set LLM_IN_COST/LLM_OUT_COST)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "results.json"))
    args = ap.parse_args()

    if not llm.available():
        print("GOOGLE_API_KEY is not set. Set it in .env to run the eval.", file=sys.stderr)
        return 1

    with open(DATASET, encoding="utf-8") as f:
        reports = json.load(f)

    res = evaluate(reports, args.limit)
    print_report(res)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    print(f"\nfull results -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
