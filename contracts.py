"""Shared JSON contracts. Version 1; serialize with model_dump(mode='json')."""

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


class PolicyClause(Contract):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class SamplePolicy(Contract):
    policy_id: str
    version: str
    status: Literal["sample_only_not_ryde_policy"]
    wait_start_event: Literal["driver_arrival_time", "scheduled_time"]
    free_wait_time_min: int = Field(ge=0)
    no_show_threshold_min: int = Field(ge=0)
    cancellation_fee_after_wait: float = Field(ge=0)
    fee_goes_to: str
    clauses: list[PolicyClause]


class DerivedFact(Contract):
    id: str
    value: int | float | bool
    unit: str
    formula: str
    evidence_ids: list[str]
    policy_ids: list[str]


class ReviewInput(Contract):
    contract_version: Literal["1.0"] = "1.0"
    case_id: str
    dispute_type: str
    evidence: list[EvidenceRecord]
    policy: SamplePolicy
    facts: list[DerivedFact]


class Claim(Contract):
    statement: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)

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


class ProposedAction(Contract):
    """A recommendation only; amounts must be calculated by Python."""

    amount_cents: int = Field(ge=0, strict=True)
    currency: Literal["SGD"] = "SGD"


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
    validation_issues: list[str]
