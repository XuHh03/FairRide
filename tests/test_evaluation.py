"""Evaluation labels stay outside model inputs; live runs require explicit opt-in."""

import os
import unittest

from agents import ExampleAgentBackend
from case_data import load_case, policy_for_case
from checks import no_show_facts, policy_outcome, validate_final_ruling
from evaluation import LABELS, run_single_case
from evidence import build_evidence_index, build_review_input
from workflow import run_review


class EvaluationCasesTests(unittest.TestCase):
    def test_all_cases_build_and_match_v21_examples(self):
        for case_id, label in LABELS.items():
            with self.subTest(case=case_id):
                case = load_case(case_id)
                policy = policy_for_case(case)
                self.assertEqual(len(build_evidence_index(case)), label.evidence_count)
                review = build_review_input(case, policy)
                self.assertEqual(review.policy.version, "2.1")
                if review.dispute_type == "no_show_charge":
                    facts = no_show_facts(case, policy)
                    self.assertEqual(facts["waited_minutes"], label.expected_waited_minutes)
                    self.assertEqual(facts["fee_eligible"], label.expected_fee_eligible)
                result = run_review(case, policy, ExampleAgentBackend())
                self.assertIsNone(result.failure_category)
                actual = result.judge_result.ruling if result.status == "completed" else "human_review"
                self.assertEqual(actual, label.expected_ruling)
                if result.status == "completed":
                    self.assertEqual(validate_final_ruling(case, policy, result.judge_result), [])
                    self.assertEqual(result.judge_result.proposed_action.amount_cents, policy_outcome(case, policy)[1])
                metric = run_single_case(case_id, "example")
                self.assertIn(metric.category, ("correct_ruling", "appropriate_escalation"))


def _live_ready():
    return bool(os.getenv("FAIRRIDE_RUN_LIVE_TESTS") == "1"
                and (os.getenv("FAIRRIDE_API_KEY") or os.getenv("OPENAI_API_KEY"))
                and os.getenv("FAIRRIDE_MODEL"))


@unittest.skipUnless(_live_ready(), "Live tests require credentials and FAIRRIDE_RUN_LIVE_TESTS=1")
class LiveModeEvaluationTests(unittest.TestCase):
    def test_live_cases_match_labels_without_operational_failures(self):
        for case_id in LABELS:
            with self.subTest(case=case_id):
                metric = run_single_case(case_id, "live")
                self.assertIsNone(metric.failure_category)
                self.assertIn(metric.category, ("correct_ruling", "appropriate_escalation"))
