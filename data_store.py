"""
In-memory mock data store.

Medicine names/categories are drawn from India's National List of Essential
Medicines (NLEM 2022, 384 drugs / 27 therapeutic categories) so the demo uses
real drug names instead of a generic counter. Bed counts are grounded in real
IPHS (Indian Public Health Standards) norms: a PHC typically has ~6 beds and no
ICU, a CHC ~30 beds with a small stabilisation unit, and a District Hospital
100+ beds with a real ICU.

Three structural notes that the agents depend on:

  * Stock lives ONLY in the nested `stock` dict, keyed by catalog key. Agents
    must go through `stock_of` / `take` / `give_back` rather than reading
    keys directly - that is the seam that broke the pipeline before, when a
    top-level `platelets` key was read by four agents and defined nowhere.
  * `icu` is FREE beds, not total. `reserve` / `release` keep it balanced so
    a demo can run indefinitely instead of deadlocking after one severe case.
  * `consumption_history` is seeded daily draw per medicine so Agent 4 has an
    actual series to forecast instead of a hardcoded threshold.

CONNECT LATER: this file is the one seam to change. Swap `hospitals` for
queries against a real inventory DB (e.g. seeded from e-Aushadhi or a state
HMIS export) and none of the agent files need to change.
"""

import math
import random
import time
from typing import Optional

from models import MedicineKey, Specialist

# Reference catalog: name, therapeutic category (per NLEM), and the stock
# level below which Agent 4 raises a shortage alert.
medicines_catalog = {
    "paracetamol":          {"name": "Paracetamol 500mg",      "category": "Antipyretic / Analgesic", "reorder_threshold": 20},
    "oral_rehydration":     {"name": "Oral Rehydration Salts", "category": "Fluid & Electrolyte",     "reorder_threshold": 15},
    "doxycycline":          {"name": "Doxycycline 100mg",      "category": "Anti-infective",          "reorder_threshold": 10},
    "ceftriaxone":          {"name": "Ceftriaxone Injection",  "category": "Anti-infective",          "reorder_threshold": 8},
    "platelet_concentrate": {"name": "Platelet Concentrate",   "category": "Blood Product",            "reorder_threshold": 4},
    "ringer_lactate":       {"name": "Ringer Lactate IV",      "category": "IV Fluid",                "reorder_threshold": 8},
    "insulin_glargine":     {"name": "Insulin Glargine",       "category": "Anti-diabetic",            "reorder_threshold": 5},
    "aspirin":              {"name": "Aspirin 150mg",          "category": "Cardiac - Antiplatelet",  "reorder_threshold": 10},
    "streptokinase":        {"name": "Streptokinase",          "category": "Cardiac - Thrombolytic",  "reorder_threshold": 2},
}

# The LLM's medicine enum is generated from this list - if they drift, the model
# can be asked for a drug the allocator cannot reason about. Fail loudly at boot.
_valid_keys = set(MedicineKey.__args__)
_unknown = set(medicines_catalog) - _valid_keys
if _unknown:
    raise RuntimeError(
        f"medicines_catalog has keys missing from MedicineKey: {sorted(_unknown)}. "
        "Add them to models.MedicineKey or the LLM will emit medicines the "
        "allocator cannot stock-check."
    )

PATIENT_ORIGIN = {"lat": 25.44, "lng": 78.57}  # generic rural referral origin

# Specialty registry. Kept as a dict (not just a Literal in models.py) so the
# queue and the UI can show a human label and a queue colour per specialty
# without hardcoding them in three places.
#
# `senior` marks the specialties that have a second, senior tier for escalated
# cases. A district hospital's general duty doctor can handle most things; what
# they cannot handle is handed to a senior consultant rather than bounced back
# to the patient. `senior` is what makes `escalate` a real routing action and
# not just a relabel - agents/agent3_routing.py only reassigns to a facility
# that actually has a senior in the requested specialty.
#
# Cross-checked against models.Specialist at import below, exactly as the
# medicine catalog is.
SPECIALTIES = {
    "general_medicine": {"label": "General Medicine",   "queue": "General",     "senior": True},
    "hematologist":     {"label": "Hematology",         "queue": "Haematology", "senior": True},
    "cardiologist":     {"label": "Cardiology",         "queue": "Cardiology",  "senior": True},
    "pediatrician":     {"label": "Paediatrics",        "queue": "Paediatrics", "senior": True},
    "general_surgeon":  {"label": "General Surgery",    "queue": "Surgery",     "senior": True},
}

_valid_specialties = set(Specialist.__args__) - {"none"}
if set(SPECIALTIES) != _valid_specialties:
    raise RuntimeError(
        f"SPECTIES and models.Specialist have drifted. "
        f"only in SPECIALTIES: {sorted(set(SPECIALTIES) - _valid_specialties)}; "
        f"only in Specialist: {sorted(_valid_specialties - set(SPECIALTIES))}. "
        "The model can only emit specialties the queue can route to."
    )

# What a case routed to `none` actually lands in. "No specialty needed" is not
# "no doctor needed" - it is general duty.
DEFAULT_SPECIALTY = "general_medicine"

# Facility records carry two specialty sets, and the distinction is the whole
# basis of the escalation queue:
#
#   specialties        - a doctor of this specialty is on staff and can take a
#                        first review. Gates Agent 2 eligibility.
#   senior_specialties - a *senior consultant* of this specialty is on staff.
#                        Only these facilities can accept an escalated case,
#                        so `decision="escalate"` is a real re-routing to a
#                        different doctor at a possibly different facility
#                        rather than a status label.
#
# Bed/stock counts stay grounded in IPHS norms: PHC ~6 beds no ICU, CHC ~30 with
# a small stabilisation unit, District Hospital 100+ with a real ICU, and a
# Medical College as the regional tertiary that holds the scarce senior
# consultants. Distances are the only geography in the system, measured by
# haversine from PATIENT_ORIGIN.
hospitals = [
    {"id": "h1", "name": "Rampur District Hospital", "district": "Rampur - Rural", "type": "District Hospital",
     "lat": 25.44, "lng": 78.57, "icu_total": 2, "icu": 2,
     "specialties": {"general_medicine", "hematologist", "pediatrician"},
     "senior_specialties": {"hematologist"},
     "stock": {"paracetamol": 40, "oral_rehydration": 25, "doxycycline": 12, "ceftriaxone": 6,
               "platelet_concentrate": 8, "ringer_lactate": 15, "insulin_glargine": 6,
               "aspirin": 10, "streptokinase": 1},
     "doctors": [
         {"name": "Dr. Nair", "specialty": "hematologist", "senior": False, "load": 2, "capacity": 10},
         {"name": "Dr. Joshi", "specialty": "pediatrician", "senior": False, "load": 1, "capacity": 8},
         {"name": "Dr. Prakash", "specialty": "general_medicine", "senior": False, "load": 3, "capacity": 12},
     ]},

    {"id": "h2", "name": "Sironj PHC", "district": "Sironj - Rural", "type": "PHC",
     "lat": 25.72, "lng": 77.92, "icu_total": 0, "icu": 0,
     "specialties": {"general_medicine", "pediatrician"},
     "senior_specialties": set(),
     "stock": {"paracetamol": 15, "oral_rehydration": 10, "doxycycline": 3, "ceftriaxone": 1,
               "platelet_concentrate": 2, "ringer_lactate": 4, "insulin_glargine": 2,
               "aspirin": 5, "streptokinase": 0},
     "doctors": [
         {"name": "Dr. Verma", "specialty": "general_medicine", "senior": False, "load": 1, "capacity": 8},
     ]},

    {"id": "h3", "name": "City General", "district": "State Capital - Metro", "type": "District Hospital",
     "lat": 26.21, "lng": 78.18, "icu_total": 6, "icu": 6,
     "specialties": {"general_medicine", "hematologist", "cardiologist", "pediatrician", "general_surgeon"},
     "senior_specialties": {"cardiologist", "general_surgeon"},
     "stock": {"paracetamol": 120, "oral_rehydration": 60, "doxycycline": 30, "ceftriaxone": 25,
               "platelet_concentrate": 20, "ringer_lactate": 40, "insulin_glargine": 25,
               "aspirin": 30, "streptokinase": 6},
     "doctors": [
         {"name": "Dr. Rao", "specialty": "cardiologist", "senior": True, "load": 9, "capacity": 12},
         {"name": "Dr. Iyer", "specialty": "general_medicine", "senior": False, "load": 7, "capacity": 12},
         {"name": "Dr. Menon", "specialty": "general_surgeon", "senior": True, "load": 4, "capacity": 10},
         {"name": "Dr. Batra", "specialty": "hematologist", "senior": False, "load": 2, "capacity": 10},
     ]},

    {"id": "h4", "name": "Lakhanpur CHC", "district": "Lakhanpur - Rural", "type": "CHC",
     "lat": 26.45, "lng": 79.51, "icu_total": 2, "icu": 2,
     "specialties": {"general_medicine", "hematologist"},
     "senior_specialties": set(),
     "stock": {"paracetamol": 35, "oral_rehydration": 20, "doxycycline": 15, "ceftriaxone": 8,
               "platelet_concentrate": 12, "ringer_lactate": 18, "insulin_glargine": 8,
               "aspirin": 12, "streptokinase": 2},
     "doctors": [
         {"name": "Dr. Singh", "specialty": "hematologist", "senior": False, "load": 1, "capacity": 9},
         {"name": "Dr. Yadav", "specialty": "general_medicine", "senior": False, "load": 2, "capacity": 9},
     ]},

    # Regional tertiary. Deliberately far from the origin (~150 km) so it is
    # never the *proximity* winner for a first review, but it is where the
    # senior consultants are - which is exactly the point of an escalation path.
    {"id": "h5", "name": "Regional Medical College", "district": "State Capital - Metro", "type": "Medical College",
     "lat": 26.85, "lng": 78.35, "icu_total": 10, "icu": 10,
     "specialties": {"general_medicine", "hematologist", "cardiologist", "pediatrician", "general_surgeon"},
     "senior_specialties": {"general_medicine", "cardiologist", "hematologist", "pediatrician", "general_surgeon"},
     "stock": {"paracetamol": 300, "oral_rehydration": 150, "doxycycline": 70, "ceftriaxone": 60,
               "platelet_concentrate": 45, "ringer_lactate": 110, "insulin_glargine": 60,
               "aspirin": 80, "streptokinase": 18},
     "doctors": [
         {"name": "Dr. Kulkarni", "specialty": "cardiologist", "senior": True, "load": 5, "capacity": 16},
         {"name": "Dr. Deshmukh", "specialty": "hematologist", "senior": True, "load": 3, "capacity": 16},
         {"name": "Dr. Sundaram", "specialty": "general_surgeon", "senior": True, "load": 2, "capacity": 12},
         {"name": "Dr. Iqbal", "specialty": "pediatrician", "senior": True, "load": 1, "capacity": 12},
         # A senior general physician, without whom `general_medicine` claiming
         # `senior: True` in SPECIALTIES above was a lie the roster could not
         # keep: `facilities_with(..., senior_only=True)` returned an empty list,
         # so escalating any of the eight routine/general cases answered 409
         # `no_senior_available` for a tier the registry said existed. The
         # registry and the roster now agree, which is the invariant that
         # matters - see test_specialty_senior_flag_matches_the_roster.
         {"name": "Dr. Venkataraman", "specialty": "general_medicine", "senior": True, "load": 2, "capacity": 14},
     ]},
]


def by_id(hospital_id: str) -> Optional[dict]:
    return next((h for h in hospitals if h["id"] == hospital_id), None)


def doctors_of(hospital: dict, specialty: str, senior_only: bool = False) -> list:
    """Doctors at this facility who can take a case in `specialty`.

    `senior_only=True` is the escalation gate: it returns only consultants, so
    the caller can prove a real senior reviewer exists before re-routing a case
    rather than bouncing it to the patient.
    """
    return [d for d in hospital["doctors"]
            if d["specialty"] == specialty and (d["senior"] or not senior_only)]


def facilities_with(specialty: str, senior_only: bool = False) -> list:
    """Every facility able to take a case in `specialty`, nearest first.

    Sorted by distance so every caller that iterates eligible facilities sees
    them in the same clinically-sensible order.
    """
    out = [h for h in hospitals
           if (specialty in h["senior_specialties"] if senior_only
               else specialty in h["specialties"])]
    return sorted(out, key=distance_from_origin)


def specialty_label(specialty: str) -> str:
    return SPECIALTIES.get(specialty, {}).get("queue", specialty)


def resolve_specialty(requested: str | None) -> str:
    """Map the model's `none` to a real queue.

    "No specialty needed" still needs *a* doctor, so it becomes general
    medicine. Falling through to a literal 'none' would mean cases with nobody
    to review them, which is precisely the failure this product exists to fix.
    """
    if not requested or requested == "none":
        return DEFAULT_SPECIALTY
    return requested


def stock_of(hospital: dict, medicine: str) -> int:
    if medicine not in medicines_catalog:
        raise KeyError(f"{medicine!r} is not in medicines_catalog")
    return hospital["stock"].get(medicine, 0)


def take(hospital: dict, medicine: str, qty: int) -> None:
    """Remove `qty` units. Raises rather than silently clamping - a reservation
    that quietly under-allocates is how a patient gets routed to a facility
    that cannot actually treat them."""
    available = stock_of(hospital, medicine)
    if qty > available:
        raise ValueError(
            f"{hospital['name']} has {available} {medicine}, cannot take {qty}"
        )
    hospital["stock"][medicine] = available - qty


def give_back(hospital: dict, medicine: str, qty: int) -> None:
    hospital["stock"][medicine] = stock_of(hospital, medicine) + qty


def distance_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    """Great-circle distance in km."""
    r = 6371.0
    d_lat, d_lng = math.radians(b_lat - a_lat), math.radians(b_lng - a_lng)
    h = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat))
         * math.sin(d_lng / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(h))


def distance_from_origin(hospital: dict) -> float:
    return distance_km(PATIENT_ORIGIN["lat"], PATIENT_ORIGIN["lng"],
                       hospital["lat"], hospital["lng"])


# --- Dropdown shortcut cases (Agent 1's rule-based fallback path) -------------
# `platelets` is a count of platelet_concentrate units, kept alongside `icu`
# so the fallback emits the same shape the LLM path does.
#
# The three queue-recommendation keys mirror TriageResult's, so both Agent 1
# paths produce one `need` shape downstream (D-06). They are advisory: the
# queue engine derives priority from severity alone, and a human doctor makes
# the actual visit/escalate call.
case_types = {
    "normal":   {"label": "Routine fever checkup",      "severity": "Green",  "icu": 0, "platelets": 0,
                 "specialist": "none", "medicines": {"paracetamol": 2},
                 "physical_visit": False, "escalation": False,
                 "recommended_action": "Remote review, oral fluids, review in 48h"},

    "moderate": {"label": "Dengue - moderate",          "severity": "Yellow", "icu": 0, "platelets": 2,
                 "specialist": "hematologist", "medicines": {"oral_rehydration": 3, "paracetamol": 2},
                 "physical_visit": True, "escalation": False,
                 "recommended_action": "In-person review within 24h, ward admission"},

    "severe":   {"label": "Dengue - severe (critical)", "severity": "Red",    "icu": 1, "platelets": 5,
                 "specialist": "hematologist", "medicines": {"platelet_concentrate": 5, "ringer_lactate": 3},
                 "physical_visit": True, "escalation": True,
                 "recommended_action": "Immediate admission, senior haematology review"},

    "cardiac":  {"label": "Acute cardiac event",        "severity": "Red",    "icu": 1, "platelets": 0,
                  "specialist": "cardiologist", "medicines": {"aspirin": 1, "streptokinase": 1},
                  "physical_visit": True, "escalation": True,
                  "recommended_action": "Immediate admission, senior cardiology review"},

    "child_fever": {"label": "Paediatric febrile illness", "severity": "Yellow", "icu": 0, "platelets": 0,
                    "specialist": "pediatrician", "medicines": {"paracetamol": 2, "oral_rehydration": 2},
                    "physical_visit": True, "escalation": False,
                    "recommended_action": "Paediatric review within 6h"},

    "child_severe": {"label": "Paediatric severe dehydration", "severity": "Red", "icu": 1, "platelets": 0,
                     "specialist": "pediatrician", "medicines": {"ringer_lactate": 3, "oral_rehydration": 3},
                     "physical_visit": True, "escalation": True,
                     "recommended_action": "Immediate paediatric admission, senior review"},

    "anemia":   {"label": "Severe anaemia",             "severity": "Yellow", "icu": 0, "platelets": 2,
                 "specialist": "hematologist", "medicines": {"oral_rehydration": 2, "paracetamol": 2},
                 "physical_visit": True, "escalation": False,
                 "recommended_action": "Haematology review, transfusion assessment"},

    "trauma":   {"label": "Polytrauma - needs surgery", "severity": "Red",    "icu": 1, "platelets": 3,
                 "specialist": "general_surgeon", "medicines": {"ringer_lactate": 3, "aspirin": 1},
                 "physical_visit": True, "escalation": True,
                 "recommended_action": "Surgical emergency, theatre within 1h"},

    "chronic":  {"label": "Chronic condition review",    "severity": "Green",  "icu": 0, "platelets": 0,
                 "specialist": "general_medicine", "medicines": {"paracetamol": 2},
                 "physical_visit": False, "escalation": False,
                 "recommended_action": "Routine review at next OPD"},
}

# --- Seeded consumption history (Agent 4's forecast input) -------------------
HISTORY_DAYS = 30


def _seed_history() -> dict:
    """Deterministic 30-day daily draw per facility per medicine.

    Seeded so eval runs and screenshots are reproducible. The urban facility
    draws more of everything; rural facilities are low and flat, which is what
    makes the interesting PHC stock-out predictable rather than random.
    """
    rng = random.Random(1337)
    history: dict = {}
    for h in hospitals:
        scale = 1.8 if h["type"] == "District Hospital" and h["id"] == "h3" else (
            0.6 if h["type"] == "PHC" else 0.9)
        per_med = {}
        for med, meta in medicines_catalog.items():
            base = max(0.4, meta["reorder_threshold"] / 8.0) * scale
            series = []
            for day in range(HISTORY_DAYS):
                weekly = 1.35 if day % 7 >= 5 else 1.0  # weekend surge
                drift = 1.0 + (day / HISTORY_DAYS) * 0.25  # slow upward drift
                series.append(round(base * weekly * drift * rng.uniform(0.7, 1.3), 2))
            per_med[med] = series
        history[h["id"]] = per_med
    return history


consumption_history = _seed_history()

patients: list = []
_next_id = [1]


def next_patient_id() -> int:
    pid = _next_id[0]
    _next_id[0] += 1
    return pid


# --- Queue time -------------------------------------------------------------
# The queue's "waiting time" is a real number the patient-facing portal shows,
# so it needs a clock. A single monotonic-ish source, injectable for tests.
#
# Deliberately NOT wall-clock reads scattered through the code: one function
# means "now" is defined in one place, tests can freeze it, and a demo can
# fast-forward the queue without sleeping.
_queue_clock = [time.time()]


def now() -> float:
    return _queue_clock[0]


def set_clock(value: float) -> None:
    """Set the queue clock explicitly. Test and demo use only."""
    _queue_clock[0] = value


def advance_clock(seconds: float) -> float:
    """Move the queue clock forward. Returns the new time.

    This is how the seeded backlog gets realistic waiting times without the
    process having to actually wait.
    """
    _queue_clock[0] += seconds
    return _queue_clock[0]


def minutes_since(timestamp: float) -> float:
    return round(max(0.0, (now() - timestamp) / 60.0), 1)


# --- Seeded backlog ---------------------------------------------------------
# A demo that starts with an empty queue cannot show a queue. This seeds a
# handful of already-triaged cases so the doctor queue, the specialist queue
# and the waiting-time column all have something in them on first load.
#
# These are inserted as *records*, not run through the pipeline: they carry a
# pre-computed need and a synthetic arrival time, so they cost no LLM calls and
# cannot fail in a way that takes the server down at boot. They are marked
# `seed=True` so the UI can label them and a reviewer is never fooled into
# thinking a real report was processed.
#
# Only the arrival times are randomised, and from a fixed seed, so the demo is
# reproducible: the same waiting times appear on every boot.
SEED_CASES = [
    # (name, case_type, minutes_ago)
    # A mix of arrival times, ages, and case types so every queue has real
    # content on first load: the doctor queue needs several patients, the
    # specialist queue needs escalations, and the portal needs a case that is
    # old enough to have a visible wait.
    ("Sunita Devi",    "moderate",     4),
    ("Rakesh Kumar",   "normal",      11),
    ("Priya Nair",     "severe",       2),
    ("Anil Sharma",    "moderate",    26),
    ("Farida Begum",   "normal",      38),
    ("Ramesh Yadav",   "cardiac",      1),
    ("Kavita Pawar",   "moderate",    52),
    ("Deepak Sahu",    "normal",      67),
    ("Meena Kumari",   "severe",       7),
    ("Suresh Patel",   "normal",      83),
    ("Arjun Menon",    "child_fever", 15),
    ("Lakshmi Rao",    "child_severe",  3),
    ("Hasan Ali",      "anemia",      44),
    ("Binta Begum",    "child_fever",  9),
    ("Vikram Singh",   "trauma",       1),
    ("Nusrat Jahan",   "normal",     120),
    ("Gopal Reddy",    "chronic",     155),
    ("Zoya Khan",      "moderate",    73),
    ("Ramesh Iyer",    "cardiac",     31),
    ("Salma Bano",     "anemia",      96),
    ("Tariq Ahmed",    "child_fever", 58),
    ("Maya Ghosh",     "chronic",    185),
    ("Devendra Patil", "trauma",       6),
    ("Anjali Verma",   "normal",     142),
]


def seed_patients() -> int:
    """Populate the queue with pre-triaged demo cases.

    Called from main.py at boot, guarded so a reload does not re-seed on top of
    a queue that is already populated. Returns the number of cases inserted.
    """
    if patients:
        return 0

    from agents import agent1_triage, agent2_allocator, agent3_routing

    rng = random.Random(4242)
    inserted = 0
    for name, case_type, mins_ago in SEED_CASES:
        try:
            need, _ = agent1_triage.from_rules(case_type)
        except ValueError:
            continue

        eligible, _ = agent2_allocator.run(need)
        pid = next_patient_id()
        hospital, doctor, _, _ = agent3_routing.run(eligible, need, patient_id=pid)

        record = {
            "id": pid,
            "name": name,
            "case_label": need["label"],
            "severity": need["severity"],
            "specialty": resolve_specialty(need["specialist"]),
            "hospital": hospital["name"] if hospital else None,
            "hospital_id": hospital["id"] if hospital else None,
            "doctor": doctor["name"] if doctor else None,
            "doctor_specialty": doctor["specialty"] if doctor else None,
            # An unroutable case is NOT an escalated one. Escalation is a
            # clinical act - a doctor handing a case to a senior consultant -
            # and it needs a doctor. A case with no eligible facility at all is
            # `unassigned`, and it stays in the network queue so it keeps
            # waiting visibly instead of disappearing until someone adds
            # capacity.
            "status": "awaiting_review" if doctor else "unassigned",
            "triage_source": need["source"],
            "confidence": need["confidence"],
            "red_flags": need["red_flags"],
            "ai_recommendation": {
                "physical_visit": need["physical_visit"],
                "specialist_escalation": need["escalation"],
                "action": need["recommended_action"],
            },
            "reservation": agent3_routing.reservation(pid),
            # Queue bookkeeping.
            "enqueued_at": now() - mins_ago * 60 - rng.uniform(0, 120),
            "decided_at": None,
            "decision": None,
            "decision_note": None,
            "escalated_from": None,
            "report_text": None,
            "seed": True,
            # Carried for the same reason the live path carries it: the
            # decision endpoint commits exactly what triage asked for. Omitting
            # it here made every seeded case commit zero resources - the
            # `visit_required` path read `p.get("need") or {}`, took nothing,
            # and still reported the case as `admitted` with `committed: true`.
            # Since the 24 seeded cases are the app's default state, that was
            # the main path, not an edge case.
            "need": need,
        }
        patients.append(record)
        inserted += 1

    # Seeded records are appended oldest-arrival-first so the queue's natural
    # order already matches what a real backlog would look like.
    patients.sort(key=lambda p: p["enqueued_at"])
    return inserted

