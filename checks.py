"""Deterministic calculations and safeguards for the supplied v2.1 reference."""

import re
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from contracts import JudgeResult


def money_cents(value) -> int:
    amount = Decimal(str(value)) * 100
    if amount < 0 or amount != amount.to_integral_value():
        raise ValueError("Money must be nonnegative whole SGD cents")
    return int(amount)


def charged_cents(case: dict) -> int:
    trip = case["trip_data"]
    return money_cents(trip["charged_fare"] if "charged_fare" in trip else trip["cancellation_fee"])


def account_review_flags(case: dict) -> list[str]:
    """Section 2.5 flags verified no-show records, never generic dispute counts."""
    trip = case.get("trip_data", {})
    timestamp = trip.get("cancellation_time") or trip.get("end_time")
    if not timestamp:
        return []
    at = datetime.fromisoformat(timestamp)
    recent = {record["trip_id"] for record in case.get("rider_profile", {}).get("no_show_cancellations", [])
              if at - timedelta(days=30) <= datetime.fromisoformat(record["timestamp"]) <= at}
    return ["Section 2.5: at least three no-show cancellations in 30 days; refer rider account for review"] if len(recent) >= 3 else []


def no_show_facts(case: dict, policy: dict) -> dict:
    trip = case["trip_data"]
    scheduled = datetime.fromisoformat(trip["scheduled_time"])
    cancelled = datetime.fromisoformat(trip["cancellation_time"])
    arrival = datetime.fromisoformat(trip["driver_arrival_time"]) if trip.get("driver_arrival_time") else None
    pickup = trip["pickup_location"]
    gps = [(datetime.fromisoformat(r["timestamp"]), r.get("lat") == pickup["lat"] and r.get("lng") == pickup["lng"])
           for r in case.get("gps_telemetry", [])]
    pickup_times = [at for at, present in gps if present and at <= cancelled]
    if arrival is None and pickup_times:
        arrival = min(pickup_times)
    verified_start = min((at for at in pickup_times if arrival is not None and at >= arrival), default=None)
    if verified_start is not None:
        arrival = max(arrival, verified_start)
    wait_start = max(scheduled, arrival) if arrival else cancelled
    departure = min((at for at, present in gps if not present and arrival is not None
                     and arrival <= at <= cancelled and any(arrival <= seen < at for seen in pickup_times)), default=cancelled)
    waited = max(0, (departure - wait_start).total_seconds() / 60)
    messages, calls = [], set()
    for record in case.get("chat_logs", []):
        if record["sender"] != "driver" or datetime.fromisoformat(record["timestamp"]) >= cancelled:
            continue
        if record["type"] == "message":
            messages.append(record["id"])
        elif record["type"] == "call":
            calls.add(record["timestamp"])
    for record in case.get("app_events", []):
        if record["event_type"] == "driver_called_rider" and datetime.fromisoformat(record["timestamp"]) < cancelled:
            calls.add(record["timestamp"])
    timely_presence = any(at <= scheduled + timedelta(minutes=5) for at in pickup_times)
    driver_no_show = not timely_presence and (arrival > scheduled + timedelta(minutes=5) if arrival is not None
                      else trip.get("driver_no_show_confirmed") is True and not pickup_times)
    arrival_verified = arrival is not None and any(arrival <= at <= cancelled for at in pickup_times)
    return {
        "waited_minutes": waited,
        "scheduled_elapsed_minutes": (cancelled - scheduled).total_seconds() / 60,
        "minutes_before_scheduled_pickup": (scheduled - arrival).total_seconds() / 60 if arrival else 0,
        "arrival_verified": arrival_verified,
        "message_count": len(messages), "call_count": len(calls),
        "contact_obligations_met": bool(messages and calls),
        "driver_no_show": driver_no_show,
        "fee_eligible": arrival_verified and not driver_no_show and waited >= 5 and bool(messages and calls),
        "policy_fee": Decimal(str(policy["cancellation_fee_after_wait"])),
        "goodwill_credit_cents": 500 if driver_no_show and not messages and not calls else 0,
    }


def route_justification(case: dict) -> str:
    planned_id = next(r["id"] for r in case["route_data"] if r["type"] == "planned")
    at = next((e["timestamp"] for e in case.get("app_events", [])
               if e["event_type"] == "route_deviation_detected"), case["trip_data"]["start_time"])
    at = datetime.fromisoformat(at)
    states = set()
    for record in case.get("traffic_data", []):
        if record.get("source") not in ("historical_traffic_api", "historical_traffic_api_fixture"):
            continue
        if record.get("affected_route_id") != planned_id:
            continue
        if datetime.fromisoformat(record["valid_from"]) <= at <= datetime.fromisoformat(record["valid_until"]):
            states.add(record.get("status", "unknown"))
    if not states or not states <= {"congested", "no_congestion"} or len(states) > 1:
        return "unknown"
    return "confirmed" if states == {"congested"} else "unsupported"


def route_deviation_facts(case: dict, policy: dict) -> dict:
    routes = case.get("route_data", [])
    planned = next(r for r in routes if r["type"] == "planned")
    actual = next(r for r in routes if r["type"] == "actual")
    if planned["distance_km"] <= 0 or actual["distance_km"] < 0:
        raise ValueError("Invalid route distances")
    extra = Decimal(str(actual["distance_km"])) - Decimal(str(planned["distance_km"]))
    distance_item = next(item for item in case["fare_items"] if item["component"] == "distance_charge")
    excess = (max(extra, Decimal(0)) * Decimal(str(distance_item["rate_per_km"])) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    at = next((e["timestamp"] for e in case.get("app_events", []) if e["event_type"] == "route_deviation_detected"), case["trip_data"]["start_time"])
    notices = [r for r in case.get("chat_logs", []) if r["sender"] == "driver"
               and r["type"] in ("message", "recorded_call") and datetime.fromisoformat(r["timestamp"]) <= datetime.fromisoformat(at)
               and (r.get("route_change_notice") is True if "route_change_notice" in r
                    else re.search(r"\b(route|detour|rerout\w*|traffic|closure)\b", r.get("content", ""), re.I))]
    consent_records = [r for r in case.get("chat_logs", []) if r["sender"] == "rider"
                       and datetime.fromisoformat(r["timestamp"]) <= datetime.fromisoformat(at)
                       and any(datetime.fromisoformat(r["timestamp"]) >= datetime.fromisoformat(n["timestamp"]) for n in notices)
                       and ("route_change_acknowledged" in r or re.search(r"\b(agree|agreed|please follow|okay|ok|disagree|refuse)\b", r.get("content", ""), re.I))]
    latest_consent = max(consent_records, key=lambda r: datetime.fromisoformat(r["timestamp"]), default={})
    refused = re.search(r"\b(do not agree|don't agree|disagree|not okay|not ok|refuse)\b", latest_consent.get("content", ""), re.I)
    agreed = bool(latest_consent) and not refused and (latest_consent.get("route_change_acknowledged") is True
             if "route_change_acknowledged" in latest_consent else bool(re.search(r"\b(agree|agreed|please follow|okay|ok)\b", latest_consent.get("content", ""), re.I)))
    trip = case["trip_data"]
    difference = Decimal(str(trip["charged_fare"])) - Decimal(str(trip["estimated_fare"]))
    return {
        "planned_distance_km": planned["distance_km"], "actual_distance_km": actual["distance_km"],
        "deviation_km": float(extra), "deviation_pct": float(extra / Decimal(str(planned["distance_km"])) * 100),
        "deviation_significant": extra > Decimal("1"),
        "estimated_fare": Decimal(str(trip["estimated_fare"])), "charged_fare": Decimal(str(trip["charged_fare"])),
        "fare_difference": difference, "fare_difference_cents": int(difference * 100),
        "excess_distance_cents": int(excess), "justification": route_justification(case),
        "rider_informed": bool(notices), "rider_agreed": bool(agreed),
        "planned_route_id": planned["id"], "actual_route_id": actual["id"],
    }


def required_confidence(case: dict) -> float:
    flagged = any(case.get(name, {}).get("fraud_flags", 0) >= 1 for name in ("rider_profile", "driver_profile"))
    ticket = case["dispute_ticket"]
    value = ticket["disputed_amount_cents"] if "disputed_amount_cents" in ticket else charged_cents(case)
    return 0.95 if flagged else 0.8 if case["dispute_ticket"]["dispute_type"] == "route_deviation" or value >= 1000 else 0


def escalation_issues(case: dict, policy: dict, confidence: float | None = None, *, final=False) -> list[str]:
    ticket = case["dispute_ticket"]
    text = " ".join([ticket["description"]] + [r.get("content", "") for r in case.get("chat_logs", [])])
    issues = []
    if ticket.get("safety_flag") or re.search(r"\b(unsafe|reckless|dangerous driving|harass\w*|assault|threaten\w*|traffic accident|inappropriate\w*|verbal(?:ly)? abus\w*|physical(?:ly)? abus\w*)\b", text, re.I):
        issues.append("Section 5: safety indicator requires human review without an AI ruling")
        return issues
    dtype = ticket["dispute_type"]
    if dtype not in ("route_deviation", "no_show_charge"):
        return ["Section 6.2: this dispute category has no implemented ruling path"]
    value = ticket["disputed_amount_cents"] if "disputed_amount_cents" in ticket else charged_cents(case)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Disputed value must be nonnegative integer SGD cents")
    if value > 5000:
        issues.append("Section 6.1: dispute value above SGD 50 requires human review")
    dtype = ticket["dispute_type"]
    if dtype == "route_deviation":
        facts = route_deviation_facts(case, policy)
        if facts["deviation_km"] > 2:
            issues.append("Section 6.2: route deviation above 2 km requires human review")
        elif facts["deviation_significant"] and facts["justification"] == "confirmed" and not (facts["rider_informed"] and facts["rider_agreed"]):
            issues.append("Section 1.3: justified detour lacks agreed notification; refund disposition/formula requires human review")
    elif dtype != "no_show_charge":
        issues.append("Section 6.2: this dispute category has no implemented ruling path")
    threshold = required_confidence(case)
    if (final or confidence is not None) and threshold and (confidence is None or confidence < threshold):
        issues.append(f"Section 6: confidence must be at least {threshold:.0%}")
    return issues


def material_case_issues(case: dict, policy: dict) -> list[str]:
    if case["dispute_ticket"]["dispute_type"] == "no_show_charge":
        facts = no_show_facts(case, policy)
        issues = []
        if (case["trip_data"].get("driver_arrival_time") and not facts["arrival_verified"]
                and facts["contact_obligations_met"] and facts["waited_minutes"] >= 5):
            issues.append("Driver arrival is not corroborated at the recorded pickup coordinates")
        if "chat_logs" not in case or "app_events" not in case:
            issues.append("Contact evidence is missing rather than a verified empty log")
        if facts["fee_eligible"] and charged_cents(case) not in (0, 500):
            issues.append("Charged no-show fee differs from fixed SGD 5; refer amount correction")
        return issues
    if case["dispute_ticket"]["dispute_type"] == "route_deviation":
        return _route_deviation_material_issues(case, policy)
    return ["Unsupported dispute category requires human review"]


def _route_deviation_material_issues(case: dict, policy: dict) -> list[str]:
    issues = []
    routes = case.get("route_data", [])
    fare_items = case.get("fare_items", [])
    if route_justification(case) == "unknown" and route_deviation_facts(case, policy)["deviation_significant"]:
        issues.append("Historical traffic evidence is missing or conflicting")
    totals = {item["component"]: item for item in fare_items
              if item["component"] in ("total_charged", "estimated_total")}
    components = [item for item in fare_items if item["component"] not in totals]
    for component, field in (("total_charged", "charged_fare"), ("estimated_total", "estimated_fare")):
        if component not in totals:
            issues.append(f"Missing fare record: {component}")
            continue
        amount = Decimal(str(totals[component]["amount"]))
        if amount != Decimal(str(case["trip_data"][field])):
            issues.append(f"Fare record {component} disagrees with trip fare")
        amounts = (item["amount"] for item in components) if component == "total_charged" else totals[component].get("breakdown", {}).values()
        values = list(amounts)
        if values and sum(Decimal(str(value)) for value in values) != amount:
            issues.append(f"Fare components do not sum to {component}")
    for item in components:
        for quantity, rate in (("distance_km", "rate_per_km"), ("duration_min", "rate_per_min")):
            if quantity in item and rate in item:
                calculated = (Decimal(str(item[quantity])) * Decimal(str(item[rate]))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if calculated != Decimal(str(item["amount"])):
                    issues.append(f"Fare rate calculation disagrees with {item['id']}")
    planned = next((r for r in routes if r["type"] == "planned"), None)
    actual = next((r for r in routes if r["type"] == "actual"), None)
    if planned and actual:
        expected_estimate = {}
        for item in components:
            component = item["component"]
            if component in ("distance_charge", "time_charge"):
                quantity, rate, actual_field, planned_field = (
                    ("distance_km", "rate_per_km", "distance_km", "distance_km")
                    if component == "distance_charge" else
                    ("duration_min", "rate_per_min", "actual_duration_min", "estimated_duration_min"))
                if item.get(quantity) != actual.get(actual_field):
                    issues.append(f"Billed fare quantity disagrees with actual route: {item['id']}")
                if planned_field in planned and rate in item:
                    expected_estimate[component] = (Decimal(str(planned[planned_field])) * Decimal(str(item[rate]))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                expected_estimate[component] = Decimal(str(item["amount"]))
        breakdown = totals.get("estimated_total", {}).get("breakdown")
        if breakdown is not None and {key: Decimal(str(value)) for key, value in breakdown.items()} != expected_estimate:
            issues.append("Estimated fare breakdown disagrees with planned route and sample rates")
    return issues


def policy_outcome(case: dict, policy: dict) -> tuple[str, int, int, str]:
    """Policy-derived recommendation, never an evaluation answer label."""
    if case["dispute_ticket"]["dispute_type"] == "no_show_charge":
        facts = no_show_facts(case, policy)
        return ("uphold_charge", 0, 0, "cancellation_fee") if facts["fee_eligible"] else (
            "reverse_charge", charged_cents(case), facts["goodwill_credit_cents"], "cancellation_fee")
    facts = route_deviation_facts(case, policy)
    if not facts["deviation_significant"] or (facts["justification"] == "confirmed" and facts["rider_informed"] and facts["rider_agreed"]):
        return "uphold_charge", 0, 0, "excess_distance_fare"
    return "partial_refund", facts["excess_distance_cents"], 0, "excess_distance_fare"


def validate_final_ruling(case: dict, policy: dict, decision: JudgeResult) -> list[str]:
    if decision.action != "final_ruling":
        return []
    issues = material_case_issues(case, policy) + escalation_issues(case, policy, decision.confidence, final=True)
    if policy.get("version") != "2.1" or policy.get("status") != "supplied_project_reference":
        issues.append("The governing policy must be the supplied v2.1 reference")
    if not decision.evidence_ids or not decision.policy_ids:
        issues.append("Final ruling needs decisive evidence and policy citations")
    precedent = "POLICY-7.3" if case["dispute_ticket"]["dispute_type"] == "no_show_charge" else "POLICY-7.1"
    if precedent not in decision.policy_ids:
        issues.append("Section 7: cite the supplied relevant precedent and explain its similarity or distinction")
    expected, refund, credit, basis = policy_outcome(case, policy)
    # no_action is not a way to avoid a policy-mandated refund.
    if decision.ruling != expected:
        issues.append(f"Policy requires {expected}; {decision.ruling} cannot replace it")
    action = decision.proposed_action
    if action.amount_cents != refund or action.goodwill_credit_cents != credit:
        issues.append(f"Policy requires {refund} refund cents and {credit} separate goodwill-credit cents")
    if action.refund_basis != basis:
        issues.append(f"Refund basis must be {basis}")
    return issues


def validate_judge_decision(case: dict, policy: dict, decision: JudgeResult) -> list[str]:
    if decision.action == "final_ruling":
        return validate_final_ruling(case, policy, decision)
    if decision.action == "request_rebuttal":
        return ["Judge requested another rebuttal after its review budget ended"]
    material = material_case_issues(case, policy)
    if material or escalation_issues(case, policy, decision.confidence):
        return material
    return ["Human review is unsupported by the supplied policy checks and evidence. Issue the policy-supported decision, or report confidence below the required threshold with an evidence-based explanation. A distance exactly at the AI limit is permitted; do not invent thresholds or apply the justified-detour formula to an unjustified detour."]
