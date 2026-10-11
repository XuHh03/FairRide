from datetime import datetime
from decimal import Decimal

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


def charged_cents(case: dict) -> int:
    """Use the actual case charge, never a model-supplied amount."""
    cents = Decimal(str(case["trip_data"]["cancellation_fee"])) * 100
    if cents < 0 or cents != cents.to_integral_value():
        raise ValueError("Case charge must be nonnegative SGD cents")
    return int(cents)


def material_case_issues(case: dict, policy: dict) -> list[str]:
    """Conservative checks for the currently supported no-show evidence."""
    if case["dispute_ticket"]["dispute_type"] != "no_show_charge":
        return ["No deterministic checks exist for this dispute type"]
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


def validate_final_ruling(case: dict, policy: dict, decision: JudgeResult) -> list[str]:
    if decision.action != "final_ruling":
        return []
    issues = material_case_issues(case, policy)
    if not decision.evidence_ids or not decision.policy_ids:
        issues.append("Final ruling needs decisive evidence and policy citations")
    if policy.get("status") != "sample_only_not_ryde_policy":
        issues.append("Unexpected policy status")
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
    return issues
