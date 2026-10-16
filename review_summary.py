"""Evidence-backed presentation built from Python checks, never model prose."""

from datetime import datetime, timezone
from decimal import Decimal

from checks import escalation_issues, grounded_final_explanation, material_case_issues, no_show_facts, route_deviation_facts
from contracts import DerivedFact, WorkflowResult
from evidence import build_review_input


RULING_LABELS = {
    "uphold_charge": "Retain the charge",
    "reverse_charge": "Refund the cancellation fee",
    "partial_refund": "Refund the excess-distance component",
    "no_action": "No action recommended",
}


FACT_LABELS = {
    "waited_minutes": "Recorded waiting interval",
    "fee_eligible": "Cancellation fee eligibility",
    "message_count": "Driver messages before cancellation",
    "call_count": "Driver call attempts before cancellation",
    "goodwill_credit_cents": "Separate goodwill credit component",
    "wait_start_time": "Waiting interval starts",
    "wait_end_time": "Waiting interval ends",
    "timely_presence": "Timely driver pickup presence",
    "arrival_verified": "Pickup arrival corroborated by GPS",
    "driver_no_show": "Driver no-show established",
    "goodwill_eligibility_resolved": "Goodwill eligibility resolved against conflicting presence records",
    "planned_distance_km": "Planned route distance",
    "actual_distance_km": "Actual route distance",
    "deviation_km": "Additional distance",
    "excess_distance_cents": "Excess-distance fare component",
    "justification": "Historical traffic justification",
    "rider_informed": "Timely rider notification",
    "rider_agreed": "Rider agreement",
}


def fact_label(fact: DerivedFact) -> str:
    return FACT_LABELS.get(fact.name, fact.name.replace("_", " ").capitalize() or fact.id)


def format_fact_value(value, unit: str) -> str:
    """Format a derived value for display without changing its meaning or raw value."""
    if isinstance(value, bool):
        return "Yes" if value else "Not established"
    if unit == "SGD cents":
        return f"SGD {value / 100:.2f}"
    if isinstance(value, (int, float)):
        return f"{value:g} {unit}" if unit in ("km", "minutes") else f"{value:g}"
    return value.capitalize() if unit == "state" else str(value)


def build_decision_summary(case: dict, policy: dict, result: WorkflowResult) -> dict:
    """Keep measured facts separate from the validated recommendation/referral."""
    case_id = case["dispute_ticket"]["dispute_id"]
    if result.case_id != case_id:
        raise ValueError("Review result belongs to a different case")
    review = build_review_input(case, policy)
    facts = {fact.name: fact for fact in review.facts}
    trip = case["trip_data"]
    timeline = []
    checklist = []
    calculations = []

    def row(condition, observation, status, names, policies):
        referenced = [facts[name] for name in names]
        checklist.append({"condition": condition, "observation": observation, "status": status,
                          "fact_ids": [fact.id for fact in referenced],
                          "evidence_ids": list(dict.fromkeys(ref for fact in referenced for ref in fact.evidence_ids)),
                          "policy_ids": policies})

    def at(timestamp, event, ids):
        if timestamp:
            timeline.append({"timestamp": timestamp, "event": event, "evidence_ids": ids})

    if review.dispute_type == "no_show_charge":
        measured = no_show_facts(case, policy)
        row("Five physical minutes at pickup after scheduled time",
            f"{measured['waited_minutes']:g} min: {measured['wait_start_time']} to {measured['wait_end_time']}",
            "unresolved" if not measured["arrival_verified"] else "met" if measured["waited_minutes"] >= 5 else "not met",
            ["waited_minutes", "wait_start_time", "wait_end_time"], ["POLICY-2.1"])
        row("Pickup presence corroborated", "GPS corroboration present" if measured["arrival_verified"] else "No corroborated arrival",
            "met" if measured["arrival_verified"] else "unresolved", ["arrival_verified"], ["POLICY-2.1"])
        row("Arrival by scheduled pickup + 5 minutes (inclusive)",
            "Timely pickup presence recorded" if measured["timely_presence"] else "No timely pickup presence recorded",
            "met" if measured["timely_presence"] else "not met" if measured["driver_no_show"] else "unresolved",
            ["timely_presence", "driver_no_show"], ["POLICY-2.4"])
        for name, label in (("message_count", "At least one driver message before cancellation"),
                            ("call_count", "At least one driver call attempt before cancellation")):
            complete = "chat_logs" in case and "app_events" in case
            row(label, f"{measured[name]} recorded", "met" if measured[name] else "not met" if complete else "unresolved",
                [name], ["POLICY-2.3"])
        calculations.append({"label": "Counted pickup wait" if measured["arrival_verified"] else "Recorded wait interval", "value": measured["waited_minutes"], "unit": "minutes",
                             "formula": f"{measured['wait_start_time']} → {measured['wait_end_time']} = {measured['waited_minutes']:g} min. {facts['waited_minutes'].formula}." +
                                        (" Pickup presence is not corroborated; this interval does not verify physical waiting." if not measured["arrival_verified"] else ""),
                             "evidence_ids": facts["waited_minutes"].evidence_ids, "policy_ids": ["POLICY-2.1"]})
        for field, label in (("scheduled_time", "Scheduled pickup"), ("driver_arrival_time", "Recorded driver arrival"),
                             ("cancellation_time", "Cancellation")):
            at(trip.get(field), label, [trip["id"]])
        at(measured["wait_start_time"], "Counted wait starts", facts["wait_start_time"].evidence_ids)
        at(measured["wait_end_time"], "Counted wait ends (cancellation or GPS departure)", facts["wait_end_time"].evidence_ids)
    else:
        measured = route_deviation_facts(case, policy)
        distance = next(item for item in case["fare_items"] if item["component"] == "distance_charge")
        routes = [measured["planned_route_id"], measured["actual_route_id"]]
        calculations.extend([
            {"label": "Additional distance", "value": measured["deviation_km"], "unit": "km",
             "formula": f"{measured['actual_distance_km']:g} km actual − {measured['planned_distance_km']:g} km planned = {measured['deviation_km']:g} km",
             "evidence_ids": routes, "policy_ids": ["POLICY-1.4"]},
            {"label": "Excess-distance fare component", "value": measured["excess_distance_cents"], "unit": "SGD cents",
             "formula": f"max(0, {measured['deviation_km']:g} km) × S${Decimal(str(distance['rate_per_km'])):f}/km = S${measured['excess_distance_cents'] / 100:.2f} (rounded half up to cents). The 1 km tolerance is not deducted.",
             "evidence_ids": routes + [distance["id"]], "policy_ids": ["POLICY-1.3", "POLICY-1.4"]},
        ])
        row("Additional distance within 2 km AI limit", f"{measured['deviation_km']:g} km (2 km inclusive)",
            "met" if measured["deviation_km"] <= 2 else "not met", ["deviation_km"], ["POLICY-6.2"])
        row("Additional distance within 1 km no-refund tolerance", f"{measured['deviation_km']:g} km",
            "met" if measured["deviation_km"] <= 1 else "not met", ["deviation_km"], ["POLICY-1.3"])
        row("Historical traffic justification", {"confirmed": "Confirmed", "unsupported": "Not supported by historical traffic", "unknown": "Missing or conflicting historical traffic"}[measured["justification"]],
            {"confirmed": "met", "unsupported": "not met", "unknown": "unresolved"}[measured["justification"]],
            ["justification"], ["POLICY-1.4"])
        for name, label in (("rider_informed", "Rider informed before or at deviation"),
                            ("rider_agreed", "Rider agreed before or at deviation")):
            row(label, "Recorded" if measured[name] else "Not established", "met" if measured[name] else "not met",
                [name], ["POLICY-1.2", "POLICY-1.4"])
        at(trip.get("start_time"), "Trip starts", [trip["id"]])
        at(trip.get("end_time"), "Trip ends", [trip["id"]])

    for record in case.get("chat_logs", []):
        at(record.get("timestamp"), f"{record['sender'].title()} · {record['type'].replace('_', ' ')}", [record["id"]])
    for record in case.get("app_events", []):
        if record["event_type"] in ("route_deviation_detected", "driver_called_rider", "safety_incident"):
            at(record.get("timestamp"), record["event_type"].replace("_", " ").capitalize(), [record["id"]])
    timeline.sort(key=lambda item: datetime.fromisoformat(item["timestamp"]))
    action = result.judge_result.proposed_action if result.status == "completed" and not result.failure_category else None
    verified_issues = material_case_issues(case, policy)
    if result.failure_category:
        reason = "No validated decision was issued because the review failed."
    elif action:
        reason = grounded_final_explanation(case, policy, result.judge_result)
    else:
        gates = escalation_issues(case, policy, result.judge_result.confidence)
        if not gates and result.mandatory_escalation:
            gates = escalation_issues(case, policy, result.judge_result.confidence, final=True)
        verified_issues = list(dict.fromkeys(gates + verified_issues))
        reason = ("A human reviewer must resolve the following checks:\n\n" +
                  "\n".join(f"- {issue}" for issue in verified_issues) if verified_issues else
                  "A human reviewer must assess the case before a final decision can be made.")
        reason += "\n\nNo final refund or goodwill-credit amount has been decided."
    party_messages = None
    if action:
        component = "cancellation fee" if review.dispute_type == "no_show_charge" else "excess-distance fare"
        party_messages = {}
        for role, owner in (("rider", "your"), ("driver", "the rider's")):
            if action.amount_cents:
                recommendation = f"Recommended refund: SGD {action.amount_cents / 100:.2f} of {owner} {component}."
            else:
                recommendation = f"Retain {owner} {component}; recommended rider refund: SGD 0.00."
            if action.goodwill_credit_cents:
                recommendation += f" Separate recommended goodwill credit to {owner} account: SGD {action.goodwill_credit_cents / 100:.2f}."
            party_messages[role] = {"action": recommendation, "explanation": reason}
    return {
        "case_id": case_id, "policy_version": policy["version"], "status": result.status,
        "outcome": RULING_LABELS.get(result.judge_result.ruling, "Human review required") if action else
                   "Review could not be completed" if result.failure_category else "Human review required",
        "refund_cents": action.amount_cents if action else None,
        "goodwill_credit_cents": action.goodwill_credit_cents if action else None,
        "mandatory_escalation": result.mandatory_escalation, "failure_category": result.failure_category,
        "reason": reason,
        "party_messages": party_messages,
        "review_issues": list(dict.fromkeys(result.validation_issues + verified_issues)),
        "checklist": checklist, "calculations": calculations, "timeline": timeline,
    }


def build_review_report(case: dict, policy: dict, result: WorkflowResult, mode: str) -> dict:
    """Export the same summary and source records seen by the reviewer; exclude profiles."""
    review = build_review_input(case, policy)
    return {"report_version": "1.0", "generated_at": datetime.now(timezone.utc).isoformat(), "mode": mode,
            "summary": build_decision_summary(case, policy, result),
            "facts": [fact.model_dump(mode="json") for fact in review.facts],
            "evidence": [record.model_dump(mode="json") for record in review.evidence],
            "policy": review.policy.model_dump(mode="json"),
            "workflow": result.model_dump(mode="json"),
            "explanation_validation": "Declared fact assertions are checked against Python facts. Free-text agent commentary is not semantically certified."}
