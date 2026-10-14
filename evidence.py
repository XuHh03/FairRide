"""Traceable agent input and citation checks, without model calls."""

from decimal import Decimal

from checks import no_show_facts, route_deviation_facts, required_confidence
from contracts import (
    AdvocateResult, DerivedFact, EvidenceRecord, JudgeResult, ReviewInput, SamplePolicy,
)


def build_evidence_index(case: dict) -> dict[str, EvidenceRecord]:
    index = {}
    for section in ("dispute_ticket", "trip_data", "gps_telemetry", "chat_logs",
                    "app_events", "route_data", "fare_items", "traffic_data"):
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
    dtype = case["dispute_ticket"]["dispute_type"]
    if policy["dispute_type"] != dtype:
        raise ValueError("Policy category does not match the case")
    evidence = build_evidence_index(case)
    build_policy_index(policy)
    trip_id = case["trip_data"]["id"]
    facts = []
    if dtype == "no_show_charge":
        calculated = no_show_facts(case, policy)
        definitions = [
            ("waited_minutes", "minutes", "cancellation_time minus max(scheduled_time, driver_arrival_time)", ["POLICY-2.1"]),
            ("fee_eligible", "boolean", "pickup presence AND five-minute wait AND message AND call AND timely arrival", ["POLICY-2.1", "POLICY-2.3", "POLICY-2.4"]),
            ("message_count", "count", "driver messages before cancellation", ["POLICY-2.3"]),
            ("call_count", "count", "unique driver call attempts before cancellation", ["POLICY-2.3"]),
            ("goodwill_credit_cents", "SGD cents", "500 if driver no-show and no contact; separate from refund", ["POLICY-2.4"]),
        ]
        refs = [record.id for record in evidence.values() if record.source in ("trip_data", "chat_logs", "app_events", "gps_telemetry")]
    elif dtype == "route_deviation":
        calculated = route_deviation_facts(case, policy)
        definitions = [
            ("planned_distance_km", "km", "planned road route distance", ["POLICY-1.4"]),
            ("actual_distance_km", "km", "supplied GPS-reconstructed route distance", ["POLICY-1.4"]),
            ("deviation_km", "km", "actual minus planned km", ["POLICY-1.3", "POLICY-1.4"]),
            ("excess_distance_cents", "SGD cents", "max(0, additional_km) * distance_rate *100, half-up rounded", ["POLICY-1.3"]),
            ("justification", "state", "route/time-matched historical traffic evidence", ["POLICY-1.4"]),
            ("rider_informed", "boolean", "driver route notice before or at deviation", ["POLICY-1.2"]),
            ("rider_agreed", "boolean", "rider acknowledgment of notice by deviation", ["POLICY-1.4"]),
        ]
        refs = [record.id for record in evidence.values() if record.source in ("trip_data", "route_data", "fare_items", "traffic_data", "chat_logs", "app_events")]
    else:
        raise ValueError(f"Unsupported dispute type: {dtype}")
    for number, (name, unit, formula, policy_ids) in enumerate(definitions, 1):
        source_ids = [trip_id] if name == "waited_minutes" else refs
        facts.append(DerivedFact(id=f"FACT-{number:03d}", name=name, value=calculated[name],
                                 unit=unit, formula=formula, evidence_ids=source_ids, policy_ids=policy_ids))
    return ReviewInput(case_id=case["dispute_ticket"]["dispute_id"], dispute_type=dtype,
                       evidence=list(evidence.values()), policy=SamplePolicy.model_validate(policy),
                       facts=facts, required_confidence=required_confidence(case))


def validate_references(
    result: AdvocateResult | JudgeResult, case: dict, policy: dict,
) -> list[str]:
    """Check source existence, not whether a source supports a claim."""
    evidence = build_evidence_index(case)
    clauses = build_policy_index(policy)
    return citation_issues(result, evidence, clauses)


def citation_issues(result: AdvocateResult | JudgeResult, evidence_ids, policy_ids) -> list[str]:
    """Validate the two citation namespaces against their supplied ID sets."""
    claims = result.claims + result.counterpoints if isinstance(result, AdvocateResult) else [result]
    issues = []
    for claim in claims:
        issues.extend(f"Unknown evidence ID: {ref}" for ref in claim.evidence_ids if ref not in evidence_ids)
        issues.extend(f"Unknown policy ID: {ref}" for ref in claim.policy_ids if ref not in policy_ids)
    return issues


def resolve_fact_citations(result: AdvocateResult | JudgeResult, review: ReviewInput):
    """Expand declared derived facts into their sources without rewriting arguments."""
    resolved = result.model_copy(deep=True)
    facts = {fact.id: fact for fact in review.facts}
    evidence_ids = {record.id for record in review.evidence}
    items = ([(f"claims.{i}", claim) for i, claim in enumerate(resolved.claims)]
             + [(f"counterpoints.{i}", claim) for i, claim in enumerate(resolved.counterpoints)]
             if isinstance(resolved, AdvocateResult) else [("judge", resolved)])
    resolutions = []
    for location, item in items:
        sources = []
        changed = False
        for ref in item.evidence_ids:
            fact = facts.get(ref)
            if fact and fact.evidence_ids and all(source in evidence_ids for source in fact.evidence_ids):
                sources.extend(fact.evidence_ids)
                resolutions.append({"location": location, "fact_id": ref, "evidence_ids": list(fact.evidence_ids)})
                changed = True
            else:
                sources.append(ref)
        if changed:
            item.evidence_ids = list(dict.fromkeys(sources))
    return resolved, resolutions
