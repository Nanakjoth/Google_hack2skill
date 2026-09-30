# Submission — Agentic Tele-Triage Portal

Three items, as required. Anything not yet true is marked as such rather than
claimed.

| # | Requirement | Status |
|---|---|---|
| 1 | Official community track | **Resilience** — §1 |
| 2 | Public repo with app logic, prompt configs, run instructions | **Done** — §2 |
| 3 | Architecture overview of Google Cloud + Gemini | **Done** — §3 |

---

## 1. Theme alignment — Resilience

Submitted under **Resilience**. The argument is not "we used AI" — it is that the
system keeps working when its scariest dependency is broken:

| Resilience property | How this build holds it |
|---|---|
| Degrades instead of failing | The model is the only network dependency. Key missing, timeout, 5xx, schema violation or low confidence all resolve to the *same* outcome: hold for a clinician, flagged `manual_review`, never auto-cleared. A dead API degrades the demo; it does not endanger the patient. |
| Fails safe, not silent | A Red case is never softened by a low confidence score. An unreadable report becomes Yellow with a "insufficient data" flag, not Green. `llm.py` returns `None` and never raises — the process stays up. |
| Absorbs a surge | 24 seeded cases are already triaged and queued at boot, so the console is usable the moment it loads. Ordering is severity-banded (1000/500/100) plus a wait bonus **capped at 300** — strictly below the narrowest band gap, so no amount of waiting lets a mild case jump a critical one. |
| Degrades the scarce resource, not safety | Bed and medicine are committed only at the moment a doctor chooses to admit, never when a file arrives. A digital queue cannot hoard platelets. |
| Survives partial data | Facilities that fail the physical check are reported with the specific reason ("no haematology cover", "ICU full") rather than silently dropped, so a staff member can see *why* the network could not absorb a case. |
| Auditable | Every model call is traced: latency, finish reason, token counts, retry number, parse result. `GET /agents/llm-trace` renders it. |

**Why not the other tracks** — recorded so the choice is deliberate:
- *Innovation* is defensible but generic; it is the weakest of the four here.
- *Sustainability* is not addressed: the carbon story of "fewer unnecessary
  patient journeys" is real but unmeasured, and I will not claim it without a
  number.
- *Cooperation* is a stretch. The multi-agent split is an engineering
  decomposition, not inter-organisational collaboration.

---

## 2. Repository

**https://github.com/Nanakjoth/Google_hack2skill**

The Gemini migration and the gap-closing features are committed on `master` but
**not yet pushed** — the last pushed commit still predates the provider swap.
Push before submitting.

### What is in it

| Path | Contents |
|---|---|
| `llm.py` | The only module that talks to Gemini. Schema generation, retries, trace ring buffer. |
| `prompts/triage_system.md` | **The prompt config.** Reviewable and diffable without reading Python. |
| `prompts/README.md` | How the prompt and the generated schema are kept consistent, and what each env var does. |
| `models.py` | `TriageResult` — the contract. The `response_schema` is *generated* from it, not hand-written twice. |
| `agents/agent1_triage.py` | Gemini triage + confidence floor + rule-based fallback. |
| `agents/agent2_allocator.py` | Facility capacity. Deterministic. |
| `agents/agent3_routing.py` | Doctor selection, load balancing, candidate counts. Deterministic. |
| `agents/agent4_forecast.py` | 30-day stock projection. Deterministic. |
| `agents/queue.py` | Queue ordering and the patient portal view. |
| `main.py` | 16 endpoints, serves the console from the same origin. |
| `frontend/` | The console: 6 views, no build step, no framework. |
| `eval/` | 78-report harness with triage *and* routing metrics. |
| `tests/test_pipeline.py` | 59 tests, no API key and no network required. |
| `Dockerfile`, `cloudbuild.yaml`, `.dockerignore` | Cloud Run deployment. |

### Running it

```
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env        # paste your GOOGLE_API_KEY
.venv\Scripts\uvicorn main:app --reload --port 8000
```

Then open **http://localhost:8000** — the console is served by the same process
as the API, so that single URL is the whole product. `/docs` is the OpenAPI
explorer, `/healthz` reports model configuration.

The key is optional. Without it the LLM path is skipped and a trace entry
records why; everything else still runs.

---

## 3. Architecture — Google Cloud + Gemini

```
                    ┌───────────────────────────────────────────────┐
   Browser /        │  Cloud Run  ·  1 container, 1 URL             │
   phone ──────────►│  ─────────────────────────────────────────── │
   (any origin)     │  FastAPI: /healthz  /patients  /queue  …      │
                    │            + /  →  the console (static)       │
                    │                                               │
                    │  Agent 1 ──► needs a model   ┌────────────┐   │
                    │  Agent 2 ──► arithmetic      │ data_store │   │
                    │  Agent 3 ──► arithmetic      │ (in-memory)│   │
                    │  Agent 4 ──► arithmetic      └────────────┘   │
                    └───────────────┬───────────────────────────────┘
                                    │ Secret Manager
                        GOOGLE_API_KEY │ (bound at deploy, never in the image)
                                    ▼
                    ┌───────────────────────────────────────────────┐
                    │  Gemini API  ·  gemini-2.5-flash               │
                    │  google-genai SDK  ·  generative language     │
                    │                                               │
                    │  request:  system_instruction = prompt file   │
                    │             contents           = report text  │
                    │             temperature        = 0.0          │
                    │             response_mime_type = json         │
                    │             response_schema     = generated   │
                    │                                               │
                    │  returns:   constrained JSON → TriageResult   │
                    └───────────────┬───────────────────────────────┘
                                    │ every call traced
                                    ▼
                    ┌───────────────────────────────────────────────┐
                    │  Cloud Logging                               │
                    │  latency · finish reason · tokens · retries   │
                    └───────────────────────────────────────────────┘
```

### The integration, specifically

**Where Gemini sits.** One call, in `llm.py`, in Agent 1 only. Agents 2–4 are
arithmetic. The response is a *proposal*; `need()` converts it into a fixed
10-key dict that downstream agents treat identically whether it came from a
model or from the fallback.

**Structured output, not parsing.** `response_schema` is derived from
`TriageResult.model_json_schema()` and rewritten into the OpenAPI 3.0 subset
Gemini accepts — `$defs`/`$ref` inlined, `additionalProperties` dropped, every
property marked required. Decoding is constrained at the model; the reply is
then re-validated by `TriageResult.model_validate_json`. Two independent gates,
and the second one is Pydantic, not a prompt.

**Latency budget.** `temperature=0`, `thinking_config` disabled by default
(`LLM_THINKING_BUDGET=0`), 1024-token cap, 30s timeout, 2 retries. The UI shows
a trace so the cost of the AI step is visible rather than assumed.

**The key.** Stored in Secret Manager, bound with `--set-secrets` at deploy.
`.dockerignore` refuses `.env` into the image. A leaked key in a public repo
would be a real incident, so it is excluded at three layers: gitignore,
dockerignore, and the deploy command.

**No database — deliberately.** All state is in one process's memory. A queue
is a clinical safety artefact, and a demo that silently persists PHI to an
unmanaged store is worse than one that forgets. Cloud Run gives us stateless
horizontal scaling, so the first thing to add for a real deployment is a
managed datastore — Firestore for the queue, Cloud Storage for report images.
I have not added either, because inventing a persistence layer the plan did not
specify would be scope I cannot test. Firebase is not used and I am not claiming
it.

**Not yet done.** This is written and ready, but **not executed**: the image has
never been built and the service has never been deployed, because I have no GCP
project or credentials here. `cloudbuild.yaml` and the `gcloud` commands in
README.md are unverified. I will not claim a live URL.
