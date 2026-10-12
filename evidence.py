"""Traceable agent input and citation checks, without model calls."""

from decimal import Decimal

from checks import no_show_facts, route_deviation_facts
from contracts import (
    AdvocateResult, DerivedFact, EvidenceRecord, JudgeResult, ReviewInput, SamplePolicy,
)


def build_evidence_index(case: dict) -> dict[str, EvidenceRecord]:
    index = {}
    for section in ("dispute_ticket", "trip_data", "gps_telemetry", "chat_logs",
                    "app_events", "route_data", "fare_items"):
        if section not in case:
            continue
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
    """Normalize the fixture; profiles are not agent evidence."""
    dtype = case["dispute_ticket"]["dispute_type"]
    evidence = build_evidence_index(case)
    build_policy_index(policy)

    if dtype == "no_show_charge":
        facts = no_show_facts(case, policy)
        trip_id = case["trip_data"]["id"]
        fee_cents = Decimal(str(policy["cancellation_fee_after_wait"])) * 100
        if fee_cents != fee_cents.to_integral_value():
            raise ValueError("Policy fee must have at most two decimal places")
        return ReviewInput(
            case_id=case["dispute_ticket"]["dispute_id"],
            dispute_type=dtype,
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

    if dtype == "route_deviation":
        facts = route_deviation_facts(case, policy)
        return ReviewInput(
            case_id=case["dispute_ticket"]["dispute_id"],
            dispute_type=dtype,
            evidence=list(evidence.values()), policy=SamplePolicy.model_validate(policy),
            facts=[
                DerivedFact(id="FACT-001", value=facts["planned_distance_km"], unit="km",
                            formula="planned route distance from route_data",
                            evidence_ids=[facts["planned_route_id"]], policy_ids=["POLICY-001"]),
                DerivedFact(id="FACT-002", value=facts["actual_distance_km"], unit="km",
                            formula="actual route distance from GPS reconstruction",
                            evidence_ids=[facts["actual_route_id"]], policy_ids=["POLICY-001"]),
                DerivedFact(id="FACT-003", value=round(facts["deviation_pct"], 1), unit="percent",
                            formula="(actual_distance - planned_distance) / planned_distance * 100",
                            evidence_ids=[facts["planned_route_id"], facts["actual_route_id"]],
                            policy_ids=["POLICY-001", "POLICY-002"]),
                DerivedFact(id="FACT-004", value=facts["deviation_significant"], unit="boolean",
                            formula=f"deviation_pct > max_deviation_pct ({policy.get('max_deviation_pct', 0)})",
                            evidence_ids=[facts["planned_route_id"], facts["actual_route_id"]],
                            policy_ids=["POLICY-002"]),
                DerivedFact(id="FACT-005", value=facts["fare_difference_cents"], unit="SGD cents",
                            formula="(charged_fare - estimated_fare) * 100",
                            evidence_ids=["TRIP-001", "FARE-005", "FARE-006"],
                            policy_ids=["POLICY-004"]),
            ],
        )

    raise ValueError(f"Unsupported dispute type: {dtype}")


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
