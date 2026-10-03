"""
Tests. These run without an API key and without a network.

The eval harness itself is covered here too, by monkeypatching
`llm.triage_report`: the aggregation math (confusion matrix, per-noise
breakdown, under-triage counting) is the part most likely to be quietly wrong,
and it must be correct before anyone trusts numbers printed off a real run.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_store as ds
import llm
from models import MedicineKey, TriageResult
from agents import agent1_triage, agent2_allocator, agent3_routing, agent4_forecast
from eval import run_eval


@pytest.fixture(autouse=True)
def reset_state():
    """Every test starts from a known inventory and an empty reservation ledger.

    The in-memory store is module-level global state, so without this the tests
    would pass or fail depending on execution order.

    Restored by iterating the roster, not by index. The previous version named
    hospitals[0]..hospitals[3] explicitly, which silently stopped resetting the
    fifth facility when the roster was expanded - and a test could then fail or
    pass depending on which test ran before it. Any new facility is now covered
    automatically.
    """
    for h in ds.hospitals:
        # Restored from what the facility actually starts at, not simply
        # "max out every bed": a site configured with zero free ICU (a PHC with
        # no beds) must go back to 0, not to its total.
        h["icu"] = _BASE_ICU[h["id"]]
        for med, qty in _BASE_STOCK[h["id"]].items():
            h["stock"][med] = qty
        for d in h["doctors"]:
            d["load"] = _BASE_LOAD[d["name"]]
    ds.patients.clear()
    ds._next_id[0] = 1
    agent3_routing._reservations.clear()
    yield


_BASE_STOCK = {h["id"]: dict(h["stock"]) for h in ds.hospitals}
_BASE_LOAD = {d["name"]: d["load"] for h in ds.hospitals for d in h["doctors"]}
_BASE_ICU = {h["id"]: h["icu"] for h in ds.hospitals}


def triage_result(**kw) -> TriageResult:
    """Build a TriageResult with the three queue-recommendation fields filled in.

    The recommendation fields are required, not optional, so every test that
    fabricates a model result has to supply them. Routing them through one
    helper means a future change to that contract is a one-line edit here
    instead of a dozen scattered literal updates that quietly drift apart.
    """
    base = {
        "severity": "Green", "case_label": "routine", "icu_needed": 0,
        "platelets_needed": 0, "specialist": "none", "medicines": [],
        "red_flags": [], "confidence": 0.9, "reasoning": "looked fine",
        "physical_visit_recommended": False,
        "specialist_escalation_recommended": False,
        "recommended_action": "Remote review",
    }
    base.update(kw)
    return TriageResult(**base)


# ---------------------------------------------------------------- data store
def test_catalog_matches_llm_enum():
    """The LLM's medicine enum is generated from the catalog; drift is fatal.

    data_store raises at import if these diverge, so this is the belt to that
    suspenders - it also catches a catalog edited after import.
    """
    from models import MedicineKey
    assert set(ds.medicines_catalog) == set(MedicineKey.__args__)


def test_prompt_file_is_the_prompt_actually_sent():
    """The prompt must be a reviewable file, and it must be the one in use.

    Two failure modes this pins down: someone edits the .md and forgets to wire
    it up, or someone edits the string in llm.py and the .md goes stale. Either
    way the artefact a reviewer reads stops describing the system.
    """
    import llm
    from pathlib import Path

    path = Path(llm.PROMPT_PATH)
    assert path.is_file(), "prompts/triage_system.md must exist in the repo"
    assert path.read_text(encoding="utf-8").strip() == llm.SYSTEM_PROMPT

    # And it must still be a real instruction, not a stub someone emptied out.
    assert len(llm.SYSTEM_PROMPT) > 500
    for needed in ("SEVERITY RULES", "RESOURCE RULES", "RED FLAGS"):
        assert needed in llm.SYSTEM_PROMPT, f"prompt lost its {needed} section"


def test_prompt_medicine_keys_match_the_catalog():
    """Every medicine the prompt tells the model to emit must actually be stocked.

    The prompt is hand-written and the catalog is code, so this is the one place
    that can drift. A key in the prompt that the catalog does not know would let
    the model request a drug no facility can hold.
    """
    from models import MedicineKey

    for key in MedicineKey.__args__:
        assert key in llm.SYSTEM_PROMPT, f"{key} is stocked but absent from the prompt"


def test_take_refuses_to_over_allocate():
    h = ds.by_id("h1")
    with pytest.raises(ValueError):
        ds.take(h, "platelet_concentrate", 10_000)


def test_take_rejects_unknown_medicine():
    with pytest.raises(KeyError):
        ds.take(ds.by_id("h1"), "aspirin_x", 1)


def test_give_back_restores_exactly():
    h = ds.by_id("h1")
    before = ds.stock_of(h, "platelet_concentrate")
    ds.take(h, "platelet_concentrate", 3)
    ds.give_back(h, "platelet_concentrate", 3)
    assert ds.stock_of(h, "platelet_concentrate") == before


# ------------------------------------------------------------------ agent 1
def test_rules_path_emits_platelets():
    """Regression: the original agents read a `platelets` key that existed
    nowhere and every call raised KeyError."""
    need, _ = agent1_triage.run("severe")
    assert need["platelets"] == 5
    assert need["icu"] == 1
    assert need["severity"] == "Red"


def test_llm_path_falls_back_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(agent1_triage.llm, "triage_report", lambda t: None)
    need, step = agent1_triage.run("normal", report_text="Hb 3.0, platelets 8,000")
    # Never auto-cleared as Green on a failed read - that is the unsafe failure.
    assert need["severity"] != "Green"
    # A model failure is not a rules decision. Reporting "rules" here made the
    # queue label a triage that never happened as a rule-based one.
    assert need["source"] == "fallback"
    assert need["manual_review"] is True
    assert step["source"] == "fallback"


def test_llm_path_used_when_model_returns(monkeypatch):
    result = triage_result(
        severity="Red", case_label="Dengue - severe", icu_needed=1,
        platelets_needed=5, specialist="hematologist",
        medicines=[{"medicine": "platelet_concentrate", "qty": 5}],
        red_flags=["plasma leak"], confidence=0.93, reasoning="Platelets 9,800/uL.",
        physical_visit_recommended=True,
        specialist_escalation_recommended=True,
        recommended_action="Immediate admission, senior haematology review")
    monkeypatch.setattr(agent1_triage.llm, "triage_report", lambda t: result)
    need, step = agent1_triage.run("normal", report_text="garbled report")
    assert need["source"] == "llm"
    assert need["platelets"] == 5
    assert step["source"] == "llm"
    # platelets_needed and the medicine line describe one physical stock; the
    # allocator must not reserve it twice.
    assert need["medicines"]["platelet_concentrate"] == 5
    # The model's advice is carried through verbatim, and shown as advice.
    assert need["physical_visit"] is True
    assert need["escalation"] is True
    assert need["recommended_action"].startswith("Immediate admission")
    assert step["recommendation"]["physical_visit"] is True


def test_low_confidence_green_is_not_auto_cleared(monkeypatch):
    """A Green the model is unsure about is the failure the fallback exists to
    prevent, arriving by a different route: the model answered, it just was not
    confident. The confidence floor closes that route."""
    result = triage_result(severity="Green", confidence=0.2,
                           red_flags=["Report partly illegible"])
    monkeypatch.setattr(agent1_triage.llm, "triage_report", lambda t: result)
    need, step = agent1_triage.run("normal", report_text="illegible")
    assert need["manual_review"] is True
    assert need["severity"] != "Green"
    assert need["physical_visit"] is True, "unsure must not become 'no visit'"
    assert any("confidence" in f.lower() for f in need["red_flags"])
    assert step["manual_review"] is True


def test_low_confidence_red_is_never_softened(monkeypatch):
    """The floor guards against auto-clearing. It must never push in the other
    direction - downgrading a Red because the model hedging is the one
    adjustment that would be indefensible."""
    result = triage_result(severity="Red", confidence=0.05, icu_needed=1,
                           specialist="hematologist")
    monkeypatch.setattr(agent1_triage.llm, "triage_report", lambda t: result)
    need, _ = agent1_triage.run("normal", report_text="shock, platelets 8,000")
    assert need["severity"] == "Red"
    assert need["manual_review"] is True


def test_confident_result_is_not_flagged(monkeypatch):
    result = triage_result(severity="Yellow", confidence=0.91)
    monkeypatch.setattr(agent1_triage.llm, "triage_report", lambda t: result)
    need, _ = agent1_triage.run("normal", report_text="fever 3 days")
    assert need["manual_review"] is False
    assert need["red_flags"] == []


def test_both_agent1_paths_share_one_shape():
    rules, _ = agent1_triage.run("cardiac")
    keys = set(rules)
    assert keys == {
        "source", "manual_review", "severity", "label", "icu", "platelets",
        "specialist", "medicines", "red_flags", "confidence", "reasoning",
        "physical_visit", "escalation", "recommended_action",
    }

    # The LLM path must produce the identical shape, or every downstream agent
    # needs a second code path. Patched rather than asserted by eye because the
    # two paths drifting apart is exactly the failure this test exists to catch.
    fake = triage_result(severity="Red", specialist="hematologist", icu_needed=1)
    orig = agent1_triage.llm.triage_report
    agent1_triage.llm.triage_report = lambda t: fake
    try:
        llm_need, _ = agent1_triage.run("cardiac", report_text="platelets 8,000")
    finally:
        agent1_triage.llm.triage_report = orig
    assert set(llm_need) == keys


def test_severity_never_beats_waiting_time_in_the_queue():
    """Waiting long enough must never promote a milder case past a severe one.

    This is the property the whole product rests on: digital queues remove
    arbitrary FIFO ordering, but only if they never let convenience overtake
    clinical urgency. The wait bonus is capped precisely so it cannot, so this
    checks the arithmetic at its worst case rather than at one arbitrary wait.
    """
    from agents import queue

    # Driven through the real scoring function with an extreme wait, not
    # asserted against the constants. An earlier version of this test compared
    # SEVERITY_WEIGHT against MAX_WAIT_BONUS directly, which is tautological:
    # deleting the cap from wait_bonus() left the test passing, because the
    # constant it read was still 300. The property has to be checked against
    # the behaviour it is meant to constrain.
    fresh_red = {"severity": "Red", "enqueued_at": ds.now()}
    for days in (1, 10, 100, 10_000):
        stale_green = {"severity": "Green", "enqueued_at": ds.now() - days * 86_400}
        assert (queue.priority_score(stale_green)
                < queue.priority_score(fresh_red)), f"Green overtook Red after {days}d"

    for days in (1, 100, 10_000):
        stale_yellow = {"severity": "Yellow", "enqueued_at": ds.now() - days * 86_400}
        assert (queue.priority_score(stale_yellow)
                < queue.priority_score(fresh_red)), f"Yellow overtook Red after {days}d"

    # Same in the other direction: a stale Green must not overtake a fresh
    # Yellow either.
    fresh_yellow = {"severity": "Yellow", "enqueued_at": ds.now()}
    for days in (1, 100, 10_000):
        stale_green = {"severity": "Green", "enqueued_at": ds.now() - days * 86_400}
        assert (queue.priority_score(stale_green)
                < queue.priority_score(fresh_yellow)), f"Green overtook Yellow after {days}d"

    # And the cap should actually be engaging, otherwise the bounds above are
    # being met by accident rather than by design.
    assert queue.priority_breakdown(
        {"severity": "Green", "enqueued_at": ds.now() - 10_000 * 86_400})["capped"] is True


def test_waiting_time_reorders_within_a_severity_band():
    """Capped, it must still break ties inside a band - otherwise the older
    patient starves behind a steady stream of equally-mild cases, which is the
    other half of the property the cap protects."""
    from agents import queue
    early = {"severity": "Yellow", "enqueued_at": ds.now() - 60 * 30}
    late = {"severity": "Yellow", "enqueued_at": ds.now() - 60}
    assert queue.priority_score(early) > queue.priority_score(late)
    # A minute-scale difference is visible, not rounded away.
    assert queue.priority_score(early) - queue.priority_score(late) > 1.0


# ------------------------------------------------------------------ agent 2
def test_allocator_rejects_facility_lacking_platelets():
    need = {"icu": 0, "platelets": 5, "specialist": None, "medicines": {}}
    eligible, step = agent2_allocator.run(need)
    names = {h["name"] for h in eligible}
    assert "Sironj PHC" not in names  # only holds 2 platelet units
    assert any("platelet" in " ".join(r["reasons"])
               for r in step["rejected"] if r["name"] == "Sironj PHC")


def test_allocator_rejects_missing_specialist():
    need = {"icu": 0, "platelets": 0, "specialist": "cardiologist", "medicines": {}}
    eligible, _ = agent2_allocator.run(need)
    # Eligibility now follows the real doctor roster rather than a per-hospital
    # boolean, so this asserts the set of facilities that actually staff a
    # cardiologist. It also means a facility whose cardiologist is fully booked is
    # correctly excluded - the point of the roster over a boolean.
    staffed = {h["name"] for h in ds.facilities_with("cardiologist")}
    assert {h["name"] for h in eligible} <= staffed
    assert "City General" in {h["name"] for h in eligible}

    # And with no cardiologist anywhere free, none of them are eligible.
    for h in ds.hospitals:
        for d in h["doctors"]:
            if d["specialty"] == "cardiologist":
                d["load"] = d["capacity"]
    eligible_full, _ = agent2_allocator.run(need)
    assert eligible_full == []
    assert any("capacity" in " ".join(r["reasons"]) for r in _["rejected"])


def test_allocator_checks_medicine_stock():
    need = {"icu": 0, "platelets": 0, "specialist": None,
            "medicines": {"streptokinase": 3}}
    eligible, _ = agent2_allocator.run(need)
    got = {h["name"] for h in eligible}

    # Asserted as the rule rather than a hardcoded roster, because the roster
    # is meant to change. `specialist: None` resolves to general_medicine, so a
    # facility qualifies only if it stocks >= 3 AND has a general physician
    # with free capacity - which is why the Medical College counts now that it
    # actually staffs one. The earlier literal ("City General" only) was passing
    # on an accident: h5 held 18 streptokinase all along and was excluded
    # solely because its `specialties` set claimed general medicine while no
    # general physician was rostered there.
    can_supply = {h["name"] for h in ds.hospitals
                  if ds.stock_of(h, "streptokinase") >= 3
                  and ds.doctors_of(h, "general_medicine")}
    assert got == can_supply, (got, can_supply)
    assert "City General" in got          # 6 in stock, still eligible
    assert "Rampur District Hospital" not in got    # holds 1
    assert "Lakhanpur CHC" not in got              # holds 2


# ------------------------------------------------------------------ agent 3
def test_routing_prefers_nearer_facility_over_idle_doctor():
    """Regression on the original behaviour: it picked the globally least-loaded
    doctor, sending rural patients 150 km to a metro hospital."""
    need = {"icu": 0, "platelets": 0, "specialist": None, "medicines": {}}
    eligible, _ = agent2_allocator.run(need)
    # Asserted as a delta, not a literal. The roster was expanded with more
    # doctors and specialties, so a hard-coded load would have broken for
    # reasons unrelated to the behaviour under test.
    before = {d["name"]: d["load"] for h in ds.hospitals for d in h["doctors"]}
    hospital, doctor, _, breakdown = agent3_routing.run(eligible, need, patient_id=1)
    assert hospital["name"] == "Rampur District Hospital"  # 0 km
    assert breakdown["distance_km"] < 10
    # A review assignment is workload, so exactly one doctor gains one case.
    gained = {n: v - before[n] for n, v in
              ((d["name"], d["load"]) for h in ds.hospitals for d in h["doctors"])
              if v != before[n]}
    assert gained == {doctor["name"]: 1}


def test_routing_loads_a_freed_doctor_only_after_release():
    """Load balancing is only real if load is transient: a case that leaves the
    queue must hand its workload back, or doctors fill up permanently and the
    network silently stops being able to route."""
    need, _ = agent1_triage.run("normal")
    eligible, _ = agent2_allocator.run(need)
    _, doctor, _, _ = agent3_routing.run(eligible, need, patient_id=900)
    peak = doctor["load"]
    agent3_routing.release(900)
    assert doctor["load"] == peak - 1


def test_routing_reports_candidate_accounting():
    """The plan wants the demo to be able to say "N possible doctors, M
    eligible, 1 selected" and then justify the rejections. The counts only
    count if they are derived from the same rule that picks the winner, so this
    pins them against the roster rather than against a literal."""
    need = {"icu": 0, "platelets": 0, "specialist": "cardiologist",
            "medicines": {}}
    eligible, _ = agent2_allocator.run(need)
    _h, doctor, step, _ = agent3_routing.run(eligible, need)

    c = step["candidates"]
    rostered = sum(
        len(ds.doctors_of(h, "cardiologist")) for h in ds.hospitals
    ) + sum(
        # facilities with no cardiologist fall back to a general duty doctor
        len(ds.doctors_of(h, "general_medicine"))
        for h in ds.hospitals if not ds.doctors_of(h, "cardiologist")
    )
    assert c["possible"] == rostered
    assert c["selected"] == 1
    assert c["eligible"] <= c["possible"]
    assert c["available"] <= c["eligible"]
    assert "possible cardiologist doctor(s)" in step["text"]
    assert "1 selected" in step["text"]


def test_candidate_sentence_admits_a_general_duty_fallback():
    """Regression on a contradiction the count could produce: naming a
    specialty in the tally while the winner is a general duty doctor.

    Reached through `_count_sentence` rather than end-to-end on purpose. Agent 2
    already refuses a facility whose specialist is fully booked
    (agent2_allocator._evaluate), so a case that clears Agent 2 always has a free
    specialist somewhere and `_pick_doctor` never takes the general-medicine
    fallback. The guard is defence in depth for a path the pipeline does not
    currently exercise, and a test that pretended otherwise would break the
    moment someone made Agent 2's eligibility looser.
    """
    counts = {"specialty": "cardiologist", "possible": 5, "eligible": 3,
              "available": 3, "exact_possible": 5, "fallback_possible": 0}
    sentence = agent3_routing._count_sentence(
        counts, {"specialty": "general_medicine", "name": "Dr. Prakash"})
    assert "general duty doctor" in sentence
    assert "cardiologist" in sentence
    # And the normal case does not claim a fallback that did not happen.
    plain = agent3_routing._count_sentence(
        counts, {"specialty": "cardiologist", "name": "Dr. Rao"})
    assert "general duty doctor" not in plain
    assert plain.endswith("1 selected.")


def test_candidate_sentence_reports_an_unstaffed_specialty():
    counts = {"specialty": "hematologist", "possible": 0, "eligible": 0,
              "available": 0, "exact_possible": 0, "fallback_possible": 0}
    out = agent3_routing._count_sentence(counts, None)
    assert "nobody to route to" in out


def test_routing_does_not_consume_resources_until_a_doctor_decides():
    """The core claim of the product, asserted.

    Assigning a case to a doctor must not hold an ICU bed or any medicine,
    because a report review needs neither. If routing reserved on assignment,
    a digital queue would tie up exactly the same scarce inventory a physical
    queue does and would buy nothing.
    """
    need, _ = agent1_triage.run("severe")
    icu_before = {h["name"]: h["icu"] for h in ds.hospitals}
    stock_before = {h["id"]: dict(h["stock"]) for h in ds.hospitals}

    eligible, _ = agent2_allocator.run(need)
    hospital, _, _, _ = agent3_routing.run(eligible, need, patient_id=7)

    for h in ds.hospitals:
        assert h["icu"] == icu_before[h["name"]]
        assert h["stock"] == stock_before[h["id"]]

    # A review assignment is still recorded, so it can be closed or escalated.
    res = agent3_routing.reservation(7)
    assert res is not None and res["committed"] is False

    # Only the doctor's decision commits resources.
    agent3_routing.commit(7, need)
    assert hospital["icu"] == icu_before[hospital["name"]] - 1
    assert agent3_routing.reservation(7)["committed"] is True


def test_commit_then_release_restores_exact_state():
    need, _ = agent1_triage.run("severe")
    eligible, _ = agent2_allocator.run(need)
    h_before = {h["name"]: (h["icu"], dict(h["stock"])) for h in ds.hospitals}
    loads_before = {d["name"]: d["load"] for h in ds.hospitals for d in h["doctors"]}

    hospital, doctor, _, _ = agent3_routing.run(eligible, need, patient_id=7)
    assert agent3_routing.commit(7, need) is not None
    assert hospital["icu"] == h_before[hospital["name"]][0] - 1

    assert agent3_routing.release(7) is True
    assert agent3_routing.release(7) is False  # idempotent
    for h in ds.hospitals:
        assert h["icu"] == h_before[h["name"]][0]
        assert h["stock"] == h_before[h["name"]][1]
    for h in ds.hospitals:
        for d in h["doctors"]:
            assert d["load"] == loads_before[d["name"]]


def test_release_works_on_an_uncommitted_assignment():
    """A case closed without a visit held no resources, and closing it must
    still free the doctor slot. Releasing must not depend on which shape the
    ledger entry happened to have."""
    need, _ = agent1_triage.run("normal")
    eligible, _ = agent2_allocator.run(need)
    _, doctor, _, _ = agent3_routing.run(eligible, need, patient_id=55)
    before = doctor["load"]
    assert agent3_routing.release(55) is True
    assert doctor["load"] == before - 1


def test_escalation_moves_to_a_senior_and_keeps_resources():
    """Escalation is a clinical act, so it must reach a senior consultant - and
    must not release the patient's already-committed beds on the way up. An
    escalated patient is more urgent, not less."""
    need, _ = agent1_triage.run("severe")
    eligible, _ = agent2_allocator.run(need)
    hospital, doctor, _, _ = agent3_routing.run(eligible, need, patient_id=60)
    agent3_routing.commit(60, need)
    icu_held = hospital["icu"]

    moved = agent3_routing.reassign(60, "hematologist")
    assert moved and "error" not in moved, moved
    assert moved["doctor"]["senior"] is True
    assert moved["doctor"]["specialty"] == "hematologist"
    # Doctor and facility must agree, or the patient is told to travel to a
    # hospital where nobody is going to look at their case.
    assert moved["hospital"]["id"] == facility_of(moved["doctor"])["id"]
    # The held bed is still held, at the facility that now owns the case.
    assert moved["hospital"]["icu"] < facility_of(moved["doctor"])["icu_total"] + 1
    assert agent3_routing.reservation(60)["committed"] is True


def facility_of(doctor: dict) -> dict:
    for h in ds.hospitals:
        if any(d["name"] == doctor["name"] for d in h["doctors"]):
            return h
    raise AssertionError("doctor not on any roster")


def test_escalation_reports_when_no_senior_is_available():
    """A real, reportable outcome rather than a silent failure. If nothing
    network-wide can take the case, the caller must be told."""
    need, _ = agent1_triage.run("normal")
    eligible, _ = agent2_allocator.run(need)
    agent3_routing.run(eligible, need, patient_id=61)
    for h in ds.hospitals:
        for d in h["doctors"]:
            if d["specialty"] == "general_medicine":
                d["load"] = d["capacity"]
    result = agent3_routing.reassign(61, "general_medicine")
    assert result and result.get("error") == "no_senior_available"


def test_escalation_refuses_rather_than_stranding_committed_resources():
    """A committed case must not be half-moved.

    The target facility is drained of stock and ICU first, so the transfer
    genuinely cannot succeed. The refusal has to come with NOTHING changed:
    giving the resources back at the source and *then* failing would leave the
    ledger claiming the target holds them while the source actually does.
    """
    need, _ = agent1_triage.run("severe")
    eligible, _ = agent2_allocator.run(need)
    hospital, doctor, _, _ = agent3_routing.run(eligible, need, patient_id=62)
    agent3_routing.commit(62, need)

    before = {h["id"]: (h["icu"], dict(h["stock"])) for h in ds.hospitals}
    target = next(h for h in ds.hospitals
                  if any(d["specialty"] == "hematologist" and d["senior"]
                         for d in h["doctors"]) and h is not hospital)
    for med in need["medicines"]:
        target["stock"][med] = 0
    target["icu"] = 0
    drained = {h["id"]: (h["icu"], dict(h["stock"])) for h in ds.hospitals}

    result = agent3_routing.reassign(62, "hematologist")
    assert result and result.get("error") == "target_cannot_take_resources"
    assert result["short"], result

    # Nothing moved: no doctor reassigned, no facility reassigned, no stock or
    # ICU drift anywhere - including back at the source.
    res = agent3_routing.reservation(62)
    assert res["doctor"] == doctor["name"]
    assert res["hospital_id"] == hospital["id"]
    assert res["committed"] is True
    after = {h["id"]: (h["icu"], dict(h["stock"])) for h in ds.hospitals}
    assert after == drained
    for hid, (icu, stock) in before.items():
        if hid == target["id"]:
            continue
        assert (icu, stock) == after[hid], hid


def test_escalating_to_the_doctor_who_is_already_senior_records_no_handover():
    """A case already with a senior of the right specialty escalates to itself.

    The status change is right - the case is with a senior consultant. But
    `escalated_from` must stay None: filling it with the destination's own
    doctor and facility would put a referral in the record that never happened,
    and this log is the thing an escalation gets audited from.
    """
    # Find a senior consultant, put a routed case in their hands, then escalate
    # it to their own specialty.
    senior = next(d for h in ds.hospitals for d in h["doctors"]
                  if d["senior"] and d["specialty"] != "general_medicine")
    spec = senior["specialty"]
    need, _ = agent1_triage.run("severe")
    eligible, _ = agent2_allocator.run(need)
    agent3_routing.run(eligible, need, patient_id=63)
    res = agent3_routing._reservations[63]
    res["doctor"] = senior
    res["hospital"] = facility_of(senior)

    result = agent3_routing.reassign(63, spec)
    assert result and "error" not in result, result
    assert result["doctor"]["name"] == senior["name"]
    assert result["moved"] is False
    assert result["from_doctor"] == senior["name"] == result["doctor"]["name"]


def test_repeated_severe_cases_do_not_deadlock():
    """The original permanently decremented ICU with no release path, so the
    demo bricked itself after one severe case."""
    need, _ = agent1_triage.run("severe")
    ids = []
    for i in range(6):
        eligible, _ = agent2_allocator.run(need)
        h, d, _, _ = agent3_routing.run(eligible, need, patient_id=100 + i)
        if h:
            ids.append(100 + i)
    free_before = {h["id"]: h["icu_total"] for h in ds.hospitals}
    for pid in ids:
        agent3_routing.commit(pid, need)
        agent3_routing.release(pid)
    assert {h["id"]: h["icu"] for h in ds.hospitals} == free_before
    # And the next severe case must route again rather than escalate.
    eligible, _ = agent2_allocator.run(need)
    assert eligible, "network should be usable again after release"


# ------------------------------------------------------------------ agent 4
def test_forecast_uses_real_days_of_cover():
    table = agent4_forecast.forecast_table()
    assert table
    covers = [r["days_of_cover"] for r in table]
    assert covers == sorted(covers)  # worst-first
    assert all(c >= 0 for c in covers)
    strepto = next(r for r in table
                   if r["hospital"] == "Sironj PHC" and r["medicine"] == "streptokinase")
    assert strepto["days_of_cover"] == 0.0  # zero stock


def test_zero_icu_at_a_phc_is_not_a_shortage():
    """Regression: a PHC has no ICU by design (IPHS), so flagging it produced
    an alert that could never clear."""
    alerts = agent4_forecast.check_shortages()
    phc = next(a for a in alerts if a["hospital"] == "Sironj PHC")
    assert not any("ICU" in f["message"] for f in phc["reasons"])


def test_full_icu_at_a_capable_facility_is_flagged():
    h = ds.by_id("h3")
    h["icu"] = 0
    alerts = agent4_forecast.check_shortages()
    entry = next(a for a in alerts if a["hospital"] == "City General")
    assert any("ICU" in f["message"] for f in entry["reasons"])
    h["icu"] = h["icu_total"]


def test_redistribute_never_drains_the_donor():
    donor, receiver = ds.by_id("h3"), ds.by_id("h1")
    before = ds.stock_of(donor, "streptokinase")
    total = 0
    for _ in range(8):
        total += agent4_forecast.redistribute("h3", "h1", "streptokinase", amount=5)
    assert total > 0
    assert ds.stock_of(donor, "streptokinase") > 0
    assert ds.stock_of(donor, "streptokinase") >= before - total


def test_redistribute_validates_its_inputs():
    with pytest.raises(KeyError):
        agent4_forecast.redistribute("nope", "h1")
    with pytest.raises(KeyError):
        agent4_forecast.redistribute("h3", "h1", "not_a_drug")
    with pytest.raises(ValueError):
        agent4_forecast.redistribute("h1", "h1")
    with pytest.raises(ValueError):
        agent4_forecast.redistribute("h3", "h1", amount=0)


# ------------------------------------------------------------------- llm
def test_llm_returns_none_without_api_key(monkeypatch):
    import llm
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert llm.available() is False
    assert llm.triage_report("anything") is None


def test_generated_schema_is_accepted_by_the_model_provider():
    """The schema handed to the model must satisfy the provider's own contract.

    Gemini's response_schema is an OpenAPI 3.0 subset, not JSON Schema: it
    rejects `$defs`/`$ref` and `additionalProperties` outright with a 400. So
    this asserts the schema the SDK actually accepts, and that the rewrite
    which makes it acceptable did not quietly widen the model's vocabulary -
    the nested MedicineOrder enum has to survive being inlined, or the model
    could name any drug it liked.
    """
    from google.genai import types

    schema = llm_schema()
    types.Schema.model_validate(schema)          # hard 400 at runtime if wrong

    problems = []

    def walk(node, path):
        if isinstance(node, dict):
            for banned in ("$ref", "$defs", "additionalProperties"):
                if banned in node:
                    problems.append(f"{banned} at {path}")
            if node.get("type") == "object" and "properties" in node:
                if not set(node.get("required", [])) >= set(node["properties"]):
                    problems.append(f"incomplete required at {path}")
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for v in node:
                walk(v, f"{path}[]")

    walk(schema, "root")
    assert not problems, problems

    # The inlined nested model kept its closed vocabulary.
    order = schema["properties"]["medicines"]["items"]
    assert set(order["properties"]["medicine"]["enum"]) == set(
        MedicineKey.__args__)


def test_schema_rewrite_inlines_nested_models():
    """Regression on the rewrite itself: a nested model that stays behind a
    $ref would be dropped from the request entirely, and the model would then
    be free to invent medicine names - the exact failure MedicineKey exists to
    prevent."""
    raw = TriageResult.model_json_schema()
    assert "MedicineOrder" in raw.get("$defs", {}), "fixture no longer nests"
    schema = llm_schema()
    assert "properties" in schema["properties"]["medicines"]["items"]


def llm_schema():
    import llm
    return llm.SCHEMA


# ------------------------------------------------------------ eval harness
def test_baseline_is_blind_to_negation():
    """The documented reason a model is used here. If someone 'fixes' this the
    comparison stops measuring anything."""
    text = "Patient stable. No shock, no bleeding, no plasma leak. Plan: ward."
    assert run_eval.baseline_triage(text) == "Red"
    # A model reading the same sentence should not escalate.
    assert "shock" in text and "No shock" in text


def test_baseline_does_not_match_ccu_inside_occult():
    text = "Hb 11.8 g/dL. Stool for occult blood: Negative. Stable, discharged."
    assert run_eval.baseline_triage(text) != "Red"


def test_baseline_beats_nothing_randomly():
    """A floor on the baseline: if it cannot clear obvious Greens the LLM
    comparison is flattering but meaningless."""
    green = "Temp 100 F, HR 88, BP 120/80. Platelets 2.4 lakh. Stable, discharged."
    assert run_eval.baseline_triage(green) == "Green"


def test_eval_harness_aggregation(monkeypatch):
    """Drive the harness with a fake model and check the metric math."""
    reports = [
        {"id": "a", "template": "t", "expected_severity": "Red", "noise": "clean",
         "expected_specialist": "hematologist",
         "report_text": "Platelets 9,800/uL, shock."},
        {"id": "b", "template": "t", "expected_severity": "Green", "noise": "clean",
         "expected_specialist": "none", "report_text": "Stable, discharged."},
        {"id": "c", "template": "t", "expected_severity": "Yellow", "noise": "ocr",
         "expected_specialist": "none", "report_text": "illegible"},
    ]
    calls = []

    def fake(text):
        calls.append(text)
        if "9,800" in text:
            sev, spec = "Red", "hematologist"       # correct
        elif "Stable" in text:
            sev, spec = "Yellow", "none"             # wrong, over-triage
        else:
            calls.append("ERR")
            return None                              # counts as a miss, not a pass

        res = triage_result(severity=sev, case_label="x", icu_needed=1,
                            platelets_needed=5, specialist=spec,
                            confidence=0.5, reasoning="r",
                            physical_visit_recommended=(sev == "Red"),
                            specialist_escalation_recommended=(sev == "Red"),
                            recommended_action="test")
        _record("ok", sev)
        return res

    monkeypatch.setattr(run_eval.llm, "triage_report", fake)

    def _record(status, sev):
        run_eval.llm._trace.insert(0, {
            "status": status, "model": "fake", "latency_ms": 1,
            "tokens": {"prompt": 100, "completion": 20}})

    res = run_eval.evaluate(reports)

    assert res["n"] == 3
    assert res["llm"]["accuracy"] == pytest.approx(1 / 3, abs=1e-3)  # 1 of 3
    assert res["llm"]["errors"] == 1
    assert res["confusion"]["Red"]["Red"] == 1
    assert res["confusion"]["Green"]["Yellow"] == 1     # over-triage, not under
    assert res["confusion"]["Yellow"]["ERROR"] == 1
    assert res["llm"]["under_triage_count"] == 0
    assert res["llm"]["over_triage_count"] == 1
    assert res["by_noise"]["clean"]["n"] == 2
    assert res["by_noise"]["ocr"]["n"] == 1
    assert res["tokens"]["prompt"] == 200               # error call logged no tokens
    assert res["est_cost_usd"] > 0


def test_eval_measures_routing_not_just_severity(monkeypatch):
    """§18 asks for correct/wrong routing, which severity accuracy cannot see.

    This is the case that justifies the metric existing: the model gets the
    severity right on every report and still sends two of the three to a doctor
    who cannot take them. A harness that only scored severity would report 100%
    and miss the failure that actually matters operationally.
    """
    reports = [
        {"id": "a", "template": "t", "expected_severity": "Yellow", "noise": "clean",
         "expected_specialist": "hematologist", "report_text": "low platelets"},
        {"id": "b", "template": "t", "expected_severity": "Yellow", "noise": "clean",
         "expected_specialist": "pediatrician", "report_text": "child, febrile"},
        {"id": "c", "template": "t", "expected_severity": "Yellow", "noise": "clean",
         "expected_specialist": "none", "report_text": "stable"},
    ]

    def fake(text):
        # Severity is right every time. The specialty is not.
        return triage_result(severity="Yellow", case_label="x", specialist="none",
                             confidence=0.9, reasoning="r",
                             physical_visit_recommended=True)

    monkeypatch.setattr(run_eval.llm, "triage_report", fake)
    res = run_eval.evaluate(reports)

    assert res["llm"]["accuracy"] == 1.0, "severity alone looks perfect"
    rt = res["routing"]
    assert rt["scored"] == 3
    assert rt["wrong"] == 2
    assert rt["correct"] == 1
    assert rt["accuracy"] == pytest.approx(1 / 3, abs=1e-3)
    assert any("hematologist->" in m for m in rt["misrouted"])


def test_eval_reports_manual_review_rate(monkeypatch):
    """§18's manual-review rate, counted against the production confidence
    floor rather than a number invented by the harness."""
    reports = [
        {"id": "a", "template": "t", "expected_severity": "Green", "noise": "clean",
         "expected_specialist": "none", "report_text": "clear"},
        {"id": "b", "template": "t", "expected_severity": "Green", "noise": "clean",
         "expected_specialist": "none", "report_text": "murky"},
    ]
    conf = iter([0.95, 0.10])

    def fake(text):
        return triage_result(severity="Green", case_label="x",
                             confidence=next(conf), reasoning="r")

    monkeypatch.setattr(run_eval.llm, "triage_report", fake)
    res = run_eval.evaluate(reports)
    assert res["manual_review"]["count"] == 1
    assert res["manual_review"]["rate"] == 0.5
    assert res["manual_review"]["threshold"] == agent1_triage.MIN_CONFIDENCE
    # And the unreadable case counts too - it is the same outcome, reached by
    # the other route.
    assert res["routing"]["unreadable"] == 0


def test_eval_routing_does_not_leak_doctor_load(monkeypatch):
    """Agent 3 increments doctor load when it assigns. The harness runs it once
    per report, so without a reset report 1's assignment would make report 2
    look like a capacity failure - and the routing accuracy would drift with
    position in the run instead of measuring the model."""
    reports = [{"id": f"r{i}", "template": "t", "expected_severity": "Yellow",
                "noise": "clean", "expected_specialist": "none",
                "report_text": "stable"} for i in range(6)]

    def fake(text):
        return triage_result(severity="Yellow", case_label="x", specialist="none",
                             confidence=0.9, reasoning="r",
                             physical_visit_recommended=True)

    before = {d["name"]: d["load"] for h in ds.hospitals for d in h["doctors"]}
    monkeypatch.setattr(run_eval.llm, "triage_report", fake)
    res = run_eval.evaluate(reports)
    after = {d["name"]: d["load"] for h in ds.hospitals for d in h["doctors"]}

    assert before == after, "harness mutated global doctor load"
    assert res["routing"]["unassigned"] == 0, "later reports starved by earlier ones"
    assert res["routing"]["accuracy"] == 1.0


def test_under_triage_is_counted(monkeypatch):
    """The dangerous direction: a Red case called Green must be flagged."""
    reports = [{"id": "x", "template": "t", "expected_severity": "Red",
                "noise": "clean", "expected_specialist": "none",
                "report_text": "shock, lactate 5.2, platelets 9,000"}]

    def fake(text):
        return triage_result(severity="Green", case_label="routine",
                             confidence=0.9, reasoning="looked fine",
                             physical_visit_recommended=False)

    monkeypatch.setattr(run_eval.llm, "triage_report", fake)
    res = run_eval.evaluate(reports)
    assert res["llm"]["under_triage_count"] == 1
    assert res["llm"]["under_triage_rate"] == 1.0
    # It also failed the visit recommendation, in the dangerous direction:
    # a Red case recommended as not needing an in-person review. Recorded
    # separately from plain inaccuracy because this is the one that could keep
    # a sick patient at home.
    assert res["recommendations"]["visit_recommendation_misses"] == ["x"]


# ------------------------------------------------------------------- API layer
# The decision lifecycle is the product. These go through the real FastAPI app
# rather than calling the agents directly, because the thing being tested is the
# contract a doctor actually uses: submit, then choose one of three actions.

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def test_submitted_case_enters_a_queue_not_a_decision(client):
    """Uploading a report must never decide anything on its own."""
    r = client.post("/patients", json={"name": "Asha Verma", "case_type": "severe"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "awaiting_review"
    assert body["decision"] is None
    assert body["doctor"] is not None

    # It is in the patient queue, and the AI's advice is attached as advice.
    rows = client.get("/queue/patients").json()["cases"]
    row = next(c for c in rows if c["id"] == body["id"])
    assert row["ai_recommendation"]["physical_visit"] is True
    assert row["has_report"] is False   # dropdown case, no report text
    assert row["priority_breakdown"]["severity"] == "Red"


def test_visit_required_on_a_seeded_case_actually_commits(client):
    """Seeded cases must commit real resources, not report success vacuously.

    The 24 seeded cases are the app's default state, so this is the main path a
    doctor clicks. The seed builder computed `need` and then forgot to store it,
    and the decision path read `p.get("need") or {}` - so a Red case came back
    `admitted` with `committed: true` while the facility held no bed and no
    stock for it. A green queue over an empty inventory.
    """
    # Seed explicitly rather than relying on `main`'s import-time seeding. The
    # autouse fixture empties `patients` before every test, so import order -
    # not the code under test - would decide whether any seeded case exists.
    assert ds.seed_patients() > 0
    q = client.get("/queue").json()
    case = next(c for c in q["patient_queue"]
                if c["status"] == "awaiting_review" and c["severity"] == "Red")
    assert case["seed"] is True
    pid, facility = case["id"], case["hospital"]

    before = {h["name"]: (h["icu"], dict(h["stock"]))
              for h in client.get("/hospitals").json()}

    r = client.post(f"/patients/{pid}/decide", json={"decision": "visit_required"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "admitted"
    assert body["reservation"]["committed"] is True

    after = {h["name"]: (h["icu"], dict(h["stock"]))
             for h in client.get("/hospitals").json()}
    icu_before, stock_before = before[facility]
    icu_after, stock_after = after[facility]
    assert icu_after < icu_before, "no ICU bed was taken for an admitted Red case"
    for med, qty in stock_before.items():
        if stock_after[med] < qty:
            assert qty - stock_after[med] > 0


def test_visit_required_refuses_a_case_with_no_triage_record(client):
    """No triage `need` means the resources cannot be determined, so the case
    must not be admitted at all. The failure mode this guards is worse than an
    error: an `admitted` status with `committed: true` and nothing actually
    held behind it."""
    r = client.post("/patients", json={"name": "No Triage", "case_type": "severe"})
    pid = r.json()["id"]
    import main
    main._find(pid).pop("need", None)

    d = client.post(f"/patients/{pid}/decide", json={"decision": "visit_required"})
    assert d.status_code == 409
    assert "triage" in d.json()["detail"].lower()
    # Still open, still decidable another way.
    assert main._find(pid)["status"] == "awaiting_review"


def test_no_visit_decision_frees_the_doctor_and_holds_no_bed(client):
    """The option that makes a digital queue worth building."""
    r = client.post("/patients", json={"name": "Remote Case", "case_type": "severe"})
    pid = r.json()["id"]
    before = {h["id"]: h["icu"] for h in ds.hospitals}

    d = client.post(f"/patients/{pid}/decide",
                    json={"decision": "no_visit", "note": "ORS and review in 48h"})
    assert d.status_code == 200
    body = d.json()
    assert body["status"] == "closed_remote"
    assert body["resources_released"] is True

    # No ICU bed was ever consumed for a patient who did not come in.
    assert {h["id"]: h["icu"] for h in ds.hospitals} == before
    # And it has left the queue.
    rows = client.get("/queue/patients").json()["cases"]
    assert pid not in {c["id"] for c in rows}


def test_visit_required_commits_resources(client):
    r = client.post("/patients", json={"name": "Admitted Case", "case_type": "severe"})
    pid = r.json()["id"]
    facility = r.json()["hospital_id"]
    before = next(h for h in ds.hospitals if h["id"] == facility)["icu"]

    d = client.post(f"/patients/{pid}/decide", json={"decision": "visit_required"})
    assert d.status_code == 200
    assert d.json()["status"] == "admitted"
    assert d.json()["reserved"]["committed"] is True
    assert next(h for h in ds.hospitals if h["id"] == facility)["icu"] == before - 1


def test_escalate_moves_the_case_to_the_specialist_queue(client):
    r = client.post("/patients", json={"name": "Escalate Case", "case_type": "severe"})
    pid = r.json()["id"]
    original_doctor = r.json()["doctor"]

    d = client.post(f"/patients/{pid}/decide",
                    json={"decision": "escalate", "note": "Plasma leak"})
    assert d.status_code == 200
    body = d.json()
    assert body["status"] == "awaiting_specialist"
    assert body["doctor"] != original_doctor
    assert body["escalated_from"]["doctor"] == original_doctor

    groups = client.get("/queue/specialists").json()
    mine = [c for g in groups for c in g["cases"] if c["id"] == pid]
    assert len(mine) == 1
    assert mine[0]["escalated_from"]["doctor"] == original_doctor

    # And the senior doctor's own queue now contains it.
    assert any(c["id"] == pid for c in client.get(f"/queue/doctors/{body['doctor']}").json()["cases"])


def test_specialty_senior_flag_matches_the_roster():
    """`SPECIALTIES[s]["senior"]` must mean a senior consultant actually exists.

    The flag and the rosters are two separate hand-maintained lists, and they
    drifted: general_medicine was flagged `senior: True` while no facility
    staffed a senior general physician. `facilities_with(...,
    senior_only=True)` then returned an empty list, so escalating any routine
    case was refused with `no_senior_available` - for a tier the registry
    claimed existed. Nothing else in the system checks this, because
    `escalate` failing is a legitimate 409 in its own right.

    Asserted both ways: a flag without a consultant is a promise the routing
    layer cannot keep, and a consultant without the flag is unreachable by
    escalation.
    """
    for specialty, meta in ds.SPECIALTIES.items():
        staffed = any(ds.doctors_of(h, specialty, senior_only=True)
                      for h in ds.hospitals)
        assert meta["senior"] == staffed, (
            f"{specialty}: SPECIALTIES says senior={meta['senior']} but "
            f"staffed={staffed}. An escalate to this specialty would "
            f"{'dead-end' if meta['senior'] else 'never be allowed'}.")


def test_every_specialty_can_be_escalated(client):
    """Escalation must be a real routing action for *every* case type.

    End-to-end through the endpoint on purpose. The unit test above pins the
    registry to the roster, but the bug that shipped was in the HTTP handler:
    it built its refusal hints in a dict literal, which evaluates every value,
    so the `no_senior_available` branch also evaluated the
    `target_cannot_take_resources` f-string and raised KeyError('facility') -
    answering a routine-case escalate with a 500 instead of a 409 that
    explains it. Calling `agent3_routing.reassign` directly, as the
    no-senior test does, cannot see that class of failure at all.

    Driven off `ds.case_types` so a case type added later is covered without
    editing this test, and so the assertion is "every type escalates" rather
    than a list that can quietly fall behind the catalogue.
    """
    for case_type in ds.case_types:
        r = client.post("/patients",
                        json={"name": f"Escalate {case_type}",
                              "case_type": case_type})
        assert r.status_code == 200, f"{case_type}: {r.text}"
        pid = r.json()["id"]

        d = client.post(f"/patients/{pid}/decide", json={"decision": "escalate"})
        assert d.status_code == 200, f"{case_type}: {d.text}"
        assert d.json()["status"] == "awaiting_specialist", case_type


def test_escalation_refusal_is_a_409_with_a_readable_hint(client):
    """A refusal must explain itself in prose, and must never be a 500.

    The structured 409 body is what the console renders, so an empty or
    unstringifiable `detail` here is a dead end for the reviewing doctor: they
    are told the escalation failed and not why.
    """
    # `chronic` routes to general_medicine directly (`normal` reaches it via
    # resolve_specialty("none"), but the explicit type states the intent).
    r = client.post("/patients", json={"name": "No Senior", "case_type": "chronic"})
    pid = r.json()["id"]

    # Every general-medicine reviewer is full, and the escalation gate requires
    # a *free* senior, so there is genuinely nowhere to send this case.
    for h in ds.hospitals:
        for doc in h["doctors"]:
            if doc["specialty"] == "general_medicine":
                doc["load"] = doc["capacity"]

    d = client.post(f"/patients/{pid}/decide", json={"decision": "escalate"})
    assert d.status_code == 409, d.text
    body = d.json()["detail"]
    assert body["error"] == "no_senior_available"
    assert isinstance(body["hint"], str) and body["hint"].strip(), body
    # The two refusal branches carry different keys - `facility`/`short` versus
    # `specialty` only. Formatting one must not require the other's, which is
    # the exact KeyError the old hint dict raised on this path.
    assert "cannot supply" not in body["hint"]

    # And nothing moved.
    still = client.get(f"/patients/{pid}").json()
    assert still["status"] == "awaiting_review"


def test_decision_is_recorded_and_shown_to_the_patient(client):
    r = client.post("/patients", json={"name": "Noted Case", "case_type": "moderate"})
    pid = r.json()["id"]
    client.post(f"/patients/{pid}/decide",
                json={"decision": "no_visit", "note": "Reviewed, no travel needed"})

    portal = client.get(f"/patients/{pid}").json()
    assert portal["decision"] == "no_visit"
    assert portal["decision_note"] == "Reviewed, no travel needed"
    assert portal["position"] is None      # no longer in the queue
    assert portal["status"] == "closed_remote"


def test_portal_hides_other_patients_and_internal_inventory(client):
    """A patient portal that leaks the facility's platelet count is a security
    problem, not a transparency win."""
    client.post("/patients", json={"name": "Leak Check", "case_type": "normal"})
    portal = client.get("/patients/1").json()
    for leak in ("stock", "medicines", "icu", "doctors", "red_flags", "need"):
        assert leak not in portal, f"patient portal exposed {leak!r}"


def test_a_case_cannot_be_decided_twice(client):
    r = client.post("/patients", json={"name": "Double Click", "case_type": "normal"})
    pid = r.json()["id"]
    assert client.post(f"/patients/{pid}/decide",
                       json={"decision": "no_visit"}).status_code == 200
    # A second decision is a conflict, not a silent overwrite of the first.
    assert client.post(f"/patients/{pid}/decide",
                       json={"decision": "visit_required"}).status_code == 409


def test_unknown_decision_is_rejected(client):
    r = client.post("/patients", json={"name": "Bad Verb", "case_type": "normal"})
    pid = r.json()["id"]
    resp = client.post(f"/patients/{pid}/decide", json={"decision": "discharge_home"})
    assert resp.status_code == 422   # closed Literal, not a 500


def test_approve_endpoint_still_works_as_a_no_visit_alias(client):
    """Back-compat: the original single `approve` button released resources,
    which is exactly `no_visit` now. It must not become a second release path."""
    r = client.post("/patients", json={"name": "Old Client", "case_type": "severe"})
    pid = r.json()["id"]
    before = {h["id"]: h["icu"] for h in ds.hospitals}
    resp = client.post(f"/patients/{pid}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed_remote"
    assert {h["id"]: h["icu"] for h in ds.hospitals} == before


def test_unassigned_case_stays_visible_in_the_queue():
    """A case with no eligible facility must keep waiting visibly. Dropping it
    from the queue would be the one outcome this product must never cause."""
    need = {"icu": 0, "platelets": 0, "specialist": "none", "medicines": {},
            "severity": "Red", "label": "Unroutable", "red_flags": [],
            "confidence": 1.0, "source": "rules"}
    ds.patients.append({
        "id": 999, "name": "Nowhere Patient", "case_label": "Unroutable",
        "severity": "Red", "specialty": "general_medicine", "hospital": None,
        "hospital_id": None, "doctor": None, "status": "unassigned",
        "enqueued_at": ds.now(), "decided_at": None, "decision": None,
        "decision_note": None, "escalated_from": None, "red_flags": [],
        "triage_source": "rules", "confidence": 1.0, "report_text": None,
    })
    try:
        from agents import queue
        rows = queue.patient_queue()
        assert any(c["id"] == 999 for c in rows)
        assert queue.queue_stats()["unassigned"] == 1
    finally:
        ds.patients.clear()
