import copy
import unittest

from agents import ExampleAgentBackend, ModelAgentBackend
from case_data import load_case, policy_for_case
from workflow import run_review


class DecisionClient:
    def __init__(self, case_id, decisions):
        self.examples = ExampleAgentBackend().examples[case_id]
        self.decisions = decisions
        self.judge_payloads = []

    async def complete_json(self, instructions, payload):
        if "rider_argument" in payload:
            self.judge_payloads.append(copy.deepcopy(payload))
            return copy.deepcopy(self.decisions[len(self.judge_payloads) - 1]), {"total_tokens": 5}
        role = "rider_advocate" if "rider_advocate" in instructions else "driver_advocate"
        key = role
        if payload.get("follow_up_question"):
            key = role.removesuffix("_advocate") + "_rebuttal_advocate"
        return copy.deepcopy(self.examples.get(key, self.examples[role])), {"total_tokens": 5}


class JudgeCorrectionTests(unittest.TestCase):
    def run_case(self, case_id, decisions):
        case = load_case(case_id)
        client = DecisionClient(case_id, decisions)
        progress = []
        result = run_review(case, policy_for_case(case), ModelAgentBackend(client), on_progress=progress.append)
        return result, client, progress

    def final(self, case_id="DISP-006"):
        return copy.deepcopy(ExampleAgentBackend().examples[case_id]["judge_final_ruling"])

    def test_clear_two_km_unjustified_detour_referral_is_corrected(self):
        wrong = {"action": "human_review", "explanation": "The 1.3.35 km threshold and unspecified formula require review at exactly 2 km."}
        result, client, updates = self.run_case("DISP-006", [wrong, self.final()])
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.judge_result.proposed_action.amount_cents, 110)
        feedback = client.judge_payloads[1]["validation_feedback"]
        self.assertTrue(feedback["errors"])
        self.assertEqual(feedback["policy_requirements"]["ruling"], "partial_refund")
        self.assertEqual(feedback["policy_requirements"]["refund_cents"], 110)
        self.assertEqual(client.judge_payloads[0]["decision_rules"]["route_ai_distance_limit_km"], 2)
        self.assertEqual(client.judge_payloads[0]["decision_rules"]["route_no_refund_tolerance_km"], 1)
        self.assertIn("Judge is correcting its decision", updates)
        self.assertTrue(any(e.event == "decision_correction" for e in result.activity_log))

    def test_missing_precedent_and_wrong_amount_or_basis_are_corrected(self):
        for defect in ("precedent", "amount", "basis"):
            with self.subTest(defect=defect):
                wrong = self.final()
                if defect == "precedent":
                    wrong["policy_ids"].remove("POLICY-7.1")
                elif defect == "amount":
                    wrong["proposed_action"]["amount_cents"] = 360
                else:
                    wrong["proposed_action"]["refund_basis"] = "cancellation_fee"
                result, client, _ = self.run_case("DISP-006", [wrong, self.final()])
                self.assertIsNone(result.failure_category)
                self.assertEqual(result.status, "completed")
                self.assertEqual(len(client.judge_payloads), 2)

    def test_persistent_unsupported_referral_is_validation_failure(self):
        wrong = {"action": "human_review", "explanation": "Exactly 2 km is too complex."}
        result, client, _ = self.run_case("DISP-006", [wrong, wrong])
        self.assertEqual(len(client.judge_payloads), 2)
        self.assertEqual(result.failure_category, "validation")
        self.assertIsNone(result.judge_result.proposed_action)

    def test_explicit_low_confidence_is_preserved_without_correction(self):
        for action in ("human_review", "final_ruling"):
            with self.subTest(action=action):
                decision = self.final() if action == "final_ruling" else {"action": action, "explanation": "Confidence is insufficient."}
                decision["confidence"] = 0.7
                result, client, _ = self.run_case("DISP-006", [decision])
                self.assertIsNone(result.failure_category)
                self.assertTrue(result.mandatory_escalation)
                self.assertEqual(len(client.judge_payloads), 1)
                if action == "human_review":
                    self.assertEqual(result.judge_result.confidence, 0.7)
                    self.assertEqual(result.judge_result.explanation, decision["explanation"])

    def test_missing_traffic_conflict_keeps_human_review_and_original_question(self):
        examples = ExampleAgentBackend().examples["DISP-012"]
        result, client, _ = self.run_case("DISP-012", [examples["judge_rebuttal"], examples["judge_human_review"]])
        self.assertIsNone(result.failure_category)
        self.assertEqual(result.status, "human_review")
        self.assertNotIn("validation_feedback", client.judge_payloads[-1])
        self.assertEqual(client.judge_payloads[-1]["previous_assessment"]["question"], examples["judge_rebuttal"]["question"])

    def test_correction_cannot_start_another_rebuttal(self):
        wrong = {"action": "human_review", "explanation": "Boundary is uncertain."}
        request = {"action": "request_rebuttal", "explanation": "Ask again.", "question": "Explain the boundary.", "rebuttal_roles": ["driver_advocate"]}
        result, client, _ = self.run_case("DISP-006", [wrong, request])
        self.assertEqual(result.failure_category, "validation")
        self.assertTrue(client.judge_payloads[-1]["rebuttal_round_complete"])
        self.assertFalse(any(e.event == "rebuttal" for e in result.activity_log))

    def test_correction_after_rebuttal_preserves_original_question(self):
        request = {"action": "request_rebuttal", "explanation": "Clarify the contacts.",
                   "question": "Were both required contacts attempted?", "rebuttal_roles": ["rider_advocate"]}
        wrong = self.final("DISP-003")
        wrong["policy_ids"].remove("POLICY-7.3")
        result, client, _ = self.run_case("DISP-003", [request, wrong, self.final("DISP-003")])
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(client.judge_payloads), 3)
        self.assertEqual(client.judge_payloads[-1]["previous_assessment"]["question"], request["question"])
        self.assertEqual(len(client.judge_payloads[-1]["rebuttals"]), 1)
        self.assertTrue(client.judge_payloads[-1]["rebuttal_round_complete"])

    def test_no_show_wrong_reversal_is_corrected_without_forcing_confidence(self):
        wrong = self.final("DISP-002")
        wrong["ruling"] = "reverse_charge"
        wrong["proposed_action"]["amount_cents"] = 500
        result, client, _ = self.run_case("DISP-002", [wrong, self.final("DISP-002")])
        self.assertEqual(result.judge_result.ruling, "uphold_charge")
        self.assertEqual(result.judge_result.proposed_action.amount_cents, 0)
        self.assertEqual(len(client.judge_payloads), 2)

    def test_corrected_low_confidence_remains_a_policy_referral(self):
        wrong = {"action": "human_review", "explanation": "Boundary is too complex."}
        low = {"action": "human_review", "confidence": 0.7, "explanation": "I cannot reach the required confidence from the supplied records."}
        result, client, _ = self.run_case("DISP-006", [wrong, low])
        self.assertTrue(result.mandatory_escalation)
        self.assertIsNone(result.failure_category)
        self.assertEqual(len(client.judge_payloads), 2)
        self.assertEqual(result.judge_result.confidence, 0.7)
        self.assertEqual(result.judge_result.explanation, low["explanation"])
