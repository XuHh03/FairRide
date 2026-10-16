import asyncio
import copy
import json
import unittest

from agents import ExampleAgentBackend, ModelAgentBackend
from case_data import load_case, policy_for_case
from contracts import AdvocateResult
from evidence import build_review_input
from review_summary import build_review_report
from workflow import run_review
from claim_repair_fixtures import patch_response


class ResponseDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case("DISP-004")
        self.policy = policy_for_case(self.case)
        self.review = build_review_input(self.case, self.policy)
        self.examples = ExampleAgentBackend().examples["DISP-004"]

    def client(self, outputs):
        class Client:
            calls = 0
            async def complete_json(self, instructions, payload):
                value = outputs[self.calls]
                self.calls += 1
                if isinstance(value, Exception):
                    raise value
                return patch_response(copy.deepcopy(value), payload), {"total_tokens": 5}
        return Client()

    def wrong_fact(self, role="driver_advocate"):
        output = copy.deepcopy(self.examples[role])
        output["claims"][0]["fact_assertions"] = [{"fact_id": "FACT-001", "value": 8}]
        return output

    def test_failed_repair_keeps_both_responses_errors_and_sent_assertions(self):
        initial = self.wrong_fact()
        repaired = copy.deepcopy(self.examples["driver_advocate"])
        client = self.client([initial, repaired])
        with self.assertRaisesRegex(ValueError, "must retain FACT-001") as raised:
            asyncio.run(ModelAgentBackend(client).advocate(self.review, "driver_advocate"))
        diagnostic = getattr(raised.exception, "validation_diagnostics", None)
        self.assertIsNotNone(diagnostic)
        self.assertEqual(diagnostic["case_id"], self.review.case_id)
        self.assertEqual(diagnostic["actor"], "driver_advocate")
        first, second = diagnostic["attempts"]
        self.assertEqual(first["response"], initial)
        self.assertEqual(second["response"], {"patches": [{"section": "claims", "index": 0,
                                                         "replacement": repaired["claims"][0]}]})
        self.assertIn("must equal 9", first["validation_errors"][0])
        self.assertIn("must retain FACT-001", second["validation_errors"][0])
        self.assertEqual(second["required_fact_assertions"], [{"fact_id": "FACT-001", "value": 9}])
        self.assertEqual(diagnostic["usage"]["total_tokens"], 10)
        self.assertEqual(client.calls, 2)

    def test_successful_repair_is_retained_without_changing_result(self):
        corrected = self.wrong_fact()
        corrected["claims"][0]["fact_assertions"][0]["value"] = 9
        client = self.client([self.wrong_fact(), corrected])
        call = asyncio.run(ModelAgentBackend(client).advocate(self.review, "driver_advocate"))
        diagnostic = getattr(call, "validation_diagnostics", None)
        self.assertIsNotNone(diagnostic)
        self.assertEqual(diagnostic["outcome"], "accepted_after_repair")
        self.assertEqual(diagnostic["attempts"][1]["validation_errors"], [])
        self.assertEqual(call.result, AdvocateResult.model_validate(corrected))

    def test_schema_diagnostics_filter_private_fields_without_mutating_validation_input(self):
        invalid = copy.deepcopy(self.examples["driver_advocate"])
        invalid.update(rider_profile={"name": "PRIVATE_RIDER"}, driver_profile={"name": "PRIVATE_DRIVER"},
                       headers={"Authorization": "PRIVATE_HEADER"}, api_key="PRIVATE_KEY")
        client = self.client([invalid, invalid])
        with self.assertRaisesRegex(ValueError, "Schema correction failed") as raised:
            asyncio.run(ModelAgentBackend(client).advocate(self.review, "driver_advocate"))
        diagnostic = getattr(raised.exception, "validation_diagnostics", None)
        self.assertIsNotNone(diagnostic)
        serialized = json.dumps(diagnostic)
        for secret in ("PRIVATE_RIDER", "PRIVATE_DRIVER", "PRIVATE_HEADER", "PRIVATE_KEY"):
            self.assertNotIn(secret, serialized)
        self.assertIn("rider_profile", invalid)  # Filtering did not make the invalid response pass.
        self.assertTrue(diagnostic["attempts"][0]["validation_errors"])

    def test_transport_failure_during_repair_preserves_available_response_and_category(self):
        client = self.client([self.wrong_fact(), RuntimeError("Model request failed (TimeoutError)")])
        with self.assertRaises(RuntimeError) as raised:
            asyncio.run(ModelAgentBackend(client).advocate(self.review, "driver_advocate"))
        diagnostic = getattr(raised.exception, "validation_diagnostics", None)
        self.assertIsNotNone(diagnostic)
        self.assertEqual(diagnostic["outcome"], "call_failed")
        self.assertEqual(diagnostic["attempts"][0]["response"], self.wrong_fact())
        self.assertIsNone(diagnostic["attempts"][1]["response"])
        self.assertEqual(client.calls, 2)

    def test_judge_failure_diagnostics_identify_judge(self):
        invalid = copy.deepcopy(self.examples["judge_final_ruling"])
        invalid["fact_assertions"] = [{"fact_id": "FACT-001", "value": 8}]
        client = self.client([invalid, invalid])
        rider = AdvocateResult.model_validate(self.examples["rider_advocate"])
        driver = AdvocateResult.model_validate(self.examples["driver_advocate"])
        with self.assertRaises(ValueError) as raised:
            asyncio.run(ModelAgentBackend(client).judge(self.review, rider, driver))
        self.assertEqual(getattr(raised.exception, "validation_diagnostics", {}).get("actor"), "judge")

    def test_workflow_failure_exports_diagnostics_and_counts_failed_call_usage(self):
        initial = self.wrong_fact("rider_advocate")
        repaired = copy.deepcopy(self.examples["rider_advocate"])
        examples = self.examples
        class Client:
            rider_calls = 0
            async def complete_json(self, instructions, payload):
                if "rider_advocate" in instructions:
                    self.rider_calls += 1
                    return patch_response(copy.deepcopy(initial if self.rider_calls == 1 else repaired), payload), {"total_tokens": 5}
                return copy.deepcopy(examples["driver_advocate"]), {"total_tokens": 7}
        result = run_review(self.case, self.policy, ModelAgentBackend(Client()))
        self.assertEqual(result.failure_category, "validation")
        self.assertIsNone(result.judge_result.proposed_action)
        events = [e for e in result.activity_log if e.event == "response_validation_failed"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].actor, "rider_advocate")
        self.assertEqual(events[0].output["usage"]["total_tokens"], 10)
        report = build_review_report(self.case, self.policy, result, "Live model")
        exported = next(e for e in report["workflow"]["activity_log"] if e["event"] == "response_validation_failed")
        self.assertEqual(len(exported["output"]["validation_diagnostics"]["attempts"]), 2)
        self.assertNotIn("rider_profile", json.dumps(report))

    def test_successful_workflow_repair_diagnostics_are_exported(self):
        examples = self.examples
        initial = self.wrong_fact("rider_advocate")
        corrected = copy.deepcopy(initial)
        corrected["claims"][0]["fact_assertions"][0]["value"] = 9
        class Client:
            rider_calls = 0
            async def complete_json(self, instructions, payload):
                if "rider_argument" in payload:
                    return copy.deepcopy(examples["judge_final_ruling"]), {}
                if "rider_advocate" in instructions:
                    self.rider_calls += 1
                    return patch_response(copy.deepcopy(initial if self.rider_calls == 1 else corrected), payload), {}
                return copy.deepcopy(examples["driver_advocate"]), {}
        result = run_review(self.case, self.policy, ModelAgentBackend(Client()))
        self.assertEqual(result.status, "completed")
        entry = next(e for e in result.activity_log if e.actor == "rider_advocate" and e.event == "initial_argument")
        self.assertEqual(entry.output.get("validation_diagnostics", {}).get("outcome"), "accepted_after_repair")
