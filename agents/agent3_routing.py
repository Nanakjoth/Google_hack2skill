"""
Agent 3 - Routing & Load Balancing.

Picks a facility and a qualified doctor for the case, then records a *review
assignment* keyed by patient id so it can be moved or released later.

The reservation ledger is the part the original version was missing: it
permanently decremented `icu` and never gave it back, so after one severe case
the demo deadlocked and could only be recovered by restarting the server.
Everything held here is keyed by patient id and returned by `release()`.

A review assignment is NOT a resource reservation. Assigning a report to Dr.
Rao holds no ICU bed, because a report review needs no bed. Physical resources
are committed by `commit()` only once a doctor decides the patient must
actually be seen. Keeping those two separate is what lets the digital queue
recover capacity a physical queue would have tied up.

Selection is a transparent weighted score, not a model decision, and the
winning breakdown is returned so a human can sanity-check the route:

    score = 0.45 * proximity + 0.35 * free capacity + 0.20 * doctor availability

Proximity dominates because a nearer facility with a slightly busier doctor
beats a metro hospital 150 km away. Distance is a real clinical factor in
rural referral and the original version ignored it entirely.

CONNECT LATER: factor real-time shift/attendance data into `availability`.
"""

from data_store import (
    hospitals, distance_from_origin, take, stock_of, give_back,
    resolve_specialty, doctors_of, facilities_with,
)

W_PROXIMITY = 0.45
W_CAPACITY = 0.35
W_AVAILABILITY = 0.20

# A doctor counts as having headroom while this fraction of their capacity is
# still free. Past it, the nearest facility is considered full and the case is
# referred onward rather than piling up. See run() for why this is a threshold
# and not just another weighted term.
MIN_HEADROOM = 0.25

# patient_id -> {"hospital": h, "doctor": d, "icu": int, "medicines": {k: v}}
_reservations: dict = {}


def _score(h: dict, need: dict, doctor: dict | None) -> tuple:
    """Return (score, breakdown). All three terms are normalised 0-1 so the
    weights are directly comparable and the breakdown is meaningful."""
    dist = distance_from_origin(h)
    proximity = 1.0 / (1.0 + dist / 40.0)  # ~40 km decay, so 80 km -> 0.33

    capacity = 1.0
    if need["icu"]:
        capacity = min(1.0, h["icu"] / max(1, h["icu_total"] or 1))

    # Availability is that one doctor's remaining headroom, as a fraction of
    # their capacity. Using the pair means a nearly-full doctor drags their
    # facility's score down, which is what lets the case spread to a colleague
    # in the next district instead of stacking up locally.
    if doctor is None:
        availability = 0.0
    else:
        availability = max(0, doctor["capacity"] - doctor["load"]) / max(1, doctor["capacity"])

    score = (W_PROXIMITY * proximity
             + W_CAPACITY * capacity
             + W_AVAILABILITY * availability)

    breakdown = {
        "distance_km": round(dist, 1),
        "proximity": round(proximity, 3),
        "capacity": round(capacity, 3),
        "availability": round(availability, 3),
    }
    return score, breakdown


def run(eligible: list, need: dict, patient_id: int | None = None):
    # Computed up front so every exit path below can report it, including the
    # ones that assign nobody. "We could not route this" is only a useful
    # statement if it comes with the size of the pool that failed to cover it.
    counts = _candidate_counts(eligible or [], need)

    if not eligible:
        step = {
            "title": "Agent 3 - Routing & Load Balancing",
            "text": (
                f"No facility passed the physical-capacity check. "
                f"{_count_sentence(counts)} "
                "Patient held for manual override."
            ),
            "source": "deterministic",
            "candidates": counts,
        }
        return None, None, step, {}

    # Score each survivor as a (facility, doctor) *pair* rather than scoring
    # the facility and then the doctor separately. Scoring the facility first
    # is what produced the original bug: the nearest hospital won on proximity
    # every time, and then its one relevant doctor absorbed the entire
    # district's caseload while three other haematologists sat idle.
    candidates = []
    for h in eligible:
        doctor = _pick_doctor(h, need)
        score, breakdown = _score(h, need, doctor)
        candidates.append((score, h, doctor, breakdown))

    if not candidates:
        step = {
            "title": "Agent 3 - Routing & Load Balancing",
            "text": ("No facility has a free doctor in the required specialty "
                     f"right now. {_count_sentence(counts)} "
                     "Case held for the next available slot."),
            "source": "deterministic",
            "candidates": counts,
        }
        return None, None, step, {}

    # Selection: nearest facility that still has real headroom, then the least
    # loaded doctor there.
    #
    # The obvious implementation - take the highest weighted score - does not
    # balance load at all here. W_PROXIMITY is 0.45, while the whole spread of
    # the availability term across a realistic roster is about 0.09, so
    # proximity swamps it and every case lands at the nearest hospital forever.
    # The 5 percent of a queue engine that is actually load balancing, gone.
    #
    # So availability is applied as a threshold rather than a nudge: a facility
    # is eligible while its doctor still has MIN_HEADROOM free, and once the
    # nearest one is genuinely full the case spills to the next district. That
    # is the behaviour a rural referral network actually wants, and it is the
    # behaviour the plan's phrase "spread the load" describes.
    def headroom(candidate):
        _, _, doc, _ = candidate
        return 0 if doc is None else (doc["capacity"] - doc["load"]) / max(1, doc["capacity"])

    with_headroom = [c for c in candidates
                     if c[2] is not None and headroom(c) >= MIN_HEADROOM]
    pool = with_headroom or [c for c in candidates if c[2] is not None]

    if not pool:
        step = {
            "title": "Agent 3 - Routing & Load Balancing",
            "text": ("No facility has a free doctor in the required specialty "
                     f"right now. {_count_sentence(counts)} "
                     "Case held for the next available slot."),
            "source": "deterministic",
            "candidates": counts,
        }
        return None, None, step, {}

    ranked = sorted(pool, key=lambda c: (c[1] and distance_from_origin(c[1]),
                                         headroom(c)))
    best_score, best_hospital, doctor, best_breakdown = ranked[0]

    if doctor is None:
        step = {
            "title": "Agent 3 - Routing & Load Balancing",
            "text": ("No facility has a free doctor in the required specialty "
                     f"right now. {_count_sentence(counts)} "
                     "Case held for the next available slot."),
            "source": "deterministic",
            "candidates": counts,
        }
        return None, None, step, {}

    # Report the alternative, because "why not the nearer hospital" is the
    # first question a supervisor asks when a case is referred onward.
    if len(ranked) > 1:
        alt = ranked[1]
        runner_up = (f'Runner-up: {alt[1]["name"]} at {distance_from_origin(alt[1]):.0f} km '
                     f'({alt[2]["name"]}, {headroom(alt):.0%} headroom).')
    else:
        runner_up = "Sole eligible facility."

    # --- Reservation is deferred, not skipped. ------------------------------
    # Assigning a case to a doctor does NOT commit an ICU bed or medicine. A
    # case in the queue is waiting to be *reviewed*, and a report-only review
    # needs no bed. Committing resources here would mean holding the same scarce
    # inventory that the physical queue used to hold, which is the one thing a
    # digital queue has to avoid in order to be worth anything.
    #
    # Resources are committed by `commit()` at the moment a doctor decides the
    # patient must actually be seen, and returned by `release()`. That also
    # means the reservation ledger records a *review assignment* (who is looking
    # at this case) separately from a *resource commitment* (what is being held
    # for the patient), which is what makes `reassign()` on escalation possible.
    reserved = False
    if patient_id is not None:
        _reservations[patient_id] = {
            "hospital": best_hospital,
            "doctor": doctor,
            "icu": 0,                       # committed later by commit()
            "medicines": {},                # committed later by commit()
            "committed": False,
            "specialty": resolve_specialty(need.get("specialist")),
        }

    # A review assignment IS workload, so the doctor's load goes up here even
    # though no physical resource does. This is the increment that makes load
    # balancing work at all: without it every doctor's load stays flat
    # forever, `headroom` never shrinks, and the nearest-with-headroom policy
    # degenerates into "always the nearest hospital". It is released in
    # `release()` and transferred in `reassign()`.
    doctor["load"] += 1

    step = {
        "title": "Agent 3 - Routing & Load Balancing",
        "text": (
            f'Assigned to {doctor["name"]}'
            f' ({doctor["specialty"].replace("_", " ")}) at {best_hospital["name"]} - '
            f'{best_breakdown["distance_km"]} km away, '
            f'{doctor["load"]}/{doctor["capacity"]} case load. Score {best_score:.3f} '
            f'(proximity {best_breakdown["proximity"]}, capacity {best_breakdown["capacity"]}, '
            f'availability {best_breakdown["availability"]}). '
            f"{_count_sentence(counts, doctor)} "
            f"No physical resources held until a doctor confirms the visit. "
            f"{runner_up}"
        ),
        "source": "deterministic",
        "score": round(best_score, 4),
        "breakdown": best_breakdown,
        "candidates": counts,
        "reserved": reserved,
    }
    return best_hospital, doctor, step, best_breakdown


def _count_sentence(counts: dict, doctor: dict | None = None) -> str:
    """The plan's "7 possible doctors, 3 eligible, 1 selected", as prose.

    `possible` counts every fitting doctor network-wide, `eligible` only those
    at facilities that cleared Agent 2's physical check. The gap between the two
    is the resource constraint stated in numbers rather than as a delay.

    When the winner came from the general-medicine fallback the sentence says so
    explicitly. Reporting "1 of 5 cardiologists selected" directly above a
    general physician's name would be a contradiction the first reviewer
    catches, and the count would then be decoration rather than evidence.
    """
    label = counts["specialty"].replace("_", " ")
    if not counts["possible"]:
        return (f"No {label} doctor is rostered anywhere in the network, so "
                "there was nobody to route to.")

    head = (f'{counts["possible"]} possible {label} doctor(s) network-wide, '
            f'{counts["eligible"]} at a facility with the capacity for this '
            f'case, {counts["available"]} free right now')

    if doctor is not None and counts["specialty"] != "general_medicine" \
            and doctor["specialty"] == "general_medicine":
        return (f"{head}. 1 selected - a general duty doctor, since no "
                f"{label} had free capacity at an eligible facility.")
    return f"{head}. 1 selected."


def _candidate_counts(eligible: list, need: dict) -> dict:
    """How many doctors could have taken this case, and how many actually could.

    The plan asks the demo to be able to say "7 possible doctors, 3 eligible,
    1 selected" and then explain the rejections. Those numbers are only
    meaningful if "possible" is computed by the same rule that picks the doctor,
    so this reuses `doctors_of` rather than re-deriving the matching: a count
    that disagreed with the selection would make the explanation worse than no
    explanation.

    `possible` is network-wide, ignoring load - every doctor whose specialty
    fits, which is the number a patient would recognise as "how many doctors
    could see me". `eligible` is restricted to facilities Agent 2 cleared on
    physical capacity, so the gap between the two is the resource constraint
    made visible. `available` narrows further to doctors with free capacity.

    The general-medicine fallback is counted separately rather than folded into
    `possible`. `_pick_doctor` will hand a case to a general duty doctor if the
    requested specialty has nobody free, and reporting that as "1 of 5
    cardiologists selected" when the winner was a general physician would make
    the panel contradict the assignment sitting directly above it in the same
    view. Agent 2 already refuses a facility whose specialist is fully booked, so
    that fallback is not reachable through the pipeline today; it is counted
    correctly anyway rather than assumed away.
    """
    specialty = resolve_specialty(need.get("specialist"))

    def rosters(facilities: list):
        """(exact-specialty roster, fallback roster) per facility."""
        out = []
        for h in facilities:
            exact = doctors_of(h, specialty)
            fallback = ([] if exact or specialty == "general_medicine"
                        else doctors_of(h, "general_medicine"))
            out.append((exact, fallback))
        return out

    def count(facilities: list) -> dict:
        exact_n = exact_free = fallback_n = fallback_free = 0
        for exact, fallback in rosters(facilities):
            exact_n += len(exact)
            exact_free += sum(1 for d in exact if d["load"] < d["capacity"])
            fallback_n += len(fallback)
            fallback_free += sum(1 for d in fallback if d["load"] < d["capacity"])
        return {
            "exact": exact_n, "exact_available": exact_free,
            "fallback": fallback_n, "fallback_available": fallback_free,
        }

    net = count(hospitals)
    elig = count(eligible)
    return {
        "specialty": specialty,
        "possible": net["exact"] + net["fallback"],
        "free_networkwide": net["exact_available"] + net["fallback_available"],
        "exact_possible": net["exact"],
        "exact_available": net["exact_available"],
        "fallback_possible": net["fallback"],
        "eligible": elig["exact"] + elig["fallback"],
        "exact_eligible": elig["exact"],
        "available": elig["exact_available"] + elig["fallback_available"],
        "selected": 1,
    }


def _pick_doctor(hospital: dict, need: dict):
    """The doctor at this facility best placed to take the case.

    Prefers someone in the required specialty; falls back to a general duty
    doctor with free capacity, because a general doctor reviewing a routine
    report is normal practice, not a mismatch. Among equals, least loaded wins.
    """
    specialty = resolve_specialty(need.get("specialist"))
    roster = [d for d in doctors_of(hospital, specialty)
              if d["load"] < d["capacity"]]
    if not roster and specialty != "general_medicine":
        roster = [d for d in doctors_of(hospital, "general_medicine")
                  if d["load"] < d["capacity"]]
    if not roster:
        return None
    return min(roster, key=lambda d: d["load"] / max(1, d["capacity"]))


def commit(patient_id: int, need: dict) -> dict | None:
    """Hold physical resources for a case that a doctor confirmed needs a visit.

    The counterpart to the deferred reservation in `run()`. Called only from the
    decision path, so an ICU bed is held because a clinician decided the patient
    is coming in - never because a report was uploaded.

    Raises nothing: if the network cannot supply the resources after all, the
    caller is told what it got via the returned dict and the case is escalated
    rather than silently under-resourced.
    """
    res = _reservations.get(patient_id)
    if not res or res.get("committed"):
        return res

    h = res["hospital"]
    icu_wanted = need.get("icu", 0)
    if h["icu"] < icu_wanted:
        return {"error": "no_free_icu", "have": h["icu"], "need": icu_wanted}

    medicines = {k: v for k, v in (need.get("medicines") or {}).items() if v > 0}
    short = [f"{k}: needs {v}, has {stock_of(h, k)}"
             for k, v in medicines.items() if stock_of(h, k) < v]
    if short:
        return {"error": "insufficient_stock", "details": short}

    for med, qty in medicines.items():
        take(h, med, qty)
    h["icu"] -= icu_wanted
    res["icu"] = icu_wanted
    res["medicines"] = medicines
    res["committed"] = True
    return res


def reassign(patient_id: int, specialty: str | None = None) -> dict | None:
    """Move a case to a senior consultant - the escalation action.

    Symmetric with `release()`: it moves the review assignment from one doctor
    to another, and it is the only function that does. It deliberately does NOT
    touch committed resources. An escalated case is more urgent, not less, so
    releasing its held beds on the way up would be exactly backwards; the
    commitment follows the case to the new facility.

    Returns None if there is no ledger entry (nothing to escalate), or a dict
    with `error` if no senior consultant of that specialty exists anywhere -
    which is a real, reportable outcome rather than a silent failure.
    """
    res = _reservations.get(patient_id)
    if not res:
        return None

    target = resolve_specialty(specialty or res.get("specialty"))

    # Prefer a senior consultant who is not already at capacity, nearest first.
    # `facilities_with(..., senior_only=True)` is the proof that a senior
    # reviewer actually exists, so we never re-route into a dead end.
    for facility in facilities_with(target, senior_only=True):
        candidates = [d for d in doctors_of(facility, target, senior_only=True)
                      if d["load"] < d["capacity"] or d is res["doctor"]]
        if candidates:
            senior = min(candidates, key=lambda d: d["load"] / max(1, d["capacity"]))
            break
    else:
        return {"error": "no_senior_available", "specialty": target}

    previous_doctor = res["doctor"]
    previous_hospital = res["hospital"]

    # Preflight the destination before touching anything at all - not just
    # before the resource movement, but before the doctor swap as well.
    #
    # Two failure modes are being avoided. Giving the resources back at the
    # source and *then* finding the target short would strand them: the ledger
    # would claim the target holds them while the source actually does. And
    # swapping the doctor first, then refusing, would leave a case pointing at
    # a senior consultant who was never told they had it. An escalation either
    # happens completely or not at all.
    moves_resources = facility is not previous_hospital and res.get("committed")
    if moves_resources:
        short = [med for med, qty in res["medicines"].items()
                 if stock_of(facility, med) < qty]
        if res["icu"] and facility["icu"] < res["icu"]:
            short.append("ICU")
        if short:
            return {"error": "target_cannot_take_resources",
                    "specialty": target,
                    "facility": facility["name"],
                    "short": short}

    if senior is not previous_doctor:
        previous_doctor["load"] = max(0, previous_doctor["load"] - 1)
        senior["load"] += 1
        res["doctor"] = senior

    # The case now belongs to whichever facility the senior consultant works at.
    #
    # This has to happen whether or not resources were committed. Gating it on
    # `committed` was wrong, and silently so: the only senior haematologist in
    # the network is 158 km away at the Medical College, so an uncommitted
    # escalation kept `hospital` pointing at the original district hospital while
    # `doctor` pointed 158 km away. The patient portal then told a patient to
    # travel to a hospital where nobody was going to look at their case.
    # Assignment and resource commitment are separate concerns - only the
    # resource movement is conditional on the commitment.
    if facility is not previous_hospital:
        if moves_resources:
            for med, qty in res["medicines"].items():
                give_back(previous_hospital, med, qty)
                take(facility, med, qty)
            if res["icu"]:
                previous_hospital["icu"] = min(
                    previous_hospital["icu_total"],
                    previous_hospital["icu"] + res["icu"])
                facility["icu"] -= res["icu"]
        res["hospital"] = facility

    res["specialty"] = target
    return {
        "doctor": senior,
        "hospital": res["hospital"],
        "specialty": target,
        "from_doctor": previous_doctor["name"],
        "from_hospital": previous_hospital["name"],
        # Whether a handover actually occurred. Escalating a case that is
        # already with a senior consultant of the right specialty is a no-op,
        # and that has to be reported as one: recording `from` and `to` as the
        # same doctor and facility fabricates a handover that never happened,
        # which is exactly the kind of thing an escalation log gets audited for.
        "moved": senior is not previous_doctor or facility is not previous_hospital,
    }


def release(patient_id: int) -> bool:
    """Close out a case: free the doctor slot and return any held resources.

    Idempotent. Handles both shapes a ledger entry can have - a bare review
    assignment with nothing committed, and a case that went on to hold an ICU
    bed and medicines - because closing a case should never fail on the basis of
    which of those it was.
    """
    res = _reservations.pop(patient_id, None)
    if not res:
        return False
    h, d = res["hospital"], res["doctor"]
    d["load"] = max(0, d["load"] - 1)
    if res.get("committed"):
        h["icu"] = min(h.get("icu_total", h["icu"] + res["icu"]), h["icu"] + res["icu"])
        for med, qty in res["medicines"].items():
            h["stock"][med] = stock_of(h, med) + qty
    return True


def reservation(patient_id: int) -> dict | None:
    res = _reservations.get(patient_id)
    if not res:
        return None
    return {"hospital_id": res["hospital"]["id"],
            "hospital": res["hospital"]["name"],
            "doctor": res["doctor"]["name"],
            "specialty": res.get("specialty"),
            "committed": bool(res.get("committed")),
            "icu": res["icu"],
            "medicines": dict(res["medicines"])}


def outstanding() -> dict:
    return {pid: {"hospital_id": r["hospital"]["id"],
                  "doctor": r["doctor"]["name"],
                  "specialty": r.get("specialty"),
                  "committed": bool(r.get("committed")),
                  "icu": r["icu"]}
            for pid, r in _reservations.items()}
