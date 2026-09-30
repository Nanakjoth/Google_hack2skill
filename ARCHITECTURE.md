# Architecture

The shape of the system: what each layer owns, what flows between them, what
lives in memory, and where the trust boundary sits.

- **Why** things are the way they are → [`DECISIONS.md`](DECISIONS.md) (D-01…D-56)
- **Line-by-line trace** of every request → [`FLOW.md`](FLOW.md)
- **Running it** → [`README.md`](README.md)

Line references are `file:line` against the current tree. Counts below are from
the current data (`4` facilities, `9` medicines, `78` eval reports) — verified,
not estimated.

---

## 1. One-paragraph version

A FastAPI process owns all state in memory and exposes nine routes. One
request runs three agents in sequence: a model-backed triage agent turns a raw
lab report into a **validated proposal**, then two deterministic agents verify
that proposal against live inventory and reserve resources for it. A fourth
agent runs independently, on demand, and forecasts stock-out risk from a
consumption time series. The model's output crosses exactly one trust boundary —
into a Pydantic schema — and is never trusted for a fact about the physical
world. A dependency-free browser app reads the same API and renders the
decision trail, so a human can audit every number the system produced.

---

## 2. System context

```
┌────────────────────────────────────────────────────────────────────────┐
│ CLIENTS                                                                 │
│                                                                        │
│  frontend/ (vanilla JS, no build)          eval/ (offline, separate)    │
│   4 views · localStorage run history         make_dataset → JSON        │
│   polls /command-center/* every 15s         run_eval → results.json     │
└──────────────┬──────────────────────────────────────┬──────────────────┘
               │ HTTP + JSON                          │ in-process import
               │                                      │
┌──────────────▼──────────────────────────────────────▼──────────────────┐
│ APPLICATION PROCESS  (uvicorn, single process, no external services)     │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ HTTP EDGE                    main.py                             │  │
│  │  14 routes · CORS · validation · the doctor decision endpoint     │  │
│  └───────┬──────────────────────────────────────────────────────────┘  │
│          │                                                          │
│  ┌───────▼──────────────────────────────────────────────────────────┐  │
│  │ AGENT PLANE  (patient path, sequential, one case per request)     │  │
│  │                                                                   │  │
│  │   1_triage ──► 2_allocator ──► 3_routing ──► queue                │  │
│  │   (LLM read)    (verify)        (slot only)   3 views + 3_decide  │  │
│  └───────┬──────────────────────────────────────────────────────────┘  │
│          │                                                          │
│  ┌───────▼──────────────────────────────────────────────────────────┐  │
│  │ INVENTORY PLANE  (command centre, on demand, network-wide)        │  │
│  │   4_forecast  (pandas over a 30-day series → days-of-cover)       │  │
│  └───────┬──────────────────────────────────────────────────────────┘  │
│          │                                                          │
│  ┌───────▼──────────────────────────────────────────────────────────┐  │
│  │ STATE  data_store.py   (the only mutable state in the system)     │  │
│  │   hospitals · stock · doctors · case_types · consumption_history  │  │
│  │   patients · _next_id                                           │  │
│  │   + reservations ledger inside agents/agent3_routing.py           │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ MODEL ACCESS  llm.py   ← the ONLY outbound network dependency     │  │
│  │   Groq · strict JSON schema · retry · trace ring buffer           │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

**Outbound dependencies, exhaustively:** Groq (only from `llm.py`), and nothing
else. No database, no cache, no queue, no object store, no external auth
provider. Everything the system knows lives in one process's memory and dies
with it.

---

## 3. Layers

Four layers, strictly one-directional dependencies. An import that points
backwards is a design error, not a style preference.

| Layer | Modules | May import from | Must never |
|---|---|---|---|
| **L4 Edge** | `main.py` | L3, L2, L1 | contain business logic |
| **L3 Agents** | `agents/agent1..4` | L2, L1 | import `main`, import each other's state |
| **L2 Access** | `llm.py`, `models.py` | L1, L0 | import agents |
| **L1 State** | `data_store.py` | L0 | import agents, `llm`, or `main` |
| **L0 Primitives** | `pydantic`, `pandas`, `groq`, `re`, `json` | — | — |

Verified import graph (`grep` over `agents/*.py`):

```
agent1_triage  → llm, data_store
agent2_allocator → data_store
agent3_routing → data_store
agent4_forecast → data_store, pandas
```

`data_store.py:31` imports `models.MedicineKey` — L1 reaching *up* to L2. This
is the one intentional exception and it is a hard import-time assertion
(`data_store.py:49-56`): the catalog and the model's enum must agree, and failing
loudly at boot beats failing at request time (D-04). It is an upward import for
the purpose of a *consistency check*, not for a dependency.

### Module responsibility table

| Module | Lines | Responsibility | Owns state? |
|---|---|---|---|
| `main.py` | 166 | HTTP routing, CORS, request/response shapes, status derivation | no |
| `models.py` | 71 | The schema contracts: `TriageResult`, `PatientIn`, `RedistributeIn`, `MedicineKey` | no |
| `llm.py` | 198 | The only model call: prompt, strict schema, retries, trace | `_trace` ring buffer |
| `data_store.py` | 189 | All inventory + patient state and every mutation accessor | **yes — the whole system** |
| `agents/agent1_triage.py` | 165 | Read a report (LLM) or a profile (rules) → a `need` | no |
| `agents/agent2_allocator.py` | 71 | Filter facilities to those that can physically treat the case | no |
| `agents/agent3_routing.py` | 148 | Score eligible facilities, assign, **reserve**, release | `_reservations` ledger |
| `agents/agent4_forecast.py` | 262 | Days-of-cover forecast, shortage alerts, donor-safe transfers | no |
| `eval/make_dataset.py` | 371 | Generate the synthetic 78-report eval set | writes `lab_reports.json` |
| `eval/run_eval.py` | 251 | Score the model vs. ground truth and vs. a regex baseline | writes `results.json` |
| `tests/test_pipeline.py` | 47 tests, no network, no API key | no |
| `frontend/*` | 1994 | 4 views over 8 endpoints; run history in `localStorage` | `att_runs_v3`, `att_theme` |

---

## 4. The trust boundary

This is the architecture. Everything else is in service of it.

```
   UNTRUSTED                          BOUNDARY                    TRUSTED
   ─────────                          ────────                    ───────

   report text  ──►  Groq (llama-3.3)  ──►  response_format:        TriageResult
   phone photo       a probabilistic       {type: json_schema,       (pydantic)
   OCR noise         function we do        strict: true,
                     not control                              │
                                                               ▼
                                                    need  ──►  Agents 2,3,4
                                          (fixed 10-key dict)       arithmetic over
                                                                    real inventory
```

Three mechanisms, each closing a distinct failure mode:

1. **Constrained decoding, not parsing.** The response schema is *generated from*
   `TriageResult` (`llm.py:90-99`) and forced into strict mode by `_close()`
   (`llm.py:71-87`). The model cannot emit a field the pipeline does not
   understand, and cannot name a drug outside the 9-key `MedicineKey` `Literal`
   (`models.py:11-21`). A hallucinated medicine is a decode-time schema
   violation, not a `KeyError` three agents later.
2. **Proposal, never fact.** `icu_needed` and `platelets_needed` are *requests*.
   Agent 2 re-derives whether the network can satisfy them from live stock
   (`agent2_allocator.py:23-40`). A hallucinated ICU bed cannot become a reserved
   one (D-02).
3. **Total function, never an exception.** `llm.triage_report()` returns
   `TriageResult | None` and never raises (`llm.py:125-198`). Missing key,
   timeout, 500, or invalid JSON all collapse to `None`, and Agent 1's fallback
   routes an unreadable report to *manual review* — never to Green (`agent1_triage.py:100-124`).

The converse rule is equally load-bearing: **the model is never asked a question
arithmetic answers.** Agent 4's forecast is a mean daily draw and a division
(`agent4_forecast.py:59-90`), not a prompt. Asking a model "how many days of
platelet stock remain" would be strictly worse and slower.

---

## 5. Contracts

Four shapes cross module boundaries. Nothing else should.

### 5.1 `TriageResult` — the model boundary (`models.py:35-59`)

```
severity       Literal["Green","Yellow","Red"]
case_label     str
icu_needed     int     0 ≤ n ≤ 10
platelets_needed int   0 ≤ n ≤ 50
specialist     Literal["hematologist","cardiologist","pediatrician","none"]
medicines      [{ medicine: MedicineKey, qty: int 0..100 }]
red_flags      [str]
confidence     float   0.0 ≤ n ≤ 1.0
reasoning      str
```

Doubles as the JSON Schema handed to the LLM. It is generated, not hand-written,
so it cannot drift from what the pipeline expects. Bounds are not decoration —
they bound the blast radius of a bad proposal to 10 beds and 50 units.

### 5.2 `need` — the agent-to-agent contract (`agent1_triage.py:28-42`)

```
source  severity  label  icu  platelets  specialist
medicines  red_flags  confidence  reasoning
```

Exactly 10 keys, built by `_need()`, emitted identically by the LLM path and the
rule path. **Agents 2–4 must never branch on `need["source"]`** — if they could,
a model outage would change routing behaviour, and the test suite would need two
code paths per agent (D-06). The shape is asserted at
`tests/test_pipeline.py:114-120`.

### 5.3 `step` — the audit contract

Each agent returns a display dict beside its real return value: `title`, `text`,
`source`, plus agent-specific extras (`eligible`, `rejected`, `score`,
`breakdown`, `latency_ms`, `tokens`). Returned in the `steps` array of
`POST /patients` (`main.py:76`) and rendered by the Pipeline tab. It is
presentation, never control flow — no agent reads another agent's step.

> `models.AgentStep` (`models.py:62-64`) exists as a partial formalisation of
> this shape but is **not used by any agent**. The steps are plain dicts.

### 5.4 API surface — 14 routes

| Method | Path | Reads | Writes |
|---|---|---|---|
| GET | `/` | config | — |
| POST | `/patients` | `case_types` (rules) | `patients`, `_next_id`, ledger (**load only**), `enqueued_at` |
| GET | `/patients` | `patients` | — |
| GET | `/patients/{id}` | `patients` | — (patient-facing projection) |
| POST | `/patients/{id}/decide` | `patients` | **`status`, `decision`, ledger, stock, `icu`, `load`** |
| POST | `/patients/{id}/approve` | `patients` | alias for `decide(no_visit)` |
| GET | `/queue` | `patients` | — |
| GET | `/queue/patients` | `patients` | — |
| GET | `/queue/doctors` | `patients`, `hospitals` | — |
| GET | `/queue/doctors/{name}` | `patients` | — |
| GET | `/queue/specialists` | `patients` | — |
| GET | `/hospitals` | `hospitals` | — |
| GET | `/command-center/alerts` | `hospitals`, `consumption_history` | — |
| GET | `/command-center/forecast` | same | — |
| POST | `/command-center/redistribute` | same | stock (donor → receiver) |
| GET | `/agents/llm-trace` | `_trace` | — |

The asymmetry in the Writes column is the design. `POST /patients` writes **no
physical resources** — only a review assignment and the queue entry. The only
routes that can commit or return an ICU bed and medicine stock are
`/decide` and `/command-center/redistribute`, and `/decide` is a human action by
construction. There is no endpoint that commits a resource because a model
produced a value.

The queue views are pure derivations over `patients`: nothing is stored, so
there is no persisted queue position to drift out of sync with the records it
was derived from.

---

## 5b. The trust boundary, restated

`DECISIONS.md` D-39 records that the plan labels the queue engine an "AI QUEUE
ENGINE" and that it is implemented as deterministic code. The reason is worth
stating at the architectural level rather than only in the decision log:

> Priority is a comparison over facts the server already holds — severity from
> triage, wait time from a clock, availability from the doctor roster. A model
> in that position would produce unstable ordering between identical requests,
> could not be explained to the patient waiting in it, and could not be tested.
> It would also re-open the exact trust boundary D-01 closed, in the one place
> where an error means a patient waits longer than they should.

The model's influence is therefore bounded to three fields, all advisory, none
acted upon: `physical_visit_recommended`, `specialist_escalation_recommended`,
`recommended_action`. They exist so the doctor queue can show advice beside the
case — the difference between "the AI decided" and "the AI advised". If a
proposed change makes any of them *load-bearing*, it has crossed the boundary
and needs a new decision record, not a patch.

---

## 6. The two planes

The patient plane and the inventory plane share `data_store` and share **no
control flow**. That separation is what keeps Agent 4 from being able to affect a
routing decision.

```
   QUEUE PLANE                            INVENTORY PLANE
   ───────────                            ───────────────
   POST /patients                         GET  /command-center/alerts
     1 → 2 → 3   (sequential, per case)   GET  /command-center/forecast
   GET  /queue{,/patients,                POST /command-center/redistribute
         /doctors,/specialists}              4_forecast
   POST /patients/{id}/decide
     no_visit      → 3.release()
     visit_required→ 3.commit()   ← the only place a bed is taken
     escalate      → 3.reassign() to a senior

   reads:  case_types, hospitals,         reads:  consumption_history,
            + the model (1 only)                  hospitals
   writes: patients, _next_id,            writes: stock (transfers only)
            _reservations, load,
            stock + icu  (decide only)
```

They meet in exactly one place: both can move medicine between `stock` dicts.
Agent 3 removes units for a patient; Agent 4 moves units between facilities. Both
go through the same accessors (`take` / `give_back`), so a transfer cannot drive
a stock level negative and a routing reservation cannot exceed what exists.

Note the write asymmetry between the two queue writes. `POST /patients` writes
`load` and the ledger but **no** stock and **no** ICU — assignment is workload,
not commitment (D-42). Only `decide(visit_required)` calls `take()` and
decrements `icu`. That single line is the difference between a digital queue and
a physical one; see §5b and D-39–D-43.

Agent 4 has no scheduler. It is called on demand by the API and the docstring
says to cron it in production (`agent4_forecast.py:3-5`) — the natural place for
a real deployment to add one.

---

## 7. State ownership

All state is module-level mutable Python in one process. There is no database,
and no lock.

| State | Owner | Mutated by | Lifetime |
|---|---|---|---|
| `hospitals[]` — beds, stock, doctor load | `data_store` | `take`, `give_back`, agent 3, `redistribute` | process |
| `patients[]` | `data_store` | `POST /patients`, `/decide` | process |
| `_next_id[0]` | `data_store` | `next_patient_id()` | process |
| `_reservations{}` | `agent3_routing` | `run()`, `release()` | process |
| `consumption_history` | `data_store` | **never** (seeded once at import) | process |
| `_trace[]` (cap 50) | `llm` | every model call | process |
| `att_runs_v3` | browser | frontend | browser profile |
| `att_theme` | browser | frontend | browser profile |

### The single-writer rule for stock

`data_store.take()` / `give_back()` are the only functions that change a stock
level, and `agent3_routing.release()` is the only thing that gives back what
`run()` took. That symmetry is the invariant the whole demo rests on: without a
release path, one severe case permanently consumed an ICU bed and the demo
deadlocked (`tests/test_pipeline.py:179-196` is the regression test).

### Derived values are computed, never stored

`free_platelets` and `distance_km` do not exist on the hospital record — they are
computed at the API boundary (`main.py:115`, `main.py:119`). Same for
`days_of_cover` in Agent 4. A stored derived field is a field that will disagree
with its source; the previous version's top-level `platelets` key is exactly that
bug (D-17, D-18).

### The concurrency consequence

Handlers are sync `def`, so FastAPI runs them in a threadpool. `_next_id` and
Agent 3's read-modify-write of `icu` / `load` / `stock` are **not** atomic. Two
concurrent `POST /patients` can hand out the same id, or both pass an Agent 2
capacity check and then double-reserve a single ICU bed. This is a known and
documented gap (D-22), not an oversight — the fix is a lock or a real database,
and both are listed as open questions in `DECISIONS.md` Part 3.

---

## 8. Request lifecycle

### `POST /patients` — the canonical sequence

```
Client ──► main.py:39   validate PatientIn
        ──► main.py:46   agent1.run(case_type, report_text)
        │                    report_text non-blank ──► llm.triage_report()
        │                                                   │
        │                          Groq, strict schema ◄────┘
        │                          ├─ TriageResult ──► need(source="llm")
        │                          └─ None ──────────► need(Yellow, conf 0.0)   ← never Green
        │                    report_text blank ──────► need(source="rules")
        │
        ──► main.py:50   agent2.run(need)
        │                    per facility: icu ≥ need.icu ?
        │                               specialist on staff ?
        │                               platelets ≥ need.platelets ?
        │                               every medicine in stock ?
        │                    ──► (eligible[], step2 with rejected[] + reasons[])
        │
        ──► main.py   next_patient_id()
        ──► main.py   agent3.run(eligible, need, pid)
        │                    eligible empty ──► (None, None) ──► status "unassigned"
        │                    else score 0.45·proximity + 0.35·capacity + 0.20·availability
        │                         nearest facility with ≥25% headroom, then
        │                         least-loaded qualified doctor there
        │                         load += 1                              ← workload only
        │                         _reservations[pid] = {icu: 0, medicines: {},
        │                                             committed: False} ← no bed held
        │
        ──► main.py   status: unassigned | awaiting_review
        ──► main.py   patients.insert(0, record)  +  enqueued_at
        ──► main.py   {**record, steps: [step1, step2, step3]}
```

Nothing here reserves an ICU bed or a single unit of medicine. The record enters
the queue as work for a doctor, and the physical world is only touched when that
doctor asks for it (§5b, D-42).

### `POST /patients/{id}/decide` — the commitment point

```
find patient            ─► 404 if absent
already decided (409)   ─► refuse: the first decision is not silently overwritten
decision not in {no_visit, visit_required, escalate} ─► 422 (closed Literal)

no_visit       ─► release(pid): pop ledger, restore doctor load -= 1
                 (icu/medicines were never taken)
                 status = "closed_remote"

visit_required ─► commit(pid): check THEN take() every medicine, icu -= n
                 fails → 409, nothing taken
                 ok     → status = "admitted", ledger.committed = True

escalate       ─► reassign(pid, reason): nearest SENIOR consultant of the same
                 specialty, free doctor only
                 committed?  move icu + stock to the new facility
                 uncommitted? move the load only
                 no senior free ─► 409 no_senior_available
                 ok ─► status = "awaiting_specialist", escalated_from = {...}
```

Idempotent on the resource side: `release()` and `commit()` return `False` and
change nothing if there is nothing to move, so a retried request cannot
double-commit.

`POST /patients/{id}/approve` is an alias for `no_visit` (D-48) — kept so an
existing client does not break, and deliberately the *only* alias, so release
cannot be reached through two code paths that could drift.

---

## 9. Data model

### Hospital (`data_store.py:60-93`)

```
{ id, name, district, type,            # type ∈ {PHC, CHC, District Hospital}
  lat, lng,                             # haversine against PATIENT_ORIGIN
  icu_total, icu,                       # icu = FREE, not total
  hematologist, cardiologist, pediatrician,   # bools — a facility-level roster
  stock: { <medicine_key>: int },       # ALL stock, nested, no flat copies
  doctors: [{ name, load, capacity }] }
```

Grounded in IPHS norms: a PHC has ~6 beds and no ICU, a CHC ~30 with a small
stabilisation unit, a District Hospital 100+ with a real ICU. Medicines are
NLEM 2022 names across 27 therapeutic categories. The `type` distinction is
load-bearing, not decoration — it is why Agent 4 does not raise a false ICU
alert at a PHC (D-12).

### Medicine catalog (`data_store.py:35-45`)

```
key → { name, category, reorder_threshold }
```

The key set is asserted equal to `models.MedicineKey` at import. Adding a drug
requires editing both files, and the process refuses to start if you forget.

### Reservation (`agents/agent3_routing.py:88-93`)

```
patient_id → { hospital: <ref>, doctor: <ref>, icu: int, medicines: {key: int} }
```

References to the live objects, not copies, so release always restores to the
same facility the reserve touched. `reservation()` (`:133-141`) projects it into
a JSON-safe summary for the API; `outstanding()` (`:144-148`) exists to support a
reaper that nothing currently calls.

### Consumption history (`data_store.py:155-180`)

```
hospital_id → medicine → [30 daily draw floats]
```

Seeded from `random.Random(1337)` so forecasts, eval runs and screenshots are
reproducible. Weekend surge (×1.35) and a slow upward drift are baked in, which
is what makes the PHC stock-out *predictable* rather than random noise. This is
the input that would be replaced by real dispensing records first.

---

## 10. Failure model

Every failure mode has a defined, tested behaviour. There is no unhandled
degradation path in the pipeline.

| Failure | Detected at | Behaviour | Test |
|---|---|---|---|
| No `GROQ_API_KEY` | `llm.py:132` | `skipped` trace entry → `None` → Yellow fallback | `test_llm_returns_none_without_api_key` |
| Rate limit / timeout / 5xx | `llm.py:178` | retry up to `LLM_RETRIES` with linear backoff → `None` | — |
| Schema violation | `llm.py:162` | `ValidationError`, **not** retried (same input, same violation) → `None` | `test_generated_schema_is_strict_mode_clean` |
| Catalog ↔ enum drift | `data_store.py:51` | `RuntimeError` at import — the process does not start | `test_catalog_matches_llm_enum` |
| Over-allocation | `data_store.py:111` | `ValueError`, no silent clamp | `test_take_refuses_to_over_allocate` |
| Unknown `case_type` | `agent1_triage.py:48` | `ValueError` → HTTP 422 | — |
| No facility eligible | `agent3_routing.run` | `unassigned` — still open, still queued, no doctor | `test_unassigned_case_stays_visible_in_the_queue` |
| Second decision on one case | `main.py` | HTTP 409 — no silent overwrite | `test_a_case_cannot_be_decided_twice` |
| `visit_required`, stock or ICU short at decision time | `agent3_routing.commit` | HTTP 409, **nothing taken** — check before mutate | `test_commit_then_release_restores_exact_state` |
| `escalate`, no senior consultant free | `agent3_routing.reassign` | HTTP 409 `no_senior_available` — never fall back to a junior silently | `test_escalation_reports_when_no_senior_is_available` |
| Unknown donor/receiver/medicine | `agent4_forecast.py:216-223` | `KeyError` → HTTP 404 | `test_redistribute_validates_its_inputs` |
| Donor at its floor | `agent4_forecast.py:233` | moves `0` — a success, not an error | `test_redistribute_never_drains_the_donor` |
| PHC with no ICU | `agent4_forecast.py:104` | **no alert** — correctly equipped, not short | `test_zero_icu_at_a_phc_is_not_a_shortage` |
| Concurrent writes | nowhere | **races.** Documented, unfixed (D-22) | — |

The asymmetry worth stating: failures bias toward *over*-triage and
*escalation*, never toward auto-clearing. An unreadable report is Yellow, not
Green. A transfer that cannot happen is `0`, not a silent partial. A facility
that cannot treat a case is rejected, not assigned anyway.

---

## 11. Observability

| Signal | Where produced | Where consumed |
|---|---|---|
| `steps[0..2]` | every agent | `POST /patients` response → Pipeline tab |
| `step["source"]` | agents 1–3 | source badge: LLM / Conservative fallback / Rule-based |
| `step.breakdown` | agent 3 | three score bars with their weights |
| `step.rejected[]` | agent 2 | "why was this filtered out" |
| `step.latency_ms`, `step.tokens` | agent 1 (reads `llm._trace[0]`) | model chip |
| `_trace[]` (cap 50) | `llm.py:111` | `GET /agents/llm-trace` → trace list + raw structured output |
| `GET /` | `main.py:29` | status pills: API online, model configured |

The design goal: **every number on screen can be traced to a line of code.** The
frontend computes only four aggregates client-side — free ICU, platelet total,
alert count, under-7-days count (`app.js:705-710`) — everything else is either
server-computed or read straight off a returned payload.

---

## 12. Extension points

Each is a single-file change, by construction.

| To do this | Edit | Why nothing else breaks |
|---|---|---|
| Real hospital inventory | `data_store.hospitals` | Agents go through `by_id` / `stock_of` / `take`; no agent hardcodes a facility |
| Real dispensing records | `data_store.consumption_history` | Agent 4's output shape is unchanged, so the frontend does not change |
| Add a medicine | `models.MedicineKey` **and** `data_store.medicines_catalog` | The import assertion forces both; nothing else references drug keys |
| Widen a `TriageResult` field | `models.py` | Schema is generated — but re-run the eval, the schema *is* the safety boundary (D-03) |
| Add an agent | new `agents/agent5_*.py` + `main.py:76` + the Pipeline renderer | Agents are pure functions over `need`; there is no registry to update |
| Change routing weights | `agent3_routing.py:26-28` | Constants, and the breakdown is returned so the change is visible in the UI |
| Swap the model | `LLM_MODEL` env var | `TriageResult` is the contract, not the vendor |
| Deploy elsewhere | `frontend/config.js` | One line; the frontend has no build step and no other environment coupling |

The `data_store` seam is the load-bearing one: it is the only module whose
replacement changes the meaning of the system rather than its behaviour.

---

## 13. What this architecture is not

Stated so the design is not over-claimed:

- **Not horizontally scalable.** One process, one copy of the state. Two workers
  would give two divergent networks.
- **Not durable.** A restart loses every patient, reservation and stock level.
  It comes back to seed data, which is why the demo is reproducible and why it
  is not a system of record.
- **Not concurrently safe.** See §7.
- **Not an authenticated system.** `POST /patients/{id}/decide` and
  `POST /command-center/redistribute` are open to any caller, and `ALLOWED_ORIGINS`
  defaults to `*`. Real PHI needs authentication, consent handling and an audit
  log on every release.
- **Not a validated medical device.** Synthetic data, synthetic eval set, unmeasured
  model accuracy. The eval harness exists so that claim can eventually be tested
  rather than asserted.
- **Not benchmarked.** 78 reports over 24 templates is a scaffold. The harness
  prints lift over a regex baseline and counts under-triage separately, but no
  accuracy number from this repo should be quoted before running it with a key.
