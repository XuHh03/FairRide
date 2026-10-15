import copy
import unittest

from agents import AgentCall, ExampleAgentBackend
from case_data import load_case, policy_for_case
from contracts import AdvocateResult, JudgeResult, WorkflowResult
from checks import grounded_final_explanation, validate_final_ruling
from review_summary import build_decision_summary
from workflow import run_review


class FinalExplanationTests(unittest.TestCase):
    def test_every_demo_case_only_gets_final_explanation_after_a_completed_review(self):
        for number in range(2, 13):
            with self.subTest(case_id=f"DISP-{number:03d}"):
                case = load_case(f"DISP-{number:03d}")
                result = run_review(case, policy_for_case(case), ExampleAgentBackend())
                self.assertIsNone(result.failure_category)
                if result.status == "completed":
                    self.assertEqual(validate_final_ruling(case, policy_for_case(case), result.judge_result), [])
                    amount = result.judge_result.proposed_action.amount_cents
                    self.assertIn(f"Recommended rider refund: SGD {amount / 100:.2f}", result.final_explanation)
                else:
                    self.assertIsNone(result.final_explanation)

    def test_goodwill_is_explained_as_separate_from_fee_refund(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["trip_data"]["driver_arrival_time"] = None
        case["trip_data"]["driver_no_show_confirmed"] = True
        case["gps_telemetry"] = []
        case["chat_logs"] = []
        case["app_events"] = []
        decision = JudgeResult(action="final_ruling", ruling="reverse_charge", confidence=0.99,
            proposed_action={"amount_cents": 500, "goodwill_credit_cents": 500, "refund_basis": "cancellation_fee"},
            explanation="Fee reversal and separate goodwill.", evidence_ids=["TRIP-001"],
            policy_ids=["POLICY-2.3", "POLICY-2.4", "POLICY-7.3"])
        policy = policy_for_case(case)
        self.assertEqual(validate_final_ruling(case, policy, decision), [])
        explanation = grounded_final_explanation(case, policy, decision)
        self.assertIn("Recommended rider refund: SGD 5.00", explanation)
        self.assertIn("Separate goodwill credit under POLICY-2.4: SGD 5.00", explanation)
        result = WorkflowResult(case_id="DISP-004", status="completed", activity_log=[],
                                judge_result=decision, final_explanation=explanation, validation_issues=[])
        messages = build_decision_summary(case, policy, result)["party_messages"]
        for role, owner in (("rider", "your"), ("driver", "the rider's")):
            self.assertIn(f"SGD 5.00 of {owner} cancellation fee", messages[role]["action"])
            self.assertIn(f"Separate recommended goodwill credit to {owner} account: SGD 5.00", messages[role]["action"])
            self.assertEqual(messages[role]["explanation"], result.final_explanation)

    def review(self, case_id, explanation="Incorrect model arithmetic: refund SGD 99.00."):
        class Backend(ExampleAgentBackend):
            async def judge(self, review, rider_argument, driver_argument, rebuttals=None, previous_assessment=None):
                output = copy.deepcopy(self.examples[review.case_id]["judge_final_ruling"])
                output["explanation"] = explanation
                return AgentCall(JudgeResult.model_validate(output))

        case = load_case(case_id)
        return run_review(case, policy_for_case(case), Backend())

    def test_no_show_explanation_uses_eligible_wait_and_preserves_model_response(self):
        result = self.review("DISP-004")
        self.assertEqual(result.status, "completed")
        self.assertIn("9 eligible waiting minutes", result.final_explanation)
        self.assertIn("before cancellation", result.final_explanation)
        self.assertIn("SGD 0.00", result.final_explanation)
        self.assertNotIn("99.00", result.final_explanation)
        self.assertIn("99.00", result.judge_result.explanation)
        judge = next(e for e in result.activity_log if e.actor == "judge")
        self.assertEqual(judge.output["result"]["explanation"], result.judge_result.explanation)

    def test_route_explanation_uses_full_excess_and_rounded_refund(self):
        for case_id, distance, refund in (("DISP-006", "2", "1.10"), ("DISP-010", "1.5", "0.83")):
            with self.subTest(case_id=case_id):
                result = self.review(case_id)
                self.assertEqual(result.status, "completed")
                self.assertIn(f"{distance} km excess", result.final_explanation)
                self.assertIn("SGD 0.55/km", result.final_explanation)
                self.assertIn(f"SGD {refund}", result.final_explanation)
                self.assertIn("entire excess distance", result.final_explanation)
                self.assertNotIn("99.00", result.final_explanation)

    def test_valid_detour_explanation_uses_traffic_notice_and_agreement(self):
        result = self.review("DISP-011")
        self.assertIn("historical traffic", result.final_explanation)
        self.assertIn("rider agreed", result.final_explanation)
        self.assertIn("SGD 0.00", result.final_explanation)

    def test_notice_at_deviation_is_described_as_inclusive_boundary(self):
        case = copy.deepcopy(load_case("DISP-011"))
        at = next(event["timestamp"] for event in case["app_events"] if event["event_type"] == "route_deviation_detected")
        for contact in case["chat_logs"]:
            contact["timestamp"] = at
        result = run_review(case, policy_for_case(case), ExampleAgentBackend())
        self.assertEqual(result.status, "completed")
        self.assertIn("before or at deviation", result.final_explanation)

    def test_unverified_presence_does_not_become_verified_wait_in_explanation(self):
        class Backend(ExampleAgentBackend):
            async def advocate(self, review, role, question=None):
                return AgentCall(AdvocateResult(role=role, claims=[{
                    "statement": "Pickup presence is not verified.", "evidence_ids": ["TRIP-001"]}],
                    counterpoints=[], unanswered_questions=[]))

            async def judge(self, *args, **kwargs):
                return AgentCall(JudgeResult(action="final_ruling", ruling="reverse_charge",
                    proposed_action={"amount_cents": 500, "refund_basis": "cancellation_fee"},
                    explanation="Unverified presence and missing contacts invalidate the fee.", confidence=0.99,
                    evidence_ids=["TRIP-001"], policy_ids=["POLICY-2.1", "POLICY-2.3", "POLICY-7.3"]))

        case = copy.deepcopy(load_case("DISP-004"))
        case["gps_telemetry"] = []
        case["chat_logs"] = []
        case["app_events"] = []
        result = run_review(case, policy_for_case(case), Backend())
        self.assertEqual(result.status, "completed")
        self.assertNotIn("establish 9 eligible waiting minutes", result.final_explanation)
        self.assertIn("does not establish eligible waiting", result.final_explanation)

    def test_referrals_and_operational_failures_have_no_final_explanation(self):
        case = load_case("DISP-012")
        result = run_review(case, policy_for_case(case), ExampleAgentBackend())
        self.assertIsNone(result.final_explanation)
        class BrokenBackend(ExampleAgentBackend):
            async def advocate(self, *args, **kwargs):
                raise ValueError("Invalid model output")
        case = load_case("DISP-004")
        failed = run_review(case, policy_for_case(case), BrokenBackend())
        self.assertEqual(failed.failure_category, "validation")
        self.assertIsNone(failed.final_explanation)
