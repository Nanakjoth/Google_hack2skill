# AI Medical Queue --- Prototype Implementation Plan

## 1. Current State

The current prototype already has a working FastAPI backend and
frontend.

Current flow:

``` text
Patient / Report
      ↓
Agent 1 — Triage logic
      ↓
Agent 2 — Resource verification
      ↓
Agent 3 — Hospital / Doctor routing
      ↓
Assignment
```

There is also an inventory/forecasting path.

The important point is:

> The current system has an agent architecture, but the main clinical
> decision path is not yet meaningfully AI-driven in the prototype
> unless the LLM path is configured and used.

The current architecture already separates the model proposal from
deterministic verification. Keep this design.

------------------------------------------------------------------------

# 2. Main Product Focus

## AI-Powered Government Medical Queue

The product should focus on converting the traditional repeated physical
queue into an intelligent digital queue.

### Current problem

``` text
Patient
  ↓
Physical queue
  ↓
Doctor
  ↓
Test
  ↓
Physical queue again
  ↓
Report
  ↓
Doctor
  ↓
Possible specialist
  ↓
Another queue
```

### Proposed flow

``` text
Patient
  ↓
Upload report
  ↓
AI understands report
  ↓
AI determines urgency + specialty + required action
  ↓
Intelligent queue
  ↓
Available government doctor
  ↓
Doctor review
  ↓
┌───────────────────────────────┐
│ No physical visit required    │
│ Consultation required         │
│ Specialist escalation         │
└───────────────────────────────┘
```

The goal is NOT to replace doctors.

The goal is to get the patient/report to the **right doctor at the right
time** while reducing unnecessary physical waiting.

------------------------------------------------------------------------

# 3. What Already Exists

Keep these components:

-   FastAPI backend
-   Frontend
-   Patient API
-   Hospital/facility data
-   Doctor data
-   Resource/inventory checks
-   Routing logic
-   Doctor workload
-   Agent pipeline
-   Audit/step trail
-   Forecasting/inventory functionality
-   Evaluation/testing framework

Do NOT rebuild the backend from scratch.

------------------------------------------------------------------------

# 4. The Biggest Missing Piece: Real AI

Currently, much of the useful behavior can work through deterministic
rules.

That is good for the infrastructure, but the prototype needs a visible
AI capability.

The AI should be responsible for understanding an unstructured medical
report.

## AI input

Example:

``` text
Patient: Demo Patient

Lab Report:
Hb: 8.2 g/dL
Heart rate: 110 bpm
BP: 150/95
...
```

The AI should interpret the report and produce a structured proposal.

## AI output

Example:

``` json
{
  "severity": "Yellow",
  "specialist": "cardiologist",
  "case_label": "Requires cardiac review",
  "physical_visit": false,
  "specialist_escalation": true,
  "red_flags": [
    "Elevated heart rate",
    "Abnormal blood pressure"
  ],
  "confidence": 0.87,
  "reasoning": "..."
}
```

IMPORTANT:

The AI output is a **proposal**, not the final truth.

------------------------------------------------------------------------

# 5. Recommended AI Architecture

Use this pattern:

``` text
                  ┌─────────────────┐
                  │ Patient Report  │
                  └────────┬────────┘
                           ↓
                  ┌─────────────────┐
                  │   AI Agent 1    │
                  │ Report Analysis │
                  └────────┬────────┘
                           ↓
                    Structured JSON
                           ↓
             ┌─────────────┴─────────────┐
             ↓                           ↓
      AI interpretation          Deterministic checks
                                      ↓
                            ┌────────────────────┐
                            │ Agent 2            │
                            │ Eligibility        │
                            └─────────┬──────────┘
                                      ↓
                            ┌────────────────────┐
                            │ Agent 3            │
                            │ Queue + Routing    │
                            └─────────┬──────────┘
                                      ↓
                                Doctor Queue
                                      ↓
                         Doctor decision / escalation
```

This is important because the AI should NOT directly decide:

-   Whether a hospital has a bed
-   Whether a doctor is actually available
-   Whether medicine is in stock
-   Which physical resource gets reserved

Those should remain deterministic checks.

------------------------------------------------------------------------

# 6. Where AI Should Be Added

## Agent 1 --- Make this genuinely AI-powered

Current responsibility:

> Convert report → clinical need

Upgrade it to:

> Convert unstructured report → structured triage proposal

The LLM should extract:

-   Severity
-   Case type
-   Specialist
-   Red flags
-   Required resources
-   Whether physical consultation may be required
-   Whether specialist review is recommended
-   Explanation
-   Confidence

Use structured output / JSON schema.

The existing `TriageResult` concept is a good foundation.

------------------------------------------------------------------------

# 7. AI Model Options

The prototype does NOT need to train a model.

Use an existing LLM API.

Possible architecture:

``` text
FastAPI
   ↓
LLM API
   ↓
Structured response
   ↓
Pydantic validation
   ↓
Deterministic agents
```

The exact provider/model can be changed through configuration.

The important part for the demo is that:

> The AI is actually receiving a report and producing a structured
> interpretation that changes the downstream queue decision.

Do not fake AI by putting a hardcoded response behind an "AI" button.

------------------------------------------------------------------------

# 8. AI Prompt

Create a dedicated system prompt for the triage agent.

The prompt should tell the model:

1.  You are analyzing a medical report for routing.
2.  Do not invent values.
3.  Extract only information supported by the report.
4.  Identify red flags.
5.  Determine the appropriate specialty.
6.  Determine urgency.
7.  Recommend whether the case needs doctor review.
8.  Recommend whether specialist escalation may be needed.
9.  Return only the required structured schema.
10. If the report is unclear, return a conservative/manual-review
    result.

The AI should NOT diagnose diseases.

Its purpose is **routing and prioritization**, not clinical diagnosis.

------------------------------------------------------------------------

# 9. Add a Real Queue Model

The central product should have three queues.

## Patient Queue

Shows:

``` text
Case ID
Severity
Specialty
Waiting time
Current status
Assigned doctor
```

Example:

``` text
#1042 | Yellow | Cardiology | 12 min | Dr. Rao
#1043 | Green  | General    |  4 min | Dr. Kumar
#1044 | Red    | Cardiology |  2 min | Escalated
```

## Doctor Queue

Each doctor sees only their assigned cases.

``` text
Dr. Rao — Cardiology

1. Patient #1044 — RED
2. Patient #1038 — YELLOW
3. Patient #1022 — YELLOW
```

## Specialist Queue

Escalated cases appear here.

``` text
Senior Cardiology Queue

#1044 — Escalated
Reason: AI identified red flags
Previous doctor: Dr. Rao
Report: Available
```

------------------------------------------------------------------------

# 10. Add Doctor Decision

After reviewing a case, the doctor should be able to select:

### Option A

``` text
No physical visit required
```

Patient receives the decision.

### Option B

``` text
Physical consultation required
```

Patient gets a visit/appointment requirement.

### Option C

``` text
Escalate to specialist
```

Case moves automatically into the specialist queue.

This is the feature that connects the AI queue to the real healthcare
workflow.

------------------------------------------------------------------------

# 11. Show WHY AI Made the Queue Decision

Do not hide the AI.

For every case show:

``` text
AI Assessment

Severity: Yellow
Specialty: Cardiology

Red Flags:
• Elevated heart rate
• Abnormal BP

Recommended Action:
Specialist review

Confidence:
87%
```

Then show deterministic verification:

``` text
Routing Verification

✓ Cardiology specialist available
✓ Facility has required resources
✓ Doctor capacity available
✓ Location considered

Assigned:
Dr. Rao
Government Hospital A
```

This clearly demonstrates:

> AI understands the case; the system verifies reality.

------------------------------------------------------------------------

# 12. Before vs After

Add a screen/section showing the existing process.

## Existing

``` text
Patient
 ↓
Queue
 ↓
Doctor
 ↓
Test
 ↓
Queue
 ↓
Report
 ↓
Doctor
 ↓
Specialist queue
```

## AI Medical Queue

``` text
Patient
 ↓
Digital report
 ↓
AI triage
 ↓
Right doctor
 ↓
Remote review
 ↓
Normal / Visit / Specialist
```

This should be one of the strongest pitch visuals.

------------------------------------------------------------------------

# 13. Demo Scenario

Use one realistic synthetic patient.

### Step 1

Patient uploads a report.

### Step 2

AI reads the report.

### Step 3

Show:

``` text
AI:
Yellow
Cardiology
2 red flags
Specialist review recommended
```

### Step 4

System checks government doctors.

``` text
7 possible doctors
3 eligible
1 selected
```

### Step 5

Show why others were rejected.

``` text
Hospital A
✓ Specialist
✓ Capacity

Hospital B
✗ No cardiologist

Hospital C
✗ Doctor capacity full
```

### Step 6

Patient enters doctor queue.

### Step 7

Doctor reviews.

### Step 8

Doctor clicks:

``` text
Escalate to Specialist
```

### Step 9

The case immediately appears in the senior specialist queue.

This should be the main demo.

------------------------------------------------------------------------

# 14. Use the Existing Inventory/Command Centre as Supporting Infrastructure

Do NOT remove the current inventory functionality.

Position it as:

> Government Healthcare Network Command Centre

It can show:

-   Hospital capacity
-   Doctor workload
-   Medicine availability
-   Resource shortages
-   Forecasts
-   Transfers

But it should NOT dominate the demo.

The product headline remains:

> AI Medical Queue.

------------------------------------------------------------------------

# 15. What the AI Should NOT Do

Do not claim:

-   AI diagnoses patients
-   AI replaces doctors
-   AI makes final medical decisions
-   AI guarantees medical safety
-   AI can determine the exact treatment

Instead:

> AI assists with report understanding, prioritization, routing and
> escalation. Final clinical decisions remain with qualified healthcare
> professionals.

------------------------------------------------------------------------

# 16. Prototype Data

For the hackathon/demo, synthetic data is acceptable.

Create:

-   20--50 patients
-   10--20 doctors
-   Multiple government facilities
-   Multiple specialties
-   Different doctor workloads
-   Different resource availability
-   10--20 sample reports

Create examples covering:

-   Green
-   Yellow
-   Red
-   No specialist available
-   Doctor fully occupied
-   Specialist escalation
-   Unclear report/manual review

The prototype should visibly behave differently for different reports.

------------------------------------------------------------------------

# 17. Reliability / Safety

Keep the existing principle:

``` text
AI proposes
      ↓
Schema validation
      ↓
Rules verify
      ↓
System routes
```

If AI fails:

``` text
AI unavailable
      ↓
Manual review
```

Never:

``` text
AI unavailable
      ↓
Automatically mark patient as safe
```

The current architecture already follows this conservative fallback
pattern and should retain it.

------------------------------------------------------------------------

# 18. Evaluation

Do not claim AI accuracy without measuring it.

Keep the existing evaluation framework.

Add test cases specifically for:

-   Correct specialty extraction
-   Severity classification
-   Red-flag extraction
-   OCR/noisy reports
-   Negation
-   Missing information
-   Unclear reports
-   Specialist escalation

Measure at least:

``` text
Correct routing
Wrong routing
Under-triage
Over-triage
Manual-review rate
```

For a healthcare prototype, under-triage should be tracked separately.

------------------------------------------------------------------------

# 19. UI Changes

Prioritize these screens:

## 1. Patient Portal

``` text
Upload Report
Case Status
Assigned Doctor
Decision
```

## 2. AI Pipeline

``` text
Report
 ↓
AI Analysis
 ↓
Eligibility
 ↓
Routing
 ↓
Assignment
```

## 3. Doctor Queue

``` text
Assigned Cases
Priority
Report
AI Summary
Decision
```

## 4. Specialist Queue

``` text
Escalated Cases
Reason
Previous Review
Report
```

## 5. Government Command Centre

Keep the existing inventory/forecasting dashboard here.

------------------------------------------------------------------------

# 20. Submission Demo

The ideal demo should be around 60--120 seconds.

### Opening

> "Today a patient may stand in multiple queues just to get one report
> reviewed. Our system turns that physical queue into an AI-assisted
> digital medical queue."

### Demo

``` text
Upload report
      ↓
AI reads report
      ↓
AI identifies specialty + urgency
      ↓
Government doctor availability checked
      ↓
Doctor assigned
      ↓
Doctor reviews
      ↓
Specialist escalation
```

### Closing

> "We are not replacing doctors. We are making sure the right report
> reaches the right doctor without making the patient repeatedly stand
> in line."

------------------------------------------------------------------------

# 21. Implementation Priority

## P0 --- Must Have

-   [ ] Connect Agent 1 to a real LLM API
-   [ ] Structured AI output
-   [ ] AI report analysis
-   [ ] AI severity/specialty/red-flag extraction
-   [ ] Patient digital queue
-   [ ] Doctor queue
-   [ ] Specialist escalation
-   [ ] Doctor decision
-   [ ] AI reasoning/trace visible
-   [ ] End-to-end demo scenario

## P1 --- Strongly Recommended

-   [ ] Better frontend
-   [ ] 20--50 synthetic patients
-   [ ] Multiple specialties
-   [ ] Queue priority
-   [ ] Waiting time
-   [ ] Doctor workload visualization
-   [ ] Manual-review fallback
-   [ ] AI evaluation results
-   [ ] Demo deployment

## P2 --- Supporting Features

-   [ ] Inventory forecasting
-   [ ] Medicine redistribution
-   [ ] Government command centre
-   [ ] Resource analytics
-   [ ] Historical analytics

## P3 --- Production Future

-   [ ] Authentication
-   [ ] Real database
-   [ ] Audit logging
-   [ ] Encryption
-   [ ] Consent management
-   [ ] Real hospital integration
-   [ ] Real government health-system integration
-   [ ] Production monitoring

------------------------------------------------------------------------

# 22. Final Architecture

``` text
                    PATIENT
                       │
                       ▼
                Upload Report
                       │
                       ▼
             ┌──────────────────┐
             │   AI TRIAGE      │
             │                  │
             │ • Understand     │
             │ • Extract        │
             │ • Prioritize     │
             │ • Recommend      │
             └────────┬─────────┘
                      │
                Structured JSON
                      │
                      ▼
             ┌──────────────────┐
             │ VALIDATION       │
             │ Pydantic/Rules   │
             └────────┬─────────┘
                      │
                      ▼
             ┌──────────────────┐
             │ RESOURCE CHECK   │
             │                  │
             │ Doctor           │
             │ Facility         │
             │ Capacity         │
             │ Resources        │
             └────────┬─────────┘
                      │
                      ▼
             ┌──────────────────┐
             │ AI QUEUE ENGINE  │
             │                  │
             │ Priority         │
             │ Specialty        │
             │ Availability     │
             │ Workload         │
             └────────┬─────────┘
                      │
              ┌───────┼────────┐
              ▼       ▼        ▼
           Doctor   Specialist  Visit
            Queue     Queue     Queue
              │       │
              └───────┴────────┘
                      │
                      ▼
             Doctor Final Decision
                      │
              ┌───────┼─────────┐
              ▼       ▼         ▼
            Close   Visit    Escalate
```

------------------------------------------------------------------------

# 23. Definition of Done

The prototype is ready when a judge can sit down and do this without
explanation:

1.  Upload a sample report.
2.  See the AI analyze it.
3.  See the AI produce structured triage information.
4.  See the system verify actual government resources.
5.  See the case enter the appropriate queue.
6.  See the doctor receive it.
7.  Click "Escalate".
8.  See the case appear in the specialist queue.
9.  Open the audit trail and understand why the system made the routing
    proposal.

If this works smoothly, **stop adding features**.

The goal is not to prove that you built a huge hospital-management
system.

The goal is to prove:

> **AI can turn an unstructured patient report into an explainable,
> verified, network-wide medical queue while keeping the final medical
> decision with a doctor.**
