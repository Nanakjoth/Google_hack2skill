from pydantic import BaseModel, Field
from typing import Optional, List, Literal

Severity = Literal["Green", "Yellow", "Red"]

# The specialties a case can be routed to. `none` means "no specialty required",
# which the queue engine resolves to general medicine rather than dropping.
# This enum is the model's vocabulary, so it is a closed Literal: a closed set is
# what makes an invented specialty a schema violation instead of a routing bug
# (same reasoning as MedicineKey below). data_store asserts the specialist
# catalog matches this enum at import.
Specialist = Literal[
    "none",
    "general_medicine",
    "hematologist",
    "cardiologist",
    "pediatrician",
    "general_surgeon",
]

# The three actions a reviewing doctor can take. Deliberately a closed Literal:
# the decision is the handoff point of the whole product, so an unrecognised
# verb must be a 422 rather than a case that silently never closes.
DoctorDecisionKind = Literal[
    "no_visit",        # option A - report handled, patient does not travel
    "visit_required",  # option B - patient must be seen; resources committed
    "escalate",        # option C - hand to a senior specialist queue
]

# Kept in sync with medicines_catalog in data_store.py (asserted at import
# there). Constraining this to a Literal means the model *cannot* invent a
# drug name - a bare `dict` field would allow any key, and strict structured
# output rejects open-ended objects outright.
MedicineKey = Literal[
    "paracetamol",
    "oral_rehydration",
    "doxycycline",
    "ceftriaxone",
    "platelet_concentrate",
    "ringer_lactate",
    "insulin_glargine",
    "aspirin",
    "streptokinase",
]


class MedicineOrder(BaseModel):
    medicine: MedicineKey
    qty: int = Field(ge=0, le=100)


class PatientIn(BaseModel):
    name: str
    case_type: str  # dropdown shortcut; ignored when `report_text` is supplied
    report_text: Optional[str] = None  # real pasted lab report -> Agent 1 LLM path


class TriageResult(BaseModel):
    """Agent 1's output contract.

    This doubles as the JSON schema handed to the LLM for constrained
    decoding, so the model can only ever emit fields we validate. Never
    widen a field's type here without re-running the eval harness - the
    schema *is* the safety boundary between the model and the rest of the
    pipeline.

    Note what is NOT here: any claim about beds, stock, doctor availability
    or queue position. The model reads a report; it never asserts a fact
    about the network. Those are computed by Agents 2-4.
    """

    severity: Severity
    case_label: str = Field(description="Short clinical label, e.g. 'Dengue - severe (critical)'")
    icu_needed: int = Field(ge=0, le=10, description="ICU beds required right now")
    platelets_needed: int = Field(ge=0, le=50, description="Platelet concentrate units required")
    specialist: Specialist = Field(description="'none' if no specialty-specific review is needed")
    medicines: List[MedicineOrder] = Field(
        default_factory=list,
        description="Drugs required for this case, with quantities",
    )
    red_flags: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="2-3 sentences citing the specific abnormal values")

    # --- Queue recommendations -------------------------------------------------
    # These are the model's *advice* about what should happen next. They are
    # never acted on automatically: the queue engine derives priority from
    # severity, and a human doctor makes the final call on visit vs. escalation.
    # They exist so the doctor queue can show an AI recommendation next to the
    # case, which is the difference between "the AI decided" and "the AI advised".
    physical_visit_recommended: bool = Field(
        description=(
            "True if the report suggests the patient must be examined in person "
            "(e.g. needs monitoring, an exam, or a procedure). False if the report "
            "can plausibly be reviewed remotely. A recommendation only - the "
            "reviewing doctor decides."
        )
    )
    specialist_escalation_recommended: bool = Field(
        description=(
            "True if this looks beyond routine scope for a general duty doctor and "
            "warrants senior specialty review. A recommendation only."
        )
    )
    recommended_action: str = Field(
        description=(
            "One short phrase naming the suggested next step, e.g. 'Senior "
            "cardiologist review within 24h' or 'Remote review, ORS + review in 48h'."
        )
    )

    def medicine_map(self) -> dict:
        return {m.medicine: m.qty for m in self.medicines}


class AgentStep(BaseModel):
    title: str
    text: str


class RedistributeIn(BaseModel):
    donor_id: str
    receiver_id: str
    medicine: str = "platelet_concentrate"
    amount: int = 5


class DecisionIn(BaseModel):
    """A reviewing doctor's verdict on one case.

    This is the point where clinical authority is exercised, so it is a
    human input with no model involvement at all. The AI proposed; the
    doctor disposes.

    `note` is free text shown back in the patient-facing timeline. It is
    optional because a doctor closing a routine case should not be forced to
    type anything.
    """

    decision: DoctorDecisionKind
    note: Optional[str] = Field(default=None, max_length=600)
    # Only meaningful for decision="escalate": which specialty the senior
    # reviewer should come from. Defaults to the case's own specialist.
    escalate_to: Optional[Specialist] = None
