import io
import os
import unittest
from unittest.mock import patch

from agents import AgentCall, ExampleAgentBackend
from contracts import JudgeResult
from evaluation import LABELS, print_report, run_single_case, summarize
from workflow import run_review


class DecisionBackend(ExampleAgentBackend):
    def __init__(self, decision=None, error=None):
        super().__init__()
        self.decision = decision
        self.error = error

    async def judge(self, review, rider_argument, driver_argument, rebuttals=None):
        if self.error:
            raise self.error
        return AgentCall(JudgeResult.model_validate(self.decision))


class EvaluationScoringTests(unittest.TestCase):
    def score(self, case_id, backend):
        def review(case, policy, ignored_backend):
            return run_review(case, policy, backend)
        with patch("evaluation.run_review", side_effect=review):
            return run_single_case(case_id, "example")

    def escalate(self, case_id):
        return self.score(case_id, DecisionBackend({
            "action": "human_review", "explanation": "The records need further review.",
        }))

    def test_clear_case_labels_do_not_accept_human_review(self):
        self.assertEqual(LABELS["DISP-002"].expected_ruling, "human_review")
        for case_id, label in LABELS.items():
            if case_id != "DISP-002":
                self.assertNotIn("human_review", label.acceptable_alternatives)

    def test_correct_refund_is_an_autonomous_resolution(self):
        metric = run_single_case("DISP-003", "example")
        self.assertEqual(metric.category, "correct_ruling")
        self.assertTrue(metric.ruling_match)
        summary = summarize([metric], "example")
        self.assertEqual(summary.autonomous_resolution_rate, 1)
        self.assertEqual(summary.ruling_accuracy, 1)

    def test_clear_case_escalation_is_not_a_matching_ruling(self):
        metric = self.escalate("DISP-003")
        self.assertEqual(metric.category, "unnecessary_escalation")
        self.assertFalse(metric.ruling_match)
        self.assertIsNone(metric.amount_correct)
        self.assertEqual(summarize([metric], "example").unnecessary_escalation_rate, 1)

    def test_ambiguous_case_escalation_is_appropriate_but_not_autonomous(self):
        metric = run_single_case("DISP-002", "example")
        self.assertEqual(metric.category, "appropriate_escalation")
        self.assertFalse(metric.ruling_match)
        summary = summarize([metric], "example")
        self.assertEqual(summary.autonomous_resolution_rate, 0)
        self.assertIsNone(summary.ruling_accuracy)

    def test_missing_credentials_are_operational_failure_even_for_ambiguous_case(self):
        with patch.dict(os.environ, {}, clear=True):
            metric = run_single_case("DISP-002", "live")
        self.assertEqual(metric.failure_category, "setup")
        self.assertEqual(metric.category, "operational_failure")
        self.assertFalse(metric.ruling_match)

    def test_model_and_schema_failures_have_explicit_categories(self):
        for error, expected in [(RuntimeError("Provider unavailable"), "model"),
                                (ValueError("Invalid response"), "validation")]:
            with self.subTest(category=expected):
                metric = self.score("DISP-003", DecisionBackend(error=error))
                self.assertEqual(metric.failure_category, expected)
                self.assertEqual(metric.category, "operational_failure")

    def test_unknown_citation_is_a_validation_failure(self):
        metric = self.score("DISP-003", DecisionBackend({
            "action": "human_review", "explanation": "Unknown record cited.",
            "evidence_ids": ["GPS-999"],
        }))
        self.assertEqual(metric.failure_category, "validation")
        self.assertEqual(metric.category, "operational_failure")

    def test_wrong_valid_final_ruling_reduces_accuracy(self):
        metric = self.score("DISP-004", DecisionBackend({
            "action": "final_ruling", "ruling": "reverse_charge",
            "proposed_action": {"amount_cents": 500},
            "explanation": "Incorrect full refund despite valid wait.",
            "evidence_ids": ["TRIP-001"], "policy_ids": ["POLICY-003"],
        }))
        self.assertEqual(metric.category, "incorrect_ruling")
        summary = summarize([metric], "example")
        self.assertEqual(summary.autonomous_resolution_rate, 1)
        self.assertEqual(summary.ruling_accuracy, 0)

    def test_invalid_refund_is_a_validation_failure(self):
        metric = self.score("DISP-003", DecisionBackend({
            "action": "final_ruling", "ruling": "reverse_charge",
            "proposed_action": {"amount_cents": 400},
            "explanation": "Refund the charge.", "evidence_ids": ["TRIP-001"],
            "policy_ids": ["POLICY-003"],
        }))
        self.assertEqual(metric.failure_category, "validation")
        self.assertEqual(metric.category, "operational_failure")

    def test_all_failed_reviews_have_zero_resolution_and_na_accuracy(self):
        with patch.dict(os.environ, {}, clear=True):
            metrics = [run_single_case(cid, "live") for cid in LABELS]
        summary = summarize(metrics, "live")
        self.assertEqual(summary.operational_failure_rate, 1)
        self.assertEqual(summary.autonomous_resolution_rate, 0)
        self.assertIsNone(summary.ruling_accuracy)
        self.assertEqual(summary.abstentions, 0)
        self.assertEqual(summary.amount_errors, 0)
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            print_report(metrics, [summary])
        self.assertIn("N/A", output.getvalue())

    def test_mixed_summary_uses_separate_denominators(self):
        with patch.dict(os.environ, {}, clear=True):
            failure = run_single_case("DISP-004", "live")
        metrics = [run_single_case("DISP-003", "example"),
                   self.escalate("DISP-004"),
                   run_single_case("DISP-002", "example"), failure]
        summary = summarize(metrics, "example")
        self.assertEqual(summary.autonomous_resolution_rate, 0.25)
        self.assertEqual(summary.ruling_accuracy, 1)
        self.assertEqual(summary.operational_failure_rate, 0.25)
        self.assertAlmostEqual(summary.unnecessary_escalation_rate, 1 / 3)

    def test_empty_summary_has_na_accuracy(self):
        self.assertIsNone(summarize([], "example").ruling_accuracy)
