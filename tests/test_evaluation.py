"""Evaluation labels stay outside model inputs; live runs require explicit opt-in."""

import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agents import ExampleAgentBackend
from case_data import load_case, policy_for_case
from checks import no_show_facts, validate_final_ruling
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
                    self.assertEqual(result.judge_result.proposed_action.amount_cents, label.expected_refund_cents)
                    self.assertEqual(result.judge_result.proposed_action.goodwill_credit_cents, label.expected_goodwill_credit_cents)
                    self.assertEqual(result.judge_result.proposed_action.refund_basis, label.expected_refund_basis)
                metric = run_single_case(case_id, "example")
                self.assertIn(metric.category, ("correct_ruling", "appropriate_escalation"))


def _live_ready():
    return bool(os.getenv("FAIRRIDE_RUN_LIVE_TESTS") == "1"
                and (os.getenv("FAIRRIDE_API_KEY") or os.getenv("OPENAI_API_KEY"))
                and os.getenv("FAIRRIDE_MODEL"))


@unittest.skipUnless(_live_ready(), "Live tests require credentials and FAIRRIDE_RUN_LIVE_TESTS=1")
class LiveModeEvaluationTests(unittest.TestCase):
    def test_live_cases_match_labels_without_operational_failures(self):
        for number, (case_id, label) in enumerate(LABELS.items(), 1):
            prefix = f"[{number}/{len(LABELS)}] {case_id}"
            print(f"\n{prefix}: Starting (expected {label.expected_ruling})", flush=True)
            with self.subTest(case=case_id):
                metric = run_single_case(case_id, "live", on_progress=lambda message: print(f"  {case_id}: {message}", flush=True))
                refund = f"SGD {metric.amount_cents / 100:.2f}" if metric.amount_cents is not None else "n/a"
                summary = f"ruling={metric.ruling}, refund={refund}, {metric.wall_duration_ms:.0f} ms, {metric.total_tokens} tokens"
                try:
                    self.assertIsNone(metric.failure_category)
                    self.assertIn(metric.category, ("correct_ruling", "appropriate_escalation"))
                    self.assertEqual(metric.ruling, label.expected_ruling)
                    if label.expected_ruling != "human_review":
                        self.assertTrue(metric.ruling_match)
                        self.assertTrue(metric.amount_correct)
                except AssertionError:
                    print(f"{prefix}: FAIL — {summary}", flush=True)
                    for issue in metric.validation_issues:
                        print(f"  {issue}", flush=True)
                    raise
                else:
                    print(f"{prefix}: PASS — {summary}", flush=True)


class LiveRegressionHarnessTests(unittest.TestCase):
    def test_live_regression_rejects_referrals_on_clear_cases(self):
        metric = SimpleNamespace(failure_category=None, category="appropriate_escalation", ruling="human_review", amount_correct=None,
                                 amount_cents=None, total_tokens=0, wall_duration_ms=0, validation_issues=[])
        result = unittest.TestResult()
        with patch.object(LiveModeEvaluationTests, "__unittest_skip__", False, create=True), patch("test_evaluation.run_single_case", return_value=metric), patch("sys.stdout", new_callable=io.StringIO):
            LiveModeEvaluationTests("test_live_cases_match_labels_without_operational_failures").run(result)
        self.assertEqual(len(result.failures), 7)
        self.assertEqual(result.errors, [])

    def test_fixed_refund_oracle_does_not_reuse_application_calculation(self):
        case = load_case("DISP-010")
        result = run_review(case, policy_for_case(case), ExampleAgentBackend())
        result.judge_result.proposed_action.amount_cents = 110
        with patch("evaluation.run_review", return_value=result), patch("evaluation.policy_outcome", return_value=("partial_refund", 110, 0, "excess_distance_fare"), create=True):
            metric = run_single_case("DISP-010", "live")
        self.assertEqual(metric.category, "incorrect_ruling")
        self.assertFalse(metric.amount_correct)

    def test_evaluation_forwards_progress_during_review(self):
        updates = []
        metric = run_single_case("DISP-003", "example", on_progress=updates.append)
        self.assertEqual(metric.category, "correct_ruling")
        self.assertIn("Preparing evidence", updates[0])
        self.assertEqual(updates[-1], "Review complete")

    def test_live_test_prints_case_and_stage_progress_without_paid_calls(self):
        def evaluate(case_id, mode, *, on_progress):
            on_progress("Preparing evidence")
            on_progress("Judge is reviewing initial arguments")
            label = LABELS[case_id]
            clear = label.expected_ruling != "human_review"
            return SimpleNamespace(failure_category=None, category="correct_ruling" if clear else "appropriate_escalation",
                ruling=label.expected_ruling, ruling_match=clear, amount_correct=True if clear else None,
                amount_cents=label.expected_refund_cents, total_tokens=5, wall_duration_ms=10, validation_issues=[])

        result = unittest.TestResult()
        with patch.object(LiveModeEvaluationTests, "__unittest_skip__", False, create=True), patch("test_evaluation.run_single_case", side_effect=evaluate), patch("sys.stdout", new_callable=io.StringIO) as output:
            LiveModeEvaluationTests("test_live_cases_match_labels_without_operational_failures").run(result)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])
        text = output.getvalue()
        self.assertIn("[1/11] DISP-002: Starting", text)
        self.assertIn("DISP-002: Judge is reviewing initial arguments", text)
        self.assertIn("[11/11] DISP-012: PASS", text)
        self.assertLess(text.index("DISP-002: Preparing evidence"), text.index("[1/11] DISP-002: PASS"))
