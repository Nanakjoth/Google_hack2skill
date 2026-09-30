# Prompt configuration

The triage prompt is a reviewable artefact, not a string buried in `llm.py`.
Judges, clinicians and reviewers can read and diff it without running code.

| File | What it is | Loaded by |
|---|---|---|
| `triage_system.md` | The system instruction sent to Gemini | `llm.py` `_system_prompt()` |
| `schema` | **Not a file.** The `response_schema` is generated from `TriageResult` (`models.py`) | `llm.py` `_gemini_schema()` |

## Why the schema is generated rather than written here

Duplicating the schema into a hand-maintained JSON file would create two sources
of truth for the same contract, and they would drift the first time someone
changed a field. The prompt file and the generated schema are checked against
each other instead — see `tests/test_pipeline.py`:

- `test_catalog_matches_llm_enum` — the medicine keys the prompt tells the model
  to use are the same keys `data_store.py` stocks. The process refuses to start
  if they diverge.
- `test_severity_values_match_the_catalog` — the severity vocabulary the prompt
  hard-codes matches what the queues can order.

So the prompt is hand-written and versioned; the contract it has to satisfy is
derived from the code that enforces it.

## Runtime configuration

Everything else is environment configuration, not prompt text. See
`.env.example` for the full set:

| Variable | Default | Effect |
|---|---|---|
| `GOOGLE_API_KEY` | — | Absent ⇒ LLM path is skipped, rule-based fallback runs |
| `LLM_MODEL` | `gemini-2.5-flash` | Any Gemini model id |
| `LLM_TIMEOUT` | `30` | Seconds before the call is abandoned |
| `LLM_RETRIES` | `2` | Extra attempts on API errors only |
| `LLM_THINKING_BUDGET` | `0` | Reasoning tokens; `0` disables thinking for latency |
| `LLM_MAX_TOKENS` | `1024` | Output cap |

## Editing the prompt

Change `triage_system.md`, not `llm.py`. If you add a medicine key, add it to
the catalog in `data_store.py` in the same commit — the startup check will fail
loudly otherwise, which is the intended behaviour.
