# Flow — how this project actually runs

A trace-oriented guide: what happens, in what order, and **where every value
comes from**. Read this when you need to answer "where does that number on the
screen come from?" or "what breaks if I change X?".

For *why* things are the way they are, see [`DECISIONS.md`](DECISIONS.md). For
the layer structure, contracts and trust boundary, see
[`ARCHITECTURE.md`](ARCHITECTURE.md).

Line references are `file:line` against the current tree.

---

## 1. The whole shape

```
                    ┌──────────────── browser ────────────────┐
                    │  frontend/  (no build step)             │
                    │  app.js → fetch(API_BASE + path)        │
                    └───────────────────┬──────────────────────┘
                                        │ HTTP (JSON)
                    ┌───────────────────▼──────────────────────┐
   QUEUE PATH                          │  main.py — FastAPI, 14 routes           │
                    └───────────────────┬──────────────────────┘
                                        │
      report_text ──► Agent 1 ──► Agent 2 ──► Agent 3 ──► review slot
                    1_triage   2_allocator 3_routing          (NO bed held)
                       │           │            │                   │
                    (LLM)       (code)       (code)      ← only Agent 1 may call a model
                       │           │            │                   │
                    llm.py     data_store  data_store         agents/queue.py
                     Groq      (beds,stock) (roster)         (3 ordered views)
                                        │                        │
                                        │                        ▼
                                        │              doctor decides:
                                        │              no_visit ────────► nothing held
                                        │              visit_required ──► commit() holds ICU+stock
                                        │              escalate ────────► senior consultant
                                        │
   INVENTORY PATH   data_store.consumption_history ──► Agent 4 ──► alerts + transfers
                    (30-day seeded series)            4_forecast

   EVAL PATH        eval/make_dataset.py ──► lab_reports.json ──► eval/run_eval.py ──► results.json
                    (synthetic, seeded)                (78 reports)   (scores the model)
```

The two paths share `data_store` but never share control flow. Agent 4 is
called on demand by the API, not by the patient pipeline. The queue engine
(`agents/queue.py`) reads the same `patients` list the API writes and derives
its ordering on every request, so there is no stored queue position to fall out
of sync with reality.

---

## 2. Boot sequence

Importing anything that touches `data_store` executes, in order:

| Step | Where | What happens |
|---|---|---|
| 1 | `llm.py:30` | `load_dotenv()` runs. Real env vars still win over the file. |
| 2 | `llm.py:32-34` | `MODEL`, `TIMEOUT`, `RETRIES` read from env with defaults. |
| 3 | `llm.py:90-99` | `SCHEMA` built from `TriageResult` and closed for strict mode (`_close`, `llm.py:71`). |
| 4 | `llm.py:104` | `_trace` = empty ring buffer, cap 50. |
| 5 | `data_store.py:35-45` | `medicines_catalog` literal — 9 drugs, NLEM 2022. |
| 6 | **`data_store.py:49-56`** | **Assertion:** if the catalog has a key missing from `models.MedicineKey`, the process raises `RuntimeError` here. This is the intended loud failure (D-04). |
| 7 | `data_store.py:60-93` | `hospitals` list — 4 facilities, literal. |
| 8 | `data_store.py:140-149` | `case_types` — the 4 dropdown profiles. |
| 9 | `data_store.py:155-180` | `consumption_history` — 30 days × 4 facilities × 9 medicines, generated from `random.Random(1337)`. Deterministic. |
| 10 | `main.py:17-25` | CORS middleware added; `ALLOWED_ORIGINS` defaults to `*`. |

Nothing is loaded from a database or a file. `data_store.py` is the single
seam for real data — the `CONNECT LATER` note at `data_store.py:22-24` and the
README's "Swapping in real data" section both point at it.

---

## 3. The patient path — `POST /patients`

Entry: `main.py:38-76`. Body validated as `PatientIn` (`models.py:29-32`):
`name: str`, `case_type: str`, `report_text: Optional[str]`.

### Step 0 — routing the input (`main.py:46`)

```python
need, step1 = agent1_triage.run(p.case_type, p.report_text)
```

`agents/agent1_triage.py:158-162` picks the path:

- `report_text` present and non-blank → `from_report()` — the **LLM path**
- otherwise → `from_rules()` — the **rule path**

A `ValueError` (unknown `case_type`, `agents/agent1_triage.py:48`) becomes HTTP
422 at `main.py:47-48`.

> Note: `case_type` is **ignored** whenever `report_text` is supplied. The
> frontend relies on this — in "Case profile" mode a pasted report still wins.

### Step 1 — Clinical Triage (`agents/agent1_triage.py`)

Two paths, one output shape (D-06).

**LLM path** — `from_report()`, `agent1_triage.py:70-97`:

1. `llm.triage_report(report_text)` (`llm.py:125`)
2. `None` returned → `_fallback_step()` (`:100-125`) → Yellow, confidence 0.0,
   red flag, `step["source"] = "fallback"`
3. Otherwise normalise the result into `need`:
   - `medicines = result.medicine_map()` (`models.py:58`)
   - merge `platelets_needed` into the `platelet_concentrate` line with
     `max()` (`:78-79`, D-08)
   - drop zero quantities (`:83`)
   - `"none"` specialist → `None` (`:91`)

**Rule path** — `from_rules()`, `agent1_triage.py:45-67`: reads
`data_store.case_types[case_type]`, applies the same platelet merge (`:50-56`).

Both return a `need` dict with exactly these 10 keys (`:28-42`):

```
source  severity  label  icu  platelets  specialist
medicines  red_flags  confidence  reasoning
```

**Where the numbers come from on this path:**

| `need` field | LLM path source | Rule path source |
|---|---|---|
| `severity` | model output, validated by `Literal["Green","Yellow","Red"]` (`models.py:4`) | `case_types[x]["severity"]` |
| `label` | `TriageResult.case_label` | `case_types[x]["label"]` |
| `icu` | `TriageResult.icu_needed`, `0 ≤ n ≤ 10` (`models.py:47`) | `case_types[x]["icu"]` |
| `platelets` | `TriageResult.platelets_needed`, `0 ≤ n ≤ 50` | `case_types[x]["platelets"]` |
| `specialist` | `Literal["hematologist","cardiologist","pediatrician","none"]` | `case_types[x]["specialist"]` |
| `medicines` | `List[MedicineOrder]`, keys restricted to `MedicineKey` | `case_types[x]["medicines"]` |
| `confidence` | `0.0–1.0` float from the model | hardcoded `1.0` (`:38`) |
| `reasoning` | free text, prompted to cite actual values (`llm.py:61-66`) | generated string (`:65`) |

### Step 1b — inside the LLM call (`llm.py:125-198`)

This is the only place in the codebase that talks to a model.

- **Availability gate** — `llm.available()` (`llm.py:116`) is just
  `bool(os.getenv("GROQ_API_KEY"))`. If unset, a `skipped` trace entry is
  recorded and `None` is returned immediately.
- **Client** — `_client()` (`llm.py:120-122`) constructs `groq.Groq` with
  `timeout=TIMEOUT`, `max_retries=0` (retries are handled by our own loop so
  they are traceable).
- **Request** (`llm.py:139-155`):
  - `messages` = `[SYSTEM_PROMPT, "Lab report:\n\n" + report_text]`
  - `SYSTEM_PROMPT` (`llm.py:36-69`) carries the severity rubric, the resource
    rules, and explicit instructions to cite values and never invent them
  - `temperature = 0.0` — deterministic decoding, this is classification
  - `max_tokens = 900`
  - `response_format = {type: "json_schema", strict: true, schema: SCHEMA}`
- **Retry loop** (`llm.py:155-190`): `RETRIES + 1` attempts. Only
  `RateLimitError` / `APIConnectionError` / `APIStatusError` / `APIError` are
  retried, with `sleep(1.5 * (attempt+1))` between. A `pydantic.ValidationError`
  is **not** retried — a second identical request produces the same violation.
- **Trace** — every attempt records to `_trace` via `_record()` (`llm.py:111`):
  status, model, latency, attempt number, token counts, and the parsed result.
  This is what `GET /agents/llm-trace` serves and what the Pipeline tab renders.
- **Return** — `TriageResult` on success, `None` on any failure. **Never
  raises.** A demo that dies because an API is down is a bad demo (`llm.py:11`).

### Step 2 — Resource Allocator (`agents/agent2_allocator.py:43-71`)

Takes `need`, returns `(eligible, step2)`. Pure arithmetic, no model.

For each of the 4 hospitals, `_evaluate()` (`:23-40`) collects reasons it
**cannot** take the case:

| Check | Code | Reads |
|---|---|---|
| Free ICU | `:26-27` | `h["icu"]` vs `need["icu"]` |
| Specialist on staff | `:28-29` | `h[need["specialist"]]` bool |
| Platelet units | `:30-32` | `stock_of(h, "platelet_concentrate")` |
| Every medicine | `:33-39` | `stock_of(h, med)`; unknown key → "not in catalog" |

An empty reason list means eligible. `rejected` carries `{id, name, reasons}`
so the UI can explain itself (D-11). `platelet_concentrate` is skipped in the
medicine loop because it is the same physical stock already checked (`:34-35`).

### Step 3 — Routing & Load Balancing (`agents/agent3_routing.py:61-114`)

Takes `(eligible, need, patient_id)`, returns `(hospital, doctor, step3, breakdown)`.

- **No eligible facility** → `(None, None, step, {})` (`:62-68`). The case is
  escalated.
- **Score** each survivor, `_score()` (`:34-58`):
  ```
  proximity    = 1 / (1 + distance_km / 40)      # 80km → 0.33
  capacity     = min(1, icu / icu_total)          # 1.0 if no ICU needed
  availability = min(1, max(capacity - load) / 10)
  score        = 0.45·proximity + 0.35·capacity + 0.20·availability
  ```
  Weights are module constants. **Distance comes from**
  `data_store.distance_from_origin()` — a haversine between `PATIENT_ORIGIN`
  and the hospital's `lat`/`lng`. That is the only geography in the system.
- **Score the (facility, doctor) pair, not the facility alone.** Scoring the
  facility and then picking a doctor inside it was a real defect: the nearest
  hospital won on proximity every time and its one relevant doctor absorbed the
  whole district's caseload (D-46).
- **Select: nearest facility that still has headroom, then least loaded there.**
  The weighted score is *not* the decider, because proximity (0.45) dwarfs the
  entire realistic spread of the availability term (~0.09) — it does not
  balance load. Availability is applied as a ≥25% headroom threshold
  (`MIN_HEADROOM`) so a full doctor spills the case to the next district
  instead of stacking it locally. The score is still returned as `breakdown`
  because it is a good explanation even when it is not the decision.
- **Pick a doctor**: least `load/capacity` among the required specialty, with a
  general-medicine fallback, then a fall-through to the runner-up facility if
  nobody is free.
- **Increment `doctor["load"] += 1`** — but reserve *nothing*. A review
  assignment is workload, so load must rise, or the headroom threshold in the
  selection above never shrinks and the whole mechanism degenerates (D-47).
- **Record the ledger** with `icu: 0, medicines: {}, committed: False`. The
  empty `icu`/`medicines` is the point: resources are not held (D-42).
- **Step payload**: prose `text` plus machine-readable `score` and `breakdown`.

### Step 4 — status decision and record

```
doctor assigned → status = "awaiting_review"
no doctor       → status = "unassigned"   (still open, still in the queue)
```

Note what is *not* decided here. Severity does not choose a status, and nothing
is reserved. The record carries the triage `need` so the later decision path
commits exactly what triage asked for rather than re-deriving it, plus queue
bookkeeping: `enqueued_at`, `decided_at`, `decision`, `escalated_from`,
`ai_recommendation`. The response includes `steps`, which is what makes the
Pipeline tab possible.

---

## 3b. The queues — `agents/queue.py`

Pure derivation over `data_store.patients`. No stored positions, so the ordering
cannot drift from the underlying records.

**Priority** (D-40, D-41):

```
priority = SEVERITY_WEIGHT[severity] + min(waited_minutes / WAIT_DIVISOR, MAX_WAIT_BONUS)
           Red 1000 · Yellow 500 · Green 100        (12 min/point, capped at 300)
```

Severity dominates; waiting time breaks ties inside a band. The cap is
*strictly* below the narrowest band gap (300 < 400) so no wait can climb a case
out of its severity band — a cap equal to the gap lets a stale Green case tie a
fresh Yellow, and the tie falls back to arrival time, which is the FIFO the
queue exists to remove.

`priority_breakdown()` returns the arithmetic per row, so the order can be
argued with rather than merely trusted.

**Three views**, all recomputed per request:

| View | Function | Content |
|---|---|---|
| Whole network | `patient_queue()` | every open case, priority order, with position |
| Per doctor | `doctor_queues()`, `doctor_queue(name)` | one panel per doctor; top row is their next patient |
| Senior | `specialist_queue()` | `awaiting_specialist` cases grouped by required specialty, with the referring doctor recorded |

Open statuses are `awaiting_review`, `awaiting_specialist`, `unassigned`.
`unassigned` is deliberately open (D-44) — a case with no eligible facility is
still a patient waiting.

`portal_view()` is the patient-facing projection: position, wait, decision,
assigned doctor and facility. It omits stock, ICU counts, doctor workload, red
flags and the internal `need` block (D-49).

---

## 4. The doctor decision — `POST /patients/{id}/decide`

The core handoff. No model is involved at any point.

Request body is `DecisionIn` (`models.py`), a closed `Literal` of three verbs —
an unrecognised verb is a 422, not a case that silently never closes.

Already-decided → 409 (`:decide_patient`). The decision is not a silent
overwrite of the first one.

| Decision | Doctor slot | ICU / medicines | Status out |
|---|---|---|---|
| `no_visit` | released | never held | `closed_remote` |
| `visit_required` | held | **committed now** | `admitted` |
| `escalate` | moves to senior consultant | follow the case | `awaiting_specialist` |

- **`no_visit`** → `release()` returns the slot. `resources_released` in the
  response. This is the option that makes a digital queue worth building: a
  report handled remotely never consumed a bed.
- **`visit_required`** → `commit()` checks and *then* takes stock and the ICU
  bed. If the facility cannot supply them, it returns `{"error": ...}` and the
  endpoint raises 409 rather than admitting a patient the hospital cannot
  treat. On success the record's `reservation.committed` is `True`.
- **`escalate`** → `reassign()` finds a **senior** consultant of the same
  specialty, nearest first, and moves the review assignment. Any committed
  resources follow the case to the new facility (D-43). If no senior is free
  network-wide, 409 with `no_senior_available` — a reportable outcome, not a
  silent failure. `escalated_from` records the referring doctor and facility.

In all three, `decision`, `decision_note` and `decided_at` are written to the
record. `POST /patients/{id}/approve` is an alias for `no_visit` (D-48), kept
so existing clients keep working without creating a second release path.

`commit()`/`release()` keep ICU bounded by `min(icu_total, ...)` and are
idempotent, which is what lets the demo run indefinitely (D-09).

---

## 5. The inventory path — Agent 4

Independent of the patient pipeline. Called on demand by two endpoints.

### `GET /command-center/forecast` → `agent4_forecast.py:241-262`

```
consumption_history  (data_store.py:180, seeded 30 days)
        │
        ├─ _history_frame()   :43-56  → long DataFrame, one row per (hospital, medicine, day)
        ├─ _daily_draw()      :59-77  → groupby → mean_daily, recent (day ≥ 23),
        │                                 prior (16 ≤ day < 23), trend = recent − prior
        └─ _coverage()        :80-90  → stock / max(mean, recent[, recent+trend])
                                    │
                                    └─→ one row per (facility, medicine), sorted worst-first
```

Each row: `hospital_id, hospital, medicine, medicine_name, stock,
reorder_threshold, mean_daily, recent_daily, days_of_cover`. `medicine_name`
comes from the catalog (`data_store.py:35-45`), not the key — the UI uses this
to label transfers readably (`app.js:246` `medName`).

36 rows today: 4 facilities × 9 medicines.

### `GET /command-center/alerts` → `agent4_forecast.py:93-156`

Per facility, build a `factors` list:

1. **ICU** (`:104-109`) — fires only if `icu_total > 0 and icu == 0`. A PHC with
   no ICU is correctly equipped, not short (D-12).
2. **Per medicine** (`:111-134`) — skip if `days >= WARN_DAYS (7)` **and**
   `stock >= reorder_threshold`. Otherwise emit a factor carrying the reason
   text, severity, days of cover, draw rate and direction.
3. If no factors → the facility is skipped entirely (`:136-137`).
4. `_find_donor()` (`:188-205`) scores every other facility by *true surplus*
   above its own floor across the needed medicines; the best becomes `donor_id`.
5. `_primary_shortage()` (`:159-164`) picks the worst stock factor;
   `_suggested_amount()` (`:167-176`) proposes
   `min(donor_surplus, receiver_gap)` where
   `gap = reorder_threshold × 3 − receiver_stock`.

Response per alert: `hospital_id, hospital, critical, reasons[], message,
donor_id, donor, transfer{medicine, amount}`. `message` is a pre-joined string
kept for API consumers; the UI renders `reasons[]` because it is structured.

### `POST /command-center/redistribute` → `agent4_forecast.py:208-238`

Recomputes everything server-side; the client-suggested `amount` is a
*request*, not an instruction.

```
validate medicine ∈ catalog      → KeyError  → 404   (:216-217)
validate donor / receiver exist   → KeyError  → 404   (:219-223)
validate donor != receiver        → ValueError → 400  (:224-225)
validate amount > 0               → ValueError → 400  (:226-227)
        │
        ├─ stats   = _daily_draw() → the DONOR's own current draw   (:229)
        ├─ surplus = donor_stock − _min_keep(medicine, stats)      (:231)
        │            _min_keep = max(reorder_threshold, days_of_cover × 3.0)
        ├─ moved   = int(max(0, min(amount, surplus)))              (:233)
        └─ take(donor) + give_back(receiver) when moved > 0         (:236-237)
```

`moved == 0` is a **success**, not an error: the donor has nothing above its
floor (D-15). The UI reports it as "Nothing moved" with an explanation, which
is more useful than an error toast.

---

## 6. `GET /hospitals` — why it is a projection

`main.py:98-124` builds a fresh dict per facility rather than returning the
stored record. Two fields are **derived here and stored nowhere**:

- `free_platelets` = `h["stock"]["platelet_concentrate"]` (`main.py:119`)
- `distance_km` = `round(distance_from_origin(h), 1)` (`main.py:115`)

D-18: a stored derived field drifts; keeping them out of the store is what stops
`free_platelets` disagreeing with `stock`.

The response also copies `stock` and `doctors` (`main.py:120-121`) so the UI
never touches internal objects.

---

## 7. Frontend → backend map

Every network call the UI makes, and what it drives. `API_BASE` is
`http://localhost:8000` (`frontend/config.js:2`).

| UI action | Function | Request | Rendered by |
|---|---|---|---|
| Page load | `checkHealth` | `GET /` | status pills |
| Page load | `init` → `loadQueue` | `GET /queue` | warms the queue + nav count |
| Run Triage / `Ctrl+Enter` | `submitPatient` | `POST /patients` | toast + Pipeline tab |
| Pipeline tab | `renderPipeline` | *(local)* | `runCard` from `state.history` |
| Pipeline tab | `loadTrace` | `GET /agents/llm-trace` | trace list + structured JSON |
| Queues tab | `loadQueue` | `GET /queue` | `renderQueue`: tiles, scope switch, panels |
| Scope switch | `renderQueue` | *(local)* | by doctor / whole network / senior queues |
| Search + severity filter | `filteredQueue` | *(local)* | re-renders from cached `state.queue` |
| Decision button | `decidePatient` | `POST /patients/{id}/decide` | confirm modal → refetch → toast |
| Command tab | `loadCommandCenter` | 3 parallel GETs | KPIs + 2 tables + alerts |
| Refresh / 15s tick | `refreshLoop` | command: 3 GETs · queue: `GET /queue` | same |
| Transfer | `redistribute` | `POST /command-center/redistribute` | toast + re-render |

`decidePatient` **refetches `GET /queue` after a decision** rather than patching
local state. A decision can move a case between queues, change another doctor's
workload, and commit or release resources; guessing the resulting position
client-side is the kind of optimistic update that makes a queue lie to its
users.

The 15s tick also polls the Queues tab, not just Command Center: waiting time
is shown live on every row, so an open queue screen must keep counting up.

Client-side state that has **no** server equivalent:

- `state.history` (`app.js:86`) — the `steps` arrays. Persisted to
  `localStorage` under `att_runs_v3` (`:252`, `:255`, D-32). The server keeps
  patient records but does not expose past `steps` for query, so a refresh would
  otherwise erase every agent trace.
- `state.query` / `state.filter` — pure view filters over the cached
  `state.queue`, applied client-side. The *ordering* is never a client concern;
  it comes from the server so every consumer sees one ranking.
- `state.scope` — which of the three queue views is on screen.
- `state.sort` — column sort for the command-center tables.
- `state.countdown` — the auto-refresh ring.

Every backend-originated string is escaped through `esc()` (`app.js:109`) before
reaching `innerHTML` (D-35).

---

## 8. Where every number on screen comes from

| Screen value | Origin |
|---|---|
| Queue header tiles (in queue / critical / with senior / unassigned / longest wait) | `GET /queue` → `queue_stats()`, server-computed. Not counted client-side, so a tile cannot disagree with the list under it |
| Per-row wait time | `waiting_minutes` from `queue.priority_breakdown()`'s clock, not a client timer |
| Per-row priority | `priority` + `priority_breakdown` from `GET /queue`; the bar visualises the *wait* component only |
| Case count per doctor panel | `doctor_queues[].open_cases` from the server, not a client-side count |
| "With senior" count | `queue_stats().escalated_pending` |
| Free ICU `3/10` | `sum(h["icu"])` / `sum(h["icu_total"])` computed in the UI at `app.js:702-703` from `GET /hospitals` |
| Platelet units total | `sum(h["free_platelets"])`, `app.js:704` |
| Shortage alert count | `alerts.length` and `alerts.filter(a => a.critical).length` on the `list[dict]` `check_shortages()` returns, `app.js:708` |
| "Under 7 days cover" | `forecast.filter(f => f.days_of_cover < 7).length`, `app.js:706` |
| Route score bars | `step.breakdown.{proximity,capacity,availability}` from `_score()`, `agent3_routing.py:52-57` |
| Distance `0.0 km` | haversine, `data_store.py:122-134` |
| "why filtered out" | `step.rejected[].reasons` from `_evaluate()`, `agent2_allocator.py:23-40` |
| Model chip + latency | `step.model` / `step.latency_ms`, sourced from `llm._trace[0]`, `agent1_triage.py:137-155` |
| Structured JSON block | `llm._trace[i].result` — the validated `TriageResult` |
| Confidence chip | `need["confidence"]` → record `confidence`, `main.py:70` |
| Triage chip (LLM/fallback/rules) | `step["source"]`, **not** `need["source"]` — see D-07 |
| Doctor case count | `GET /patients`, grouped client-side by `p.doctor` |
| Severity badge colour | `record["severity"]`, from Agent 1 |
| Medicine display name | `medicines_catalog[med]["name"]`, learned into `medNames` at `app.js:242` |

---

## 9. Variable glossary

Names that recur across modules and are easy to confuse.

| Name | Type | Meaning | Defined |
|---|---|---|---|
| `need` | `dict` | Agent 1's output: what the patient requires, plus a **recommendation**. 13 fixed keys. The contract between Agent 1 and everything downstream. Identical on both the LLM and rule paths. | `agent1_triage._need` |
| `step` / `step1..3` | `dict` | Per-agent display record: `title`, `text`, `source`, plus agent-specific extras. Returned to the UI; never used for logic. | `agent1_triage.py:127,137` etc. |
| `eligible` | `list[dict]` | Facilities that passed Agent 2. Actual hospital dicts, not copies. | `agent2_allocator.py:43` |
| `rejected` | `list[dict]` | `{id, name, reasons[]}` for the ones that failed, and why. | `agent2_allocator.py:69` |
| `breakdown` | `dict` | `{distance_km, proximity, capacity, availability}` for the winning pair. Explanation only — selection uses distance + headroom, not this score (D-46). | `agent3_routing._score` |
| `_reservations` | `dict` | `patient_id → {hospital, doctor, icu, medicines, committed, specialty}`. The ledger. `icu`/`medicines` are empty until `commit()`. Module-level, process-lifetime. | `agent3_routing._reservations` |
| `committed` | `bool` | On a ledger entry: are physical resources actually held? Distinguishes a review slot from a resource commitment, which is what makes `release()` handle both and `reassign()` move one without disturbing the other. | `agent3_routing.commit` |
| `priority_breakdown` | `dict` | `{severity, severity_points, waited_minutes, wait_points, capped, total}`. The arithmetic behind a queue position. | `agents/queue.py` |
| `OPEN_STATUSES` | `tuple` | `awaiting_review`, `awaiting_specialist`, `unassigned` — the statuses that mean "still in the queue". | `agents/queue.py` |
| `draw` | `DataFrame` | Per (facility, medicine): `mean_daily, recent, trend`. | `agent4_forecast.py:59` |
| `lookup` | `dict` | `draw` indexed by `(hospital_id, medicine)` for O(1) row access. | `agent4_forecast.py:97` |
| `factors` | `list[dict]` | Everything wrong with one facility in one check pass. Drives both the alert and the donor search. | `agent4_forecast.py:101` |
| `_min_keep` | `float` | The floor below which a donor may not be drained. | `agent4_forecast.py:179` |
| `SCHEMA` | `dict` | Strict-mode JSON Schema derived from `TriageResult`. | `llm.py:99` |
| `_trace` | `list` | Last 50 model calls, newest first. In-memory, process-lifetime. | `llm.py:103` |

Three different things are all called "source": `need["source"]`
(`llm`/`rules`, D-07), `step["source"]` (adds `fallback`/`deterministic`),
and the CORS/`SOURCE`-ish config in `main.py:17`. Don't conflate them.

---

## 10. Eval flow

```
eval/make_dataset.py
  TEMPLATES (24)  ──►  build(count_per_template=2)   :322
                        for each template, emit a "clean" copy
                        and (for Red/Yellow) an "ocr" copy  :342-351
                        corruption: _corrupt()              :298-319
                          28% digit-pair swap on numeric lines
                          18% one substitution from OCR_SUBSTITUTIONS  :291-295
                          10% whitespace collapse
                        rng = random.Random(20240917)      :323  ← deterministic
  ──► eval/lab_reports.json   78 reports
        24 templates · 48 clean · 30 ocr
        severity: 20 Green / 26 Yellow / 32 Red

eval/run_eval.py
  for each report:
    result = llm.triage_report(report_text)        :104   ← real API call
    base   = baseline_triage(report_text)          :109   ← regex, :71-76
    compare, accumulate confusion + per-noise + per-template
  ──► results.json  +  printed report  :188-225
```

The harness makes one API call per report, so `--limit N` exists for iteration
(`:230`). It refuses to run without a key (`:234-236`).

The baseline is *deliberately* bad at negation: `"No shock, no bleeding"`
matches the literal `shock` and scores Red (`run_eval.py:57-59`). That is the
measured justification for using a model, pinned by
`tests/test_pipeline.py:286-292`. If someone "fixes" the baseline, the
comparison stops measuring anything.

`results.json` is gitignored (`.gitignore`).

---

## 11. Test flow

`pytest.ini` sets `testpaths=tests`, `pythonpath=.`. 47 tests, no network, no
API key — they import the real agents and monkeypatch only `llm.triage_report`.

The autouse fixture `reset_state` restores ICU, stock, doctor load, the patient
list, the id counter and the reservation ledger before every test. Without it
the suite would depend on execution order, because the store is module-level
mutable state. It restores by **iterating the roster**, not by index — the
previous version named `hospitals[0..3]` explicitly and silently stopped
resetting the fifth facility when the roster was expanded, so a test's result
depended on which test ran before it.

`triage_result(**kw)` is the single factory for fake model output. The three
queue-recommendation fields are required by the schema, so every test that
fabricates a `TriageResult` must supply them; routing them through one helper
keeps a future contract change to a one-line edit instead of a dozen literals
drifting apart.

Groups: data-store accessors, Agent 1 both paths (including a cross-path shape
equality check), Agent 2 filtering, Agent 3 scoring + ledger, the queue's
priority arithmetic, Agent 4 forecast + donor floor, schema strictness, the
API decision lifecycle through the real FastAPI app, and the eval harness's own
metric math via a fake model.

Several tests are named as regressions. They encode a specific past bug and
should not be deleted or relaxed:

| Test | Bug it prevents |
|---|---|
| `test_rules_path_emits_platelets` | agents read a `platelets` key that existed in no dict → `KeyError` on every call |
| `test_routing_prefers_nearer_facility_over_idle_doctor` | picking the globally least-loaded doctor sent rural patients 150 km away |
| `test_repeated_severe_cases_do_not_deadlock` | permanent ICU decrement with no release path bricked the demo |
| `test_zero_icu_at_a_phc_is_not_a_shortage` | a permanently un-clearable alert trains people to ignore alerts |
| `test_baseline_is_blind_to_negation` | "fixing" the baseline would void the model's justification |
| `test_routing_does_not_consume_resources_until_a_doctor_decides` | reserving on assignment would tie up exactly the inventory a physical queue ties up — the digital queue would recover nothing (D-42) |
| `test_severity_never_beats_waiting_time_in_the_queue` | an uncapped wait term lets a mild case outrank a critical one, i.e. under-triage by arithmetic (D-40, D-41) |
| `test_escalation_moves_to_a_senior_and_keeps_resources` | escalation that releases resources frees the bed at the moment a consultant picks the case up (D-43) |
| `test_portal_hides_other_patients_and_internal_inventory` | a patient-facing view leaking the facility's platelet count (D-49) |

**A note on the queue tests, because it bit us once.** The first version of
`test_severity_never_beats_waiting_time_in_the_queue` compared
`SEVERITY_WEIGHT` against `MAX_WAIT_BONUS` directly. That is tautological:
deleting the cap from `wait_bonus()` left the test passing, because the constant
it read was unchanged. The test now drives `priority_score()` with extreme waits
(1 day → 10,000 days) and asserts on the returned scores. **When a test guards
behaviour, assert through the function, not through the constant it reads** —
otherwise it cannot fail.

Mutation-checked, so the guards are known to bite: re-adding eager reservation
to `run()` fails 5 tests; removing the wait cap fails 1; inverting
`SEVERITY_WEIGHT` fails 1.

---

## 12. Things to know before changing anything

- **Adding a medicine** requires edits in two places or the process raises at
  import: `models.MedicineKey` (`models.py:11-21`) and
  `data_store.medicines_catalog` (`data_store.py:35-45`).
- **Widening a `TriageResult` field type** means re-running the eval harness —
  the schema *is* the safety boundary (D-03, `models.py:36-43`).
- **Adding an agent** means adding to the `steps` list at `main.py:76` and
  teaching the Pipeline tab to render it (`app.js:426-437`).
- **Any new endpoint** needs an entry in the `README.md` table and a mapping in
  the §7 frontend map.
- **Concurrency is not safe.** `_next_id` and Agent 3's read-modify-write race
  under FastAPI's threadpool (D-22). If you add parallelism, fix that first.
- **Never reserve during `agent3_routing.run()`.** It assigns a review slot and
  increments `load`; that is all. Reserving belongs in `commit()`, called only
  from the `visit_required` decision path. Putting a `take()` or
  `icu -=` back into `run()` reintroduces D-42 and is caught by
  `test_routing_does_not_consume_resources_until_a_doctor_decides`.
- **Adding a specialty** needs edits in three places: `models.Specialist`,
  `data_store.SPECIALTIES`, and the `doctors` rosters — plus any place that
  assumes `resolve_specialty()` cannot return `general_medicine`. Note that
  `resolve_specialty("none")` deliberately returns `general_medicine`: "no
  specialty needed" still needs a doctor, and letting it through as a literal
  `"none"` would mean cases with nobody to review them.
- **Re-tuning `SEVERITY_WEIGHT` means re-checking `MAX_WAIT_BONUS`.** The cap
  must stay strictly below the narrowest band gap, or a long-waiting mild case
  ties (and so is ordered by arrival time) a fresh severe one. The queue test
  asserts this through the scoring function and will fail if you get it wrong.
- **The queue clock is not wall-clock.** `data_store.now()` is a stored value
  advanced only by `advance_clock()`. Displayed wait times only move when the
  server does. Keeping it this way is what makes the seeded demo reproducible
  and the tests deterministic; production needs a real clock behind the same
  interface.
