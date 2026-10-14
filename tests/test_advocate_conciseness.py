import asyncio
import copy
import unittest

from pydantic import ValidationError

from agents import ExampleAgentBackend, ModelAgentBackend
from case_data import load_case, policy_for_case
from contracts import AdvocateResult
from evidence import build_review_input
from workflow import run_review


class AdvocateConcisenessTests(unittest.TestCase):
    def setUp(self):
        self.output = copy.deepcopy(ExampleAgentBackend().examples["DISP-002"]["rider_advocate"])

    def test_more_than_three_short_points_are_allowed(self):
        for section in ("claims", "counterpoints"):
            with self.subTest(section=section):
                output = copy.deepcopy(self.output)
                output[section] = [
                    {"statement": statement, "evidence_ids": ["TRIP-001"]}
                    for statement in ["The driver arrived early.", "The wait starts at scheduled pickup.",
                                      "The cancellation occurred after the wait period.", "Contact obligations affect fee validity."]]
                self.assertEqual(len(getattr(AdvocateResult.model_validate(output), section)), 4)

    def test_overlong_claims_and_counterpoints_are_rejected(self):
        for section in ("claims", "counterpoints"):
            with self.subTest(section=section):
                output = copy.deepcopy(self.output)
                output[section] = [{"statement": "x" * 1501, "evidence_ids": ["TRIP-001"]}]
                with self.assertRaises(ValidationError):
                    AdvocateResult.model_validate(output)

    def test_three_short_sentences_are_allowed(self):
        self.output["claims"][0]["statement"] = "The rider alleges presence. The driver waited. Contact was attempted."
        self.assertEqual(AdvocateResult.model_validate(self.output).claims[0].statement, self.output["claims"][0]["statement"])

    def test_statement_longer_than_old_guard_is_allowed(self):
        self.output["claims"][0]["statement"] = "Evidence detail " * 40
        self.assertEqual(AdvocateResult.model_validate(self.output).claims[0].statement, self.output["claims"][0]["statement"])

    def test_concession_and_empty_counterpoints_are_valid(self):
        self.output["claims"] = [{
            "statement": "The rider alleges presence, but this is unverified. The records support retaining the SGD 5.00 fee under policy 2.3.",
            "evidence_ids": ["TICKET-001", "TRIP-001"], "policy_ids": ["POLICY-2.3"]}]
        self.output["counterpoints"] = []
        self.assertEqual(AdvocateResult.model_validate(self.output).claims[0].statement, self.output["claims"][0]["statement"])

    def test_live_advocate_receives_length_constraints_and_concession_instruction(self):
        output = self.output

        class Client:
            async def complete_json(self, instructions, payload):
                self.instructions = instructions
                self.payload = payload
                return output, {}

        case = load_case("DISP-002")
        review = build_review_input(case, policy_for_case(case))
        client = Client()
        asyncio.run(ModelAgentBackend(client).advocate(review, "rider_advocate"))
        schema = client.payload["output_schema"]
        self.assertNotIn("maxItems", schema["properties"]["claims"])
        self.assertNotIn("maxItems", schema["properties"]["counterpoints"])
        self.assertEqual(schema["$defs"]["Claim"]["properties"]["statement"]["maxLength"], 1500)
        self.assertIn("concede", client.instructions)

    def test_overlong_live_response_never_reaches_judge(self):
        output = copy.deepcopy(self.output)
        output["claims"][0]["statement"] = "x" * 1501

        class Client:
            async def complete_json(self, instructions, payload):
                if "rider_argument" in payload:
                    raise AssertionError("Invalid argument must not reach Judge")
                response = copy.deepcopy(output)
                response["role"] = "rider_advocate" if "rider_advocate" in instructions else "driver_advocate"
                return response, {}

        case = load_case("DISP-002")
        result = run_review(case, policy_for_case(case), ModelAgentBackend(Client()))
        self.assertEqual(result.failure_category, "validation")
        self.assertEqual(result.status, "human_review")
        self.assertFalse(any(entry.actor == "judge" for entry in result.activity_log))
