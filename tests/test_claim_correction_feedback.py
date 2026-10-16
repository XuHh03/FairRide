import asyncio
import copy
import unittest

from agents import ModelAgentBackend
from case_data import load_case, policy_for_case
from contracts import AdvocateResult
from evidence import build_review_input, claim_correction_feedback, validate_references


class ClaimCorrectionFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case("DISP-004")
        self.case["dispute_ticket"]["dispute_id"] = "UNSEEN-FEEDBACK-CASE"
        self.case["chat_logs"] = []
        self.case["app_events"] = []
        for point in self.case["gps_telemetry"]:
            point["lat"] += 0.01
        self.policy = policy_for_case(self.case)
        self.review = build_review_input(self.case, self.policy)

    def argument(self, statement, *, section="claims", assertions=None, role="driver_advocate"):
        output = {"role": role, "claims": [], "counterpoints": [], "unanswered_questions": []}
        output[section] = [{"statement": statement, "evidence_ids": ["TRIP-001"],
                            "fact_assertions": assertions or []}]
        return AdvocateResult.model_validate(output)

    def test_wrong_fact_feedback_identifies_exact_counterpoint_and_canonical_value(self):
        statement = "The driver’s presence at pickup was established."
        result = self.argument(statement, section="counterpoints", assertions=[{"fact_id": "FACT-009", "value": True}])
        finding = claim_correction_feedback(result, self.review)[0]
        self.assertEqual(finding["section"], "counterpoints")
        self.assertEqual(finding["index"], 0)
        self.assertEqual(finding["statement"], statement)
        fact = next(f for f in finding["facts"] if f["fact_id"] == "FACT-009")
        self.assertIs(fact["value"], False)
        self.assertIn("correction", finding)

    def test_correct_false_assertions_do_not_hide_affirmative_pickup_claim(self):
        for role in ("rider_advocate", "driver_advocate"):
            result = self.argument("The driver was physically present at the pickup location, confirmed by GPS.",
                                   role=role, assertions=[{"fact_id": "FACT-009", "value": False}])
            with self.subTest(role=role):
                findings = claim_correction_feedback(result, self.review)
                self.assertTrue(findings)
                self.assertIn("unresolved", findings[0]["correction"].lower())
                self.assertTrue(validate_references(result, self.case, self.policy))

    def test_qualified_negated_hypothetical_and_offsite_statements_are_allowed(self):
        for statement in (
            "The driver was not physically present at the pickup location according to the rider.",
            "It is not established that the driver was physically present at the pickup location.",
            "It is false that the driver was physically present at the pickup location.",
            "There is no evidence that the driver was physically present at the pickup location.",
            "There is no evidence the driver was physically present at the pickup location.",
            "It has not been established that the driver was physically present at the pickup location.",
            "We cannot conclude that the driver was physically present at the pickup location.",
            "The rider denies that the driver was physically present at the pickup location.",
            "The arrival-service record reports that the driver was physically present at the pickup location, but GPS conflicts.",
            "The driver was physically present at the pickup location according to the arrival-service record; independent verification remains unresolved.",
            "If the driver was physically present at the pickup location, that would not resolve the missing contact.",
            "Whether the driver was physically present at the pickup location remains unresolved.",
            "The claim that the driver was physically present at the pickup location is not verified.",
            "The driver was physically present at an off-site depot.",
            "Pickup presence is not verified; the arrival records conflict.",
            "The driver was physically present at the pickup location after cancellation, so arrival before cancellation is unverified.",
        ):
            with self.subTest(statement=statement):
                result = self.argument(statement)
                self.assertEqual(claim_correction_feedback(result, self.review), [])
                self.assertEqual(validate_references(result, self.case, self.policy), [])

    def test_explicit_verified_presence_phrasings_are_rejected(self):
        for statement in ("Pickup presence was verified.", "Physical arrival was confirmed.",
                          "GPS confirms the driver's physical presence at the pickup location."):
            with self.subTest(statement=statement):
                self.assertTrue(claim_correction_feedback(self.argument(statement), self.review))

    def test_conflict_word_does_not_hide_an_affirmative_presence_claim(self):
        for statement in (
            "Despite conflicting GPS records, the driver was physically present at the pickup location.",
            "The rider’s claim of 'no car' is factually false because the driver was physically present at the pickup location.",
        ):
            with self.subTest(statement=statement):
                self.assertTrue(claim_correction_feedback(self.argument(statement), self.review))

    def test_verified_pickup_presence_remains_allowed(self):
        case = load_case("DISP-004")
        result = self.argument("The driver was physically present at the pickup location, confirmed by GPS.")
        self.assertEqual(claim_correction_feedback(result, build_review_input(case, policy_for_case(case))), [])

    def test_repair_receives_targeted_feedback_within_existing_two_calls(self):
        wrong = self.argument("The driver was physically present at the pickup location, confirmed by GPS.",
                              assertions=[{"fact_id": "FACT-009", "value": False}]).model_dump(mode="json")
        corrected = self.argument("The arrival record reports pickup presence, but GPS conflicts; presence and goodwill remain unresolved.",
                                  assertions=[{"fact_id": "FACT-009", "value": False}]).model_dump(mode="json")
        class Client:
            def __init__(self):
                self.payloads = []
            async def complete_json(self, instructions, payload):
                self.payloads.append(copy.deepcopy(payload))
                return copy.deepcopy(wrong if len(self.payloads) == 1 else corrected), {"total_tokens": 5}
        client = Client()
        call = asyncio.run(ModelAgentBackend(client).advocate(self.review, "driver_advocate"))
        self.assertEqual(len(client.payloads), 2)
        feedback = client.payloads[1]["schema_correction"]["claim_feedback"]
        self.assertEqual(feedback[0]["statement"], wrong["claims"][0]["statement"])
        self.assertEqual(feedback[0]["section"], "claims")
        self.assertEqual(feedback[0]["index"], 0)
        self.assertEqual(call.usage["total_tokens"], 10)
        self.assertEqual(call.result.claims[0].statement, corrected["claims"][0]["statement"])
        self.assertEqual(call.validation_diagnostics["attempts"][0]["claim_feedback"], feedback)

    def test_persistent_prose_error_is_rejected_after_one_repair(self):
        output = self.argument("The driver was physically present at the pickup location.").model_dump(mode="json")
        class Client:
            calls = 0
            async def complete_json(self, instructions, payload):
                self.calls += 1
                return copy.deepcopy(output), {}
        client = Client()
        with self.assertRaisesRegex(ValueError, "Prose consistency correction failed"):
            asyncio.run(ModelAgentBackend(client).advocate(self.review, "driver_advocate"))
        self.assertEqual(client.calls, 2)

    def test_valid_arguments_do_not_trigger_feedback_or_an_extra_call(self):
        output = self.argument("The missing contacts invalidate the fee; pickup presence remains disputed.").model_dump(mode="json")
        class Client:
            calls = 0
            async def complete_json(self, instructions, payload):
                self.calls += 1
                return copy.deepcopy(output), {}
        client = Client()
        asyncio.run(ModelAgentBackend(client).advocate(self.review, "driver_advocate"))
        self.assertEqual(client.calls, 1)
