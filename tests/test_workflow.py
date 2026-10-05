import asyncio
import copy
import json
import unittest
from io import BytesIO
from unittest.mock import patch

from agents import AgentCall, ChatClient, ExampleAgentBackend, ModelConfig
from case_data import load_case, load_policy
from contracts import AdvocateResult, JudgeResult
from workflow import run_review, run_review_async


def resolvable_case() -> dict:
    case = copy.deepcopy(load_case("DISP-002"))
    case["trip_data"]["pickup_location"]["designated_entrance"] = "Main lobby entrance"
    event = next(item for item in case["app_events"] if item["id"] == "EVENT-008")
    event["details"] = "The five-minute free wait period expired; no-show threshold has not yet been reached."
    return case


class FixedJudgeBackend(ExampleAgentBackend):
    def __init__(self, decision: dict):
        super().__init__()
        self.decision = decision
        self.judge_calls = 0

    async def judge(self, review, rider_argument, driver_argument, rebuttals=None):
        self.judge_calls += 1
        return AgentCall(JudgeResult.model_validate(self.decision))


def final_decision(ruling="uphold_charge", amount=0):
    return {
        "action": "final_ruling", "ruling": ruling,
        "proposed_action": {"amount_cents": amount, "currency": "SGD"},
        "explanation": "Proposed sample-policy result based on the recorded trip and threshold.",
        "evidence_ids": ["TRIP-001", "GPS-005"],
        "policy_ids": ["POLICY-001", "POLICY-003", "POLICY-004"],
    }


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case("DISP-002")
        self.policy = load_policy("sample_no_show")

    def test_example_walkthrough_reaches_human_review_after_one_rebuttal(self):
        result = run_review(self.case, self.policy, ExampleAgentBackend())
        self.assertEqual(result.status, "human_review")
        self.assertEqual(result.judge_result.action, "human_review")
        self.assertEqual(sum(entry.event == "rebuttal" for entry in result.activity_log), 2)
        self.assertEqual(sum(entry.actor == "judge" for entry in result.activity_log), 2)
        self.assertTrue(any("EVENT-008" in issue for issue in result.validation_issues))
        self.assertTrue(any("entrance" in issue for issue in result.validation_issues))
        self.assertTrue(any("wall_duration_ms" in entry.output for entry in result.activity_log))

    def test_unsupported_final_ruling_is_referred_to_human(self):
        result = run_review(self.case, self.policy, FixedJudgeBackend(final_decision()))
        self.assertEqual(result.status, "human_review")
        self.assertTrue(result.validation_issues)
        self.assertEqual(result.judge_result.action, "human_review")

    def test_valid_synthetic_final_ruling_and_amount_check(self):
        case = resolvable_case()
        result = run_review(case, self.policy, FixedJudgeBackend(final_decision()))
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.validation_issues, [])
        wrong = run_review(case, self.policy, FixedJudgeBackend(final_decision("reverse_charge", 400)))
        self.assertEqual(wrong.status, "human_review")
        self.assertTrue(any("Full reversal" in issue for issue in wrong.validation_issues))

    def test_second_rebuttal_request_is_stopped(self):
        backend = FixedJudgeBackend(ExampleAgentBackend().examples["judge_rebuttal"])
        result = run_review(self.case, self.policy, backend)
        self.assertEqual(backend.judge_calls, 2)
        self.assertEqual(result.status, "human_review")
        self.assertIn("Judge requested a second rebuttal round", result.validation_issues)

    def test_unknown_citation_is_referred_to_human(self):
        class BadCitationBackend(FixedJudgeBackend):
            async def advocate(self, review, role, question=None):
                call = await super().advocate(review, role, question)
                output = call.result.model_dump()
                output["claims"][0]["evidence_ids"] = ["GPS-999"]
                return AgentCall(AdvocateResult.model_validate(output))

        result = run_review(self.case, self.policy, BadCitationBackend(final_decision()))
        self.assertEqual(result.status, "human_review")
        self.assertTrue(any("GPS-999" in issue for issue in result.validation_issues))

    def test_independent_advocates_run_concurrently(self):
        class BarrierBackend(FixedJudgeBackend):
            def __init__(self):
                super().__init__(final_decision())
                self.started = 0
                self.both_started = asyncio.Event()

            async def advocate(self, review, role, question=None):
                self.started += 1
                if self.started == 2:
                    self.both_started.set()
                await asyncio.wait_for(self.both_started.wait(), timeout=0.5)
                return await super().advocate(review, role, question)

        backend = BarrierBackend()
        result = asyncio.run(run_review_async(resolvable_case(), self.policy, backend))
        self.assertEqual(result.status, "completed")
        self.assertEqual(backend.started, 2)

    def test_live_client_request_shape_and_usage_without_network(self):
        response = {"choices": [{"message": {"content": '{"ok": true}'}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}
        client = ChatClient(ModelConfig(api_key="test-secret", model="test-model", base_url="https://example.test/v1"))

        def fake_urlopen(req, timeout):
            self.assertEqual(req.full_url, "https://example.test/v1/chat/completions")
            self.assertEqual(timeout, 45)
            body = json.loads(req.data)
            self.assertEqual(body["model"], "test-model")
            self.assertEqual(body["response_format"], {"type": "json_object"})
            self.assertEqual(body["messages"][1]["role"], "user")
            return BytesIO(json.dumps(response).encode())

        with patch("agents.request.urlopen", side_effect=fake_urlopen):
            output, usage = client._complete_json("Return JSON", {"case": "DISP-002"})
        self.assertEqual(output, {"ok": True})
        self.assertEqual(usage["total_tokens"], 5)


if __name__ == "__main__":
    unittest.main()
