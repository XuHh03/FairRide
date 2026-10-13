from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from contracts import JudgeResult


def no_show_facts(case: dict, policy: dict) -> dict:
    trip = case["trip_data"]
    arrival = datetime.fromisoformat(trip["driver_arrival_time"])
    scheduled = datetime.fromisoformat(trip["scheduled_time"])
    cancelled = datetime.fromisoformat(trip["cancellation_time"])
    wait_start = datetime.fromisoformat(trip[policy["wait_start_event"]])
    waited_seconds = (cancelled - wait_start).total_seconds()

    return {
        "waited_minutes": waited_seconds / 60,
        "minutes_before_scheduled_pickup": (scheduled - arrival).total_seconds() / 60,
        "fee_eligible": waited_seconds >= policy["no_show_threshold_min"] * 60,
        "policy_fee": Decimal(str(policy["cancellation_fee_after_wait"])),
    }


def route_deviation_facts(case: dict, policy: dict) -> dict:
    """Calculate route deviation metrics from case data."""
    routes = case.get("route_data", [])
    planned = next((r for r in routes if r["type"] == "planned"), None)
    actual = next((r for r in routes if r["type"] == "actual"), None)
    if not planned or not actual:
        raise ValueError("Route deviation case needs planned and actual route records")

    planned_km = planned["distance_km"]
    actual_km = actual["distance_km"]
    if planned_km <= 0 or actual_km < 0:
        raise ValueError("Route distances must have a positive plan and nonnegative actual distance")
    deviation_pct = ((actual_km - planned_km) / planned_km) * 100

    trip = case["trip_data"]
    estimated_fare = Decimal(str(trip["estimated_fare"]))
    charged_fare = Decimal(str(trip["charged_fare"]))
    fare_difference = charged_fare - estimated_fare

    max_dev = policy.get("max_deviation_pct", 0)
    deviation_significant = deviation_pct > max_dev

    return {
        "planned_distance_km": planned_km,
        "actual_distance_km": actual_km,
        "deviation_pct": deviation_pct,
        "estimated_fare": estimated_fare,
        "charged_fare": charged_fare,
        "fare_difference": fare_difference,
        "fare_difference_cents": int(fare_difference * 100),
        "deviation_significant": deviation_significant,
        "planned_route_id": planned["id"],
        "actual_route_id": actual["id"],
    }


def charged_cents(case: dict) -> int:
    """Use the actual case charge, never a model-supplied amount."""
    trip = case["trip_data"]
    fee_field = "charged_fare" if "charged_fare" in trip else "cancellation_fee"
    cents = Decimal(str(trip[fee_field])) * 100
    if cents < 0 or cents != cents.to_integral_value():
        raise ValueError("Case charge must be nonnegative SGD cents")
    return int(cents)


def material_case_issues(case: dict, policy: dict) -> list[str]:
    """Conservative checks for supported dispute types."""
    dtype = case["dispute_ticket"]["dispute_type"]
    if dtype == "no_show_charge":
        return _no_show_material_issues(case, policy)
    if dtype == "route_deviation":
        return _route_deviation_material_issues(case, policy)
    return [f"No deterministic checks exist for {dtype}"]


def _no_show_material_issues(case: dict, policy: dict) -> list[str]:
    issues = []
    facts = no_show_facts(case, policy)
    wait_start = datetime.fromisoformat(case["trip_data"][policy["wait_start_event"]])
    threshold_seconds = policy["no_show_threshold_min"] * 60
    for event in case.get("app_events", []):
        details = event.get("details", "").lower()
        if "fee now applicable" in details or "cancellation fee now applicable" in details:
            elapsed = (datetime.fromisoformat(event["timestamp"]) - wait_start).total_seconds()
            if elapsed < threshold_seconds:
                issues.append(
                    f"{event['id']} claims fee eligibility before the sample policy's "
                    f"{policy['no_show_threshold_min']}-minute threshold"
                )
    ticket = case["dispute_ticket"]["description"].lower()
    pickup = case["trip_data"]["pickup_location"]
    if any(phrase in ticket for phrase in ("couldn't find", "never showed", "wrong entrance")):
        if not pickup.get("designated_entrance"):
            issues.append("The disputed physical pickup entrance is not designated in the supplied trip record")
    if facts["waited_minutes"] < 0:
        issues.append("Cancellation precedes the policy wait start")
    return issues


def route_justification(case: dict) -> str:
    """Read explicit, route- and time-matched alert snapshots, never keyword matches."""
    planned_id = next(r["id"] for r in case["route_data"] if r["type"] == "planned")
    start = datetime.fromisoformat(case["trip_data"]["start_time"])
    snapshots = {}
    for event in case.get("app_events", []):
        if event["event_type"] not in ("traffic_alert", "road_closure", "rider_route_change"):
            continue
        if event.get("affected_route_id") != planned_id:
            continue
        states = snapshots.setdefault(event["event_type"], set())
        if not event.get("valid_from") or not event.get("valid_until"):
            states.add("unknown")
            continue
        if datetime.fromisoformat(event["valid_from"]) <= start <= datetime.fromisoformat(event["valid_until"]):
            status = event.get("status", "unknown")
            states.add(status if status in ("active", "none") else "unknown")
    if any("unknown" in states or {"active", "none"} <= states for states in snapshots.values()):
        return "unresolved"
    return "confirmed" if any("active" in states for states in snapshots.values()) else "unsupported"


def _route_deviation_material_issues(case: dict, policy: dict) -> list[str]:
    issues = []
    routes = case.get("route_data", [])
    if not any(r["type"] == "planned" for r in routes):
        issues.append("No planned route record in the case data")
    if not any(r["type"] == "actual" for r in routes):
        issues.append("No actual route record in the case data")
    fare_items = case.get("fare_items", [])
    if not any(f.get("component") == "total_charged" for f in fare_items):
        issues.append("No total charged fare item in the case data")
    if not issues and route_justification(case) == "unresolved":
        issues.append("Route justification records conflict or their status is unknown")
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


def validate_final_ruling(case: dict, policy: dict, decision: JudgeResult) -> list[str]:
    if decision.action != "final_ruling":
        return []
    issues = material_case_issues(case, policy)
    if not decision.evidence_ids or not decision.policy_ids:
        issues.append("Final ruling needs decisive evidence and policy citations")
    if policy.get("status") != "sample_only_not_ryde_policy":
        issues.append("Unexpected policy status")

    dtype = case["dispute_ticket"]["dispute_type"]
    if dtype == "no_show_charge":
        issues.extend(_validate_no_show_ruling(case, policy, decision))
    elif dtype == "route_deviation":
        issues.extend(_validate_route_deviation_ruling(case, policy, decision))
    return issues


def _validate_no_show_ruling(case: dict, policy: dict, decision: JudgeResult) -> list[str]:
    issues = []
    charge = charged_cents(case)
    policy_charge = Decimal(str(policy["cancellation_fee_after_wait"])) * 100
    if policy_charge != charge:
        issues.append("Charged amount differs from the selected sample policy")
    refund = decision.proposed_action.amount_cents
    if decision.ruling == "reverse_charge" and refund != charge:
        issues.append("Full reversal must refund the actual charged amount")
    if decision.ruling == "partial_refund" and not 0 < refund < charge:
        issues.append("Partial refund must be positive and below the actual charge")
    if decision.ruling in ("uphold_charge", "no_action") and refund != 0:
        issues.append("Upheld charge or no action requires zero refund")
    if decision.ruling == "uphold_charge" and not no_show_facts(case, policy)["fee_eligible"]:
        issues.append("Cannot uphold charge before the no-show time threshold")
    if decision.ruling == "partial_refund" and not no_show_facts(case, policy)["fee_eligible"]:
        issues.append("Cannot partially refund when the no-show time threshold is not met; reverse the full charge")
    return issues


def _validate_route_deviation_ruling(case: dict, policy: dict, decision: JudgeResult) -> list[str]:
    issues = []
    facts = route_deviation_facts(case, policy)
    charge = charged_cents(case)
    refund = decision.proposed_action.amount_cents
    justified = route_justification(case) == "confirmed"

    if decision.ruling == "reverse_charge" and refund != charge:
        issues.append("Full reversal must refund the actual charged amount")
    if decision.ruling == "partial_refund":
        expected_refund = facts["fare_difference_cents"]
        if refund != expected_refund:
            issues.append(
                f"Partial refund must equal the fare difference ({expected_refund} cents), got {refund}"
            )
        if not 0 < refund < charge:
            issues.append("Partial refund must be positive and below the actual charge")
        if justified:
            issues.append("Cannot refund a deviation with a confirmed policy justification")
    if decision.ruling in ("uphold_charge", "no_action") and refund != 0:
        issues.append("Upheld charge or no action requires zero refund")
    if decision.ruling in ("uphold_charge", "no_action") and facts["deviation_significant"] and not justified:
        issues.append("Cannot retain charge when significant route deviation lacks policy justification")
    if decision.ruling == "partial_refund" and not facts["deviation_significant"]:
        issues.append("Cannot order a partial refund when the deviation is below the policy threshold")
    return issues
