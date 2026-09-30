# AI Medical Queue — Backend

A FastAPI service that reads raw lab reports with an LLM, ranks patients into a
**priority queue**, and hands each case to a human doctor who decides what
happens next.

```
report text ──► Agent 1  ──► Agent 2 ──► Agent 3 ──► review slot
               Clinical    Resource    Routing &     (no bed held)
               Triage      Allocator   Load Balancing      │
               (LLM)       (code)      (code)             │
                                                            ▼
                                              Doctor Queue  ──► no_visit      (patient stays home)
                                                            ├─► visit_required (bed + stock committed)
                                                            └─► escalate        (senior specialty queue)

consumption history ──► Agent 4 ──► shortage forecast + transfers
```

## The one rule: the LLM proposes, code disposes

Agent 1 is the only model-backed agent, and it only ever *reads a report*.
Whether a hospital has a free bed or enough platelets is arithmetic against
live inventory, and a model must never be the thing asserting it — a
hallucinated ICU bed is a patient-safety failure, not a UI glitch. So Agents
2, 3 and 4 are deterministic code that verify whatever Agent 1 proposed.

Agent 1 returns a severity and a *recommendation* (`physical_visit_recommended`,
`specialist_escalation_recommended`, `recommended_action`). Those are shown to
the reviewing doctor as advice. No code path acts on them. The queue orders by
severity alone, and a human decides whether the patient comes in.

The model's output is schema-constrained to `TriageResult` (see `models.py`),
so it cannot emit a field the pipeline doesn't understand, and cannot name a
medicine outside the NLEM catalog. If the model is unavailable, times out, or
returns something invalid, Agent 1 falls back to the built-in case profiles —
and routes an unreadable report to *manual review*, never to Green, because
auto-clearing an unclassified patient is the failure mode that hurts.

## Run it

Requires Python 3.12 (3.14 has no `pydantic-core` wheel and fails to build).

```
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env        # then paste your GOOGLE_API_KEY
.venv\Scripts\uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** for the console — FastAPI serves `frontend/` from
the same origin, so one URL is the whole product and CORS never applies. Also
available: `/docs` for the OpenAPI explorer, `/healthz` for model configuration.
Opening `frontend/index.html` straight off disk still works if you prefer to
keep the two separate.

The LLM path needs a Google AI Studio key; without one everything still runs on
the rule-based path.

A demo backlog of 24 already-triaged cases is seeded at boot, so the queues have
content on first load. They are flagged `seed: true` in the API and marked
*demo* in the UI — no reviewer should mistake seeded data for a processed report.

## Deploy to Google Cloud

One container serves both the API and the console, so Cloud Run needs no static
hosting bucket. **The API key is a Secret Manager value bound at deploy time —
it is never baked into the image.**

```
# one-time setup
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
                  secretmanager.googleapis.com artifactregistry.googleapis.com
gcloud artifacts repositories create tele-triage \
  --repository-format=docker --location=asia-south1
gcloud secrets create gemini-api-key --replication-policy=automatic
printf '%s' "$YOUR_KEY" | gcloud secrets versions add gemini-api-key

# build, push and deploy
gcloud builds submit --config cloudbuild.yaml
```

`cloudbuild.yaml` tags by commit SHA, pushes to Artifact Registry and deploys
with `--set-secrets=GOOGLE_API_KEY=gemini-api-key:latest`. It also sets
`ALLOWED_ORIGINS=none`, which disables the CORS middleware entirely — safe
precisely because the console is served from the same origin as the API.

The `Dockerfile` runs as an unprivileged user, binds `$PORT` (Cloud Run sets it
to 8080) and `.dockerignore` refuses `.env` into the build context, so a stray
key on a laptop cannot end up in a public image.

> Not yet run. The build and deploy steps above are written but unverified — no
> GCP project was available in the environment where this was written.

## Evaluating the model

This is the part that makes it a project rather than a demo — it measures the
model instead of asserting it works.

```
.venv\Scripts\python -m eval.make_dataset     # regenerate the 78-report set
.venv\Scripts\python -m eval.run_eval          # one API call per report
.venv\Scripts\python -m eval.run_eval --limit 6   # while iterating
```

The dataset is synthetic, built from clinical templates whose values sit
unambiguously on one side of the severity rules, so the ground-truth label
follows from published criteria rather than opinion. Every template also has an
OCR-degraded twin (swapped digits, dropped lines, `SpO2`→`Sp02`) because real
referrals arrive as phone photos of photocopied reports.

The harness reports accuracy against a **keyword/regex baseline** — what you'd
write before reaching for a model. That baseline currently scores 62% on clean
reports and **0% on the adversarial templates**, because it reads the literal
string "shock" in *"no shock, no bleeding"* and escalates. That blindness is
the justification for the model, so it is a documented, tested property rather
than an accident.

It also counts **under-triage** (a Red case called Yellow or Green) separately
from raw accuracy, since that is the error direction that kills, and prints a
confusion matrix so a model that never says Red cannot look good.

**Caveat, stated plainly:** 78 reports over 24 templates is a scaffold, not a
validated benchmark, and the model's real accuracy is unmeasured until you run
the harness with a key. Do not quote a number from this repo.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/patients` | `report_text` → LLM path; `case_type` → rule path. Returns the queue assignment plus the step log. Decides nothing. |
| GET | `/patients` | Raw patient records |
| GET | `/patients/{id}` | Patient-facing portal view — position, wait, decision. No internal inventory. |
| POST | `/patients/{id}/decide` | **The doctor decision.** `no_visit` · `visit_required` · `escalate` |
| POST | `/patients/{id}/approve` | Back-compat alias for `no_visit` |
| GET | `/queue` | Stats + patient queue + per-doctor queues + senior queues, in one call |
| GET | `/queue/patients` | Whole-network queue, priority order, with the arithmetic behind each position |
| GET | `/queue/doctors` | One panel per doctor, already sorted — top row is their next patient |
| GET | `/queue/doctors/{name}` | A single doctor's cases |
| GET | `/queue/specialists` | Escalated cases grouped by the specialty that must review them |
| GET | `/hospitals` | Live inventory with `free_platelets`, `distance_km` and the real doctor roster |
| GET | `/command-center/alerts` | Agent 4 shortage forecasts |
| GET | `/command-center/forecast` | Days-of-cover for every facility × medicine |
| POST | `/command-center/redistribute` | `medicine`-aware; will not drain a donor below its buffer |
| GET | `/agents/llm-trace` | Recent model calls: latency, tokens, status |

## The three queues

The product is the queue, not the triage. Reports are ranked by **clinical
severity first, waiting time second**:

```
priority = SEVERITY_WEIGHT[severity] + min(waited_minutes / 12, 300)
```

Severity bands are 1000 / 500 / 100 and the wait bonus is capped at 300 —
strictly below the narrowest band gap. That is deliberate: an uncapped wait term
lets a mild case out-rank a critical one by arithmetic, which is under-triage
laundered through a scheduling formula. `tests/test_pipeline.py` asserts the
invariant through the real scoring function, because asserting it against the
constants alone does not notice when the cap is deleted.

`GET /queue/patients` returns the breakdown for every row, so the order can be
argued with rather than merely trusted.

## A report never holds a bed

The load-bearing design decision. Assigning a case to a doctor reserves a
**review slot only**. ICU beds and medicine stock are committed by
`commit()`, which runs at the moment a doctor chooses `visit_required` — never
earlier, and never by the model.

If routing reserved on assignment, a digital queue would tie up exactly the
scarce inventory a physical queue ties up and would buy nothing. It is
asserted directly in `test_routing_does_not_consume_resources_until_a_doctor_decides`.

The three decisions:

| Decision | Doctor slot | ICU / medicines | Patient travels |
|---|---|---|---|
| `no_visit` | released | never held | no |
| `visit_required` | held | **committed now** | yes |
| `escalate` | moves to a senior consultant of the same specialty | follow the case, not released | yes |

## Tests

```
.venv\Scripts\python -m pytest
```

47 tests, no API key or network required. They cover the schema-drift class of
bug (the original code read a `platelets` key that existed in no dict, so every
call raised `KeyError`), the decision lifecycle end-to-end through the real
FastAPI app, the invariant that routing consumes no resources, the queue's
severity-dominates-waiting property, escalation reaching a senior consultant,
the PHC false alarm, the donor floor, and the eval harness's own metric math via
a mocked model.

## Swapping in real data

Everything lives behind `data_store.py` on purpose:
- `hospitals` (with each facility's `doctors` roster) → your real hospital
  inventory and staffing DB. Specialty eligibility is derived from the roster,
  not from a hand-maintained boolean, so the two cannot disagree.
- `consumption_history` → actual dispensing records, which is what would make
  Agent 4's forecast meaningful rather than seeded
- `case_types` → keep only as the fallback; the real path is `report_text`
- `patients` + `agent3_routing._reservations` → a real database. The ledger is
  keyed by patient id and is the only thing preventing double-allocation, so it
  needs a uniqueness constraint and a transaction, not a dict.

## Design documentation

- **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — the shape of the system: layer and
  dependency rules, the model trust boundary, the four cross-module contracts,
  state ownership and its concurrency consequences, the two independent planes,
  a failure-mode table, and the extension points. Read this first to understand
  the system as a whole.
- **[`DECISIONS.md`](DECISIONS.md)** — every design decision (D-01…D-51) with
  the alternatives that were rejected and *why*. Start here if you want to know
  why something is the way it is, or want to argue with it.
- **[`FLOW.md`](FLOW.md)** — end-to-end walkthrough: boot order, per-agent
  control flow, variable/return types, the frontend ↔ API mapping, data
  provenance, glossary, eval flow, and the test map.

## Known gaps

- **In-memory state, no locking.** Sync handlers run in FastAPI's threadpool, so
  concurrent `POST /patients` can race on the ID counter and on Agent 3's
  read-modify-write. Fine for a demo, not for concurrent use.
- **No auth.** `POST /patients/{id}/decide` is open to any caller, so anyone can
  admit or discharge a patient. This is the first thing that must change before
  the service touches real PHI — a real deployment needs authentication,
  per-doctor authorisation, and an append-only audit log of who decided what.
- **Decisions have no undo.** A `visit_required` decision commits resources and
  only a later `release()` returns them; there is no "undo admission" endpoint,
  and a second decision on the same case is refused with 409. A mis-click is
  therefore not correctable through the API at all — recovering one means
  editing the in-memory store out of band.
- **The queue clock is not wall-clock.** Waiting times come from
  `data_store.now()`, which is a fixed value unless a test or demo advances it.
  It makes waiting times deterministic and testable, and it also means the
  displayed wait only moves when the server does. Replace it with a real clock
  in production, keeping the injection point so the tests still work.
- **Model accuracy is unmeasured here** (no key in this environment). Run the
  harness before making any claim about how well it triages.
- This is a simulation on synthetic data. It is not a medical device and the
  triage output is not for clinical use.
