import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def load_case(case_id: str) -> dict:
    return json.loads((ROOT / "cases" / f"{case_id}.json").read_text())


def load_policy(policy_id: str) -> dict:
    return json.loads((ROOT / "policies" / f"{policy_id}.json").read_text())


def policy_for_case(case: dict) -> dict:
    """Load the appropriate policy based on the case's dispute type."""
    dtype = case["dispute_ticket"]["dispute_type"]
    if dtype == "no_show_charge":
        return load_policy("sample_no_show")
    if dtype == "route_deviation":
        return load_policy("sample_route_deviation")
    raise ValueError(f"No policy configured for dispute type: {dtype}")
