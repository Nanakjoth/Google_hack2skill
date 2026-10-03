import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

import llm
from models import PatientIn, RedistributeIn, DecisionIn
from data_store import (
    hospitals, patients, next_patient_id, by_id, distance_from_origin,
    seed_patients, now, resolve_specialty, specialty_label, SPECIALTIES,
)
from agents import (
    agent1_triage, agent2_allocator, agent3_routing, agent4_forecast, queue,
)

app = FastAPI(title="Agentic Tele-Triage Portal API", version="3.0.0")

# Seed the demo backlog at boot so the queues have real content on first load.
# Guarded inside seed_patients() against a re-seed on reload.
seed_patients()

# Dev default is wide open so the static frontend on any port can call it.
# Set ALLOWED_ORIGINS to a comma-separated list (or "none" to disable CORS
# entirely) before exposing this anywhere.
_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
if _origins_env.lower() != "none":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if _origins_env.strip() == "*" else
                      [o.strip() for o in _origins_env.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/healthz")
def health():
    """API + model configuration.

    The root path is the UI, so health lives here. This is also what the
    frontend's status pill calls, which means one URL serves both the console
    and its own health check - no CORS, no second origin.
    """
    return {
        "status": "ok",
        "service": "agentic-tele-triage-api",
        "llm_configured": llm.available(),
        "llm_model": llm.MODEL,
    }


@app.post("/patients")
def submit_patient(p: PatientIn):
    """Run the patient-path pipeline for one incoming report.

    Supply `report_text` to use the LLM path; `case_type` alone uses the
    built-in case profiles. Either way the case lands in a queue for a human
    doctor - this endpoint never decides that a patient does or does not need
    to be seen.
    """
    try:
        need, step1 = agent1_triage.run(p.case_type, p.report_text)
    except ValueError as e:
        raise HTTPException(422, str(e))

    eligible, step2 = agent2_allocator.run(need)

    pid = next_patient_id()
    hospital, doctor, step3, _ = agent3_routing.run(eligible, need, patient_id=pid)

    # No eligible facility is NOT an escalation. Escalation needs a doctor who
    # decided to hand a case up; this case has nobody at all. It stays in the
    # network queue as `unassigned` so it keeps waiting visibly.
    status = "awaiting_review" if doctor else "unassigned"

    record = {
        "id": pid,
        "name": p.name,
        "case_label": need["label"],
        "severity": need["severity"],
        "specialty": resolve_specialty(need["specialist"]),
        "hospital": hospital["name"] if hospital else None,
        "hospital_id": hospital["id"] if hospital else None,
        "doctor": doctor["name"] if doctor else None,
        "doctor_specialty": doctor["specialty"] if doctor else None,
        "status": status,
        "triage_source": need["source"],
        "manual_review": need["manual_review"],
        "confidence": need["confidence"],
        "red_flags": need["red_flags"],
        "ai_recommendation": {
            "physical_visit": need["physical_visit"],
            "specialist_escalation": need["escalation"],
            "action": need["recommended_action"],
        },
        "reservation": agent3_routing.reservation(pid),
        # Queue bookkeeping.
        "enqueued_at": now(),
        "decided_at": None,
        "decision": None,
        "decision_note": None,
        "escalated_from": None,
        "report_text": p.report_text,
        "seed": False,
        # Kept so the decision path can commit exactly what triage asked for,
        # rather than re-deriving it and risking a drift between the two.
        "need": need,
    }
    patients.append(record)
    return _public(record) | {"steps": [step1, step2, step3]}


def _public(record: dict) -> dict:
    """Strip the internal triage block from a patient record.

    `need` is the contract between triage and the decision path; it is not part
    of anything a client needs, and `POST /patients` and `/decide` both already
    withhold it. `GET /patients` returning the raw records leaked it on exactly
    one endpoint, which is the kind of drift that gets fixed in one place and
    reappears in the next.
    """
    return {k: v for k, v in record.items() if k != "need"}


@app.get("/patients")
def list_patients():
    return [_public(p) for p in patients]


def _find(patient_id: int) -> dict:
    for p in patients:
        if p["id"] == patient_id:
            return p
    raise HTTPException(404, "Patient not found")


@app.get("/patients/{patient_id}")
def get_patient(patient_id: int):
    """The patient-facing portal view. Deliberately a different shape from the
    internal record - see queue.portal_view for what is withheld and why."""
    return queue.portal_view(_find(patient_id))


@app.post("/patients/{patient_id}/decide")
def decide_patient(patient_id: int, body: DecisionIn):
    """Record a reviewing doctor's decision. The core handoff of the product.

    Three outcomes, and they differ in what happens to scarce resources:

      no_visit       report handled remotely. The doctor slot is freed and any
                     held resources are returned. No bed was ever wasted on a
                     patient who did not need one.
      visit_required the patient is coming in. ICU beds and medicines are
                     committed *now*, by a human decision, not by a report.
      escalate       handed to a senior consultant. The review assignment moves
                     to a matching senior doctor, and any already-committed
                     resources follow the case rather than being released -
                     an escalated patient is more urgent, not less.

    No model is involved. Ever. This is where clinical authority lives.
    """
    p = _find(patient_id)

    if p["status"] not in queue.OPEN_STATUSES:
        raise HTTPException(409, f"Case is already {p['status']}")

    need = p.get("need") or {}
    result = {"patient_id": patient_id, "decision": body.decision}

    if body.decision == "no_visit":
        released = agent3_routing.release(patient_id)
        p["status"] = "closed_remote"
        p["reservation"] = None
        result["resources_released"] = released

    elif body.decision == "visit_required":
        # A record with no triage `need` cannot be committed faithfully, and
        # admitting it anyway would be the worst outcome available: the case
        # would read `admitted` / `committed: true` while the facility held no
        # bed and no stock for it. Refuse and say why, rather than let a missing
        # field look like a successful admission.
        if not p.get("need"):
            raise HTTPException(
                409,
                "This case has no triage record, so the resources it needs "
                "cannot be determined. Do not admit it on this endpoint; "
                "re-submit the report to get a fresh triage.")
        commit = agent3_routing.commit(patient_id, need)
        if not commit:
            raise HTTPException(
                409,
                "Case is no longer routed to a doctor, so there is nothing to "
                "commit resources against. Re-submit the case.")
        if "error" in commit:
            # The doctor said yes, but the network cannot honour it. Say so
            # plainly instead of quietly admitting a patient the hospital
            # cannot treat.
            raise HTTPException(409, {
                "error": commit["error"],
                "detail": commit,
                "hint": "Escalate this case to arrange a transfer.",
            })
        p["status"] = "admitted"
        p["reservation"] = agent3_routing.reservation(patient_id)
        result["reserved"] = p["reservation"]

    else:  # escalate
        target = body.escalate_to or p.get("specialty")
        moved = agent3_routing.reassign(patient_id, target)
        if not moved:
            raise HTTPException(
                409, "Case is not routed to a doctor, so it cannot be escalated "
                     "to one. Re-submit the case.")
        if "error" in moved:
            # One hint per error, selected before it is built. A dict literal
            # evaluates *every* value, so writing all the hints up front meant
            # the `no_senior_available` path also evaluated the
            # `target_cannot_take_resources` f-string - and that error carries
            # `facility`/`short` while `no_senior_available` does not. The
            # refusal therefore raised KeyError('facility') and answered the
            # doctor with a 500 instead of the 409 that explains it. Look the
            # key up first, then format only the branch that applies.
            error = moved["error"]
            if error == "no_senior_available":
                hint = (f"No senior {specialty_label(moved['specialty'])} is "
                        f"free network-wide right now.")
            elif error == "target_cannot_take_resources":
                hint = (f"{moved['facility']} cannot supply "
                        f"{', '.join(moved['short'])} for this case, so the "
                        f"consultant was not moved and the case stays with "
                        f"the referring doctor.")
            else:
                hint = "Escalation was refused; nothing changed."
            raise HTTPException(409, {
                "error": error,
                "detail": moved,
                "hint": hint,
            })
        p["status"] = "awaiting_specialist"
        if moved.get("moved"):
            p["escalated_from"] = {
                "doctor": moved["from_doctor"],
                "hospital": moved["from_hospital"],
            }
        else:
            # Already with a senior of the right specialty: no handover
            # happened, so there is no "from" to record. Left as None rather
            # than filled in with the destination's own doctor and facility,
            # which would read as a referral that never occurred.
            p["escalated_from"] = None
        p["specialty"] = moved["specialty"]
        p["doctor"] = moved["doctor"]["name"]
        p["hospital"] = moved["hospital"]["name"]
        p["hospital_id"] = moved["hospital"]["id"]
        p["doctor_specialty"] = moved["doctor"]["specialty"]
        p["reservation"] = agent3_routing.reservation(patient_id)
        result["escalated_to"] = {
            "doctor": p["doctor"],
            "specialty": specialty_label(moved["specialty"]),
            "from": p["escalated_from"],
            "already_with_senior": not moved.get("moved"),
        }

    p["decision"] = body.decision
    p["decision_note"] = body.note
    p["decided_at"] = now()
    return _public(p) | result


@app.post("/patients/{patient_id}/approve")
def approve_patient(patient_id: int):
    """Backwards-compatible alias for the no-visit path.

    The original version had one `approve` button that released resources.
    That behaviour is exactly `no_visit` now, so this maps onto it rather than
    growing a second, subtly different release path.
    """
    return decide_patient(patient_id, DecisionIn(decision="no_visit"))


@app.get("/hospitals")
def get_hospitals():
    """Inventory plus the derived fields the UI needs.

    `free_platelets` is computed here rather than stored, so the old
    top-level `platelets` key that four agents used to read can never drift
    out of sync with `stock` again.

    Specialties are reported from the real doctor roster instead of the old
    per-hospital booleans, so "has a cardiologist" cannot disagree with the list
    of cardiologists shown two lines below it.
    """
    out = []
    for h in hospitals:
        roster = [d["specialty"] for d in h["doctors"]]
        out.append({
            "id": h["id"],
            "name": h["name"],
            "district": h["district"],
            "type": h["type"],
            "icu": h["icu"],
            "icu_total": h["icu_total"],
            "distance_km": round(distance_from_origin(h), 1),
            "specialties": sorted(set(roster)),
            "senior_specialties": sorted({
                d["specialty"] for d in h["doctors"] if d.get("senior")}),
            "free_platelets": h["stock"]["platelet_concentrate"],
            "stock": dict(h["stock"]),
            "doctors": [dict(d) for d in h["doctors"]],
        })
    return out


@app.get("/queue")
def get_queue():
    """The whole queue picture in one call.

    The three queues plus stats are fetched together because the header tiles,
    the patient list, and the doctor panels are always viewed together, and
    three round trips to render one screen makes the queue feel slower than it
    is - which is the opposite of what a queue is for.
    """
    return {
        "stats": queue.queue_stats(),
        "patient_queue": queue.patient_queue(),
        "doctor_queues": queue.doctor_queues(),
        "specialist_queues": queue.specialist_queue(),
        "server_time": now(),
        # Model configuration rides along with the queue the console already
        # fetches on every load.
        #
        # `/healthz` is the obvious home for it, and it still is - but Google
        # Front End reserves that path and answers it with its own 404 HTML page
        # *before* the request reaches the container. Deployed on Cloud Run, a
        # console whose status pill depended on /healthz alone therefore
        # reported "API: offline" and "Model: unknown" while /queue, /hospitals
        # and every other route returned 200 from the same container. Two
        # booleans duplicated here keep the pills honest regardless of which
        # paths the proxy in front decides to claim.
        "llm_configured": llm.available(),
        "llm_model": llm.MODEL,
    }


@app.get("/queue/patients")
def get_patient_queue():
    return {"stats": queue.queue_stats(), "cases": queue.patient_queue()}


@app.get("/queue/doctors")
def get_doctor_queues():
    return queue.doctor_queues()


@app.get("/queue/doctors/{doctor_name}")
def get_doctor_queue(doctor_name: str):
    cases = queue.doctor_queue(doctor_name)
    if not cases:
        raise HTTPException(404, f"No open cases for {doctor_name}")
    return {"doctor": doctor_name, "cases": cases}


@app.get("/queue/specialists")
def get_specialist_queue():
    return queue.specialist_queue()


@app.get("/command-center/alerts")
def get_alerts():
    return agent4_forecast.check_shortages()


@app.get("/command-center/forecast")
def get_forecast():
    """Days-of-cover for every facility x medicine, worst first."""
    return agent4_forecast.forecast_table()


@app.post("/command-center/redistribute")
def redistribute(body: RedistributeIn):
    try:
        moved = agent4_forecast.redistribute(
            body.donor_id, body.receiver_id, body.medicine, body.amount)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "moved": moved,
        "medicine": body.medicine,
        "donor": by_id(body.donor_id)["name"],
        "receiver": by_id(body.receiver_id)["name"],
    }


@app.get("/agents/llm-trace")
def llm_trace():
    """Recent model calls, so the Pipeline tab shows a real trace."""
    return {
        "configured": llm.available(),
        "model": llm.MODEL,
        "calls": llm.trace(),
    }


# ---------------------------------------------------------------------------
# The console is served from this same container, so a deployed judge needs one
# URL rather than an API host plus a separately-hosted page. The mount is added
# LAST on purpose: every route above is matched first, so /patients, /queue and
# /docs keep working, and only genuinely unmatched paths fall through to the
# filesystem.
# ---------------------------------------------------------------------------
_frontend = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
if os.path.isdir(_frontend):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="console")


if __name__ == "__main__":
    import uvicorn
    # Cloud Run injects PORT and expects the container to listen on 0.0.0.0.
    # Locally PORT is unset, so this stays on 8000.
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))