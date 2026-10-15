import asyncio
import copy
import unittest

from agents import ExampleAgentBackend, ModelAgentBackend
from case_data import load_case, policy_for_case
from contracts import AdvocateResult
from evidence import build_review_input
from workflow import run_review


class SchemaRetryTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case("DISP-002")
        self.policy = policy_for_case(self.case)
        self.review = build_review_input(self.case, self.policy)
        self.examples = ExampleAgentBackend().examples["DISP-002"]
        self.request = {"action": "request_rebuttal", "explanation": "Clarify the pickup allegation.",
                        "question": "Is the rider's presence independently verified?", "rebuttal_roles": ["rider_advocate"]}

    def client(self, outputs):
        class Client:
            def __init__(self):
                self.payloads = []

            async def complete_json(self, instructions, payload):
                self.payloads.append(copy.deepcopy(payload))
                return copy.deepcopy(outputs[len(self.payloads) - 1]), {"total_tokens": 5}

        return Client()

    def judge(self, client, prior=None):
        rider = AdvocateResult.model_validate(self.examples["rider_advocate"])
        driver = AdvocateResult.model_validate(self.examples["driver_advocate"])
        return asyncio.run(ModelAgentBackend(client).judge(self.review, rider, driver, previous_assessment=prior))

    def test_missing_explanation_gets_one_schema_repair(self):
        invalid = copy.deepcopy(self.request)
        del invalid["explanation"]
        client = self.client([invalid, self.request])
        call = self.judge(client)
        self.assertEqual(call.result.question, self.request["question"])
        self.assertEqual(call.result.explanation, self.request["explanation"])
        self.assertEqual(call.schema_retries, 1)
        self.assertEqual(call.citation_retries, 0)
        self.assertEqual(call.usage["total_tokens"], 10)
        self.assertIn("explanation: Field required", client.payloads[1]["schema_correction"]["errors"])
        self.assertEqual(client.payloads[1]["schema_correction"]["previous_response"], invalid)
        self.assertFalse(client.payloads[1]["rebuttal_round_complete"])

    def test_overlong_advocate_is_rewritten_without_truncation(self):
        valid = copy.deepcopy(self.examples["rider_advocate"])
        invalid = copy.deepcopy(valid)
        invalid["claims"][0]["statement"] = "x" * 1501
        client = self.client([invalid, valid])
        call = asyncio.run(ModelAgentBackend(client).advocate(self.review, "rider_advocate"))
        self.assertEqual(call.result.model_dump(), AdvocateResult.model_validate(valid).model_dump())
        self.assertEqual(call.schema_retries, 1)
        self.assertEqual(call.usage["total_tokens"], 10)
        correction = client.payloads[1]["schema_correction"]
        self.assertEqual(correction["previous_response"], invalid)
        self.assertIn("main points", correction["instruction"])

    def test_persistent_overlong_advocate_fails_after_two_calls(self):
        invalid = copy.deepcopy(self.examples["rider_advocate"])
        invalid["claims"][0]["statement"] = "x" * 1501
        client = self.client([invalid, invalid])
        with self.assertRaisesRegex(ValueError, "Schema correction failed: claims.0.statement"):
            asyncio.run(ModelAgentBackend(client).advocate(self.review, "rider_advocate"))
        self.assertEqual(len(client.payloads), 2)

    def test_length_and_citation_corrections_share_budget_in_both_orders(self):
        valid = copy.deepcopy(self.examples["rider_advocate"])
        overlong = copy.deepcopy(valid)
        overlong["claims"][0]["statement"] = "x" * 1501
        bad_citation = copy.deepcopy(valid)
        bad_citation["claims"][0]["evidence_ids"] = ["UNKNOWN-001"]
        for responses, error in (([overlong, bad_citation], "Citation correction failed"),
                                 ([bad_citation, overlong], "Schema correction failed")):
            with self.subTest(error=error):
                client = self.client(responses)
                with self.assertRaisesRegex(ValueError, error):
                    asyncio.run(ModelAgentBackend(client).advocate(self.review, "rider_advocate"))
                self.assertEqual(len(client.payloads), 2)

    def test_persistent_missing_field_fails_after_two_calls(self):
        invalid = copy.deepcopy(self.request)
        del invalid["explanation"]
        client = self.client([invalid, invalid])
        with self.assertRaisesRegex(ValueError, "Schema correction failed: explanation: Field required"):
            self.judge(client)
        self.assertEqual(len(client.payloads), 2)

    def test_schema_and_citation_repairs_share_one_retry_budget(self):
        invalid = copy.deepcopy(self.request)
        del invalid["explanation"]
        second = copy.deepcopy(self.request)
        second["evidence_ids"] = ["POLICY-2.4"]
        client = self.client([invalid, second])
        with self.assertRaisesRegex(ValueError, "Unknown evidence ID: POLICY-2.4"):
            self.judge(client)
        self.assertEqual(len(client.payloads), 2)

    def test_schema_repair_preserves_rebuttal_question_in_workflow(self):
        request = self.request
        invalid = copy.deepcopy(request)
        del invalid["explanation"]
        examples = self.examples
        responses = [invalid, request, examples["judge_final_ruling"]]

        class Client:
            def __init__(self):
                self.payloads = []

            async def complete_json(self, instructions, payload):
                if "argument" in payload:
                    return {"findings": []}, {"total_tokens": 5}
                if "rider_argument" in payload:
                    self.payloads.append(copy.deepcopy(payload))
                    return copy.deepcopy(responses[len(self.payloads) - 1]), {"total_tokens": 5}
                role = "rider_advocate" if "rider_advocate" in instructions else "driver_advocate"
                return copy.deepcopy(examples[role]), {"total_tokens": 5}

        client = Client()
        result = run_review(self.case, self.policy, ModelAgentBackend(client))
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(client.payloads), 3)
        self.assertEqual(client.payloads[-1]["previous_assessment"]["question"], request["question"])
        self.assertEqual(sum(e.event == "rebuttal" for e in result.activity_log), 1)
        initial = next(e for e in result.activity_log if e.event == "provisional_review")
        self.assertEqual(initial.output["schema_retries"], 1)
