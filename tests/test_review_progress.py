import unittest

from agents import ExampleAgentBackend
from case_data import load_case, policy_for_case
from workflow import run_review


class ReviewProgressTests(unittest.TestCase):
    def review(self, case_id, backend=None):
        case = load_case(case_id)
        updates = []
        result = run_review(case, policy_for_case(case), backend or ExampleAgentBackend(), on_progress=updates.append)
        return result, updates

    def test_stage_is_reported_before_agent_work_starts(self):
        updates = []
        test = self

        class Backend(ExampleAgentBackend):
            async def advocate(self, review, role, question=None):
                test.assertTrue(any("Advocates are analyzing" in text for text in updates))
                return await super().advocate(review, role, question)

            async def judge(self, review, rider_argument, driver_argument, rebuttals=None, previous_assessment=None):
                test.assertIn("Judge is reviewing initial arguments", updates[-1])
                return await super().judge(review, rider_argument, driver_argument, rebuttals, previous_assessment)

        case = load_case("DISP-003")
        result = run_review(case, policy_for_case(case), Backend(), on_progress=updates.append)
        self.assertEqual(result.status, "completed")
        self.assertIn("Preparing evidence", updates[0])
        self.assertTrue(any("Finalizing" in text for text in updates))
        self.assertEqual(updates[-1], "Review complete")

    def test_rebuttal_and_second_judge_are_visible_in_order(self):
        result, updates = self.review("DISP-012")
        initial = updates.index("Judge is reviewing initial arguments")
        rebuttal = updates.index("Advocates are answering the Judge's follow-up question")
        final = updates.index("Judge is reviewing rebuttals")
        self.assertLess(initial, rebuttal)
        self.assertLess(rebuttal, final)
        self.assertEqual(result.status, "human_review")
        self.assertEqual(updates[-1], "Review finished: human review required")

    def test_mandatory_referral_does_not_show_agent_stages(self):
        result, updates = self.review("DISP-005")
        self.assertTrue(result.mandatory_escalation)
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[-1], "Human review required by policy")

    def test_failure_finishes_progress_instead_of_staying_on_advocates(self):
        class Backend(ExampleAgentBackend):
            async def advocate(self, review, role, question=None):
                raise RuntimeError("Model unavailable")

        result, updates = self.review("DISP-003", Backend())
        self.assertEqual(result.failure_category, "model")
        self.assertEqual(updates[-1], "Agent review failed; human review required")
