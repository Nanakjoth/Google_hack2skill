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
from models import TriageResult
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
    assert need["source"] == "rules"
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


def test_both_agent1_paths_share_one_shape():
    rules, _ = agent1_triage.run("cardiac")
    keys = set(rules)
    assert keys == {
        "source", "severity", "label", "icu", "platelets", "specialist",
        "medicines", "red_flags", "confidence", "reasoning",
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
    # Rampur holds 1 and Lakhanpur 2; only City General (6) can supply 3.
    assert {h["name"] for h in eligible} == {"City General"}


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
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert llm.available() is False
    assert llm.triage_report("anything") is None


def test_generated_schema_is_strict_mode_clean():
    """Strict structured output rejects any object node lacking
    additionalProperties:false or an incomplete `required` list."""
    schema = llm_schema()
    problems = []

    def walk(node, path):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                if node.get("additionalProperties") is not False:
                    problems.append(f"open object at {path}")
                if set(node.get("required", [])) != set(node["properties"]):
                    problems.append(f"incomplete required at {path}")
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for v in node:
                walk(v, f"{path}[]")

    walk(schema, "root")
    assert not problems, problems


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
    assert res["by_noise"]["clean"]["n"] == 2
    assert res["by_noise"]["ocr"]["n"] == 1
    assert res["tokens"]["prompt"] == 200               # error call logged no tokens
    assert res["est_cost_usd"] > 0


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
