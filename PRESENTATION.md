# PRESENTATION.md — deck source for **Agentic Tele-Triage Portal**

> This is not documentation. It is the **raw material for a slide deck / PDF**.
> Every section is one slide. Under each slide you get three things:
>
> - **ON SLIDE** — the few words that actually appear. Nothing else.
> - **SAY** — the spoken script. Read it once, then talk from the bullets.
> - **VISUAL** — what to put on the slide. Diagram specs are written so they can
>   be handed to whoever draws them.
>
> Target length: **18 slides / 12–15 minutes**, plus backup slides in §S.
>
> Every number in this file was verified by running the code, not copied from
> the existing docs. Where an existing doc disagrees, the verified value wins
> and the disagreement is listed in **§S5 · Doc drift you must not repeat**.

---

## S0 · How to use this file

| Section | Slides | Use for |
|---|---|---|
| §1–§3 | 1–5 | The opening: problem, stakes, answer |
| §4–§6 | 6–10 | The core: rule, architecture, flow |
| §7–§9 | 11–15 | The proof: decisions, queue, evidence |
| §10–§12 | 16–18 | The close: resilience, honesty, ask |
| §S1–§S6 | backup | Q&A defence, cheat sheet, glossary, drift |

**Two rules for the deck itself:**

1. **Never put a code block on a slide longer than 6 lines.** Convert to a
   diagram. The one exception is the queue formula, which earns its 3 lines.
2. **The word "LLM" appears on 4 slides, not 12.** The project's argument is
   about *where the model is allowed to act*, not about the model. Slides that
   brag about Gemini are the ones a judge will distrust.

---

# §1 — Title

**ON SLIDE**

```
AGENTIC TELE-TRIAGE PORTAL
Clinical triage and hospital routing for a rural
healthcare network — with a human in the loop.

Google AI · Gemini  |  FastAPI  |  Cloud Run
```

**SAY**
> This is a clinical triage and hospital-routing system for a rural healthcare
> network. A free-text patient report goes in. A severity, a recommended
> facility, an assigned reviewing doctor and a full audit trail come out.
>
> The thing I want to spend most of this talk on is not the model. It is
> *exactly where I let the model act, and where I refused to.*

**VISUAL**
Dark background. Title centred, no logo wall. Bottom-right: repo URL. Keep it
boring — the deck is long.

---

# §2 — The problem

**ON SLIDE**

| | |
|---|---|
| **Where** | Rural India: PHC → district hospital referral |
| **Input** | A photo of a photocopied lab report, read over the phone |
| **Scarcity** | ICU beds, platelets, one haematologist |
| **Process** | A paper register and a phone call |
| **Failure** | The register is full, the platelet is not, the call is lost |

**SAY**
> In a rural network, a patient is stabilised at a primary health centre and
> needs to move up. The referral arrives as a phone photo of a photocopied lab
> report. The receiving hospital has a finite number of ICU beds, a finite
> number of platelet units, and one or two specialists.
>
> The coordination mechanism is a paper register and a phone call. That gives us
> four failure modes, and I want to be concrete about them.
>
> One: **under-triage**. A patient who needs to be seen tonight is seen
> tomorrow because their line read "no shock, no bleeding" and the word
> "shock" was the only thing the reader keyed on.
>
> Two: **phantom capacity**. A case is accepted, the bed is spoken for, and the
> bed is not there. The register now lies to both hospitals.
>
> Three: **no audit**. Six hours later nobody can reconstruct who decided the
> patient was fine.
>
> Four: **silent degradation**. The AI dependency breaks at 2am and the process
> stops, so nobody gets triaged at all.

**VISUAL**
Left half: a 4-box flow — PHC → phone photo → district hospital register →
specialist. Draw a red "?" at each arrow. Right half: the four failure modes as
four short lines. Do not use stock photography of doctors; it reads as filler.

---

# §3 · S3 — Why the obvious answers don't work

**ON SLIDE**

| Tempting answer | Why it fails |
|---|---|
| "Let the LLM route the patient" | A hallucinated ICU bed is a patient-safety failure |
| "Auto-admit the Red cases" | A digital queue that hoards scarce stock buys nothing |
| "Sort by waiting time (FIFO)" | Routine cases starve; critical cases wait |
| "Sort by severity only" | Routine cases never get seen at all |
| "If the model fails, page someone" | 2am. Nobody is paged. The queue stops. |

**SAY**
> Before showing you the design, here are the five things I could have built in
> an afternoon, and why each one is wrong.
>
> Letting the model route the patient: no. If the model asserts a bed exists
> and it does not, that is a patient-safety failure, not a UI glitch. So the
> model never gets to assert inventory — not anywhere, not ever.
>
> Auto-admitting the Red cases: that sounds helpful and it is actively
> harmful. If every Red case immediately holds a bed, then a burst of Red
> cases reserves the entire ICU of a hospital that can only physically treat
> one of them. The digital queue would hoard the exact resource the paper
> queue hoards, and it would do it faster.
>
> Pure FIFO is the thing I am replacing. Pure severity starves the routine
> cases forever. I needed something between them, and I will show you what.
>
> And the last row is the one that took the most design work: what happens
> when the model is down at 2am. Not "the demo breaks" — what happens to
> patients.

**VISUAL**
Table, five rows, no graphics. This slide exists to make the audience
admit the naive solution is wrong *before* you show yours. Pause here.

---

# §4 — The answer, in one line

**ON SLIDE**

> ### The LLM proposes. Code disposes.

```
report text → Agent 1 → Agent 2 → Agent 3 → review slot  (no bed held)
              (Gemini)    (code)    (code)                    │
                                                        doctor decides
```

**SAY**
> Here is the whole design in one sentence: **the LLM proposes, code
> disposes.**
>
> There are four agents. Exactly one of them talks to a model, and it only
> ever reads a report. It never writes anything, never moves stock, never
> touches a bed. The other three are deterministic Python that verify whatever
> the first one proposed against real inventory.
>
> The doctor is not advisory. The doctor is the decision point. Everything
> before the doctor is advice; everything after the doctor is a transaction.

**VISUAL**
This is your **hero diagram**. Big, centred, and it should be the only thing on
the slide. Model the four boxes distinctly: Agent 1 outlined in a different
colour and tagged `Gemini`; Agents 2–4 in neutral grey tagged `deterministic`.
Tag the final box `review slot — no resource held`. If you only get one
diagram right, get this one right.

---

# §5 — Where the model is, and where it is not

**ON SLIDE**

| | Agent | Model? | Authority |
|---|---|---|---|
| 1 | Clinical triage | **Gemini** | *Proposes* severity + recommendation |
| 2 | Resource allocator | Code | *Verifies* ICU, roster, platelets, medicines |
| 3 | Routing & load balancing | Code | *Assigns* a review slot only |
| 4 | Stock forecasting | Code | *Warns* before a shortage |
| — | **The doctor** | Human | **Decides.** Commits resources. |

**SAY**
> I want to be precise about the split, because this is the entire thesis.
>
> Agent 1 reads the report and produces a structured triage object: severity,
> ICU need, platelet units, medicines, which specialist, and a confidence
> score. All of that is a *recommendation*. It is shown to the doctor as
> advice, and no code path acts on the recommendation fields.
>
> Agent 2 does arithmetic against live inventory and rejects facilities one at
> a time, recording *why* each one failed. Agent 3 picks the eligible facility
> and the doctor, using a weighted score. Both deterministic.
>
> Agent 4 forecasts stockouts from 30 days of consumption. Also deterministic.
>
> And then a human decides. The doctor's decision is the only thing in this
> system that changes physical state.

**VISUAL**
A matrix, five rows. Colour the entire Model column: one cell coloured, three
greyed. The point lands from the *emptiness* of the Model column, so make the
grey cells visibly empty. If you animate anything in this deck, animate this
reveal.

---

# §6 — Request lifecycle

**ON SLIDE**

```
POST /patients
  │
  ├─ 0  route input  ── report text? → LLM path : rule path
  ├─ 1  TRIAGE       ── Gemini, schema-constrained  → need{}
  │        └─ model dead / invalid / low confidence? → Yellow + manual_review
  ├─ 2  ELIGIBILITY  ── ICU? specialist on roster? platelets? all medicines?
  │        └─ each rejection recorded with its reason
  ├─ 3  ROUTING      ── 0.45·proximity + 0.35·capacity + 0.20·availability
  │        └─ assigns a REVIEW SLOT. reserves nothing physical.
  └─ 4  QUEUE        ── severity band + capped wait bonus
                        │
                        ▼   POST /patients/{id}/decide
              no_visit │ visit_required │ escalate
```

**SAY**
> This is one request end to end. Five steps, and I will spend the next three
> slides on the three that matter.
>
> Step zero is an input router: if there is report text we go to the model
> path, otherwise a rule-based path over the case profiles. Both paths return
> the *same ten-key structure*, so nothing downstream can tell which one ran.
> That is deliberate — it means the fallback is a real code path, not a stub.
>
> Step two, eligibility, is where the safety lives. A facility survives only
> if it has the ICU capacity, a qualified specialist actually on the roster
> right now, enough platelets, and every medicine in stock. And crucially it
> does not silently drop the failures — it records *why*, so the patient sees
> "no haematology cover" or "ICU full" rather than a blank.
>
> Step three, routing, scores the survivors on proximity, capacity and
> availability, and assigns a review slot. Note the last line: **it reserves
> nothing physical.** I will come back to that.

**VISUAL**
Vertical numbered flow, five steps. Colour-code step 1 as "the only model
call". Put the failure branch off step 1 in a different colour running
*forward* into the pipeline, not off the edge — the point is that the fallback
rejoins the flow, it does not dead-end it.

---

# §7 — Step 1 detail: two gates, not one

**ON SLIDE**

```
Gate 1   response_schema  generated from TriageResult (Pydantic)
              ↓
         constrained at the model — it *cannot* emit an unknown field
              ↓
Gate 2   TriageResult.model_validate_json(...)
              ↓
         validated by code — a second, independent gate
```

```
failure anywhere  →  return None  →  rule path  →  Yellow · manual_review
                                        never Green
```

**SAY**
> Two things here that I think matter more than the model choice.
>
> First: the response schema is *generated* from the Pydantic model, not
> hand-written twice. There is exactly one definition of what a triage result
> is, and the wire format is derived from it. When someone adds a field to
> `TriageResult`, the schema changes with them. You cannot drift.
>
> Second: two independent gates. The model is constrained at the source, and
> then the reply is re-validated by Pydantic. The second gate is code, not a
> prompt. A model that is asked nicely to behave is not a guarantee; a schema
> is.
>
> And the failure row. If the model is unavailable, times out, returns 5xx, or
> violates the schema, the call returns `None` and the request drops to the
> rule path. Notice the last two words: **never Green.** An unreadable report
> becomes Yellow with a manual-review flag. Auto-clearing a patient you could
> not read is the failure mode that actually hurts people. A low confidence
> score does not soften a Red either — it routes the case to a human.

**VISUAL**
Two stacked "gate" boxes in series, then a third box underneath for the
failure path, with an arrow labelled `rejoins pipeline` pointing back up. This
is the resilience story told visually, so make the rejoin arrow prominent.

---

# §8 — Step 3 detail: a report never holds a bed

**ON SLIDE**

| | Doctor slot | ICU / medicines | Patient travels |
|---|---|---|---|
| `no_visit` | released | **never held** | no |
| `visit_required` | held | **committed now** | yes |
| `escalate` | moves to senior consultant | follows the case | yes |

```
route  →  load += 1   ·   reservation ledger written
                     ·   stock UNCHANGED
decide →  commit()   →  check, then take
```

**SAY**
> This is the load-bearing decision in the whole system, and it is the one I
> would defend hardest in a review.
>
> When routing assigns a case to a doctor, it increments that doctor's load
> and writes a reservation record. It does **not** decrement an ICU bed and it
> does **not** decrement stock. Nothing physical moves.
>
> Stock is committed by `commit()`, and `commit()` only runs on the
> `visit_required` path — the moment a human chooses to admit. And it is
> *check-then-take*: it verifies every medicine and the bed before removing
> anything, so a partial failure commits nothing rather than half of
> something.
>
> Why does this matter? Because a digital queue that reserves on assignment
> ties up exactly the same scarce inventory a paper queue ties up, and it
> buys you nothing. With 24 cases in flight, eager reservation would exhaust
> the network's platelets while nineteen of those patients are still sitting
> in a waiting room being reviewed. **A queue must not hoard.**
>
> There is a matching asymmetry: `commit` and `release` are the only two
> functions that move resources, and they are not the same function. When
> they were asymmetric the demo deadlocked. There is a regression test
> specifically for it, because I broke it once.

**VISUAL**
The table is the slide. Under it, one line of state transitions. Do **not**
draw a bed icon being held — the point is that it is not.

---

# §9 — The queue

**ON SLIDE**

```
priority = SEVERITY_WEIGHT[severity] + min(waited_minutes / 12, 300)
```

```
Red 1000      Yellow 500      Green 100        wait bonus capped at 300

  Red    1000 ─────────────────────────────────────────────►  (1000+)
  Yellow  500 ────────────────────────►                     (500 .. 1300)
           400 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   narrowest band gap
  Green   100 ──────►                                       (100 .. 400)
             0     100  300 400      500                  1000
                       ^cap
```

> The cap (300) sits **below the narrowest band gap (400)**.
> No amount of waiting lets a mild case outrank a critical one.

**SAY**
> The product is the queue, not the triage. Reports are ranked by clinical
> severity first, waiting time second.
>
> Severity carries a band: Red 1000, Yellow 500, Green 100. Waiting adds a
> bonus that grows with time but is capped at 300.
>
> Here is the part worth pausing on. The narrowest gap between two bands is
> 400 — Green tops out at 400, Yellow starts at 500. The wait cap is 300. So
> a Green case that has waited an extremely long time still cannot reach a
> fresh Yellow, let alone a Red. If the wait term were uncapped, arithmetic
> would quietly do the under-triaging for you: a patient who is mildly unwell
> but has waited long enough would outrank a patient who is crashing right
> now. That is under-triage laundered through a scheduling formula, and it
> is the most plausible way to reintroduce the exact bug this project is
> supposed to be about.
>
> The formula is **additive, not multiplicative**, on purpose: the API returns
> the full arithmetic breakdown for every row, so the order can be argued
> with rather than merely trusted. And the invariant is tested through the
> real scoring function, not against the constants — asserting it against the
> constants does not notice when somebody deletes the cap.

**VISUAL**
The formula, large, monospace. Below it, one horizontal band chart showing the
three severity bands with the cap line drawn across them at 300 and the band
boundary at 400 marked. The visual claim is *"the cap never crosses the
boundary"* — the audience should see that in one glance, before you say it.

---

# §10 — Agent 4: the network runs out of things too

**ON SLIDE**

```
mean daily consumption  →  days of cover  →  alert
                                              ├─  ≥ 7 days   warning
                                              └─  ≤ 3 days   critical
                                              transfers respect a 3-day donor floor
```

**SAY**
> Triage is only half of a referral network. The other half is that the
> hospital you just routed to actually has the platelets.
>
> Agent 4 computes mean daily consumption per facility per medicine from 30
> days of history and converts that into days of cover. Under seven days
> raises a warning, under three is critical. It can also propose transfers
> between facilities — but a donor facility will not be drained below a
> three-day buffer, because the system that predicts a shortage must not
> *cause* one.
>
> All of it is arithmetic. It is deterministic, and the API returns the
> coverage matrix so the number is auditable rather than asserted.

**VISUAL**
Small multiples: five facility rows, nine medicine columns, cell shading by
days-of-cover. It looks like a heatmap and it is the most screenshot-worthy
thing in the project. Use it as a **demo** slide, not an architecture slide.

---

# §11 — Gemini, specifically

**ON SLIDE**

| | |
|---|---|
| **Where** | One call. `llm.py`. Agent 1 only. |
| **Model** | `gemini-3-flash-preview` |
| **Config** | `temperature=0` · thinking off · 1024-token cap · 30s timeout · 2 retries |
| **Output** | Schema-constrained JSON → re-validated by Pydantic |
| **Prompt** | A versioned file, `prompts/triage_system.md` — diffable without reading Python |
| **Key** | Secret Manager, bound at deploy. Never in the image, repo, or log. |
| **Trace** | Every call logged: latency · finish reason · tokens · retries · parse result |

**SAY**
> Concretely, on the Gemini integration.
>
> One call, in one module, in one agent. `temperature` is zero, thinking is
> disabled by default, the output is capped, the timeout is 30 seconds with
> two retries.
>
> The prompt is a file, not a string literal. `prompts/triage_system.md` is
> the prompt config — you can review the clinical instructions, diff a change
> to the triage criteria, and see what a prompt edit did to the eval, without
> reading a line of Python. That is the difference between a prompt and a
> magic string.
>
> The response schema is generated from the Pydantic contract, so it cannot
> drift from the code that consumes it.
>
> Every call is traced — latency, finish reason, token counts, retry number,
> whether the parse succeeded. `GET /agents/llm-trace` renders it. So the cost
> and the behaviour of the AI step are *visible*, not assumed. I would rather
> show a judge a trace than a benchmark I did not run.
>
> The key: Secret Manager, bound with `--set-secrets` at deploy, and excluded
> at three separate layers — gitignore, dockerignore, and the deploy command
> itself. A leaked key in a public repository is a real incident, so it is
> defended three times rather than once.

**VISUAL**
Two columns: left = request, right = response, with the traced fields listed
down the side. Monospace only for the config values. This slide is dense on
purpose — it is the one that answers "did you actually integrate it".

---

# §12 — Resilience: what happens at 2am

**ON SLIDE**

| Resilience property | How this build holds it |
|---|---|
| **Degrades, never fails** | Key missing · timeout · 5xx · schema violation · low confidence → all resolve to the *same* outcome: hold for a clinician, flagged `manual_review` |
| **Fails safe, not silent** | A Red is never softened by low confidence. An unreadable report → Yellow + flag, never Green. |
| **Absorbs a surge** | 24 cases already triaged and queued at boot. Ordering is severity-banded with a capped wait bonus. |
| **Degrades the scarce resource, not safety** | Beds and stock committed only at the moment a doctor admits — never on file arrival. |
| **Survives partial data** | Failed facilities are reported *with the reason* — "no haematology cover" — not silently dropped. |
| **Auditable** | Every model call traced. Every decision logged. |

**SAY**
> I picked the Resilience track, and this is the argument.
>
> The system has exactly one network dependency, and it is the model. So I
> asked a specific question: what is the *worst thing that can happen* when
> that dependency is broken? Not "the demo breaks" — what happens to a
> patient.
>
> The answer here is: five different model failures — missing key, timeout,
> 5xx, schema violation, low confidence — all collapse into one outcome. The
> case is held for a human and flagged. The process does not crash. Nothing is
> auto-cleared. A Red case is never softened just because confidence was low.
>
> And a dead API degrades the demonstration, not the patient.
>
> The last row is subtle and I like it: facilities that fail the physical
> check are not silently dropped from the network. They are reported with the
> specific missing thing. A staff member should be able to see *why* the
> network could not absorb a case — that is a staffing and procurement
> problem, and hiding it makes it invisible.

**VISUAL**
The table. Six rows, no icons, generous line height. This is the slide a
judge photographs, so make it readable at the back of the room. If you only
have time for one table in the whole deck, make it this one.

---

# §13 — Evidence

**ON SLIDE**

| Claim | Number | How it was obtained |
|---|---|---|
| Tests | **59 passing** | `pytest`, offline, no API key required |
| Endpoints | **16** | FastAPI, same process serves the console |
| Console views | **6** | intake · pipeline · doctor · portal · compare · command |
| Network | 5 hospitals · 14 doctors (6 senior) · 9 medicines | seeded, deterministic |
| Eval set | **78** synthetic reports | 24 templates × 2, 30 OCR-degraded, seeded |
| Deploy | 1 container → Cloud Run | non-root, `$PORT`, Secret Manager |

```
keyword/regex baseline, measured on the 78-report set

              Red  → Yellow  Green
        Red    28        4       0
  Yellow     8       16       2
   Green      4        8       8

clean 30/48 = 62.5%    OCR-degraded 22/30 = 73.3%    overall 52/78 = 66.7%
```

**SAY**
> I would rather show you measurements than adjectives, so here is what I can
> actually stand behind.
>
> Fifty-nine tests, and they need neither a network nor an API key, which is
> the point — the safety invariants are tested in CI, not by vibes. Sixteen
> endpoints, six console views, all served from one process on one URL.
>
> The interesting number is the last one. The confusion matrix is the
> **keyword and regex baseline** — what you would write before reaching for a
> model. Overall it is 66.7% accurate. Look at the shape of the errors rather
> than the total: twelve non-Red cases were escalated to Red. That is the
> failure mode of literal reading — it keys on the word "shock" inside "no
> shock, no bleeding". Four Red cases were let down, which is the direction
> that kills.
>
> I am showing you the baseline, not the model, and here is why: I have not
> run the model against this set in a way I would defend, so I am not going to
> quote a number for it. But a 66.7% literal-reading baseline that
> over-escalates on negations *is* the justification for the model existing.
> That blindness is a documented, tested property of the system, not an
> accident.
>
> One caveat stated plainly: 78 reports over 24 templates is a scaffold, not a
> validated benchmark. Treat it as a harness, not a scoreboard.

**VISUAL**
Left: the counts table. Right: the confusion matrix as a proper 3×3 heatmap
with row = truth, column = prediction, and the misclassification cells
highlighted. The two over-triage clusters in the Yellow→Red and Green→Red
cells should be the visually loud ones. Print the caption in the footer, not
in the body.

---

# §14 — Demo script

**ON SLIDE**

```
1  open the console            →  24 cases already queued
2  paste a messy report        →  watch Agent 1's trace
3  compare vs. a rule case     →  same shape, both paths
4  doctor view                 →  "no haematology cover" on a failure
5  click visit_required        →  watch stock actually move
6  click escalate              →  senior consultant, stock NOT released
7  command center              →  days-of-cover heatmap
8  /agents/llm-trace           →  latency, tokens, retries
```

**SAY**
> If I have a live terminal, this is the path. The console loads with
> twenty-four already-triaged cases, so the queues are never empty — which is
> also the surge-absorbing property from the resilience slide.
>
> The moment worth narrating is step four. I pick a case the network cannot
> absorb, and instead of the case disappearing, the doctor sees exactly which
> facility failed and why. Then step five: I commit a visit and watch the
> inventory numbers move. Then step six, escalate — and the stock is *not*
> released, because the case is still live. That contrast is the design.

**VISUAL**
Print this as a speaker-view script, not a slide. If the demo fails, skip
straight to §15 and do not apologise on stage.

**DEMO SAFETY**
- The key is optional. If it is missing the run still works on the rule path —
  say so out loud rather than debugging silently.
- The deployed console is hardcoded to `localhost:8000`; demo from a local
  server, not from Cloud Run.
- `cloudbuild.yaml` currently pins a model id that 404s for new keys. Deploys
  will land on the fallback path. Fix it before you present a live URL.

---

# §15 — What this is not

**ON SLIDE**

| Not done | Why it matters |
|---|---|
| **No auth** | `/patients/{id}/decide` is open to any caller. **First** change before real PHI. |
| **In-memory state, no locking** | Concurrent `POST /patients` can race the ID counter and the bed reservation. |
| **No database** | Deliberate. A demo that silently persists PHI to an unmanaged store is worse than one that forgets. |
| **Not deployed** | Image never built, service never run. **No live URL will be claimed.** |
| **Model accuracy unmeasured** | 78 synthetic reports is a harness, not a benchmark. |
| **Synthetic data** | A simulation. Not a medical device. Triage output is not for clinical use. |

**SAY**
> I want to close with what this is not, because a submission that hides its
> gaps is telling you something about the rest of it.
>
> There is no authentication. The decision endpoint is open to anybody who can
> reach it, so before this touched real patient data the first change would be
> authentication, per-doctor authorisation, and an append-only audit log. That
> is not a nice-to-have, and I am not going to let the demo look more finished
> than it is.
>
> State is in memory with no locking, so concurrent intake can race. A real
> deployment needs a managed datastore.
>
> The absence of a database is deliberate, and I will defend it: a queue is a
> clinical safety artefact, and a demo that quietly persists patient data to a
> store nobody manages is worse than one that forgets. The first thing to add
> is Firestore for the queue.
>
> The deployment path is written and reviewed but **has never been executed** —
> I had no GCP project available — so I am not going to show you a URL that
> does not resolve.
>
> Finally: this is a simulation on synthetic data. It is not a medical device
> and its triage output is not for clinical use.

**VISUAL**
Two columns, honest-red for the gaps. Do not soften this slide with a
"future work" ribbon. Judges trust a team that names its own failure modes.

---

# §16 — Roadmap

**ON SLIDE**

```
NOW         the demo, as built
  1  fix the deployed model id + the console's hardcoded API base
  2  authentication, per-doctor authorisation, append-only audit log

NEXT        concurrency and durability
  3  Firestore for the queue + Cloud Storage for report images
  4  a lock or a transaction on the reservation ledger
  5  a reaper for reservations that were never approved  (outstanding() exists, unused)
  6  a real wall-clock behind the existing clock injection point

LATER       clinical and operational depth
  7  an endpoint to assign a facility manually — escalation currently has no exit
  8  a scheduler for Agent 4; it is on-demand today
  9  a model-accuracy run on a labelled real referral set
```

**SAY**
> The first two items are defects, not features — a deployed model id that
> 404s, and a console that points at localhost. Then authentication, which is
> the gate for anything real.
>
> Next block is concurrency and durability. Note item five: I wrote
> `outstanding()` to find reservations that were never approved, and nothing
> calls it. An unapproved case holds a review slot for the life of the
> process. The function is there; the reaper is not.
>
> Last block: escalation currently has no exit. Once a case moves to a senior
> consultant, no endpoint lets a human assign it a facility — it can only
> clear if the network recovers on its own. That is a real product gap and I
> would rather name it than have a judge find it.

**VISUAL**
Three horizontal swim lanes, Now / Next / Later. Numbered items so the
roadmap can be read as commitments.

---

# §17 — Close

**ON SLIDE**

```
A model that is confident is not a model that is correct.
A model that is fast is not a model that is accountable.
The only thing that makes triage safe is deciding
        what you will let the model do —
and then refusing to let it do anything else.

                        The LLM proposes. Code disposes.
```

**SAY**
> The thing I would like to leave you with is not "we used Gemini". It is that
> a triage system is only safe if you can say precisely what the model is
> permitted to do, and then actually enforce it.
>
> I did that with one rule, and I enforced it structurally: one call, in one
> module, in one agent, whose entire authority is to read text and propose a
> structured opinion. Everything that moves a bed, a unit of platelets, or a
> patient is deterministic code. Everything that decides is a human.
>
> That rule is what makes the system degrade instead of fail at 2am, what
> makes 24 cases in flight not exhaust the network, and what makes every
> number on the screen arguable.
>
> Thank you. Happy to take questions.

**VISUAL**
Text only. Nothing else on this slide. Hold it for the full duration of the
silence after you say thank you.

---

# §S · Backup slides (Q&A defence)

## §S1 · Anticipated questions

**Q — "How do you know the LLM is actually better than the regex?"**
> I don't, and I said so on the evidence slide. What I can show is that the
> regex baseline over-escalates on negations — 12 non-Red cases called Red —
> and that a schema-constrained model cannot emit a field the pipeline does
> not understand. The harness exists to answer your version of that question
> with a key and 20 minutes. Running it and reporting the number honestly,
> whichever way it goes, is on the roadmap.

**Q — "Why not just use the model to route the patient? It's one API call."**
> Because it would have to assert that a bed exists. If it hallucinates one,
> a real patient is told to travel to a hospital that cannot take them, and
> the network's register now records a capacity claim nobody verified. A
> hallucinated ICU bed is a patient-safety failure. Every other agent is
> arithmetic precisely so that this failure mode has nowhere to occur.

**Q — "Your state is in memory. Doesn't that invalidate the whole thing?"**
> It invalidates it for concurrent production use, and I would not deploy it
> that way. The data model is already shaped for a database — the reservation
> ledger is the only thing preventing double allocation, and a dict cannot
> give you a uniqueness constraint. That is one migration. The *architecture*
> — trust boundary, decision point, reservation semantics — is unchanged by
> where the bytes live. But yes, it needs a lock or a transaction before
> concurrent use, and the tests currently reset state per-test rather than
> proving isolation.

**Q — "What if the doctor just clicks `visit_required` on everything?"**
> Then the queue is a worse version of a paper queue, and the admission data
> becomes the training signal for demand forecasting. That is a legitimate
> next step rather than a flaw: the decisions are recorded, so the network
> learns which referrals were actually warranted. I have not built that loop
> yet, and I would rather say that than imply it exists.

**Q — "Why 300? Why /12?"**
> The /12 is a tuning choice and I will not defend it as more than that. The
> 300 cap is different — it is a *safety* constant, and the requirement on it
> is structural: it must stay below the narrowest band gap of 400. That
> relationship is asserted through the real scoring function in the test
> suite, so deleting the cap fails CI rather than passing review.

**Q — "The eval set is synthetic. Isn't that circular?"**
> It is not circular — the labels come from the templates, whose values sit
> unambiguously on one side of published severity criteria, so ground truth
> follows from criteria rather than from the model's opinion. But it is
> synthetic, and 24 templates with OCR-degraded twins is a scaffold. Real
> referral data would need a labelled clinical set, which is on the roadmap
> and is not something I can manufacture.

**Q — "Is this a medical device?"**
> No. It is a simulation on synthetic data and the triage output is not for
> clinical use. The design is *engineered* to be safe — fail-closed, audited,
> human-decided — but engineering intent is not a regulatory claim and I am
> not making one.

---

## §S2 · Number cheat sheet

Print this. Every value verified by running the code.

| | Value |
|---|---|
| Tests | 59 passed, offline |
| Endpoints | 16 + static root |
| Console views | 6 — intake, pipeline, doctor, portal, compare, command |
| Hospitals / doctors / seniors | 5 / 14 / 6 |
| Medicines (NLEM 2022) | 9 |
| Case profiles | 9 |
| Seeded patients at boot | 24 — **7 Red, 9 Yellow, 8 Green** |
| Consumption history | 30 days × 5 facilities × 9 medicines, seed 1337 |
| Forecast matrix | 45 rows today (5 × 9) |
| Eval reports | 78 — **32 Red, 26 Yellow, 20 Green**; 48 clean, 30 OCR |
| Baseline accuracy | clean 62.5% · OCR 73.3% · overall **66.7%** |
| Baseline errors | **4 under-triages**, **12 over-triages** |
| Model | `gemini-3-flash-preview` (fallback `gemini-3.1-flash-lite`) |
| LLM config | temp 0, thinking off, 1024 tokens, 30s timeout, 2 retries |
| Severity bands | Red 1000 · Yellow 500 · Green 100 |
| Wait bonus | `min(waited/12, 300)` — cap below the 400 band gap |
| Routing weights | 0.45 proximity · 0.35 capacity · 0.20 availability |
| Confidence gate | below 0.5 → flagged for manual review |
| Trace buffer | last 50 calls |
| Stack | FastAPI · Pydantic v2 · google-genai · vanilla JS · no build step |

---

## §S3 · Glossary

| Term | Meaning |
|---|---|
| **PHC** | Primary Health Centre — the first point of contact |
| **ICU** | Intensive Care Unit |
| **NLEM** | National List of Essential Medicines — the 9-drug catalog |
| **Review slot** | A place in a doctor's queue. **Not** a bed |
| **Reserve vs commit** | Reserve = a slot. Commit = a physical bed and stock |
| **Manual review** | Held for a human. The universal fallback. Never Green |
| **Triage** | Classifying urgency — Red / Yellow / Green |
| **Escalate** | Move the case to a senior consultant, same specialty |

---

## §S4 · The four questions the deck must answer

If you are cut short, these are the four, in priority order.

1. **What problem does this solve?** — §2, §3
2. **Why is it safe to put a model in a clinical path?** — §4, §5, §7
3. **How do you know it works?** — §13
4. **What is broken about it?** — §15

Slides 6–12 are supporting evidence. They matter, but a deck that reaches
question 4 is already ahead of a deck that has not.

---

## §S5 · Doc drift — do not repeat these on stage

The existing `ARCHITECTURE.md`, `FLOW.md`, `README.md` and `SUBMISSION.md`
contain stale numbers. If you copy from them into the deck you will say
something false. Verified values:

| Stale claim | Where | Truth |
|---|---|---|
| "4 facilities" | FLOW, ARCHITECTURE | **5 hospitals** |
| "36 forecast rows" | FLOW | **45** (5 × 9) |
| "nine / fourteen routes" | ARCHITECTURE, FLOW | **16** routes + static root |
| "47 tests" | README, FLOW, ARCH, DECISIONS | **59** |
| "4 views" | ARCHITECTURE, DECISIONS | **6** views |
| `gemini-2.5-flash` as the model | prompts/README, SUBMISSION, **cloudbuild.yaml:9** | `gemini-3-flash-preview` |
| availability = `max(capacity-load)/10` | FLOW | `(capacity - load) / capacity` |
| baseline "0% on adversarial templates" | README | not reproducible; measured 66.7% overall with 12 over-triages |
| module line counts | ARCHITECTURE inventory | all stale |
| "not yet pushed" | SUBMISSION | merged from upstream |

**Three live defects, in priority order — fix before you present:**

| Defect | Where | Effect |
|---|---|---|
| Deployed model id 404s for new keys | `cloudbuild.yaml:9` | every Cloud Run deploy lands on the fallback path |
| Console API base hardcoded | `frontend/config.js:2` | a deployed console calls the viewer's own machine |
| Root demo HTML eager-reserves beds and has an unescaped `innerHTML` interpolation | repo root `…Demo.html` | contradicts the central design; it is the first file a reader opens |

---

## §S6 · Timing

| Slides | Content | Budget |
|---|---|---|
| 1–3 | Title, problem, why the obvious answer fails | 2:30 |
| 4–5 | The rule, and where the model is not | 1:30 |
| 6–7 | Lifecycle, and the two gates | 2:00 |
| 8–9 | Reservations, and the queue invariant | 2:00 |
| 10–11 | Agent 4, Gemini integration | 1:30 |
| 12–13 | Resilience table, evidence | 2:00 |
| 14 | Demo | 2:00 |
| 15–17 | Gaps, roadmap, close | 1:30 |

**If you have 8 minutes instead of 13:** cut 10, cut 16, and compress 6 into
one line. Never cut 5, 8, 9, 13 or 15 — those five are the argument.
