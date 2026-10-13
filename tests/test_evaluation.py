"""Evaluation labels and end-to-end tests for no-show cases.

Each no-show case has a human-labelled expected ruling. These tests verify
that derived facts match the label, that the evidence system builds cleanly,
and that the example-mode workflow produces a valid result for each case.

In live mode (FAIRRIDE_API_KEY + FAIRRIDE_MODEL set), the same tests run
against the real model and check that the Judge's ruling matches the label.
Live tests are skipped when no API key is configured.

Labels are imported from evaluation.py to avoid duplication.
"""

import os
import unittest

from case_data import load_case, load_policy, policy_for_case
from checks import no_show_facts, route_deviation_facts, validate_final_ruling, charged_cents, material_case_issues
from contracts import JudgeResult, ProposedAction
from evidence import build_evidence_index, build_review_input
from workflow import run_review
from agents import ExampleAgentBackend
from evaluation import CaseLabel, LABELS


def _policy_for_case(case: dict) -> dict:
    """Load the appropriate policy based on dispute type."""
    return policy_for_case(case)


# ---------------------------------------------------------------------------
# Fact verification tests (no model calls, deterministic)
# ---------------------------------------------------------------------------

class FactLabelTests(unittest.TestCase):
    """Verify that computed derived facts match the human labels."""

    def setUp(self):
        self.policy = load_policy("sample_no_show")

    def _run_case(self, label: CaseLabel):
        case = load_case(label.case_id)
        facts = no_show_facts(case, self.policy)
        self.assertAlmostEqual(
            facts["waited_minutes"], label.expected_waited_minutes,
            places=1,
            msg=f"{label.case_id}: waited_minutes mismatch",
        )
        self.assertEqual(
            facts["fee_eligible"], label.expected_fee_eligible,
            msg=f"{label.case_id}: fee_eligible mismatch",
        )

    def test_disp_002_facts_match_label(self):
        self._run_case(LABELS["DISP-002"])

    def test_disp_003_facts_match_label(self):
        self._run_case(LABELS["DISP-003"])

    def test_disp_004_facts_match_label(self):
        self._run_case(LABELS["DISP-004"])

    def test_disp_007_facts_match_label(self):
        self._run_case(LABELS["DISP-007"])


# ---------------------------------------------------------------------------
# Evidence system tests (no model calls, deterministic)
# ---------------------------------------------------------------------------

class EvidenceSystemTests(unittest.TestCase):
    """Verify that each case builds cleanly through the evidence pipeline."""

    def setUp(self):
        self.policy = load_policy("sample_no_show")

    def _run_case(self, label: CaseLabel):
        case = load_case(label.case_id)
        evidence = build_evidence_index(case)
        self.assertEqual(
            len(evidence), label.evidence_count,
            msg=f"{label.case_id}: evidence count mismatch",
        )
        review = build_review_input(case, self.policy)
        self.assertEqual(review.case_id, label.case_id)
        self.assertEqual(len(review.evidence), label.evidence_count)
        self.assertGreater(len(review.facts), 0)

    def test_disp_002_evidence_builds(self):
        self._run_case(LABELS["DISP-002"])

    def test_disp_003_evidence_builds(self):
        self._run_case(LABELS["DISP-003"])

    def test_disp_004_evidence_builds(self):
        self._run_case(LABELS["DISP-004"])

    def test_disp_007_evidence_builds(self):
        self._run_case(LABELS["DISP-007"])


# ---------------------------------------------------------------------------
# Route deviation fact tests (no model calls, deterministic)
# ---------------------------------------------------------------------------

class RouteDeviationTests(unittest.TestCase):
    """Verify route deviation derived facts and evidence."""

    def test_disp_005_facts_match_label(self):
        case = load_case("DISP-005")
        policy = _policy_for_case(case)
        facts = route_deviation_facts(case, policy)
        self.assertAlmostEqual(facts["planned_distance_km"], 18.5, places=1)
        self.assertAlmostEqual(facts["actual_distance_km"], 25.2, places=1)
        self.assertAlmostEqual(facts["deviation_pct"], 36.2, places=1)
        self.assertTrue(facts["deviation_significant"])
        self.assertEqual(facts["fare_difference_cents"], 693)

    def test_disp_005_evidence_builds(self):
        case = load_case("DISP-005")
        policy = _policy_for_case(case)
        evidence = build_evidence_index(case)
        self.assertEqual(len(evidence), LABELS["DISP-005"].evidence_count)
        review = build_review_input(case, policy)
        self.assertEqual(review.case_id, "DISP-005")
        self.assertEqual(review.dispute_type, "route_deviation")
        self.assertEqual(len(review.evidence), LABELS["DISP-005"].evidence_count)
        self.assertGreater(len(review.facts), 0)

    def test_disp_006_facts_match_label(self):
        """HELD-OUT: Below-threshold route deviation (12.1% < 15%)."""
        case = load_case("DISP-006")
        policy = _policy_for_case(case)
        facts = route_deviation_facts(case, policy)
        self.assertAlmostEqual(facts["planned_distance_km"], 16.5, places=1)
        self.assertAlmostEqual(facts["actual_distance_km"], 18.5, places=1)
        self.assertAlmostEqual(facts["deviation_pct"], 12.1, places=1)
        self.assertFalse(facts["deviation_significant"])
        self.assertEqual(facts["fare_difference_cents"], 360)

    def test_disp_006_evidence_builds(self):
        """HELD-OUT: Verify evidence system builds for below-threshold case."""
        case = load_case("DISP-006")
        policy = _policy_for_case(case)
        evidence = build_evidence_index(case)
        self.assertEqual(len(evidence), LABELS["DISP-006"].evidence_count)
        review = build_review_input(case, policy)
        self.assertEqual(review.case_id, "DISP-006")
        self.assertEqual(review.dispute_type, "route_deviation")
        self.assertEqual(len(review.evidence), LABELS["DISP-006"].evidence_count)
        self.assertGreater(len(review.facts), 0)


# ---------------------------------------------------------------------------
# Example-mode end-to-end tests (deterministic, no API needed)
# ---------------------------------------------------------------------------

class ExampleModeEvaluationTests(unittest.TestCase):
    """Run the full workflow with ExampleAgentBackend for each case."""

    def setUp(self):
        self.policy = load_policy("sample_no_show")
        self.backend = ExampleAgentBackend()

    def _run_case(self, label: CaseLabel):
        case = load_case(label.case_id)
        result = run_review(case, self.policy, self.backend)
        self.assertEqual(result.case_id, label.case_id)
        self.assertIn(result.status, ("completed", "human_review"))
        # Activity log should have at least system + 2 advocates + judge
        actors = {entry.actor for entry in result.activity_log}
        self.assertIn("rider_advocate", actors)
        self.assertIn("driver_advocate", actors)
        self.assertIn("judge", actors)

    def test_disp_002_example_run(self):
        self._run_case(LABELS["DISP-002"])

    def test_disp_003_example_run(self):
        """DISP-003 example should complete with reverse_charge."""
        case = load_case("DISP-003")
        result = run_review(case, self.policy, self.backend)
        self.assertEqual(result.case_id, "DISP-003")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.judge_result.action, "final_ruling")
        self.assertEqual(result.judge_result.ruling, "reverse_charge")
        self.assertEqual(result.judge_result.proposed_action.amount_cents, 500)

    def test_disp_004_example_run(self):
        """DISP-004 example should complete with uphold_charge."""
        case = load_case("DISP-004")
        result = run_review(case, self.policy, self.backend)
        self.assertEqual(result.case_id, "DISP-004")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.judge_result.action, "final_ruling")
        self.assertEqual(result.judge_result.ruling, "uphold_charge")
        self.assertEqual(result.judge_result.proposed_action.amount_cents, 0)

    def test_disp_005_example_run(self):
        """DISP-005 example should complete with partial_refund."""
        case = load_case("DISP-005")
        policy = _policy_for_case(case)
        result = run_review(case, policy, self.backend)
        self.assertEqual(result.case_id, "DISP-005")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.judge_result.action, "final_ruling")
        self.assertEqual(result.judge_result.ruling, "partial_refund")
        self.assertEqual(result.judge_result.proposed_action.amount_cents, 693)

    def test_disp_006_example_run(self):
        """HELD-OUT: DISP-006 example should complete with uphold_charge (below threshold)."""
        case = load_case("DISP-006")
        policy = _policy_for_case(case)
        result = run_review(case, policy, self.backend)
        self.assertEqual(result.case_id, "DISP-006")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.judge_result.action, "final_ruling")
        self.assertEqual(result.judge_result.ruling, "uphold_charge")
        self.assertEqual(result.judge_result.proposed_action.amount_cents, 0)

    def test_disp_007_example_run(self):
        """HELD-OUT: DISP-007 example should complete with reverse_charge ($5 = 500c)."""
        case = load_case("DISP-007")
        result = run_review(case, self.policy, self.backend)
        self.assertEqual(result.case_id, "DISP-007")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.judge_result.action, "final_ruling")
        self.assertEqual(result.judge_result.ruling, "reverse_charge")
        self.assertEqual(result.judge_result.proposed_action.amount_cents, 500)


# ---------------------------------------------------------------------------
# Live-mode evaluation tests (require API key, may be non-deterministic)
# ---------------------------------------------------------------------------

def _live_ready() -> bool:
    """Check if live model credentials are configured."""
    key = os.getenv("FAIRRIDE_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = os.getenv("FAIRRIDE_MODEL")
    return bool(key and model and os.getenv("FAIRRIDE_RUN_LIVE_TESTS") == "1")


@unittest.skipUnless(_live_ready(), "Live tests require credentials and FAIRRIDE_RUN_LIVE_TESTS=1")
class LiveModeEvaluationTests(unittest.TestCase):
    """Run the full workflow against the live API and compare to labels.

    These tests are non-deterministic. They assert that the Judge produces
    a final_ruling whose ruling matches the human label (or an acceptable
    alternative). A mismatch does not necessarily indicate a bug — it may
    indicate a model reasoning difference that warrants investigation.
    """

    def _run_case(self, label: CaseLabel):
        case = load_case(label.case_id)
        policy = _policy_for_case(case)
        result = run_review(case, policy)  # backend=None → ModelAgentBackend
        self.assertEqual(result.case_id, label.case_id)
        self.assertIsNone(result.failure_category, msg=str(result.validation_issues))

        # If the pipeline routed to human_review, check if it's acceptable
        if result.status == "human_review":
            if label.expected_ruling == "human_review":
                return
            self.fail(
                f"{label.case_id} routed to human_review but expected "
                f"{label.expected_ruling}. Issues: {result.validation_issues}"
            )

        # Verify the Judge produced a final ruling
        self.assertEqual(
            result.judge_result.action, "final_ruling",
            msg=f"{label.case_id}: expected final_ruling, got "
                f"{result.judge_result.action}",
        )

        # The key assertion: does the model's ruling match our label or
        # an acceptable alternative?
        actual = result.judge_result.ruling
        acceptable = {label.expected_ruling} | set(label.acceptable_alternatives)
        self.assertIn(
            actual, acceptable,
            msg=(
                f"{label.case_id}: ruling mismatch.\n"
                f"  Expected: {label.expected_ruling} "
                f"(alternatives: {label.acceptable_alternatives})\n"
                f"  Got:      {actual}\n"
                f"  Rationale: {label.rationale}\n"
                f"  Judge explanation: {result.judge_result.explanation}"
            ),
        )

        # If uphold_charge, verify refund is 0
        if result.judge_result.ruling == "uphold_charge":
            self.assertEqual(
                result.judge_result.proposed_action.amount_cents, 0,
                msg=f"{label.case_id}: uphold_charge but non-zero refund",
            )

        # If reverse_charge, verify refund equals full charge
        if result.judge_result.ruling == "reverse_charge":
            self.assertEqual(
                result.judge_result.proposed_action.amount_cents, charged_cents(case),
                msg=f"{label.case_id}: reverse_charge but refund != {charged_cents(case)} cents",
            )

    def test_disp_002_live_ruling_matches_label(self):
        self._run_case(LABELS["DISP-002"])

    def test_disp_003_live_ruling_matches_label(self):
        self._run_case(LABELS["DISP-003"])

    def test_disp_004_live_ruling_matches_label(self):
        self._run_case(LABELS["DISP-004"])

    def test_disp_005_live_ruling_matches_label(self):
        self._run_case(LABELS["DISP-005"])

    def test_disp_006_live_ruling_matches_label(self):
        """HELD-OUT: Below-threshold route deviation — does the model generalize?"""
        self._run_case(LABELS["DISP-006"])

    def test_disp_007_live_ruling_matches_label(self):
        """HELD-OUT: $8 fee, rider at fault — does the model follow the policy?"""
        self._run_case(LABELS["DISP-007"])


# ---------------------------------------------------------------------------
# Validation tests for expected labels
# ---------------------------------------------------------------------------

class LabelValidationTests(unittest.TestCase):
    """Verify that validate_final_ruling passes for correctly-constructed
    JudgeResults matching the case labels."""

    def setUp(self):
        self.policy = load_policy("sample_no_show")

    def _build_decision(self, ruling: str, amount: int, case_id: str = "DISP-002"):
        return JudgeResult(
            action="final_ruling", ruling=ruling,
            proposed_action=ProposedAction(amount_cents=amount),
            explanation=f"Test ruling for {case_id}.",
            evidence_ids=["TRIP-001"],
            policy_ids=["POLICY-001", "POLICY-003", "POLICY-004"],
        )

    def test_disp_002_uphold_charge_passes_validation(self):
        """DISP-002: uphold_charge with 0 refund should pass validation
        on a resolvable case (no EVENT-008 conflict, designated entrance set)."""
        import copy
        case = copy.deepcopy(load_case("DISP-002"))
        # Fix the material issues to test the amount check in isolation
        case["trip_data"]["pickup_location"]["designated_entrance"] = "Main lobby"
        event = next(e for e in case["app_events"] if e["id"] == "EVENT-008")
        event["details"] = "The five-minute free wait period expired; no-show threshold has not yet been reached."
        decision = self._build_decision("uphold_charge", 0, "DISP-002")
        issues = validate_final_ruling(case, self.policy, decision)
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_disp_003_reverse_charge_passes_validation(self):
        """DISP-003: reverse_charge with 500 refund should pass validation."""
        case = load_case("DISP-003")
        decision = self._build_decision("reverse_charge", 500, "DISP-003")
        issues = validate_final_ruling(case, self.policy, decision)
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_disp_004_uphold_charge_passes_validation(self):
        """DISP-004: uphold_charge with 0 refund should pass validation."""
        case = load_case("DISP-004")
        decision = self._build_decision("uphold_charge", 0, "DISP-004")
        issues = validate_final_ruling(case, self.policy, decision)
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_disp_003_uphold_charge_fails_validation(self):
        """DISP-003: uphold_charge should fail because fee_eligible is False
        (driver waited only 4 min, below 8-min threshold)."""
        case = load_case("DISP-003")
        decision = self._build_decision("uphold_charge", 0, "DISP-003")
        issues = validate_final_ruling(case, self.policy, decision)
        self.assertTrue(any("threshold" in issue for issue in issues),
                        f"Expected threshold issue, got: {issues}")

    def test_disp_003_partial_refund_fails_validation(self):
        """DISP-003: partial_refund should also fail because fee_eligible
        is False — if the threshold is not met, the charge must be fully
        reversed, not partially refunded."""
        case = load_case("DISP-003")
        decision = self._build_decision("partial_refund", 250, "DISP-003")
        issues = validate_final_ruling(case, self.policy, decision)
        self.assertTrue(any("threshold" in issue for issue in issues),
                        f"Expected threshold issue for partial_refund, got: {issues}")

    def test_disp_004_reverse_charge_fails_validation(self):
        """DISP-004: reverse_charge with 500 refund should pass amount check
        but the case has no material issues, so the ruling itself is valid
        in terms of structure (the model would be wrong, but validation
        checks structure not correctness)."""
        case = load_case("DISP-004")
        decision = self._build_decision("reverse_charge", 500, "DISP-004")
        issues = validate_final_ruling(case, self.policy, decision)
        # reverse_charge with full refund should pass amount validation
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_disp_005_partial_refund_passes_validation(self):
        """DISP-005: partial_refund with 693 cents (fare difference)
        should pass validation for the route deviation case."""
        case = load_case("DISP-005")
        policy = _policy_for_case(case)
        decision = self._build_decision("partial_refund", 693, "DISP-005")
        issues = validate_final_ruling(case, policy, decision)
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_disp_005_uphold_charge_fails_validation(self):
        """DISP-005: uphold_charge should fail because the deviation
        exceeds the 15% policy threshold (36.2% > 15%)."""
        case = load_case("DISP-005")
        policy = _policy_for_case(case)
        decision = self._build_decision("uphold_charge", 0, "DISP-005")
        issues = validate_final_ruling(case, policy, decision)
        self.assertTrue(any("deviation" in issue.lower() or "threshold" in issue.lower()
                           for issue in issues),
                        f"Expected deviation threshold issue, got: {issues}")

    def test_disp_006_uphold_charge_passes_validation(self):
        """HELD-OUT: DISP-006 uphold_charge should pass (deviation 12.1% < 15%)."""
        case = load_case("DISP-006")
        policy = _policy_for_case(case)
        decision = self._build_decision("uphold_charge", 0, "DISP-006")
        issues = validate_final_ruling(case, policy, decision)
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_disp_006_partial_refund_fails_validation(self):
        """HELD-OUT: DISP-006 partial_refund should fail (deviation below threshold)."""
        case = load_case("DISP-006")
        policy = _policy_for_case(case)
        decision = self._build_decision("partial_refund", 200, "DISP-006")
        issues = validate_final_ruling(case, policy, decision)
        self.assertTrue(any("below" in issue.lower() and "threshold" in issue.lower()
                           for issue in issues),
                        f"Expected below-threshold issue, got: {issues}")

    def test_disp_007_reverse_charge_passes_validation(self):
        """HELD-OUT: DISP-007 reverse_charge with 500c should pass (below threshold)."""
        case = load_case("DISP-007")
        decision = self._build_decision("reverse_charge", 500, "DISP-007")
        issues = validate_final_ruling(case, self.policy, decision)
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_disp_007_uphold_charge_fails_validation(self):
        """HELD-OUT: DISP-007 uphold_charge should fail (fee_eligible is False)."""
        case = load_case("DISP-007")
        decision = self._build_decision("uphold_charge", 0, "DISP-007")
        issues = validate_final_ruling(case, self.policy, decision)
        self.assertTrue(any("threshold" in issue for issue in issues),
                        f"Expected threshold issue, got: {issues}")


if __name__ == "__main__":
    unittest.main()
