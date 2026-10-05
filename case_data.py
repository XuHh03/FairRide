import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def load_case(case_id: str) -> dict:
    return json.loads((ROOT / "cases" / f"{case_id}.json").read_text())


def load_policy(policy_id: str) -> dict:
    return json.loads((ROOT / "policies" / f"{policy_id}.json").read_text())
