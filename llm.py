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

Provider is Google AI Studio (Gemini), chosen through configuration so it can
be swapped without touching the pipeline - see DECISIONS.md.

CONFIG (env vars, never hardcoded):
  GOOGLE_API_KEY     required for the LLM path
  LLM_MODEL          default gemini-2.5-flash
  LLM_TIMEOUT        seconds, default 30
  LLM_RETRIES        default 2
  LLM_THINKING_BUDGET  tokens of reasoning, default 0 (off)
  LLM_MAX_TOKENS     output cap, default 1024
"""

import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from models import TriageResult

# Load .env before reading any config below. Real environment variables always
# win over the file, so this does not override a real deployment's config.
load_dotenv()

# Model choice, verified against the live API rather than assumed.
#
# `gemini-2.5-flash` (the original default) now returns 404 for new API keys,
# and the `*-latest` aliases were returning 503 "high demand" on the structured
# output path during testing. A dated id also rots: a retirement silently pushes
# every report onto the fallback path until someone reads a trace. So the
# default is a model confirmed to accept our response_schema, and FALLBACK_MODELS
# gives the retry loop somewhere else to go when one is at capacity.
#
# A model that does not support `response_schema` cannot appear in this list -
# the retry would burn attempts and land on the same 400.
MODEL = os.getenv("LLM_MODEL", "gemini-3-flash-preview")
FALLBACK_MODELS = tuple(
    m.strip() for m in
    os.getenv("LLM_FALLBACK_MODELS", "gemini-3.1-flash-lite").split(",")
    if m.strip()
)
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))
RETRIES = int(os.getenv("LLM_RETRIES", "2"))
THINKING_BUDGET = int(os.getenv("LLM_THINKING_BUDGET", "0"))
# First retry wait, doubled each attempt. Gemini's Flash tier returns 503
# "high demand" under load; the wait has to outlast a capacity blip.
BACKOFF_BASE = float(os.getenv("LLM_BACKOFF_BASE", "2.5"))
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))

# Approximate Gemini per-1M-token rates (USD) used by the eval cost estimate.
# Check current pricing and update these if the model changes.
IN_COST = float(os.getenv("LLM_IN_COST", "0.30"))
OUT_COST = float(os.getenv("LLM_OUT_COST", "2.50"))

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "triage_system.md"

# The prompt lives in a file so it can be reviewed and diffed by someone who
# does not read Python. It is read once at import. A missing or empty file is a
# hard failure on purpose: a silently empty system instruction would still pass
# the schema-constrained call and return a confidently wrong triage.
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8").strip()
if not SYSTEM_PROMPT:
    raise RuntimeError(f"prompt file is empty: {PROMPT_PATH}")


# Gemini's response_schema is a subset of OpenAPI 3.0, not JSON Schema. It
# rejects the two constructs Pydantic emits for nested models and that the
# Groq path relied on:
#   * `$defs` / `$ref` - Gemini wants the nested object inlined.
#   * `additionalProperties` - not in the OpenAPI subset, a hard 400.
# Pydantic also adds `title` and `default` noise that constrains nothing here.
# So the schema is rewritten rather than handed over as-is. The rewrite only
# changes the *transport* representation: the validation boundary is still
# `TriageResult.model_validate_json` on the way back, which is the check that
# actually matters.
_UNSUPPORTED = frozenset({
    "additionalProperties", "$defs", "title", "default", "format", "examples",
})


def _inline(node: Any, defs: dict) -> Any:
    """Recursively resolve `$ref` into the node itself and drop unsupported keys."""
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        # A `$ref` node is a pure pointer; siblings alongside it are ignored
        # per JSON Schema, so replace the whole node rather than merging.
        return _inline(defs[node["$ref"].split("/")[-1]], defs)
    out = {
        k: _inline(v, defs)
        for k, v in node.items()
        if k not in _UNSUPPORTED
    }
    # Pydantic omits defaulted fields from `required`, which would let the model
    # skip `red_flags` and `medicines` and have the omission silently become an
    # empty list. "No drugs needed" and "the model did not say" are different
    # clinical statements, so every property is made mandatory here. Validation
    # on the way back still supplies the default if a response is ever missing
    # one - this closes the gap rather than replacing the check.
    if out.get("type") == "object" and "properties" in out:
        out["required"] = list(out["properties"].keys())
    return out


def _gemini_schema() -> dict:
    """TriageResult's Pydantic schema in the shape Gemini accepts."""
    raw = TriageResult.model_json_schema()
    defs = raw.get("$defs", {})
    schema = _inline({k: v for k, v in raw.items() if k != "$defs"}, defs)
    # The model does not need Agent 1's docstring - it is a note to maintainers
    # about the trust boundary, and spending prompt tokens on it is waste.
    schema.pop("description", None)
    return schema


SCHEMA = _gemini_schema()

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
    return bool(os.getenv("GOOGLE_API_KEY"))


_CLIENT = None


def _client():
    """A single SDK client, created once and reused.

    Building a throwaway client per call looks harmless and is not: the SDK's
    underlying httpx client is closed when the wrapper is finalised, and under
    GC timing the request goes out on a closed pool ("Cannot send a request, as
    the client has been closed"). One process-wide client also means one
    connection pool instead of a fresh TLS handshake per report.
    """
    global _CLIENT
    if _CLIENT is None:
        from google import genai
        _CLIENT = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    return _CLIENT


def _backoff(attempt: int, err: Exception) -> float:
    """How long to wait before the next attempt.

    Two failure modes need different treatment. A 429 comes back with a
    Retry-After, and ignoring it just burns quota. Everything else - mostly
    503 "high demand" on the Flash tier - clears in seconds, so the wait has to
    be long enough to matter. 1.5s/3s was not: three attempts inside five
    seconds all landed in the same capacity spike and the report fell through
    to the rule-based path for no good reason.
    """
    retry_after = getattr(getattr(err, "details", None), "retry_delay", None)
    if retry_after is None:
        m = re.search(r"retryDelay[:\s]+'?(\d+(?:\.\d+)?)s", str(err))
        if m:
            retry_after = float(m.group(1))
    if retry_after is not None:
        return min(float(retry_after) + 0.5, 30.0)
    return min(BACKOFF_BASE * (2 ** attempt), 30.0)


def _finish_reason(resp) -> str:
    """Why generation stopped. Truncation matters: a response cut off
    mid-JSON fails schema validation, and the fallback then reads as
    "the model is broken" rather than "the budget was too small"."""
    try:
        return str(resp.candidates[0].finish_reason or "STOP").split(".")[-1]
    except (AttributeError, IndexError):
        return "STOP"


def triage_report(report_text: str) -> Optional[TriageResult]:
    """Extract a structured triage decision from a raw lab report.

    Returns None on any failure - missing key, timeout, malformed output,
    schema violation. The caller is expected to fall back to the rule-based
    path. Never raises.
    """
    if not available():
        _record({"status": "skipped", "reason": "GOOGLE_API_KEY not set",
                 "model": MODEL, "latency_ms": 0})
        return None

    from google.genai import types
    from google.genai.errors import APIError

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.0,
        max_output_tokens=MAX_TOKENS,
        response_mime_type="application/json",
        response_schema=SCHEMA,
        # Thinking is off by default. The severity rules are stated explicitly
        # in the prompt, so this is extraction rather than inference, and a
        # reasoning pass would spend most of MAX_TOKENS before emitting any
        # JSON. Raise LLM_THINKING_BUDGET if hard reports need more reasoning
        # - and raise LLM_MAX_TOKENS with it, or the JSON gets truncated.
        thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET),
    )

    last = "unknown error"
    # Rotated across attempts. A capacity 503 on one Flash model is very often
    # fine on another, and rotating is faster than waiting out a backoff.
    order = (MODEL, *FALLBACK_MODELS)
    for attempt in range(RETRIES + 1):
        model = order[attempt % len(order)]
        started = time.perf_counter()
        try:
            resp = _client().models.generate_content(
                model=model,
                contents=f"Lab report:\n\n{report_text}",
                config=config,
            )

            reason = _finish_reason(resp)
            raw = resp.text
            if not raw:
                raise ValueError(
                    f"empty response (finish_reason={reason}"
                    f"{', check LLM_MAX_TOKENS' if reason == 'MAX_TOKENS' else ''})"
                )
            result = TriageResult.model_validate_json(raw)

            usage = getattr(resp, "usage_metadata", None)
            _record({
                "status": "ok",
                "model": model,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "attempt": attempt + 1,
                "tokens": {
                    "prompt": getattr(usage, "prompt_token_count", None),
                    "completion": getattr(usage, "candidates_token_count", None),
                },
                "result": result.model_dump(),
            })
            return result

        except APIError as e:
            # Rate limits and 5xx are worth another attempt. A 400 (bad schema,
            # bad key) will fail identically every time, but retrying it is
            # cheap and keeps this branch simple.
            last = f"{type(e).__name__}: {e}"
            if attempt < RETRIES:
                time.sleep(_backoff(attempt, e))
                continue
        except Exception as e:
            # Includes pydantic ValidationError - the model emitted JSON that
            # does not satisfy the contract. Not retryable: a second identical
            # request usually produces the same violation.
            last = f"{type(e).__name__}: {e}"

        _record({
            "status": "error",
            "model": model,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "attempt": attempt + 1,
            "reason": last[:400],
        })
        return None

    return None
