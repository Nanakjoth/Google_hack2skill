"""
LLM access layer - the ONLY place in the codebase that talks to a model.

Design rules this module exists to enforce:
  1. The model never touches hospital state. It reads a report and returns a
     structured proposal; Agents 2-4 then verify that proposal against real
     inventory. LLM proposes, code disposes.
  2. Output is schema-constrained, never parsed out of prose. A malformed
     model response is a hard failure, not a silent bad parse.
  3. Every failure degrades to `None` and the caller falls back to the
     rule-based path. A demo that dies because an API is down is a bad demo.

CONFIG (env vars, never hardcoded):
  GROQ_API_KEY    required for the LLM path
  LLM_MODEL       default llama-3.3-70b-versatile
  LLM_TIMEOUT     seconds, default 20
  LLM_RETRIES     default 2
"""

import os
import time
from typing import Optional

from dotenv import load_dotenv

from models import TriageResult

# Load .env before reading any config below. Real environment variables always
# win over the file, so this does not override a real deployment's config.
load_dotenv()

MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "20"))
RETRIES = int(os.getenv("LLM_RETRIES", "2"))

SYSTEM_PROMPT = """You are a clinical triage assistant for a rural Indian public health system.

You receive raw, often badly OCR'd or hand-typed lab reports and must convert
them into a structured triage decision.

SEVERITY RULES (follow exactly):
- Red:    shock, severe dengue (platelets <20k/uL with bleeding or haematocrit
          rise), acute coronary syndrome, stroke, sepsis, severe anaemia
          (Hb <7 g/dL), any airway compromise, GCS <13.
- Yellow: moderate dengue (platelets 20k-50k), pneumonia without shock,
          significant fever with dehydration, Hb 7-11 g/dL.
- Green:  routine fever, viral illness, stable vitals, mild anaemia
          (Hb >11), normal platelets.

RESOURCE RULES:
- icu_needed: 1 only for Red cases needing critical care. 0 otherwise.
- platelets_needed: 5 for severe dengue, 2 for moderate dengue, 0 otherwise.
  Only set this if platelets are actually abnormal in the report.
- specialist: 'hematologist' for dengue/platelet/bleeding, 'cardiologist' for
  cardiac, 'pediatrician' if the patient is a child, otherwise 'none'.
- medicines: a list of {medicine, qty} pairs. Only these exact keys are
  valid: paracetamol, oral_rehydration, doxycycline, ceftriaxone,
  platelet_concentrate, ringer_lactate, insulin_glargine, aspirin,
  streptokinase. Use an empty list if no drugs are needed.

RULES FOR THE `reasoning` FIELD:
- Cite the specific abnormal values you keyed off, with units.
- Explain the severity choice, do not just restate it.
- If the report is unreadable or clinically meaningless, say so and
  return severity 'Yellow' with a red_flag noting insufficient data.
- Never invent values that are not present in the report.

QUEUE RECOMMENDATIONS (these guide a human doctor, they do not decide):
- physical_visit_recommended: true when the patient needs to be examined in
  person - needs monitoring, an exam, a procedure, or has warning signs that
  cannot be judged from a report alone. false when the report is plausibly
  manageable remotely with oral advice and a review date.
- specialist_escalation_recommended: true when this is beyond routine scope
  for a general duty doctor and warrants senior specialty review. Use it for
  severe dengue with plasma leak, STEMI, stroke, sepsis, severe anaemia, and
  any child in a serious condition. Use false for the same severity when the
  presentation is straightforward for the specialty.
- recommended_action: one short phrase naming the concrete next step and its
  timeframe, e.g. 'Senior cardiology review within 24h'.

You are NOT diagnosing the patient and NOT deciding treatment. You are
prioritising and routing a report to the right doctor. Never claim a bed,
doctor, or medicine is available - you have no visibility into the network.

Output must match the provided JSON schema exactly."""


def _close(node) -> None:
    """Recursively make a JSON Schema strict-mode compatible.

    Strict structured output requires EVERY object node - including ones
    nested under `$defs`, which Pydantic emits for reused models - to declare
    `additionalProperties: false` and list all of its properties as required.
    Missing either one is a hard 400 from the API, not a soft warning.
    """
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
        for value in node.values():
            _close(value)
    elif isinstance(node, list):
        for value in node:
            _close(value)


def _strict_schema() -> dict:
    """Pydantic schema -> strict JSON Schema (see _close for the rules)."""
    schema = TriageResult.model_json_schema()
    _close(schema)
    for prop in schema.get("properties", {}).values():
        prop.pop("default", None)
    return schema


SCHEMA = _strict_schema()

# Rolling trace of the last N model calls, surfaced in the Pipeline tab so the
# UI shows a real trace instead of a hardcoded string.
_trace: list = []
TRACE_LIMIT = 50


def trace() -> list:
    return list(_trace)


def _record(entry: dict) -> None:
    _trace.insert(0, entry)
    del _trace[TRACE_LIMIT:]


def available() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def _client():
    from groq import Groq
    return Groq(api_key=os.environ["GROQ_API_KEY"], timeout=TIMEOUT, max_retries=0)


def triage_report(report_text: str) -> Optional[TriageResult]:
    """Extract a structured triage decision from a raw lab report.

    Returns None on any failure - missing key, timeout, malformed output,
    schema violation. The caller is expected to fall back to the rule-based
    path. Never raises.
    """
    if not available():
        _record({"status": "skipped", "reason": "GROQ_API_KEY not set",
                 "model": MODEL, "latency_ms": 0})
        return None

    from groq import APIError, APIConnectionError, APIStatusError, RateLimitError

    request = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Lab report:\n\n{report_text}"},
        ],
        "temperature": 0.0,
        "max_tokens": 900,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "triage_result",
                "schema": SCHEMA,
                "strict": True,
            },
        },
    }

    for attempt in range(RETRIES + 1):
        started = time.perf_counter()
        try:
            resp = _client().chat.completions.create(**request)
            raw = resp.choices[0].message.content
            result = TriageResult.model_validate_json(raw)

            usage = resp.usage
            _record({
                "status": "ok",
                "model": resp.model,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "attempt": attempt + 1,
                "tokens": {
                    "prompt": getattr(usage, "prompt_tokens", None),
                    "completion": getattr(usage, "completion_tokens", None),
                },
                "result": result.model_dump(),
            })
            return result

        except (RateLimitError, APIConnectionError, APIStatusError, APIError) as e:
            last = f"{type(e).__name__}: {e}"
            if attempt < RETRIES:
                time.sleep(1.5 * (attempt + 1))
                continue
        except Exception as e:
            # Includes pydantic ValidationError - the model emitted JSON that
            # does not satisfy the contract. Not retryable: a second identical
            # request usually produces the same violation.
            last = f"{type(e).__name__}: {e}"

        _record({
            "status": "error",
            "model": MODEL,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "attempt": attempt + 1,
            "reason": last[:400],
        })
        return None

    return None
