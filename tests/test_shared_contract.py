import copy
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from case_data import load_case, load_policy
from checks import no_show_facts
from contracts import AdvocateResult, JudgeResult
from evidence import build_evidence_index, build_review_input, validate_references


class SharedContractTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case("DISP-002")
        self.policy = load_policy("sample_no_show")

    def test_citation_resolves_to_original_record(self):
        record = build_evidence_index(self.case)["GPS-005"]
        self.assertEqual(record.data["timestamp"], "2026-09-13T08:43:00+08:00")
        self.assertEqual(record.source, "gps_telemetry")

    def test_missing_and_duplicate_ids_are_rejected(self):
        for missing in (True, False):
            case = copy.deepcopy(self.case)
            if missing:
                case["gps_telemetry"][0].pop("id")
            else:
                case["gps_telemetry"][0]["id"] = "GPS-005"
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                build_evidence_index(case)

    def test_review_input_excludes_profiles_and_preserves_fact_sources(self):
        review = build_review_input(self.case, self.policy)
        self.assertEqual(review.case_id, "DISP-002")
        self.assertNotIn("fraud_flags", review.model_dump_json())
        fact = next(f for f in review.facts if f.id == "FACT-001")
        self.assertEqual(fact.value, 8)
        self.assertEqual(fact.evidence_ids, ["TRIP-001"])
        self.assertIn("cancellation_time", fact.formula)

    def test_unknown_evidence_and_policy_citations_are_reported(self):
        result = AdvocateResult.model_validate({
            "role": "rider_advocate",
            "claims": [{"statement": "Unsupported claim", "evidence_ids": ["GPS-999"],
                        "policy_ids": ["POLICY-999"]}],
            "counterpoints": [], "unanswered_questions": []})
        issues = validate_references(result, self.case, self.policy)
        self.assertEqual(len(issues), 2)
        self.assertTrue(any("GPS-999" in issue for issue in issues))
        self.assertTrue(any("POLICY-999" in issue for issue in issues))

    def test_judge_action_requires_matching_fields(self):
        invalid = [
            {"action": "final_ruling", "explanation": "Missing ruling and action"},
            {"action": "request_rebuttal", "explanation": "Missing question"},
            {"action": "human_review", "explanation": "Unresolved", "ruling": "uphold_charge"},
        ]
        for output in invalid:
            with self.subTest(output=output), self.assertRaises(ValidationError):
                JudgeResult.model_validate(output)

    def test_examples_have_valid_schemas_and_citations(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "agent_outputs.json"
        examples = json.loads(path.read_text())
        for name, output in examples.items():
            with self.subTest(example=name):
                model = AdvocateResult if name.endswith("advocate") else JudgeResult
                result = model.model_validate(output)
                self.assertEqual(validate_references(result, self.case, self.policy), [])

    def test_wait_clock_follows_configured_policy(self):
        policy = copy.deepcopy(self.policy)
        policy["wait_start_event"] = "scheduled_time"
        facts = no_show_facts(self.case, policy)
        self.assertEqual(facts["waited_minutes"], 6)
        self.assertFalse(facts["fee_eligible"])


if __name__ == "__main__":
    unittest.main()
