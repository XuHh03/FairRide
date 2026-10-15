import asyncio
import copy
import os
import unittest
from unittest.mock import patch

from agents import AgentCall, ExampleAgentBackend, ModelAgentBackend
from case_data import load_case, policy_for_case
from contracts import AdvocateResult, ArgumentReview, JudgeResult
from evidence import build_review_input
from evaluation import _extract_token_usage
from workflow import run_review


def finding(index=0, section="claims"):
    return {"section": section, "index": index, "verdict": "unsupported", "explanation": "The cited policy requires no refund for a justified, notified and agreed detour.",
            "evidence_ids": ["CHAT-001", "CHAT-002", "TRAFFIC-001"], "policy_ids": ["POLICY-1.3"]}


class ReviewBackend(ExampleAgentBackend):
    def __init__(self, persistent=False):
        super().__init__()
        self.persistent = persistent
        self.review_calls = []
        self.correction_calls = []
        self.judge_arguments = []
        self.wrong = copy.deepcopy(self.examples["DISP-011"]["rider_advocate"])
        self.wrong["claims"][0]["statement"] = "The rider deserves an 83-cent refund despite agreeing to the justified detour."

    async def advocate(self, review, role, question=None):
        if role == "rider_advocate":
            return AgentCall(AdvocateResult.model_validate(self.wrong))
        return await super().advocate(review, role, question)

    async def review_argument(self, review, argument, question=None):
        self.review_calls.append((argument.role, question))
        issues = [finding()] if argument.role == "rider_advocate" and (self.persistent or "83-cent" in argument.claims[0].statement) else []
        return AgentCall(ArgumentReview(findings=issues), usage={"total_tokens": 7})

    async def correct_advocate(self, review, role, feedback, question=None):
        self.correction_calls.append((role, feedback, question))
        output = self.wrong if self.persistent else self.examples[review.case_id][role]
        return AgentCall(AdvocateResult.model_validate(output), usage={"total_tokens": 11})

    async def judge(self, review, rider_argument, driver_argument, rebuttals=None, previous_assessment=None):
        self.judge_arguments.append(rider_argument.model_dump())
        return await super().judge(review, rider_argument, driver_argument, rebuttals, previous_assessment)


class ArgumentReviewTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case("DISP-011")
        self.policy = policy_for_case(self.case)

    def test_live_pipeline_support_check_is_off_by_default_and_explicitly_opt_in(self):
        examples = ExampleAgentBackend().examples["DISP-011"]
        class Client:
            def __init__(self):
                self.reviews = 0
            async def complete_json(self, instructions, payload):
                if "argument" in payload:
                    self.reviews += 1
                    return {"findings": []}, {}
                if "rider_argument" in payload:
                    return examples["judge_final_ruling"], {}
                role = "rider_advocate" if "rider_advocate" in instructions else "driver_advocate"
                return examples[role], {}
        for flag, count in (("", 0), ("1", 2)):
            with self.subTest(flag=flag), patch.dict(os.environ, {"FAIRRIDE_CHECK_ARGUMENT_SUPPORT": flag}):
                client = Client()
                result = run_review(self.case, self.policy, ModelAgentBackend(client))
                self.assertEqual(result.status, "completed")
                self.assertEqual(client.reviews, count)

    def test_unsupported_argument_is_corrected_and_checked_before_judge(self):
        backend = ReviewBackend()
        updates = []
        result = run_review(self.case, self.policy, backend, on_progress=updates.append)
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(backend.correction_calls), 1)
        self.assertEqual(sum(role == "rider_advocate" for role, _ in backend.review_calls), 2)
        self.assertNotIn("83-cent", backend.judge_arguments[0]["claims"][0]["statement"])
        feedback = backend.correction_calls[0][1]
        self.assertEqual(feedback["previous_response"], AdvocateResult.model_validate(backend.wrong).model_dump(mode="json"))
        self.assertEqual(feedback["findings"], [finding()])
        events = [entry for entry in result.activity_log if entry.actor == "rider_advocate"]
        self.assertIn("83-cent", events[0].output["result"]["claims"][0]["statement"])
        self.assertTrue(any(e.event == "argument_correction" for e in events))
        self.assertTrue(any("checking argument support" in stage for stage in updates))
        self.assertEqual(sum(e.output.get("usage", {}).get("total_tokens", 0) for e in result.activity_log), 32)
        self.assertEqual(_extract_token_usage(result.activity_log), (32, 0, 32))

    def test_persistent_unsupported_argument_is_visible_failure_and_never_reaches_judge(self):
        backend = ReviewBackend(persistent=True)
        result = run_review(self.case, self.policy, backend)
        self.assertEqual(result.failure_category, "validation")
        self.assertIsNone(result.final_explanation)
        self.assertEqual(backend.judge_arguments, [])
        self.assertEqual(len(backend.correction_calls), 1)
        self.assertTrue(any("support review failed" in issue for issue in result.validation_issues))
        audits = [e for e in result.activity_log if e.event == "argument_support_review"]
        self.assertTrue(any(e.output["findings"] for e in audits))

    def test_invalid_finding_location_or_reference_is_rejected_without_rewriting(self):
        for item in (finding(index=99), {**finding(), "evidence_ids": ["GPS-999"]}):
            with self.subTest(item=item):
                class InvalidReviewBackend(ReviewBackend):
                    async def review_argument(self, *args, **kwargs):
                        return AgentCall(ArgumentReview(findings=[item]), usage={"total_tokens": 7})
                backend = InvalidReviewBackend()
                result = run_review(self.case, self.policy, backend)
                self.assertEqual(result.failure_category, "validation")
                self.assertFalse(backend.correction_calls)
                self.assertFalse(backend.judge_arguments)
                audits = [e for e in result.activity_log if e.event == "argument_support_review"]
                self.assertTrue(audits)
                self.assertEqual(audits[0].output["findings"], [item])
                self.assertEqual(audits[0].output["usage"]["total_tokens"], 7)
                self.assertTrue(any(e.output.get("support_status") == "review_failed" for e in result.activity_log))

    def test_supported_assessment_does_not_trigger_correction(self):
        class SupportedReviewBackend(ReviewBackend):
            async def advocate(self, review, role, question=None):
                return await ExampleAgentBackend.advocate(self, review, role, question)
            async def review_argument(self, review, argument, question=None):
                return AgentCall(ArgumentReview(findings=[{**finding(), "verdict": "supported", "explanation": "This statement correctly applies the supplied rule."}]))
        backend = SupportedReviewBackend()
        result = run_review(self.case, self.policy, backend)
        self.assertEqual(result.status, "completed")
        self.assertFalse(backend.correction_calls)

    def test_rebuttal_support_correction_preserves_judge_question_and_round_budget(self):
        question = "Did the rider agree to the justified detour?"
        class RebuttalBackend(ReviewBackend):
            def __init__(self):
                super().__init__()
                self.judge_calls = 0
            async def judge(self, review, rider_argument, driver_argument, rebuttals=None, previous_assessment=None):
                self.judge_calls += 1
                if self.judge_calls == 1:
                    return AgentCall(JudgeResult(action="request_rebuttal", question=question,
                        rebuttal_roles=["rider_advocate"], explanation="Clarify the rider's agreement."))
                self.prior = previous_assessment
                return await super().judge(review, rider_argument, driver_argument, rebuttals, previous_assessment)
        backend = RebuttalBackend()
        result = run_review(self.case, self.policy, backend)
        self.assertEqual(result.status, "completed")
        self.assertEqual(backend.judge_calls, 2)
        self.assertEqual(backend.prior.question, question)
        self.assertEqual(len(backend.correction_calls), 2)
        self.assertEqual(backend.correction_calls[-1][2], question)
        self.assertEqual(sum(e.event == "rebuttal" for e in result.activity_log), 1)

    def test_corrected_argument_cannot_change_its_assigned_role(self):
        class WrongRoleBackend(ReviewBackend):
            async def correct_advocate(self, review, role, feedback, question=None):
                return AgentCall(AdvocateResult.model_validate(self.examples[review.case_id]["driver_advocate"]))
        backend = WrongRoleBackend()
        result = run_review(self.case, self.policy, backend)
        self.assertEqual(result.failure_category, "validation")
        self.assertFalse(backend.judge_arguments)
        self.assertTrue(any("wrong role" in issue for issue in result.validation_issues))

    def test_overlong_support_explanation_gets_one_schema_repair(self):
        responses = [{"findings": [{**finding(), "explanation": "x" * 1501}]}, {"findings": [finding()]}]
        class Client:
            def __init__(self):
                self.payloads = []
            async def complete_json(self, instructions, payload):
                self.payloads.append(payload)
                return responses[len(self.payloads) - 1], {"total_tokens": 5}
        client = Client()
        review = build_review_input(self.case, self.policy)
        call = asyncio.run(ModelAgentBackend(client).review_argument(review, AdvocateResult.model_validate(ReviewBackend().wrong)))
        self.assertEqual(call.schema_retries, 1)
        self.assertEqual(call.usage["total_tokens"], 10)
        self.assertEqual(len(client.payloads), 2)

    def test_live_support_review_uses_sources_facts_and_strict_schema(self):
        class Client:
            async def complete_json(self, instructions, payload):
                self.payload = payload
                self.instructions = instructions
                return {"findings": [finding()]}, {"total_tokens": 5}
        review = build_review_input(self.case, self.policy)
        argument = AdvocateResult.model_validate(ReviewBackend().wrong)
        client = Client()
        call = asyncio.run(ModelAgentBackend(client).review_argument(review, argument, "Was the rider informed?"))
        self.assertEqual(call.result.findings[0].index, 0)
        self.assertEqual(client.payload["argument"], argument.model_dump(mode="json"))
        self.assertEqual(client.payload["follow_up_question"], "Was the rider informed?")
        self.assertTrue(client.payload["review"]["facts"])
        self.assertNotIn("expected_ruling", client.payload)
        self.assertIn("findings", client.payload["output_schema"]["required"])

    def test_empty_or_malformed_support_response_fails_closed(self):
        class Client:
            async def complete_json(self, *args):
                return {}, {}
        review = build_review_input(self.case, self.policy)
        with self.assertRaises(ValueError):
            asyncio.run(ModelAgentBackend(Client()).review_argument(review, AdvocateResult.model_validate(ReviewBackend().wrong)))
