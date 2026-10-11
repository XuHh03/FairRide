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


def validate_amounts(result: JudgeResult, policy: dict) -> list[str]:
    """Verify proposed_action.amount_cents matches the ruling type and charge.

    The charge amount is derived from policy["cancellation_fee_after_wait"].
    Returns a list of issue strings; empty means amounts are valid.
    """
    if result.action != "final_ruling" or result.ruling is None:
        return []

    charge_cents = int(Decimal(str(policy["cancellation_fee_after_wait"])) * 100)
    amount = result.proposed_action.amount_cents
    ruling = result.ruling
    issues = []

    if ruling in ("uphold_charge", "no_action"):
        if amount != 0:
            issues.append(
                f"{ruling} requires zero refund cents; got {amount}."
            )
    elif ruling == "reverse_charge":
        if amount != charge_cents:
            issues.append(
                f"reverse_charge requires {charge_cents} cents (full charge); got {amount}."
            )
    elif ruling == "partial_refund":
        if not (0 < amount < charge_cents):
            issues.append(
                f"partial_refund requires 0 < amount < {charge_cents}; got {amount}."
            )
    return issues
