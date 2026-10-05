from datetime import datetime
from decimal import Decimal


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
