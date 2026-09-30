"""
Agent 1 - Clinical Triage.

Two paths, one output shape:

  LLM path    - a real pasted lab report goes to the model, which returns a
                schema-constrained TriageResult. This is the path that makes
                the project genuinely AI: the input is unstructured and
                messy (OCR noise, typos, mixed notation) and there is no
                lookup table for it.
  Rule path   - the dropdown shortcut cases, and the fallback whenever the
                model is unavailable, times out, or emits invalid output.

Both emit the same `need` dict, so Agents 2-4 cannot tell which ran. That
matters: the downstream agents must never branch on whether the model worked.

The model is treated as an *untrusted proposal*. Its `icu` / `platelets`
figures are requests, not facts - Agent 2 verifies them against real stock
before anything is reserved.
"""

import llm
from data_store import case_types, medicines_catalog

_SPECIALIST_NONE = "none"


def _need(**kw) -> dict:
    base = {
        "source": "rules",
        "severity": "Green",
        "label": "Unknown",
        "icu": 0,
        "platelets": 0,
        "specialist": None,
        "medicines": {},
        "red_flags": [],
        "confidence": 1.0,
        "reasoning": "",
        # Queue recommendations. Advisory only - the queue engine derives
        # priority from severity alone, and a human doctor makes the
        # visit/escalate call. Defaulting both to False on the fallback is
        # deliberate: an unreadable report should not arrive pre-marked as
        # "no visit needed".
        "physical_visit": False,
        "escalation": False,
        "recommended_action": "",
    }
    base.update(kw)
    return base


def from_rules(case_type: str):
    case = case_types.get(case_type)
    if not case:
        raise ValueError(f"Unknown case type: {case_type}")

    meds = dict(case["medicines"])
    # `platelets` and the platelet_concentrate medicine line are the same
    # physical stock. Keep the larger of the two so the allocator can check
    # the blood-product count without double-reserving.
    if case["platelets"]:
        meds["platelet_concentrate"] = max(
            meds.get("platelet_concentrate", 0), case["platelets"])

    need = _need(
        severity=case["severity"],
        label=case["label"],
        icu=case["icu"],
        platelets=case["platelets"],
        specialist=None if case["specialist"] == _SPECIALIST_NONE else case["specialist"],
        medicines=meds,
        physical_visit=case.get("physical_visit", False),
        escalation=case.get("escalation", False),
        recommended_action=case.get("recommended_action", ""),
        reasoning=f"Matched the built-in '{case['label']}' case profile.",
    )
    return need, _rule_step(need)


def from_report(report_text: str):
    """LLM path. Returns (need, step) where step records the fallback if one
    happened, so the UI is honest about which path produced the decision."""
    result = llm.triage_report(report_text)

    if result is None:
        need, step = _fallback_step(report_text)
        return need, step

    meds = result.medicine_map()
    if result.platelets_needed:
        meds["platelet_concentrate"] = max(
            meds.get("platelet_concentrate", 0), result.platelets_needed)
    meds = {k: v for k, v in meds.items() if v > 0}

    need = _need(
        source="llm",
        severity=result.severity,
        label=result.case_label,
        icu=result.icu_needed,
        platelets=result.platelets_needed,
        specialist=None if result.specialist == _SPECIALIST_NONE else result.specialist,
        medicines=meds,
        red_flags=result.red_flags,
        confidence=result.confidence,
        physical_visit=result.physical_visit_recommended,
        escalation=result.specialist_escalation_recommended,
        recommended_action=result.recommended_action,
        reasoning=result.reasoning,
    )
    return need, _llm_step(need)


def _fallback_step(report_text: str):
    """Model unavailable. Route conservatively: a report we could not read is
    never auto-cleared as Green, because that is the failure mode that hurts."""
    need = _need(
        severity="Yellow",
        label="Unclassified report - needs clinician review",
        icu=0,
        platelets=0,
        specialist=None,
        medicines={},
        red_flags=["Automated triage unavailable - report requires manual review"],
        confidence=0.0,
        # physical_visit stays True on purpose. We do not know whether this
        # patient needs to come in, and "we don't know" must not become
        # "no visit needed" - that is the unsafe direction to default in.
        physical_visit=True,
        escalation=False,
        recommended_action="Manual triage review before any discharge advice",
        reasoning=(
            f"The triage model was unavailable, so the report "
            f"({len(report_text)} chars) was not classified. Held for a "
            "clinician rather than auto-cleared."
        ),
    )
    step = {
        "title": "Agent 1 - Clinical Triage",
        "text": need["reasoning"],
        "source": "fallback",
        "model": None,
        "recommendation": {
            "physical_visit": True,
            "specialist_escalation": False,
            "action": need["recommended_action"],
        },
    }
    return need, step


def _rule_step(need: dict) -> dict:
    action = f' Suggested action: {need["recommended_action"]}.' if need["recommended_action"] else ""
    text = (
        f'Diagnosis: "{need["label"]}". Severity {need["severity"]}. '
        f'Requires {need["icu"]} ICU bed(s), {need["platelets"]} platelet unit(s)'
        + (f", a {need['specialist']}" if need["specialist"] else "")
        + "."
        + action
    )
    return {
        "title": "Agent 1 - Clinical Triage",
        "text": text,
        "source": "rules",
        "model": None,
        "recommendation": {
            "physical_visit": need["physical_visit"],
            "specialist_escalation": need["escalation"],
            "action": need["recommended_action"],
        },
    }


def _llm_step(need: dict) -> dict:
    call = llm.trace()[0] if llm.trace() else {}
    flags = (" Red flags: " + "; ".join(need["red_flags"])) if need["red_flags"] else ""
    rec = need["recommended_action"] or "no specific action suggested"
    text = (
        f'{need["label"]} - severity {need["severity"]} '
        f'(confidence {need["confidence"]:.0%}). {need["reasoning"]} '
        f'Requires {need["icu"]} ICU bed(s), {need["platelets"]} platelet unit(s)'
        + (f", a {need['specialist']}" if need["specialist"] else "")
        + (f" Medicines: {need['medicines']}." if need["medicines"] else "")
        + f' Suggested action: {rec}.'
        + f' In-person review recommended: {"yes" if need["physical_visit"] else "no"};'
        f' senior specialist review recommended: {"yes" if need["escalation"] else "no"}.'
        + flags
    )
    return {
        "title": "Agent 1 - Clinical Triage",
        "text": text,
        "source": "llm",
        "model": call.get("model"),
        "latency_ms": call.get("latency_ms"),
        "tokens": call.get("tokens"),
        "recommendation": {
            "physical_visit": need["physical_visit"],
            "specialist_escalation": need["escalation"],
            "action": need["recommended_action"],
        },
    }


def run(case_type: str, report_text: str | None = None):
    if report_text and report_text.strip():
        return from_report(report_text.strip())
    return from_rules(case_type)


def catalog_keys() -> set:
    return set(medicines_catalog)
