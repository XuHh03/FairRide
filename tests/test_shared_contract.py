import copy
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from case_data import load_case, load_policy, policy_for_case
from checks import no_show_facts
from contracts import AdvocateResult, JudgeResult
from evidence import build_evidence_index, build_review_input, validate_references


class SharedContractTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case("DISP-002")
        self.policy = load_policy("ryde_v2_1_no_show")

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
        self.assertEqual(fact.value, 6)
        self.assertEqual(fact.evidence_ids, ["TRIP-001"] + [record["id"] for record in self.case["gps_telemetry"]])
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

    def test_wait_fact_cites_the_gps_departure_used_in_its_calculation(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["gps_telemetry"] = [case["gps_telemetry"][2], {
            "id": "GPS-DEPARTED", "timestamp": "2026-09-25T09:00:00+08:00",
            "lat": 1.33, "lng": 103.87, "status": "departed"}]
        review = build_review_input(case, policy_for_case(case))
        fact = next(f for f in review.facts if f.name == "waited_minutes")
        self.assertEqual(fact.value, 0)
        self.assertIn("GPS-DEPARTED", fact.evidence_ids)
        self.assertIn("departure", fact.formula)
        self.assertIn("GPS", fact.formula)

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
        for case_id, outputs in examples.items():
            case = load_case(case_id)
            for name, output in outputs.items():
                with self.subTest(case=case_id, example=name):
                    model = AdvocateResult if name.endswith("advocate") else JudgeResult
                    result = model.model_validate(output)
                    self.assertEqual(validate_references(result, case, policy_for_case(case)), [])

    def test_every_final_ruling_requires_numeric_confidence(self):
        from agents import ExampleAgentBackend

        output = copy.deepcopy(ExampleAgentBackend().examples["DISP-004"]["judge_final_ruling"])
        for value in (None, -0.01, 1.01):
            with self.subTest(confidence=value), self.assertRaises(ValidationError):
                JudgeResult.model_validate({**output, "confidence": value})
        output.pop("confidence")
        with self.assertRaises(ValidationError):
            JudgeResult.model_validate(output)
        for value in (0, 0.8, 1):
            with self.subTest(confidence=value):
                self.assertEqual(JudgeResult.model_validate({**output, "confidence": value}).confidence, value)

    def test_referral_and_rebuttal_can_omit_confidence(self):
        for output in (
            {"action": "human_review", "explanation": "Policy requires referral."},
            {"action": "request_rebuttal", "explanation": "Clarify pickup presence.",
             "question": "Is presence verified?", "rebuttal_roles": ["rider_advocate"]},
        ):
            with self.subTest(action=output["action"]):
                self.assertIsNone(JudgeResult.model_validate(output).confidence)

    def test_wait_clock_follows_configured_policy(self):
        policy = copy.deepcopy(self.policy)
        policy["wait_start_event"] = "scheduled_time"
        facts = no_show_facts(self.case, policy)
        self.assertEqual(facts["waited_minutes"], 6)
        self.assertTrue(facts["fee_eligible"])


if __name__ == "__main__":
    unittest.main()
