import asyncio
import unittest

from agents import AgentCall, ExampleAgentBackend, ModelAgentBackend
from case_data import load_case, policy_for_case
from contracts import JudgeResult
from evidence import build_review_input
from workflow import run_review


class JudgeContextTests(unittest.TestCase):
    def test_workflow_passes_original_assessment_to_second_judge(self):
        class CaptureBackend(ExampleAgentBackend):
            def __init__(self):
                super().__init__()
                self.prior = None

            async def judge(self, review, rider_argument, driver_argument, rebuttals=None, previous_assessment=None):
                if rebuttals is not None:
                    self.prior = previous_assessment
                return await super().judge(review, rider_argument, driver_argument, rebuttals, previous_assessment)

        backend = CaptureBackend()
        case = load_case("DISP-012")
        result = run_review(case, policy_for_case(case), backend)
        self.assertIsNone(result.failure_category)
        self.assertEqual(backend.prior.question, backend.examples["DISP-012"]["judge_rebuttal"]["question"])

    def test_model_payload_has_prior_question_and_exhausted_budget(self):
        class CaptureClient:
            async def complete_json(self, instructions, payload):
                self.payload = payload
                return {"action": "human_review", "explanation": "The question remains unresolved."}, {}

        async def exercise():
            case = load_case("DISP-012")
            review = build_review_input(case, policy_for_case(case))
            example = ExampleAgentBackend()
            rider = (await example.advocate(review, "rider_advocate")).result
            driver = (await example.advocate(review, "driver_advocate")).result
            prior = JudgeResult.model_validate(example.examples["DISP-012"]["judge_rebuttal"])
            client = CaptureClient()
            await ModelAgentBackend(client).judge(review, rider, driver, [rider, driver], prior)
            self.assertEqual(client.payload["previous_assessment"]["question"], prior.question)
            self.assertTrue(client.payload["rebuttal_round_complete"])
            self.assertEqual(len(client.payload["rebuttals"]), 2)
        asyncio.run(exercise())
