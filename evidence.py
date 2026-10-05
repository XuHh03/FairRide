"""Traceable agent input and citation checks, without model calls."""

from decimal import Decimal

from checks import no_show_facts
from contracts import (
    AdvocateResult, DerivedFact, EvidenceRecord, JudgeResult, ReviewInput, SamplePolicy,
)


def build_evidence_index(case: dict) -> dict[str, EvidenceRecord]:
    index = {}
    for section in ("dispute_ticket", "trip_data", "gps_telemetry", "chat_logs", "app_events"):
        records = case[section] if isinstance(case[section], list) else [case[section]]
        for record in records:
            evidence_id = record.get("id")
            if not isinstance(evidence_id, str) or not evidence_id.strip():
                raise ValueError(f"Missing evidence ID in {section}")
            if evidence_id in index:
                raise ValueError(f"Duplicate evidence ID: {evidence_id}")
            index[evidence_id] = EvidenceRecord(
                id=evidence_id, source=section,
                data={key: value for key, value in record.items() if key != "id"},
            )
    return index


def build_policy_index(policy: dict) -> dict:
    parsed = SamplePolicy.model_validate(policy)
    index = {}
    for clause in parsed.clauses:
        if clause.id in index:
            raise ValueError(f"Duplicate policy ID: {clause.id}")
        index[clause.id] = clause
    return index


def build_review_input(case: dict, policy: dict) -> ReviewInput:
    """Normalize the current no-show fixture; profiles are not agent evidence."""
    if case["dispute_ticket"]["dispute_type"] != "no_show_charge":
        raise ValueError("Derived facts currently support no_show_charge only")
    evidence = build_evidence_index(case)
    build_policy_index(policy)
    facts = no_show_facts(case, policy)
    trip_id = case["trip_data"]["id"]
    fee_cents = Decimal(str(policy["cancellation_fee_after_wait"])) * 100
    if fee_cents != fee_cents.to_integral_value():
        raise ValueError("Policy fee must have at most two decimal places")
    return ReviewInput(
        case_id=case["dispute_ticket"]["dispute_id"],
        dispute_type=case["dispute_ticket"]["dispute_type"],
        evidence=list(evidence.values()), policy=SamplePolicy.model_validate(policy),
        facts=[
            DerivedFact(id="FACT-001", value=facts["waited_minutes"], unit="minutes",
                        formula=f"(trip_data.cancellation_time - trip_data.{policy['wait_start_event']}) / 60 seconds",
                        evidence_ids=[trip_id], policy_ids=["POLICY-001"]),
            DerivedFact(id="FACT-002", value=facts["fee_eligible"], unit="boolean",
                        formula="waited_minutes >= no_show_threshold_min (time condition only)",
                        evidence_ids=[trip_id], policy_ids=["POLICY-001", "POLICY-003"]),
            DerivedFact(id="FACT-003", value=int(fee_cents), unit="SGD cents",
                        formula="Decimal(cancellation_fee_after_wait) * 100",
                        evidence_ids=[], policy_ids=["POLICY-004"]),
        ],
    )


def validate_references(
    result: AdvocateResult | JudgeResult, case: dict, policy: dict,
) -> list[str]:
    """Check source existence, not whether a source supports a claim."""
    evidence = build_evidence_index(case)
    clauses = build_policy_index(policy)
    claims = result.claims + result.counterpoints if isinstance(result, AdvocateResult) else [result]
    issues = []
    for claim in claims:
        issues.extend(f"Unknown evidence ID: {ref}" for ref in claim.evidence_ids if ref not in evidence)
        issues.extend(f"Unknown policy ID: {ref}" for ref in claim.policy_ids if ref not in clauses)
    return issues
