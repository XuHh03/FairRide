import asyncio
import copy
import unittest

from agents import ExampleAgentBackend, ModelAgentBackend
from case_data import load_case, policy_for_case
from contracts import AdvocateResult, JudgeResult
from evidence import build_review_input, validate_references
from claim_repair_fixtures import patch_response


class ProseConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.examples = ExampleAgentBackend().examples

    def test_valid_fee_cannot_be_described_as_rider_compensation(self):
        case = load_case("DISP-004")
        output = copy.deepcopy(self.examples["DISP-004"]["driver_advocate"])
        output["claims"][0]["statement"] = (
            "The driver completed 9 minutes of verified wait time, making the rider eligible for the compensation fee under POLICY-2.2.")
        issues = validate_references(AdvocateResult.model_validate(output), case, policy_for_case(case))
        self.assertTrue(any("driver" in issue and "compensation" in issue for issue in issues), issues)

    def test_incorrect_excess_distance_is_rejected_even_when_final_amount_is_correct(self):
        case = load_case("DISP-010")
        output = copy.deepcopy(self.examples["DISP-010"]["judge_final_ruling"])
        output["explanation"] = ("The excess distance is 0.5 km (1.5 km actual - 1.0 km tolerance). "
                                 "The fare is 28 cents. However, FACT-004 says 83 cents, so use 83 cents.")
        issues = validate_references(JudgeResult.model_validate(output), case, policy_for_case(case))
        self.assertTrue(any("1.5" in issue and "0.5" in issue for issue in issues), issues)

    def test_refund_distance_wording_from_live_followup_cannot_hide_deduction(self):
        case = load_case("DISP-010")
        output = copy.deepcopy(self.examples["DISP-010"]["judge_final_ruling"])
        output["explanation"] = ("The additional distance above tolerance is 1.5 - 1 = 0.5 km. "
                                 "The refund is for this 0.5 km. However, use the supplied 83 cents.")
        issues = validate_references(JudgeResult.model_validate(output), case, policy_for_case(case))
        self.assertTrue(any("0.5" in issue and "1.5" in issue for issue in issues), issues)

    def test_correct_refunds_negations_and_hypothetical_arguments_are_allowed(self):
        for case_id, statements in (
            ("DISP-004", ["The driver receives the cancellation fee as compensation.",
                          "The rider is not eligible for the compensation fee.",
                          "The rider receives no compensation under POLICY-2.2; the valid fee compensates the driver.",
                          "The rider receives confirmation that the cancellation fee is valid.",
                          "If the fee were invalid, the rider would receive a cancellation fee refund.",
                          "The driver contacted the rider and is eligible for the compensation fee."]),
            ("DISP-003", ["The rider receives a cancellation fee refund."]),
            ("DISP-010", ["The excess distance is 1.5 km; refund the entire 83-cent component.",
                          "Do not claim that the excess distance is 0.5 km.",
                          "The refund is for the entire 1.5 km.",
                          "The distance above tolerance is 0.5 km; the refund covers the full 1.5 km.",
                          "The 1 km tolerance is not subtracted from the 1.5 km excess distance."]),
        ):
            case = load_case(case_id)
            for statement in statements:
                with self.subTest(case=case_id, statement=statement):
                    output = copy.deepcopy(self.examples[case_id]["rider_advocate"])
                    output["claims"] = [{"statement": statement, "evidence_ids": ["TRIP-001"]}]
                    output["counterpoints"] = []
                    self.assertEqual(validate_references(AdvocateResult.model_validate(output), case, policy_for_case(case)), [])

    def client(self, responses):
        class Client:
            def __init__(self):
                self.payloads = []

            async def complete_json(self, instructions, payload):
                self.payloads.append(copy.deepcopy(payload))
                return patch_response(copy.deepcopy(responses[len(self.payloads) - 1]), payload), {"total_tokens": 5}

        return Client()

    def test_wrong_fee_recipient_is_rewritten_within_existing_retry(self):
        case = load_case("DISP-004")
        review = build_review_input(case, policy_for_case(case))
        valid = copy.deepcopy(self.examples["DISP-004"]["driver_advocate"])
        wrong = copy.deepcopy(valid)
        wrong["claims"][0]["statement"] = "The rider is eligible for the compensation fee under POLICY-2.2."
        client = self.client([wrong, valid])
        call = asyncio.run(ModelAgentBackend(client).advocate(review, "driver_advocate"))
        self.assertEqual(len(client.payloads), 2)
        self.assertEqual(call.schema_retries, 1)
        self.assertEqual(call.usage["total_tokens"], 10)
        self.assertIn("driver", " ".join(client.payloads[1]["schema_correction"]["errors"]))
        self.assertEqual(call.result.model_dump(), AdvocateResult.model_validate(valid).model_dump())

    def test_wrong_judge_arithmetic_is_repaired_or_fails_after_two_calls(self):
        case = load_case("DISP-010")
        review = build_review_input(case, policy_for_case(case))
        valid = copy.deepcopy(self.examples["DISP-010"]["judge_final_ruling"])
        wrong = copy.deepcopy(valid)
        wrong["explanation"] = "The excess distance is 0.5 km after deducting tolerance, so use 28 cents, or use FACT-004=83 cents."
        rider = AdvocateResult.model_validate(self.examples["DISP-010"]["rider_advocate"])
        driver = AdvocateResult.model_validate(self.examples["DISP-010"]["driver_advocate"])
        client = self.client([wrong, valid])
        call = asyncio.run(ModelAgentBackend(client).judge(review, rider, driver))
        self.assertEqual(call.schema_retries, 1)
        self.assertEqual(call.result.explanation, valid["explanation"])
        client = self.client([wrong, wrong])
        with self.assertRaisesRegex(ValueError, "Prose consistency correction failed"):
            asyncio.run(ModelAgentBackend(client).judge(review, rider, driver))
        self.assertEqual(len(client.payloads), 2)

    def test_judge_receives_authoritative_case_calculation_context(self):
        case = load_case("DISP-010")
        review = build_review_input(case, policy_for_case(case))
        client = self.client([self.examples["DISP-010"]["judge_final_ruling"]])
        rider = AdvocateResult.model_validate(self.examples["DISP-010"]["rider_advocate"])
        driver = AdvocateResult.model_validate(self.examples["DISP-010"]["driver_advocate"])
        asyncio.run(ModelAgentBackend(client).judge(review, rider, driver))
        context = client.payloads[0].get("policy_application", "")
        self.assertIn("1.5 km", context)
        self.assertIn("83 cents", context)
        self.assertIn("do not subtract", context)

    def test_prose_and_citation_repairs_share_one_budget(self):
        case = load_case("DISP-004")
        review = build_review_input(case, policy_for_case(case))
        valid = copy.deepcopy(self.examples["DISP-004"]["driver_advocate"])
        wrong_prose = copy.deepcopy(valid)
        wrong_prose["claims"][0]["statement"] = "The rider is eligible for the compensation fee."
        wrong_source = copy.deepcopy(valid)
        wrong_source["claims"][0]["evidence_ids"] = ["UNKNOWN-001"]
        for responses, error in (([wrong_prose, wrong_source], "Citation correction failed"),
                                 ([wrong_source, wrong_prose], "Prose consistency correction failed")):
            with self.subTest(error=error):
                client = self.client(responses)
                with self.assertRaisesRegex(ValueError, error):
                    asyncio.run(ModelAgentBackend(client).advocate(review, "driver_advocate"))
                self.assertEqual(len(client.payloads), 2)

    def test_both_roles_receive_the_same_explicit_driver_compensation_rule(self):
        case = load_case("DISP-004")
        review = build_review_input(case, policy_for_case(case))
        client = self.client([self.examples["DISP-004"]["driver_advocate"],
                              self.examples["DISP-004"]["judge_final_ruling"]])
        backend = ModelAgentBackend(client)
        driver = asyncio.run(backend.advocate(review, "driver_advocate")).result
        rider = AdvocateResult.model_validate(self.examples["DISP-004"]["rider_advocate"])
        asyncio.run(backend.judge(review, rider, driver))
        self.assertEqual(client.payloads[0]["policy_application"], client.payloads[1]["policy_application"])
        self.assertIn("compensates the DRIVER, not the rider", client.payloads[0]["policy_application"])
