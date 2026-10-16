"""Validate one raw case upload without saving files or calling a model."""

from datetime import datetime
import json
import math

from case_data import policy_for_case
from checks import account_review_flags, escalation_issues, material_case_issues, money_cents
from evidence import build_review_input


MAX_CASE_BYTES = 2 * 1024 * 1024
_OBJECTS = {"dispute_ticket", "trip_data", "rider_profile", "driver_profile"}
_ARRAYS = {"gps_telemetry", "chat_logs", "app_events", "route_data", "fare_items", "traffic_data"}
_TIMES = {"timestamp", "filed_at", "scheduled_time", "driver_arrival_time", "driver_wait_start",
          "cancellation_time", "start_time", "end_time", "valid_from", "valid_until"}
_NUMBERS = {"lat", "lng", "speed_kmh", "distance_km", "estimated_duration_min", "actual_duration_min",
            "duration_min", "rate_per_km", "rate_per_min", "amount", "cancellation_fee", "estimated_fare", "charged_fare"}
_MONEY = {"amount", "cancellation_fee", "estimated_fare", "charged_fare"}


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def parse_case_upload(content: bytes) -> dict:
    if not content or len(content) > MAX_CASE_BYTES:
        raise ValueError("Upload one nonempty case JSON file, up to 2 MB")
    try:
        case = json.loads(content, object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("The file must contain valid JSON with no duplicate fields") from exc
    if not isinstance(case, dict) or set(case) - (_OBJECTS | _ARRAYS):
        raise ValueError("Upload a raw case JSON only, not an answer key, review report or dataset bundle")
    if not {"dispute_ticket", "trip_data"} <= set(case):
        raise ValueError("The case needs dispute_ticket and trip_data objects")
    for section, value in case.items():
        if section in _OBJECTS and not isinstance(value, dict):
            raise ValueError(f"{section} must be a JSON object")
        if section in _ARRAYS and (not isinstance(value, list) or any(not isinstance(record, dict) for record in value)):
            raise ValueError(f"{section} must be an array of records")
    try:
        ticket, trip = case["dispute_ticket"], case["trip_data"]
        for key in ("id", "dispute_id", "trip_id", "dispute_type"):
            if not isinstance(ticket[key], str) or not ticket[key].strip():
                raise ValueError(f"dispute_ticket.{key} must be a nonempty string")
        if not isinstance(ticket["description"], str) or len(ticket["description"]) > 2000:
            raise ValueError("The complaint description must be text of at most 2000 characters")
        if ticket["trip_id"] != trip["trip_id"]:
            raise ValueError("Ticket and trip IDs must match")
        if ticket["dispute_type"] == "no_show_charge" and "cancellation_fee" not in trip:
            raise ValueError("No-show trip_data needs cancellation_fee")
        for section, fields in (("chat_logs", ("timestamp", "sender", "type", "content")),
                                ("app_events", ("timestamp", "event_type")),
                                ("gps_telemetry", ("timestamp",))):
            for record in case.get(section, []):
                if any(not isinstance(record.get(field), str) for field in fields):
                    raise ValueError(f"{section} records need text fields: {', '.join(fields)}")
        pending = [case]
        while pending:
            node = pending.pop()
            if isinstance(node, float) and not math.isfinite(node):
                raise ValueError("Numeric values must be finite")
            if isinstance(node, list):
                pending.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            for key, value in node.items():
                if key.startswith("expected_") or key in {"answer_key", "ground_truth", "evaluation_notes", "labels"}:
                    raise ValueError("Case inputs must not contain answer-key or evaluator fields")
                if key in _TIMES and value is not None:
                    if not isinstance(value, str) or datetime.fromisoformat(value).utcoffset() is None:
                        raise ValueError(f"{key} needs an ISO timestamp with a timezone")
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError("Numeric values must be finite")
                if key in _NUMBERS and (isinstance(value, bool) or not isinstance(value, (int, float))):
                    raise ValueError(f"{key} must be a number")
                if key in _MONEY:
                    money_cents(value)
                if key in {"disputed_amount_cents", "fraud_flags"} and (type(value) is not int or value < 0):
                    raise ValueError(f"{key} must be a nonnegative integer")
                if key in {"currency", "fare_currency"} and value != "SGD":
                    raise ValueError("Only SGD case records are supported")
                if isinstance(value, (dict, list)):
                    pending.append(value)
        policy = policy_for_case(case)
        review = build_review_input(case, policy)
        collisions = {record.id for record in review.evidence} & {fact.id for fact in review.facts}
        if collisions:
            raise ValueError(f"Evidence IDs conflict with derived facts: {', '.join(sorted(collisions))}")
        # Exercise the same input consumers used by the workflow. Legitimate
        # evidence conflicts remain referral issues, not import failures.
        material_case_issues(case, policy)
        escalation_issues(case, policy)
        account_review_flags(case)
    except (KeyError, TypeError, AttributeError, StopIteration, ArithmeticError, ValueError) as exc:
        raise ValueError(f"Invalid case records: {exc}") from exc
    return case
