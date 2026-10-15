"""Shared JSON contracts. Version 2; serialize with model_dump(mode='json')."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Role = Literal["rider_advocate", "driver_advocate"]
Outcome = Literal["uphold_charge", "reverse_charge", "partial_refund", "no_action"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRecord(Contract):
    id: str = Field(min_length=1)
    source: str
    data: dict


class EvidenceRequest(Contract):
    trip_id: str = Field(min_length=1)
    sources: list[Literal["trip_data", "gps_telemetry", "chat_logs", "app_events",
                          "route_data", "fare_items", "traffic_data"]] = Field(min_length=1, max_length=7)
    purpose: str = Field(min_length=1, max_length=500)


class PolicyClause(Contract):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class Policy(Contract):
    policy_id: str
    version: str
    status: Literal["supplied_project_reference"]
    source_reference: str
    effective_date: str
    dispute_type: Literal["no_show_charge", "route_deviation"]
    fee_goes_to: str
    clauses: list[PolicyClause]
    # No-show specific (optional — present only for no_show_charge policies)
    wait_start_event: Literal["driver_arrival_time", "scheduled_time"] | None = None
    free_wait_time_min: int | None = Field(default=None, ge=0)
    no_show_threshold_min: int | None = Field(default=None, ge=0)
    cancellation_fee_after_wait: float | None = Field(default=None, ge=0)
    # Route deviation specific (optional — present only for route_deviation policies)
    tolerance_km: float | None = Field(default=None, ge=0)
    max_ai_deviation_km: float | None = Field(default=None, ge=0)
    refund_basis: str | None = None


# Preserve the import name used by the existing backend integration.
SamplePolicy = Policy


class DerivedFact(Contract):
    id: str
    value: int | float | bool | str
    name: str = ""
    unit: str
    formula: str
    evidence_ids: list[str]
    policy_ids: list[str]


class ReviewInput(Contract):
    contract_version: Literal["2.0"] = "2.0"
    case_id: str
    dispute_type: str
    evidence: list[EvidenceRecord]
    policy: SamplePolicy
    facts: list[DerivedFact]
    required_confidence: float = Field(default=0, ge=0, le=1)


class FactAssertion(Contract):
    """A checkable reference to a supplied Python fact, separate from raw citations."""

    fact_id: str
    value: int | float | bool | str


class Claim(Contract):
    statement: str = Field(min_length=1, max_length=1500, description="Convey the main point and decisive evidence concisely; no deliberation or repetition.")
    evidence_ids: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)
    fact_assertions: list[FactAssertion] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_source(self):
        if not self.evidence_ids and not self.policy_ids:
            raise ValueError("A claim needs an evidence or policy citation")
        return self


class AdvocateResult(Contract):
    role: Role
    claims: list[Claim]
    counterpoints: list[Claim]
    unanswered_questions: list[str]


class ArgumentFinding(Contract):
    section: Literal["claims", "counterpoints"]
    index: int = Field(ge=0, strict=True)
    verdict: Literal["supported", "unsupported"]
    explanation: str = Field(min_length=1, max_length=1500)
    evidence_ids: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)


class ArgumentReview(Contract):
    findings: list[ArgumentFinding]


class ProposedAction(Contract):
    """A recommendation only; amounts must be calculated by Python."""

    amount_cents: int = Field(ge=0, strict=True)
    currency: Literal["SGD"] = "SGD"
    refund_basis: Literal["cancellation_fee", "excess_distance_fare"] | None = None
    goodwill_credit_cents: int = Field(default=0, ge=0, strict=True)


class JudgeResult(Contract):
    action: Literal["request_rebuttal", "final_ruling", "human_review"]
    question: str | None = None
    rebuttal_roles: list[Role] = Field(default_factory=list)
    ruling: Outcome | None = None
    proposed_action: ProposedAction | None = None
    explanation: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    fact_assertions: list[FactAssertion] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_null_lists(cls, data):
        """Models sometimes send null for list fields; normalize to []."""
        if isinstance(data, dict):
            data = data.copy()
            for key in ("rebuttal_roles", "evidence_ids", "policy_ids"):
                if data.get(key) is None:
                    data[key] = []
        return data

    @model_validator(mode="after")
    def check_action_fields(self):
        if self.action == "request_rebuttal":
            if not self.question or not self.question.strip() or not self.rebuttal_roles:
                raise ValueError("Rebuttal requires a question and target roles")
        elif self.question is not None or self.rebuttal_roles:
            raise ValueError("Only request_rebuttal may contain a question or target roles")
        if self.action == "final_ruling":
            if self.ruling is None or self.proposed_action is None:
                raise ValueError("Final ruling requires a ruling and proposed action")
            if self.confidence is None:
                raise ValueError("Final ruling requires confidence between 0 and 1")
            if self.ruling in ("uphold_charge", "no_action") and self.proposed_action.amount_cents:
                raise ValueError("Upheld charge or no action has zero refund cents")
        elif self.ruling is not None or self.proposed_action is not None:
            raise ValueError("Only final_ruling may contain a ruling or proposed action")
        return self


class ActivityEntry(Contract):
    actor: Literal["system", "rider_advocate", "driver_advocate", "judge"]
    event: str
    output: dict


class WorkflowResult(Contract):
    case_id: str
    status: Literal["completed", "human_review"]
    activity_log: list[ActivityEntry]
    judge_result: JudgeResult
    final_explanation: str | None = None
    validation_issues: list[str]
    failure_category: Literal["setup", "model", "validation"] | None = None
    mandatory_escalation: bool = False
    account_review_flags: list[str] = Field(default_factory=list)
