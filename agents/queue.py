"""
Queue engine — turns a set of triaged cases into three ordered queues.

The plan calls this the "AI Queue Engine". It is NOT model-backed, and that is
deliberate rather than a shortcut. The plan's own section 5 says the model must
not decide whether a doctor is available, whether capacity exists, or which
resource is reserved. Priority ordering is exactly that class of question: it is
a comparison over facts the server already holds. A model would make queue order
unstable between identical requests, unexplainable to the patient waiting in it,
and impossible to test.

So: deterministic, explainable, and auditable. `priority_breakdown()` returns the
arithmetic for every case so the ordering can be argued with.

Three queues, per plan section 9:

    patient_queue()    every open case, highest priority first, with wait time
    doctor_queue(doc)  one doctor's cases, priority first
    specialist_queue() escalated cases grouped by the specialty they need

PRIORITY
--------
Severity dominates, because a Red patient waiting behind six Green ones is the
failure this product exists to prevent. Waiting time then breaks ties within a
severity band, so nobody is starved by a steady stream of milder cases. The two
terms are combined additively rather than multiplied so both stay legible:

    priority = SEVERITY_WEIGHT[severity] + min(wait_minutes / WAIT_DIVISOR, cap)

with the wait term capped, so a Green case cannot eventually out-rank a Red one
no matter how long it waits. An unbounded wait term would quietly reintroduce
under-triage as a scheduling artifact.

QUEUE MEMBERSHIP IS NOT A RESERVATION
-------------------------------------
A case sitting in a queue is *waiting to be reviewed*. It does not occupy an ICU
bed. Physical resources are committed only when a doctor decides
`visit_required` (see main.decide_patient). This is what makes the product's
core claim true: replacing a physical queue only helps if waiting digitally
does not consume the same scarce resource the physical queue consumed.
"""

from data_store import (
    patients, now, minutes_since, resolve_specialty, specialty_label, SPECIALTIES,
)

# Severity dominates the ordering. The gaps are wide on purpose: a Red case must
# not be leapfrogged by an aging Green one, and a Yellow must not be buried
# behind routine cases.
SEVERITY_WEIGHT = {"Red": 1000, "Yellow": 500, "Green": 100}

# One point per WAIT_DIVISOR minutes of waiting. At 12 minutes a Green case has
# gained 1 point - enough to reorder it against an equally-severe case that
# arrived seconds ago, small enough that it never threatens a severity band.
WAIT_DIVISOR = 12.0

# The wait term is capped so waiting long enough cannot cross a severity band.
# Without this, a Green case waiting long enough would reach Red weight and the
# queue would start under-triage by arithmetic instead of by judgement.
#
# It must be strictly smaller than the *narrowest* gap between adjacent
# severity bands, or the cap is decorative: at 400 a capped Green case scored
# exactly 500, tying a freshly-arrived Yellow case, and the tie was then broken
# by arrival time - i.e. by the thing the queue exists to replace. The gaps here
# are 400 (Green->Yellow) and 500 (Yellow->Red), so 300 leaves real headroom
# under both. tests/test_pipeline.py asserts this invariant against the live
# constants, so re-tuning the weights without re-checking the cap fails the build.
MAX_WAIT_BONUS = 300.0

# Statuses that mean "this case is still open". Anything else (decided, closed)
# has left the queue. `unassigned` is open: a case with no eligible facility
# is still a patient waiting, and dropping them from the queue would be the
# one outcome this product must never cause.
OPEN_STATUSES = ("awaiting_review", "awaiting_specialist", "unassigned")


def priority_score(case: dict) -> float:
    """Queue priority. Higher = seen sooner."""
    return SEVERITY_WEIGHT.get(case.get("severity"), 100) + wait_bonus(case)


def wait_bonus(case: dict) -> float:
    waited = minutes_since(case.get("enqueued_at") or now())
    return min(waited / WAIT_DIVISOR, MAX_WAIT_BONUS)


def priority_breakdown(case: dict) -> dict:
    """The arithmetic behind a case's position, so the order can be checked.

    Returned rather than kept private because an ordering a patient cannot be
    told the reason for is indistinguishable from an arbitrary one.
    """
    waited = minutes_since(case.get("enqueued_at") or now())
    base = SEVERITY_WEIGHT.get(case.get("severity"), 100)
    bonus = min(waited / WAIT_DIVISOR, MAX_WAIT_BONUS)
    return {
        "severity": case.get("severity"),
        "severity_points": base,
        "waited_minutes": waited,
        "wait_points": round(bonus, 2),
        "capped": waited / WAIT_DIVISOR > MAX_WAIT_BONUS,
        "total": round(base + bonus, 2),
    }


def _queue_row(case: dict, position: int) -> dict:
    """The common shape every queue row has.

    Deliberately a flat dict with the fields a queue row actually needs rather
    than the whole patient record: the doctor queue has to render 30 rows and
    does not need the reasoning prose in each one.
    """
    specialty = resolve_specialty(case.get("specialty") or case.get("case_specialty"))
    return {
        "id": case["id"],
        "name": case["name"],
        "severity": case["severity"],
        "case_label": case.get("case_label"),
        "specialty": specialty,
        "specialty_label": specialty_label(specialty),
        "queue": SPECIALTIES.get(specialty, {}).get("queue", specialty),
        "status": case.get("status"),
        "hospital": case.get("hospital"),
        "hospital_id": case.get("hospital_id"),
        "doctor": case.get("doctor"),
        "doctor_specialty": case.get("doctor_specialty"),
        "waiting_minutes": minutes_since(case.get("enqueued_at") or now()),
        "priority": round(priority_score(case), 2),
        "priority_breakdown": priority_breakdown(case),
        "red_flags": case.get("red_flags") or [],
        "ai_recommendation": case.get("ai_recommendation"),
        "triage_source": case.get("triage_source"),
        "manual_review": bool(case.get("manual_review")),
        "confidence": case.get("confidence"),
        "decision": case.get("decision"),
        "escalated_from": case.get("escalated_from"),
        "seed": case.get("seed", False),
        "has_report": bool(case.get("report_text")),
    }


def _open_cases() -> list:
    return [p for p in patients if p.get("status") in OPEN_STATUSES]


def _sorted_cases(cases: list) -> list:
    """Priority order, with arrival time as a stable final tiebreak.

    Two cases can score identically (same severity, both waited 0 minutes).
    Falling back to arrival time makes the order total and reproducible instead
    of dependent on dict insertion order.
    """
    return sorted(cases, key=lambda c: (-priority_score(c),
                                        c.get("enqueued_at") or 0))


def patient_queue() -> list:
    """Every open case across the network, highest priority first."""
    return [_queue_row(c, i + 1)
            for i, c in enumerate(_sorted_cases(_open_cases()))]


def doctor_queue(doctor_name: str) -> list:
    """One doctor's cases: everything awaiting their review, plus anything that
    escalated to them as a senior consultant."""
    mine = [p for p in _open_cases()
            if p.get("doctor") == doctor_name]
    return [_queue_row(c, i + 1) for i, c in enumerate(_sorted_cases(mine))]


def doctor_queues() -> list:
    """Every doctor with at least one open case.

    This is the "Doctor Queue" view: one panel per doctor, each already sorted
    by priority so a clinician's next patient is the top row.
    """
    grouped: dict = {}
    for case in _open_cases():
        doc = case.get("doctor")
        if not doc:
            continue
        grouped.setdefault(doc, []).append(case)

    out = []
    for name, cases in grouped.items():
        rows = [_queue_row(c, i + 1) for i, c in enumerate(_sorted_cases(cases))]
        first = rows[0]
        out.append({
            "doctor": name,
            "specialty": first["specialty"],
            "specialty_label": first["specialty_label"],
            "senior": _is_senior(cases[0]),
            "open_cases": len(rows),
            "red_count": sum(1 for r in rows if r["severity"] == "Red"),
            "longest_wait_minutes": max(r["waiting_minutes"] for r in rows),
            "cases": rows,
        })
    # Busiest first: the doctor under most pressure is the one who needs to see
    # this view.
    return sorted(out, key=lambda g: (-g["red_count"], -g["open_cases"]))


def _is_senior(case: dict) -> bool:
    """Whether the assigned doctor is a consultant.

    Read off the live roster rather than stored on the case, so it stays true
    if the roster is edited.
    """
    from data_store import hospitals
    for h in hospitals:
        for d in h["doctors"]:
            if d["name"] == case.get("doctor"):
                return bool(d.get("senior"))
    return False


def specialist_queue() -> list:
    """Escalated cases, grouped by the specialty that must review them.

    Each group records where the case came from, which is the point of the
    escalation: a junior doctor at a rural CHC handing a case up, rather than
    sending the patient back to the CHC and making them travel twice.
    """
    escalated = [p for p in patients
                 if p.get("status") == "awaiting_specialist"]
    grouped: dict = {}
    for case in escalated:
        specialty = resolve_specialty(case.get("specialty"))
        grouped.setdefault(specialty, []).append(case)

    out = []
    for specialty, cases in grouped.items():
        rows = [_queue_row(c, i + 1) for i, c in enumerate(_sorted_cases(cases))]
        out.append({
            "specialty": specialty,
            "specialty_label": specialty_label(specialty),
            "queue_name": f"Senior {specialty_label(specialty)} Queue",
            "open_cases": len(rows),
            "critical_count": sum(1 for r in rows if r["severity"] == "Red"),
            "cases": rows,
        })
    return sorted(out, key=lambda g: (-g["critical_count"], g["open_cases"]))


def portal_view(case: dict) -> dict:
    """What a patient is told about their own case.

    Deliberately excludes everything internal: no stock levels, no other
    patients' names, no doctor workload. A patient portal that leaks the
    facility's platelet count is a security problem, not a transparency win.
    """
    return {
        "id": case["id"],
        "name": case["name"],
        "status": case.get("status"),
        "severity": case.get("severity"),
        "case_label": case.get("case_label"),
        "specialty": resolve_specialty(case.get("specialty")),
        "specialty_label": specialty_label(resolve_specialty(case.get("specialty"))),
        "assigned_doctor": case.get("doctor"),
        "assigned_facility": case.get("hospital"),
        "waiting_minutes": minutes_since(case.get("enqueued_at") or now()),
        "position": _position_of(case),
        "queue_length": len(_open_cases()),
        "decision": case.get("decision"),
        "decision_note": case.get("decision_note"),
        "decided_at": case.get("decided_at"),
        "ai_recommendation": case.get("ai_recommendation"),
        "report_text": case.get("report_text"),
    }


def _position_of(case: dict) -> int | None:
    """1-based place in the whole queue, or None if it has left the queue."""
    if case.get("status") not in OPEN_STATUSES:
        return None
    for i, c in enumerate(_sorted_cases(_open_cases())):
        if c["id"] == case["id"]:
            return i + 1
    return None


def queue_stats() -> dict:
    """Network-wide queue counts for the header tiles.

    `escalated_pending` is the number a supervisor should care about: those are
    cases that reached a doctor and were handed up rather than resolved.
    """
    open_cases = _open_cases()
    return {
        "open": len(open_cases),
        "by_severity": {
            sev: sum(1 for c in open_cases if c.get("severity") == sev)
            for sev in ("Red", "Yellow", "Green")
        },
        "awaiting_review": sum(1 for c in open_cases if c.get("status") == "awaiting_review"),
        "escalated_pending": sum(1 for c in open_cases if c.get("status") == "awaiting_specialist"),
        "unassigned": sum(1 for c in open_cases if not c.get("doctor")),
        "longest_wait_minutes": round(
            max((minutes_since(c.get("enqueued_at") or now()) for c in open_cases),
                default=0.0), 1),
    }
