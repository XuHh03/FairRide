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
    facts = []
    if dtype == "no_show_charge":
        calculated = no_show_facts(case, policy)
        definitions = [
            ("waited_minutes", "minutes", "Elapsed minutes from max(scheduled_time, available recorded or GPS-corroborated arrival) to cancellation_time, capped at the first subsequent GPS departure; floor at zero", ["POLICY-2.1"]),
            ("fee_eligible", "boolean", "pickup presence AND five-minute wait AND message AND call AND timely arrival", ["POLICY-2.1", "POLICY-2.3", "POLICY-2.4"]),
            ("message_count", "count", "driver messages before cancellation", ["POLICY-2.3"]),
            ("call_count", "count", "unique driver call attempts before cancellation", ["POLICY-2.3"]),
            ("goodwill_credit_cents", "SGD cents", "500 if driver no-show and no contact; separate from refund", ["POLICY-2.4"]),
            ("wait_start_time", "ISO timestamp", "max(scheduled pickup, available recorded or GPS-corroborated arrival)", ["POLICY-2.1"]),
            ("wait_end_time", "ISO timestamp", "earlier of cancellation and first subsequent GPS departure", ["POLICY-2.1"]),
            ("timely_presence", "boolean", "pickup GPS presence by scheduled pickup plus five minutes, inclusive", ["POLICY-2.4"]),
            ("arrival_verified", "boolean", "arrival corroborated by pickup GPS before cancellation", ["POLICY-2.1"]),
            ("driver_no_show", "boolean", "verified driver no-show under the five-minute arrival condition", ["POLICY-2.4"]),
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
        source_ids = refs
        if dtype == "no_show_charge":
            if name in ("waited_minutes", "wait_start_time", "wait_end_time", "timely_presence", "arrival_verified", "driver_no_show"):
                sections = ("trip_data", "gps_telemetry")
            elif name in ("message_count", "call_count"):
                sections = ("trip_data", "chat_logs", "app_events")
            else:
                sections = ("trip_data", "gps_telemetry", "chat_logs", "app_events")
            source_ids = [record.id for record in evidence.values() if record.source in sections]
        elif name in ("planned_distance_km", "actual_distance_km", "deviation_km", "excess_distance_cents"):
            source_ids = [calculated["planned_route_id"], calculated["actual_route_id"]]
            if name == "excess_distance_cents":
                source_ids += [item["id"] for item in case["fare_items"] if item["component"] == "distance_charge"]
        elif name == "justification":
            source_ids = [record.id for record in evidence.values() if record.source in ("trip_data", "route_data", "traffic_data", "app_events")]
        elif name in ("rider_informed", "rider_agreed"):
            source_ids = [record.id for record in evidence.values() if record.source in ("trip_data", "chat_logs", "app_events")]
        facts.append(DerivedFact(id=f"FACT-{number:03d}", name=name, value=calculated[name],
                                 unit=unit, formula=formula, evidence_ids=source_ids, policy_ids=policy_ids))
    return ReviewInput(case_id=case["dispute_ticket"]["dispute_id"], dispute_type=dtype,
                       evidence=list(evidence.values()), policy=SamplePolicy.model_validate(policy),
                       facts=facts, required_confidence=required_confidence(case))


def validate_references(
    result: AdvocateResult | JudgeResult, case: dict, policy: dict,
) -> list[str]:
    """Check source existence and declared fact values, not arbitrary prose support."""
    evidence = build_evidence_index(case)
    clauses = build_policy_index(policy)
    return citation_issues(result, evidence, clauses) + fact_assertion_issues(result, build_review_input(case, policy))


def fact_assertion_issues(result: AdvocateResult | JudgeResult, review: ReviewInput) -> list[str]:
    """Check declared values only; this does not certify arbitrary natural-language prose."""
    facts = {fact.id: fact for fact in review.facts}
    items = result.claims + result.counterpoints if isinstance(result, AdvocateResult) else [result]
    issues = []
    for item in items:
        for assertion in item.fact_assertions:
            fact = facts.get(assertion.fact_id)
            if fact is None:
                issues.append(f"Unknown fact assertion: {assertion.fact_id}")
            elif (isinstance(assertion.value, bool) != isinstance(fact.value, bool)
                  or assertion.value != fact.value):
                issues.append(f"Fact assertion {fact.id} ({fact.name}) must equal {fact.value!r}; got {assertion.value!r}")
    return issues


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
