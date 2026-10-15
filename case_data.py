import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def load_case(case_id: str) -> dict:
    return json.loads((ROOT / "cases" / f"{case_id}.json").read_text())


def list_demo_trips() -> list[dict]:
    """Local simulated trip catalog; no profiles or expected outcomes."""
    trips = []
    for path in sorted((ROOT / "cases").glob("DISP-*.json")):
        ticket = json.loads(path.read_text())["dispute_ticket"]
        trips.append({"trip_id": ticket["trip_id"], "case_id": ticket["dispute_id"],
                      "dispute_type": ticket["dispute_type"]})
    return trips


def file_dispute(trip_id: str, complaint: str) -> dict:
    """Attach a complaint to a known demo trip in memory; never alter fixtures."""
    complaint = complaint.strip()
    if not complaint or len(complaint) > 2000:
        raise ValueError("Describe the dispute in 1 to 2000 characters")
    matches = [trip for trip in list_demo_trips() if trip["trip_id"] == trip_id]
    if len(matches) != 1:
        raise ValueError("Select a known demo trip")
    case = load_case(matches[0]["case_id"])
    case["dispute_ticket"]["description"] = complaint
    return case


def load_policy(policy_id: str) -> dict:
    return json.loads((ROOT / "policies" / f"{policy_id}.json").read_text())


def policy_for_case(case: dict) -> dict:
    """Load the appropriate policy based on the case's dispute type."""
    dtype = case["dispute_ticket"]["dispute_type"]
    if dtype == "no_show_charge":
        return load_policy("ryde_v2_1_no_show")
    if dtype == "route_deviation":
        return load_policy("ryde_v2_1_route_deviation")
    raise ValueError(f"No policy configured for dispute type: {dtype}")
