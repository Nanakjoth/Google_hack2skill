# Decisions Log

Every non-obvious choice made in this repo, and the reason for it. Append new
entries; never delete old ones. If a decision is reversed, mark the old entry
**SUPERSEDED** and add a new one that points back at it.

Each entry has an ID (`D-nn`) so it can be referenced from a commit message, a
code comment, or a review.

For the system structure these decisions produced — layers, contracts, state
ownership, trust boundary, failure modes — see
[`ARCHITECTURE.md`](ARCHITECTURE.md).

Attribution is explicit:

- **Part 1** — Backend/architecture decisions. These were in place before the
  UI work; their rationale is recorded in the code and in `README.md`. They are
  transcribed here so there is one place to look, not because they were made
  during the UI rewrite.
- **Part 2** — Frontend decisions taken in the UI rewrite of 2026-09-27.
- **Part 3** — Open questions and things deliberately *not* decided.

---

## Part 1 — Backend and architecture

### D-01 — Only Agent 1 may call a model; Agents 2–4 are deterministic

**Decision.** `llm.py` is the only module that imports `groq`. Agents 2, 3 and
4 are arithmetic over `data_store` state.

**Why.** Whether a hospital has a free bed or enough platelets is a fact about
inventory. A model asserting it is a patient-safety failure, not a UI glitch.
This is the project's core rule: **the LLM proposes, code disposes.** It also
makes the system testable — 26 tests run with no API key and no network.

**Where.** `llm.py` (sole import), `agents/agent2_allocator.py:23`,
`agents/agent3_routing.py:34`, `agents/agent4_forecast.py:80`.

**If changed.** You would be moving bed/stock assertions into a
non-deterministic component. Don't, without a clinical safety review.

---

### D-02 — The LLM is an untrusted proposal, verified downstream

**Decision.** `TriageResult.icu_needed` / `platelets_needed` are *requests*.
Agent 2 checks every one against real stock before Agent 3 reserves anything.

**Why.** A hallucinated ICU bed routes a patient to a facility that cannot treat
them. Separating "what the report says" from "what the network has" means a
wrong model output degrades to an escalation, never a wrong bed.

**Where.** `agents/agent1_triage.py:70-97` produces the proposal;
`agents/agent2_allocator.py:23-40` (`_evaluate`) is the verification seam.

---

### D-03 — Output is schema-constrained, never parsed from prose

**Decision.** The model is called with `response_format: json_schema`,
`strict: true`, and the schema is generated from the Pydantic model
`TriageResult` rather than hand-written.

**Why.** Two reasons. (1) A malformed model response becomes a hard validation
error instead of a silent misparse. (2) The schema is derived from the code, so
it cannot drift from what the pipeline actually expects. Pydantic emits nested
`$defs` objects that strict mode rejects unless every object node declares
`additionalProperties: false` and a complete `required` list — hence
`_close()`.

**Where.** `models.py:35-59` (`TriageResult`), `llm.py:71-87` (`_close`),
`llm.py:90-96` (`_strict_schema`), `llm.py:99` (`SCHEMA`), asserted by
`tests/test_pipeline.py:257`.

---

### D-04 — Medicines are a closed `Literal`, cross-checked against the catalog at import

**Decision.** `models.MedicineKey` is a `Literal` of exactly 9 keys.
`data_store.py` raises `RuntimeError` at import if `medicines_catalog` contains
a key not in that `Literal`.

**Why.** A bare `dict` field would let the model request any drug name, and the
allocator would have no stock figure to check it against — the failure would
surface as a `KeyError` mid-routing, or worse, as a silently ignored
requirement. A `Literal` makes an unknown drug a *schema violation at decode
time*. Failing at import means a catalog edit cannot ship broken.

**Where.** `models.py:11-21`, `data_store.py:49-56`, belt-and-braces test at
`tests/test_pipeline.py:50`.

---

### D-05 — A model failure degrades to Yellow "needs clinician review", never Green

**Decision.** `_fallback_step` returns severity `Yellow` with confidence `0.0`
and a red flag, rather than auto-clearing an unreadable report.

**Why.** This is the asymmetry that matters in triage: over-triage wastes a bed,
under-triage can kill. A report the system could not read is a report with
*unknown* severity, and unknown must not be treated as benign.

**Where.** `agents/agent1_triage.py:100-125`, tested at
`tests/test_pipeline.py:89-95`.

---

### D-06 — Both Agent 1 paths emit one identical `need` shape

**Decision.** `_need()` (`agents/agent1_triage.py:28`) builds a fixed 10-key
dict; the rule path and the LLM path both return it. Downstream agents never
branch on `need["source"]`.

**Why.** If Agents 2–4 could tell which path ran, they would need two code
paths to test, and a model outage would change routing behaviour. Keeping them
blind means the fallback is *the same pipeline with a different input*, not a
separate degraded mode.

**Where.** `agents/agent1_triage.py:28-42`, shape asserted at
`tests/test_pipeline.py:114-120`.

---

### D-07 — `need["source"]` is normalised to `llm`/`rules`; the *step* records the fallback

**Decision.** When the model fails, `need["source"]` stays `"rules"` (the
default from `_need()`) but the returned `step["source"]` is `"fallback"`.

**Why.** Two different questions, deliberately answered by two different
fields. `need["source"]` answers *"which decision shape produced this need"* and
has exactly two possible values, so downstream code and the patient record stay
simple. `step["source"]` answers *"what actually happened to this request"*, and
the UI needs that distinction to be honest — a Yellow "manual review" produced by
an outage is not the same event as a Yellow from a real clinical read.

**Why it matters.** The Pipeline tab labels from the step, so it shows
"Conservative fallback". The Doctor Queue only has the patient record, so it
shows the normalised source. This is intentional, not an oversight.

**Where.** `agents/agent1_triage.py:121` (step) vs `:30` (need default), asserted
at `tests/test_pipeline.py:94-95`.

**If changed.** If you collapse these to one field, the UI can no longer tell a
model outage from a clinical Yellow. Add a separate `fallback: bool` instead of
overloading `source`.

---

### D-08 — `platelets_needed` and the `platelet_concentrate` medicine line are one physical stock

**Decision.** Both Agent 1 paths merge them with `max()` and filter zero
quantities.

**Why.** They are the same units in the same blood bank. Kept separately, the
allocator would check 5 against stock twice and Agent 3 would decrement 10
while only 5 exist.

**Where.** `agents/agent1_triage.py:50-56` (rules), `:79-83` (LLM), tested at
`tests/test_pipeline.py:108-111`.

---

### D-09 — Reservations are a ledger keyed by patient id, and release is idempotent

**Decision.** Agent 3 records `_reservations[patient_id]` and only mutates live
inventory. `release(patient_id)` restores and returns `False` on a second call.

**Why.** The previous version decremented `icu` and never gave it back, so one
severe case bricked the demo — recovery meant restarting the server. Free ICU
beds only ever went down. A ledger makes reserve/release symmetric and makes
"approve" a real operation rather than a label change.

**Where.** `agents/agent3_routing.py:31` (ledger), `:81-93` (reserve),
`:116-131` (release), `:133-142` (`reservation()`), tested at
`tests/test_pipeline.py:160-196`.

---

### D-10 — Routing is a transparent weighted score, and proximity dominates

**Decision.**
`score = 0.45·proximity + 0.35·free_capacity + 0.20·doctor_availability`,
with `proximity = 1/(1 + distance_km/40)`. The winning breakdown is returned.

**Why.** The original picked the globally least-loaded doctor, which sent rural
patients 150 km to a metro hospital. Distance is a real clinical factor in rural
referral. Returning the breakdown means a human can sanity-check the route
instead of trusting it — the score is a decision aid, not an oracle.

The 40 km decay constant means 80 km scores ~0.33: near enough that a busy
nearby facility still beats a distant idle one, far enough that proximity is
not a tiebreak.

**Where.** `agents/agent3_routing.py:26-28` (weights), `:34-58` (`_score`),
`:99-112` (breakdown in the step), tested at
`tests/test_pipeline.py:149-157`.

---

### D-11 — A facility that is rejected reports *why*

**Decision.** Agent 2 returns `rejected` with a per-facility reason list, not
just an empty eligible list.

**Why.** A command centre that only says "no match" is useless to the person who
has to fix it. Each reason is independently checkable ("needs 1 ICU bed(s), has
0 free"), which is also what makes the model's proposal auditable (D-02).

**Where.** `agents/agent2_allocator.py:23-40` (`_evaluate`), `:69` (returned),
consumed by the UI in the Pipeline tab's "why was this filtered out" panel.

---

### D-12 — A PHC having no ICU is not a shortage

**Decision.** The ICU alert fires only when `icu_total > 0 and icu == 0`.

**Why.** Under IPHS norms a PHC has ~6 beds and no ICU by design. The previous
version flagged "0 ICU beds" at every PHC, permanently. An alert that can never
clear trains people to ignore alerts — the alert system itself becomes noise.

**Where.** `agents/agent4_forecast.py:102-109`, tested both ways at
`tests/test_pipeline.py:210-224`.

---

### D-13 — Days of cover, not stock-vs-threshold

**Decision.** Alerting uses `stock / daily_draw` (days of cover) with
thresholds `WARN_DAYS = 7.0` (`agent4_forecast.py:39`) and
`CRITICAL_DAYS = 3.0` (`:38`), computed by Pandas from
the 30-day seeded history.

**Why.** A reorder threshold is a *stock level*; days of cover is a *rate of
burn*. They answer different questions — a facility can sit above its reorder
point and still be one bad weekend from a stock-out. A time series is exactly
what an LLM is bad at and a `DataFrame` is good at, which is also why this is
Agent 4 and not a model call.

**Where.** `agents/agent4_forecast.py:38-40` (thresholds), `:43-56`
(`_history_frame`), `:59-77` (`_daily_draw`), `:80-90` (`_coverage`).

---

### D-14 — Coverage uses the *higher* of long-run and recent draw

**Decision.** `rate = max(mean_daily, recent_daily)`, pushed up further by a
positive trend.

**Why.** In steady state the long-run mean is less noisy; during an outbreak the
recent week is the honest number. Taking the max is the conservative choice, and
for a stock-out forecast conservative is the correct bias. Under-forecasting
cover is the dangerous direction.

**Where.** `agents/agent4_forecast.py:80-90`.

---

### D-15 — Redistribution cannot drain a donor below its floor

**Decision.** `_min_keep(medicine, stats)` = `max(reorder_threshold,
days_of_cover · TRANSFER_BUFFER_DAYS)`. A transfer moves
`min(surplus, gap)` and may legitimately move 0.

**Why.** Otherwise a transfer re-triggers the alert it was raised to clear, and
the command centre oscillates. Returning `0` instead of raising is deliberate —
"this donor has nothing to give" is a valid answer, not an error, and the UI
reports it as such.

**Where.** `agents/agent4_forecast.py:179-185` (`_min_keep`), `:167-176`
(`_suggested_amount`), `:208-238` (`redistribute`), tested at
`tests/test_pipeline.py:227-246`.

---

### D-16 — `take()` raises instead of clamping

**Decision.** `take()` raises `ValueError` when asked for more than exists.

**Why.** A silent clamp means a patient is routed to a facility that silently
could not supply part of the order. Failing loudly is the only safe default for a
clinical path.

**Where.** `data_store.py:106-115`, tested at `tests/test_pipeline.py:60-63`.

---

### D-17 — Stock lives only in the nested `stock` dict, reached via accessors

**Decision.** Agents call `stock_of` / `take` / `give_back`; they never index
`h["stock"][key]` directly.

**Why.** The original had a top-level `hospitals[...]["platelets"]` key read by
four agents and defined in no dict — every call raised `KeyError`. The accessors
are the seam that makes that class of bug impossible and gives one place to
validate against the catalog.

**Where.** `data_store.py:100-119`, `:11-17` (the note that records this).

---

### D-18 — `free_platelets` and `distance_km` are derived at the API boundary

**Decision.** Neither is stored on the hospital record. `GET /hospitals`
computes both.

**Why.** A stored derived field drifts. The same reasoning as D-17: the old
top-level `platelets` key "can never drift out of sync with `stock` again"
because it no longer exists.

**Where.** `main.py:119` (`free_platelets`), `main.py:115` (`distance_km`),
`data_store.py:132-134`.

---

### D-19 — The eval harness scores the model against a keyword baseline, and
under-triage is counted separately

**Decision.** `run_eval.py` always reports LLM accuracy, a regex baseline
accuracy, the lift over it, a confusion matrix, and an `under_triage_count`.

**Why.** Without the baseline there is nothing to compare against, and "the model
works" is unfalsifiable. The baseline is deliberately naive and *blind to
negation* — it scores "No shock, no bleeding" as Red because it matches the
literal string `shock`. That blindness is the documented justification for using
a model, so it is pinned by a test rather than left to drift into a bug.

Under-triage is separated from raw accuracy because on a Green-heavy set a
model that never escalates scores well and is dangerous. A model that always
says Red would also score well on accuracy, which is why the confusion matrix
exists.

Model-unavailable is counted as a **miss**, never a pass.

**Where.** `eval/run_eval.py:51-76` (baseline), `:88-185` (metrics),
`:39` (`SEVERITY_PENALTY`), `:154-155` (under-triage), tested at
`tests/test_pipeline.py:286-373`.

---

### D-20 — The eval dataset is synthetic, seeded, and self-degrading

**Decision.** 78 reports from 24 clinical templates (48 clean + 30
OCR-degraded). RNG seeded (`random.Random(20240917)`). Ground truth follows from
published severity criteria, not opinion.

**Why.** Reproducibility: the same dataset, the same baseline score, the same
screenshots. The OCR twins exist because real referrals arrive as phone photos
of photocopied reports — `_corrupt` swaps digit pairs (28% of numeric lines),
applies substitutions like `SpO2`→`Sp02` (18%), and collapses whitespace (10%).

**Why it is stated plainly in the README.** 78 reports is a scaffold, not a
validated benchmark. No accuracy number should be quoted from this repo without
re-running the harness with a key.

**Where.** `eval/make_dataset.py:290-319` (`OCR_SUBSTITUTIONS`, `_corrupt`),
`:322-352` (`build`), `eval/lab_reports.json`, `README.md:73-75`.

---

### D-21 — No build step and no framework in the frontend

**Decision.** Plain HTML/CSS/JS. One configurable line (`API_BASE` in
`config.js`). No npm, no bundler, no framework.

**Why.** The backend is the project. A build step would make the UI harder to
open and read, and the interaction surface here is four views over eight
endpoints — a framework would add more ceremony than it removes. It also means
the frontend can be dropped next to any real deployment by editing one line.

**Where.** `frontend/config.js`, `frontend/README.md`.

---

### D-22 — In-memory state, wide-open CORS, no auth — acknowledged, not fixed

**Decision.** Module-level mutable globals; `ALLOWED_ORIGINS` defaults to `*`;
`POST /patients/{id}/approve` is unauthenticated.

**Why.** It is a demo. The gaps are documented rather than half-solved, because
half-solving them (e.g. a token check with no user model) would look like
security without being any.

**Known concurrency bug.** Sync handlers run in FastAPI's threadpool, so
concurrent `POST /patients` can race on `_next_id` (`data_store.py:183-189`) and
on Agent 3's read-modify-write of `icu`/`load`/stock. Fine for a demo; not fine
for concurrent use.

**Where.** `README.md:123-129` (Known gaps), `main.py:14-25`,
`data_store.py:182-189`.

---

## Part 2 — Frontend rewrite, 2026-09-27

The four frontend files were rewritten. No backend file changed, no dependency
was added. Rationale for each choice:

### D-23 — Sidebar shell instead of top tabs

**Decision.** Fixed 250px sidebar with icons and live counts; sticky topbar
carrying the view title and status.

**Why.** Top tabs with four equal-weight items gave no room for the state a
clinician actually needs (how many cases are queued, is the model configured).
The sidebar's `kbd` hints and count badges make the workflow legible at a glance,
and the narrow-width breakpoint collapses it to a scrollable row, so mobile
keeps the same affordances.

**Where.** `frontend/index.html` (`.sidebar`, `.nav`), `frontend/styles.css`
(`--sb-w`, `@media (max-width: 860px)`).

---

### D-24 — Two-pane intake with a mode toggle

**Decision.** A segmented control switches between "Lab report" and "Case
profile". Only one form is visible at a time.

**Why.** Showing a textarea and a dropdown together implied both were required
and left the user to guess precedence. The backend's actual rule is that
`report_text` wins when present; the toggle makes that explicit while still
allowing a pasted report to override the selected profile.

**Why the profile cards instead of a `<select>`.** The four profiles differ in
consequence (ICU bed + 5 platelet units vs. none). A dropdown hides that behind
a single line of text; severity-coded cards with a coloured left edge surface it
before the user clicks.

**Where.** `frontend/index.html` (`#modeSeg`, `#caseGrid`),
`frontend/app.js` `setMode()`, `buildCaseCards()`.

---

### D-25 — The triage path is labelled in the UI, per request

**Decision.** The Pipeline tab shows one of three chips on the Agent 1 step:
model + name + latency, "Conservative fallback", or "Rule-based", derived from
`step.source`.

**Why.** The project's whole premise is that the model is one bounded component
among four. Hiding which path ran makes the system look like a black box. The
label comes from the *step*, not from `need["source"]` — see D-07 for why those
two differ.

**Where.** `frontend/app.js` `sourceBadge()`, called from `runCard()`.

---

### D-26 — Routing score and rejections are both visualised

**Decision.** Agent 3's `breakdown` renders as three animated bars with their
weights labelled; Agent 2's `rejected` list renders as a collapsible
"why was this filtered out" panel.

**Why.** These two payloads already existed in the API response and were being
flattened into one sentence of prose. Showing them is what makes the routing
auditable — a human can disagree with the 0.45/0.35/0.20 weights (D-10) because
the terms are now visible. Neither panel is a graph of model output: both are
deterministic arithmetic, which is why they are safe to show raw.

**Where.** `frontend/app.js` `scoreBars()`, `rejectedReasons()`.

---

### D-27 — Approve and redistribute both require explicit confirmation

**Decision.** Both are modal, and each modal states the consequence (what gets
returned to the network / what the donor floor will do).

**Why.** Both mutate shared network state, and both are irreversible from the
UI. "Approve & release" reads like a status change but frees a real ICU bed and
restocks real units. The modal lists the exact reservation being released.

**Where.** `frontend/app.js` `confirmModal()`, `approvePatient()`,
`redistribute()`.

---

### D-28 — Command center leads with KPIs, and tables are sortable

**Decision.** Four KPI tiles (free ICU, platelet units, alert count, pairs under
7 days cover) above the tables. Both tables sort on any column, toggling
ascending/descending.

**Why.** The previous view opened on a raw 4-row table and made the reader
compute network health themselves. The KPIs answer "is anything wrong" in one
glance; sorting answers "which facility" without reading every row. ICU free
beds and days-of-cover render as meters because a bare fraction (`0/2`, `0.3d`)
does not communicate urgency the way a bar does.

**Where.** `frontend/app.js` `loadCommandCenter()`, `icuCell()`, `th()`,
`sortRows()`.

---

### D-29 — Auto-refresh is visible, pausable, and shows a countdown

**Decision.** 15s polling with a countdown ring, a 15s/off toggle, and a manual
refresh button. Polling stops the moment you leave the tab.

**Why.** A silent 15s refresh either looks broken (nothing appears to happen) or
is invisible (you cannot tell if the number is current). The ring plus "updated
4s ago" answers "is this live?" without reading code. Stopping on tab change
avoids polling an endpoint nobody is looking at.

**Where.** `frontend/app.js` `refreshLoop()`, `updateRefreshNote()`,
`switchTab()`, `frontend/index.html` (`#refreshSeg`, `#ringFg`).

---

### D-30 — Feedback is a toast layer, not a single inline notice

**Decision.** All four feedback events (submit, approve, transfer, error) go to
a bottom-right toast stack. Errors persist longer than confirmations.

**Why.** The old single `#notice` div lived inside the intake card, so an error
raised on the Command Center tab was invisible — `setNotice()` was called from
`loadDoctorQueue` and `redistribute` but rendered somewhere the user was not
looking. A toast layer is tab-independent, which fixes a real reporting bug, and
it stacks so a burst of actions is not lost.

**Why errors linger (7s vs 3.8s).** An error you missed is a user retrying
blindly. `#notice` was removed from the markup entirely to prevent a dead
reference creeping back in.

**Where.** `frontend/app.js` `toast()`, `frontend/index.html` (`#toasts`,
`#modal-root`).

---

### D-31 — Live status pills for backend and model

**Decision.** The topbar polls `GET /` and shows API online/offline and
model-configured/not-configured, with a toast if the backend is unreachable on
load.

**Why.** Without a key, the LLM path silently does not run and every submission
uses the fallback. A user who does not know that will believe they are testing
the model. The pill makes the degradation visible up front, which is the same
honesty principle as D-25.

**Where.** `frontend/app.js` `checkHealth()`, `paintPills()`.

---

### D-32 — Run history persists in `localStorage`, capped at 25

**Decision.** Runs are stored client-side under `att_runs_v3` so a page refresh
does not erase the pipeline view.

**Why.** The server holds patient records but not the `steps` array for past
runs in a queryable way, so a refresh lost every agent trace — the most
explanatory part of the UI. The cap prevents unbounded growth, and the key is
versioned so a future shape change can invalidate old data instead of crashing
on it.

**Where.** `frontend/app.js` `saveRuns()`, `loadRuns()` (`LS_RUNS`),
`state.history`.

---

### D-33 — The pasted report is deliberately *not* cleared after a run

**Decision.** Submitting clears the patient name only; the report text stays.

**Why.** The clearest demo of the reservation ledger is submitting the same
severe case repeatedly to watch ICU capacity drain, then approving in the Doctor
Queue to watch it recover. Clearing the textarea after every run made that
sequence a re-paste per iteration. The "Clear" button is there for when you do
want it gone.

**Where.** `frontend/app.js` `submitPatient()`.

---

### D-34 — Keyboard shortcuts, and a global `svg` sizing rule

**Decision.** `1`–`4` switch views, `/` focuses queue search, `Ctrl+Enter`
submits. Separately: `svg { width: 1em; height: 1em; flex: none; }` as a base
rule, with component rules overriding it.

**Why (shortcuts).** The four views are a review workflow — moving between
intake, pipeline and queue is the whole task, and it should not require reaching
for the mouse. `/` follows the convention users already expect from search
fields. `Ctrl+Enter` works while focused in the textarea, which is the only
place a long report is typed.

**Why (the svg rule).** An inline `<svg>` with no `width`/`height` renders as a
300×150 replaced element. Every icon in this UI is injected from JS strings, so
one forgotten size attribute would blow out a layout. The 1em base makes the
failure mode "slightly wrong size" instead of "breaks the page", and component
rules (`.nav button svg`, `.empty svg`, …) are all higher specificity, so they
still win.

**Where.** `frontend/app.js` (keydown handler in `init()`),
`frontend/styles.css` (`svg` rule in Primitives).

---

### D-35 — All backend values are escaped at every interpolation point

**Decision.** The existing `esc()` helper is used for every value that originates
from a request — patient name, report text, case label, hospital, doctor,
rejection reasons, trace reasoning and structured output.

**Why.** Patient names and pasted report text are attacker-controllable: anyone
can `POST /patients` with a name of `<img src=x onerror=...>`, and the pipeline
view renders it. `esc()` predates this rewrite and was retained deliberately.
The transfer/medicine-name resolver added in this session
(`medName()`) escapes its return value at the call site for the same reason.

**Verified.** The render harness asserted that an XSS payload in `name` and
`case_label` produces no raw `<img>`/`<script>` in the markup.

**Where.** `frontend/app.js` `esc()`.

---

### D-36 — A render harness was used to verify the rewrite, then deleted

**Decision.** Rather than eyeballing the UI, the actual render functions were
executed in Node against live `TestClient` payloads, with a stubbed DOM.

**Why.** Template errors (`undefined`, `NaN`, a wrong property name) are silent
in a browser — the view just looks slightly wrong and you may not notice which
field was at fault. Executing `runCard()`, `renderDoctor()` and
`loadCommandCenter()` against 12 real runs (including the escalation branch),
4 hospitals, 4 alerts and 36 forecast rows surfaced a real bug: `learnMedNames`
was passed as a `forEach` callback and so received one object where it expected
an array, which broke the entire Command Center render. The harness lived in
temp, not the repo — it is a verification tool, not a deliverable.

**How to re-run it.** Recreate it from this entry; it needs no dependencies
beyond Node and a `TestClient` payload dump.

---

### D-37 — Two CSS bugs fixed opportunistically

**Decision.** Fixed `th { color: var(-s-muted) }` (missing colon — an invalid
custom property, so table headers silently inherited body colour instead of the
muted tone) and added the global `svg` sizing rule (D-34).

**Why.** Both were found while rewriting the file and both were one-character
or one-line fixes inside code being rewritten anyway. Left in place, the first
would have looked like an intentional style choice in new code.

---

### D-38 — No change to `eval/`, `tests/`, or any backend file

**Decision.** The UI rewrite touched only `frontend/index.html`,
`frontend/styles.css`, `frontend/app.js`.

**Why.** The rewrite is presentation. No API changed shape, no agent logic was
needed, and the 26 tests passed before and after unchanged — which is the
evidence that the rewrite was genuinely presentation-only. Changing backend
behaviour to suit a UI would have invalidated that signal.

---

## Part 3 — Open questions, deliberately undecided

These are not oversights. Each needs a decision that requires information or
authority this repo does not have.

- **Model accuracy is unmeasured.** No `GROQ_API_KEY` in this environment, so
  the harness has never been run. Any claim about triage accuracy is currently
  unsupported. (`README.md:125-126`)
- **Concurrent writes are unsafe.** `_next_id` and Agent 3's read-modify-write
  race under FastAPI's threadpool. Needs a lock or a real database.
- **No auth or audit trail.** Real PHI needs authentication, consent handling
  and an audit log on every approve/release. `POST /patients/{id}/approve` is
  currently open to any caller.
- **Escalation has no exit.** An escalated case is recorded and shown, but there
  is no endpoint to manually assign a facility, so an escalation can only be
  cleared by the network recovering on its own.
- **Agent 4 has no schedule.** `check_shortages()` is called on demand by
  `GET /command-center/alerts`. The docstring says "call it on a timer/cron in
  production"; no scheduler exists.
- **Reservations are never auto-expired.** A patient who is never approved
  holds their ICU bed for the life of the process. `outstanding()`
  (`agents/agent3_routing.py:144`) exists to support such a reaper, but nothing
  calls it.
- **RESOLVED — `.env.example` no longer holds a key-shaped string.** It
  previously carried a real-format `gsk_…` value; `.env` is gitignored but
  `.env.example` is not, so committing it would have published the key. The
  value is now the placeholder `gsk_REPLACE_ME_paste_your_own_key_here` and
  `.gitignore` pins it with `!.env.example`. Kept in the log rather than deleted
  so the failure mode stays visible.
- **`alerts[].message` is unused by the UI.** Agent 4 builds both a `message`
  field and a `reasons[]` array (`agents/agent4_forecast.py:145`); the UI
  renders `reasons[]` because it is structured. `message` is kept for API
  consumers. Not removed, since external consumers may rely on it.

---

## Queues (D-39 … D-51)

The queue layer added after D-38. Same convention: what was chosen, what was
rejected, and why.

### D-39 — The queue engine is deterministic code, not a model

The implementation plan calls this component the "AI QUEUE ENGINE". It is not
model-backed, and the plan's own §5 is the reason: the model must not decide
availability, capacity, or resource reservation. Priority ordering is exactly
that class of question — a comparison over facts the server already holds.

A model-backed priority would make queue order unstable between identical
requests, unexplainable to the patient waiting in it, and impossible to test.
So priority is arithmetic, and `priority_breakdown()` returns the working for
every row so the order can be argued with.

*Rejected:* an LLM that "suggests urgency". It re-opens exactly the trust
boundary D-01 closed, in the one place where an error is a patient waiting
longer than they should.

### D-40 — Severity dominates; waiting time only breaks ties

```
priority = SEVERITY_WEIGHT[severity] + min(waited_minutes / 12, 300)
```

Bands are Red 1000 / Yellow 500 / Green 100, capped wait bonus 300.

The two terms are additive rather than multiplicative so both stay legible in
the breakdown, and the wait term is capped so a mild case can never climb out
of its band. An uncapped wait term reintroduces under-triage as a scheduling
artifact: a Green case that has waited long enough outranks a Red one, and the
queue is then making clinical decisions by arithmetic.

*Rejected:* pure FIFO (the physical queue's behaviour, and the thing being
replaced) and pure severity (starves the routine cases until the clinic empties).

### D-41 — The wait cap must be strictly below the narrowest band gap

`MAX_WAIT_BONUS` (300) < min band gap (400, Green→Yellow).

The first attempt set the cap to 400, exactly the Green→Yellow gap, which meant
a long-waiting Green case *tied* a freshly arrived Yellow case. Ties are broken
by arrival time — i.e. by the FIFO ordering the queue exists to remove. The cap
was decorative. 300 leaves real headroom under both gaps.

`test_severity_never_beats_waiting_time_in_the_queue` drives the real scoring
function with extreme waits rather than comparing constants, because the
constant-based version passed even after the cap was deleted from the code.

### D-42 — A report never holds a bed

Routing assigns a **review slot**, not resources. ICU beds and medicine stock
are committed by `agent3_routing.commit()`, called only from the
`visit_required` decision path.

This is the load-bearing decision of the whole product. If assignment reserved
resources, a digital queue would tie up exactly the inventory a physical queue
ties up and would recover none of the capacity that motivated it. The report is
evidence for a decision; it is not a decision.

*Rejected:* reserving on assignment, which is what the pre-queue code did.

### D-43 — `escalate` moves the review assignment, and never releases resources

Reassignment targets a **senior** consultant of the case's own specialty,
nearest facility with a free senior first. Any already-committed ICU bed and
stock follow the case to the new facility.

Releasing on the way up would be backwards: an escalated case is more urgent,
not less, and dropping its held bed at the moment a consultant picks it up
would free a bed that is about to be needed.

Escalation updates the case's facility whenever the senior works somewhere
else, independently of whether resources were committed. Gating that on
`committed` was a real bug: the only senior haematologist is 158 km away at the
Medical College, so an uncommitted escalation left `hospital` pointing at the
original district hospital while `doctor` pointed across the state. The patient
portal then told a patient to travel somewhere nobody would review their case.

*Rejected:* releasing and re-allocating from scratch on escalation — simpler,
and wrong in exactly the direction that hurts.

### D-44 — Unroutable is `unassigned`, not `escalated`

The seed and submit paths previously recorded `"escalated" if not hospital`,
which both misused the word (escalation needs a doctor, and there is none) and
produced a status outside the queue's own open-status set — so those cases
silently vanished from the queue entirely.

`unassigned` is an *open* status. A case with no eligible facility is still a
patient waiting, and dropping them from the queue would be the single worst
outcome this product can produce. The doctor queue renders them in an
"Unassigned" panel with an explicit label.

### D-45 — Specialty eligibility comes from the doctor roster, not a boolean

Facilities previously carried `hematologist` / `cardiologist` / `pediatrician`
booleans, which could not express "has a cardiologist, but both are fully
booked". Agent 2 now filters on whether a doctor of the required specialty has
free capacity, and reports *why* a facility was rejected ("all haematology
doctor(s) at capacity") so a supervisor can tell "cannot treat this" apart from
"cannot take this right now".

### D-46 — Load balancing is a headroom threshold, not another weighted term

Agent 3's weighted score (0.45 proximity / 0.35 capacity / 0.20 availability)
does not balance load at all against this origin. The nearest facility won
every case, because the whole spread of the availability term across a
realistic roster (~0.09) is dwarfed by a proximity difference of ~0.45. One
haematologist absorbed all 8 haematology cases while three others sat idle.

Selection is now: nearest facility whose assigned doctor still has ≥25%
headroom, then least-loaded doctor there, then nearest-with-headroom as the
fallback. The weighted score is still computed and returned in the step's
`breakdown`, because it is a useful explanation even when it is not the
decider.

Scoring the facility and then the doctor was also wrong independently: it meant
a saturated doctor could never make their own facility less attractive, so
load could not spread at all.

*Rejected:* re-weighting until proximity loses. That trades a documented
threshold for an opaque coefficient.

### D-47 — A review assignment is workload, so it increments doctor load

`run()` increments the assigned doctor's `load` even though it reserves no
physical resource. Without this, every doctor's load stays flat, `headroom`
never shrinks, and D-46's policy silently degenerates to "always the nearest
hospital". `release()` decrements, `reassign()` transfers.

### D-48 — `approve` is an alias for `no_visit`, not a second release path

The pre-queue API had one `approve` button that released resources. That is
exactly `no_visit` under the new vocabulary. Mapping it onto the real decision
keeps one code path for closing a case; giving it its own semantics would
create two subtly different ways to release resources.

### D-49 — The patient portal is a separate view, not the patient record

`GET /patients/{id}` returns `queue.portal_view()`: position, wait, decision,
assigned doctor and facility. It omits stock levels, ICU counts, doctor
workload, other patients, red flags, and the internal `need` block.

A patient portal that leaks the facility's platelet count is a security
problem, not transparency.
`test_portal_hides_other_patients_and_internal_inventory` asserts the withheld
keys stay withheld.

### D-50 — Seeded demo cases are marked, and are records rather than pipeline runs

`SEED_CASES` is expanded to 24 across 8 case types so every queue has content
at boot. They are built from the rule-based Agent 1 path with synthetic arrival
times: no LLM calls, so boot cannot fail on a missing key or a network error.

Each record carries `seed: true` and renders with a *demo* chip. A reviewer must
never mistake seeded data for a processed report. Times are random from a fixed
seed so the demo is reproducible.

### D-51 — Waiting time has one injectable clock, and it is not wall-clock

`data_store.now()` / `set_clock()` / `advance_clock()` are the single source of
"now" for the queue. This is what lets the seeded backlog show realistic waiting
times without the process sleeping, and lets tests freeze time.

The known consequence is recorded in README's Known gaps: the displayed wait
only advances when the server does, so production must swap in a real clock
while keeping the injection point.

### Still open after the queue work

- **Decisions have no undo.** `visit_required` commits; only a later
  `release()` returns it. There is no "undo admission" endpoint, and a second
  decision on the same case is refused with 409 rather than applied. So a
  mis-click is *not* correctable through the API at all: recovering it today
  means editing the store out of band. That is a deliberate trade (see D-03 on
  not overwriting the first decision) and a real gap, not a workflow.
- **No audit log.** Every decision is recorded on the patient record, but
  nothing captures *who* decided. With no auth either, "Dr. Rao admitted this"
  is currently unattributable.
- **Reservations are never auto-expired.** An admitted patient who is never
  discharged holds their bed for the life of the process. `outstanding()`
  exists to support a reaper; nothing calls it.
- **The LLM path is unexercised here** (no `GROQ_API_KEY` in this
  environment). The three recommendation fields are schema-constrained and
  unit-tested, but no live model has been asked to produce them.

---

## The bugs found by running the thing

D-39–D-51 were design decisions taken before the queue was ever executed. The
five below were found afterwards, by driving a live server through the paths a
doctor actually clicks. All five share one shape: **the code looked correct and
the tests passed, and the system was still wrong.** That is the argument for
the mutation checks and the end-to-end pass in this section over reading the
diff.

### D-52 — Seeded cases never committed anything

**Decision.** `seed_patients()` now stores the `need` it already computes, and
`visit_required` refuses (409) when a record has no `need` at all.

**Why.** The seed builder computed `need` to route the case and then omitted it
from the record it appended. The decision path read `p.get("need") or {}`, so
`commit()` took nothing — and still returned `committed: true` and the endpoint
set `status = "admitted"`.

This was not an edge case. The 24 seeded cases *are* the app's default state,
so it was the main path: a Red dengue or cardiac case came back admitted while
the facility held no ICU bed and no aspirin. A green queue over an empty
inventory is worse than no queue, because it looks like the system is working.

The test suite passed throughout. Nothing asserted that committing a seeded case
moved anything — the existing tests covered the live submit path, where `need`
*was* stored, so the gap sat in the one path with no coverage.

**Where.** `data_store.seed_patients`, `main.decide_patient`,
`tests/test_pipeline.py::test_visit_required_on_a_seeded_case_actually_commits`.

**If changed.** Never let a commit path fall back to a default. `{}` is not a
safe default for "what does this patient need" — it is a silent admission with
no resources behind it.

### D-53 — Escalation could half-move a committed case

**Decision.** `reassign()` preflights the destination's ICU and stock *before
any* mutation, and returns `target_cannot_take_resources` if the transfer
cannot be completed.

**Why.** The original order was: swap the doctor, then `give_back()` at the
source, then `take()` at the target. If the target was short, `take()` raised
`ValueError` — after the resources had already been handed back. The ledger
still claimed the target held them; the source actually did. The patient's ICU
bed was in limbo, and the request died as a 500.

Worse in the variant where the preflight existed but ran after the doctor swap:
the case pointed at a senior consultant who was never told they had it.

An escalation is a handover. It either happens completely or not at all. The
preflight is now the first thing that happens.

**Where.** `agent3_routing.reassign`,
`tests/test_pipeline.py::test_escalation_refuses_rather_than_stranding_committed_resources`.

**If changed.** Keep the preflight ahead of every mutation, not just the
resource movement. Mutation-checked both ways: dropping it raises
`ValueError`, moving it later re-assigns the doctor. Both are caught.

### D-54 — A no-op escalation forged an audit trail

**Decision.** `reassign()` returns `moved`, and `escalated_from` is left `None`
when no handover occurred.

**Why.** Escalating a case already with a senior consultant of the right
specialty selects that same doctor. The status change is correct — the case
*is* with a senior. But `escalated_from` was filled in unconditionally, so the
record read `escalated from Dr. Menon at City General` and pointed at Dr. Menon
at City General. A referral that never happened, written down as though it did.

This is the cost of fields that default to a plausible value instead of to
nothing. `None` is the honest answer and the UI already handles it.

**Where.** `agent3_routing.reassign`, `main.decide_patient`,
`frontend/app.js` (`decidePatient` toast — which also read `r.escalated_from`
when the response nests it under `escalated_to.from`, so it always printed
"duty doctor → senior" regardless of what happened),
`tests/test_pipeline.py::test_escalating_to_the_doctor_who_is_already_senior_records_no_handover`.

### D-55 — `GET /patients` leaked the internal triage block

**Decision.** All patient responses go through one `_public()` projection that
strips `need`.

**Why.** `POST /patients` and `/decide` both withheld `need`; `GET /patients`
returned the raw records and leaked it. One endpoint out of three, on a field
that exists to carry triage's contract internally. Stripping in two places and
not the third is exactly how it reappears later.

**Where.** `main._public`, `main.list_patients`.

### D-56 — The unassigned queue row offered decisions that could not work

**Decision.** Unassigned cases and cases with no doctor render a status chip,
not the three decision buttons.

**Why.** `decisionButtons()` special-cased three statuses and fell through to
the buttons for everything else. `unassigned` fell through, so the UI offered
"no visit / visit / escalate" for a case with no doctor and no ledger entry.
Every one of those three buttons returns 409. The UI was advertising an action
it knew would fail, on the rows most likely to need a human to act.

**Where.** `frontend/app.js` `decisionButtons`.

---

## Verification note

The three new regression tests were each mutation-checked — reverted, confirmed
to fail, restored. A test that cannot fail is a comment:

| Mutation | Fails |
|---|---|
| Remove `need` from seeded records (D-52) | `test_visit_required_on_a_seeded_case_actually_commits` |
| Remove the escalation preflight (D-53) | `..._refuses_rather_than_stranding_committed_resources` (`ValueError`) |
| Move the preflight after the doctor swap (D-53) | same test (doctor reassigned) |
| Force `moved: True` (D-54) | `test_escalating_to_the_doctor_who_is_already_senior_records_no_handover` |

47 tests pass. The end-to-end pass that found D-52 through D-56 was a plain HTTP
script against a real uvicorn process — not the test client — because the bugs
were in the interaction between the seed, the store and the endpoints, and
`TestClient` shares the same process state the suite resets between tests.
