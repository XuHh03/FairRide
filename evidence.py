"""Traceable agent input and citation checks, without model calls."""

from decimal import Decimal
import re

from checks import no_show_facts, route_deviation_facts, required_confidence
from contracts import (
    AdvocateResult, Claim, DerivedFact, EvidenceRecord, JudgeResult, ReviewInput, SamplePolicy,
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
            ("goodwill_eligibility_resolved", "boolean", "False when reported timely arrival conflicts with relevant pickup-window GPS and the elapsed no-contact case leaves separate goodwill unresolved; computed credit is not a final entitlement in that case", ["POLICY-2.4"]),
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
    """Check sources, declared facts and known contradictions; not arbitrary prose."""
    evidence = build_evidence_index(case)
    clauses = build_policy_index(policy)
    review = build_review_input(case, policy)
    return citation_issues(result, evidence, clauses) + fact_assertion_issues(result, review) + prose_consistency_issues(result, review)


def prose_consistency_issues(result: AdvocateResult | JudgeResult | Claim, review: ReviewInput) -> list[str]:
    """Catch a small set of explicit contradictions; not general semantic validation."""
    facts = {fact.name: fact.value for fact in review.facts}
    texts = ([claim.statement for claim in result.claims + result.counterpoints] if isinstance(result, AdvocateResult)
             else [result.statement] if isinstance(result, Claim) else [result.explanation])
    issues = []
    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            if review.dispute_type == "no_show_charge" and facts.get("arrival_verified") is False:
                presence = re.search(
                    r"\bdriver\s+(?:was|is|remained)\s+(?:physically\s+)?present\s+at\s+(?:the\s+)?pickup(?:\s+location)?\b"
                    r"|\b(?:physical\s+arrival|pickup\s+presence)\s+(?:was|is)\s+(?:verified|confirmed|established)\b"
                    r"|\bGPS(?:\s+telemetry)?\s+(?:confirms?|verifies|establishes)\s+(?:the\s+)?(?:driver['’]s\s+)?(?:physical\s+)?presence\s+at\s+(?:the\s+)?pickup\b",
                    sentence, re.I)
                if presence:
                    prefix, suffix = sentence[:presence.start()], sentence[presence.end():]
                    qualified = (re.search(r"\b(?:if|whether|assuming|according to)\b", prefix, re.I)
                                 or re.search(r"\b(?:reports?|reported|claims?|claimed|alleges?|alleged|denies|denied|false|no (?:evidence|proof)|not (?:been )?(?:established|verified|confirmed|true)|cannot (?:verify|confirm|establish|conclude))\s+(?:that\s+)?(?:the\s+)?$", prefix, re.I)
                                 or re.search(r"^\s*(?:according to|(?:only\s+)?after\s+(?:the\s+)?cancellation|(?:is|was|remains)\s+(?:unverified|uncertain|unresolved|disputed|not (?:verified|established|confirmed)))\b", suffix, re.I))
                    if not qualified:
                        issues.append("Prose inconsistency: pickup presence is not verified; describe the reported arrival and evidence uncertainty instead of asserting established physical presence. False verification does not establish absence.")
            # Do not reject explicitly negated or hypothetical comparisons.
            if re.search(r"\b(not|never|cannot|if|unless|would|could|might)\b", sentence, re.I):
                continue
            if review.dispute_type == "no_show_charge" and facts.get("fee_eligible"):
                recipient = re.search(r"\brider\s+(?:(?:is|was|becomes)\s+)?(?:(?:eligible|entitled)\s+(?:for|to)|receives?|gets?)\s+(?:(?:the|a)\s+)?(?:compensation|cancellation fee|no.show fee)\b", sentence, re.I)
                if recipient and not re.search(r"\b(refund|goodwill)\b", sentence, re.I):
                    issues.append("Prose inconsistency: POLICY-2.2 pays a valid no-show fee to the driver as compensation, not the rider.")
            if review.dispute_type == "route_deviation" and facts.get("justification") == "unsupported":
                distance_patterns = (
                    r"\b(?:excess|refundable|billable) distance\s*(?:is|equals|=|:)\s*(\d+(?:\.\d+)?)\s*km\b",
                    r"\brefund\s+is\s+for\s+(?:(?:this|the|entire)\s+)*(\d+(?:\.\d+)?)\s*km\b",
                )
                for match in re.finditer("|".join(distance_patterns), sentence, re.I):
                    value = next(group for group in match.groups() if group is not None)
                    if Decimal(value) != Decimal(str(facts["deviation_km"])):
                        issues.append(f"Prose inconsistency: excess distance is {facts['deviation_km']:g} km, not {value} km; do not subtract the tolerance or include a discarded alternative calculation.")
    return list(dict.fromkeys(issues))


def fact_assertion_issues(result: AdvocateResult | JudgeResult | Claim, review: ReviewInput) -> list[str]:
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


def claim_correction_feedback(result: AdvocateResult, review: ReviewInput) -> list[dict]:
    """Locate detected fact/prose defects without claiming arbitrary semantic coverage."""
    feedback = []
    for section in ("claims", "counterpoints"):
        for index, claim in enumerate(getattr(result, section)):
            errors = fact_assertion_issues(claim, review) + prose_consistency_issues(claim, review)
            if not errors:
                continue
            referenced = {assertion.fact_id for assertion in claim.fact_assertions}
            names = ({"fee_eligible", "arrival_verified", "timely_presence", "goodwill_eligibility_resolved"}
                     if review.dispute_type == "no_show_charge" else {"deviation_km", "excess_distance_cents", "justification"})
            facts = [{"fact_id": fact.id, "name": fact.name, "value": fact.value}
                     for fact in review.facts if fact.id in referenced or fact.name in names]
            correction = ("Use the listed canonical values and revise this claim consistently. Preserve required assertions. "
                          "False verification does not establish physical presence or absence. When goodwill_eligibility_resolved is false, "
                          "describe the reported arrival and conflicting GPS as unresolved; do not settle goodwill or dismiss either account."
                          if review.dispute_type == "no_show_charge" else
                          "Use the listed canonical values and revise this claim consistently. Preserve required assertions. "
                          "Use the entire excess-distance fare component; do not deduct the tolerance or retain a discarded alternative calculation.")
            sentences = [sentence for sentence in re.split(r"(?<=[.!?])\s+|\n+", claim.statement)
                         if prose_consistency_issues(claim.model_copy(update={"statement": sentence}), review)]
            feedback.append({"section": section, "index": index, "statement": claim.statement,
                             "offending_sentences": sentences, "errors": errors, "facts": facts, "correction": correction})
    return feedback


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
