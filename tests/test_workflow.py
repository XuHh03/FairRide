"""Integration tests for the workflow pipeline using stub mode."""

import copy
import json
import os
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from contracts import AdvocateResult, JudgeResult, ProposedAction
from case_data import load_case, load_policy
from checks import validate_amounts
from evidence import build_review_input
from workflow import run_review


class StubModeTests(unittest.TestCase):
    """Tests that run the full pipeline using FAIRRIDE_STUB=1."""

    def setUp(self):
        os.environ["FAIRRIDE_STUB"] = "1"
        self.case = load_case("DISP-002")
        self.policy = load_policy("sample_no_show")

    def test_end_to_end_returns_workflow_result(self):
        result = run_review(self.case, self.policy)
        self.assertEqual(result.case_id, "DISP-002")
        self.assertIn(result.status, ("completed", "human_review"))
        self.assertGreater(len(result.activity_log), 0)

    def test_activity_log_has_all_agents(self):
        result = run_review(self.case, self.policy)
        actors = {entry.actor for entry in result.activity_log}
        self.assertIn("rider_advocate", actors)
        self.assertIn("driver_advocate", actors)
        self.assertIn("judge", actors)

    def test_advocates_have_distinct_outputs(self):
        result = run_review(self.case, self.policy)
        rider_entry = next(
            e for e in result.activity_log
            if e.actor == "rider_advocate" and e.event == "initial_argument"
        )
        driver_entry = next(
            e for e in result.activity_log
            if e.actor == "driver_advocate" and e.event == "initial_argument"
        )
        self.assertNotEqual(rider_entry.output, driver_entry.output)

    def test_judge_action_is_valid(self):
        result = run_review(self.case, self.policy)
        self.assertIn(result.judge_result.action,
                      ("request_rebuttal", "final_ruling", "human_review"))

    def test_rebuttal_flow_completes(self):
        """Stub mode triggers a rebuttal; confirm the full flow runs."""
        result = run_review(self.case, self.policy)
        events = [e.event for e in result.activity_log]
        # The stub Judge requests rebuttal on first pass
        self.assertIn("first_pass", events)
        self.assertIn("rebuttal_response", events)
        self.assertIn("second_pass", events)

    def test_no_validation_issues_in_clean_run(self):
        result = run_review(self.case, self.policy)
        self.assertEqual(result.validation_issues, [])


class CitationRejectionTests(unittest.TestCase):
    """Test that unknown citations are caught and logged."""

    def setUp(self):
        os.environ["FAIRRIDE_STUB"] = "1"
        self.case = load_case("DISP-002")
        self.policy = load_policy("sample_no_show")

    def test_unknown_evidence_id_is_logged(self):
        """Inject a fake evidence ID into a stub advocate response."""
        from agents.client import _stub_response
        from contracts import AdvocateResult, ReviewInput

        review = build_review_input(self.case, self.policy)
        # Get the normal stub, then corrupt it
        normal = _stub_response("rider_advocate", "", AdvocateResult)
        corrupted = normal.model_copy()
        corrupted.claims[0] = corrupted.claims[0].model_copy(
            update={"evidence_ids": ["GPS-999"]}
        )
        # Patch the advocate to return the corrupted version
        with patch("workflow.rider_advocate", return_value=corrupted):
            result = run_review(self.case, self.policy)
        self.assertTrue(
            any("GPS-999" in issue for issue in result.validation_issues)
        )


class AmountValidationTests(unittest.TestCase):
    """Test validate_amounts for all four ruling types."""

    def setUp(self):
        self.policy = load_policy("sample_no_show")

    def test_uphold_charge_requires_zero(self):
        """The Pydantic contract already rejects uphold_charge with non-zero cents.
        validate_amounts is defense-in-depth; test it with model_construct to bypass."""
        result = JudgeResult.model_construct(
            action="final_ruling", ruling="uphold_charge",
            proposed_action=ProposedAction(amount_cents=500),
            explanation="test",
        )
        issues = validate_amounts(result, self.policy)
        self.assertEqual(len(issues), 1)
        self.assertIn("zero", issues[0])

    def test_reverse_charge_requires_full_amount(self):
        result = JudgeResult(
            action="final_ruling", ruling="reverse_charge",
            proposed_action=ProposedAction(amount_cents=400),
            explanation="test",
        )
        issues = validate_amounts(result, self.policy)
        self.assertEqual(len(issues), 1)
        self.assertIn("500", issues[0])

    def test_reverse_charge_full_amount_ok(self):
        result = JudgeResult(
            action="final_ruling", ruling="reverse_charge",
            proposed_action=ProposedAction(amount_cents=500),
            explanation="test",
        )
        issues = validate_amounts(result, self.policy)
        self.assertEqual(issues, [])

    def test_partial_refund_must_be_positive(self):
        result = JudgeResult(
            action="final_ruling", ruling="partial_refund",
            proposed_action=ProposedAction(amount_cents=0),
            explanation="test",
        )
        issues = validate_amounts(result, self.policy)
        self.assertEqual(len(issues), 1)

    def test_partial_refund_must_be_below_charge(self):
        result = JudgeResult(
            action="final_ruling", ruling="partial_refund",
            proposed_action=ProposedAction(amount_cents=600),
            explanation="test",
        )
        issues = validate_amounts(result, self.policy)
        self.assertEqual(len(issues), 1)

    def test_partial_refund_valid_amount_ok(self):
        result = JudgeResult(
            action="final_ruling", ruling="partial_refund",
            proposed_action=ProposedAction(amount_cents=200),
            explanation="test",
        )
        issues = validate_amounts(result, self.policy)
        self.assertEqual(issues, [])

    def test_uphold_charge_zero_ok(self):
        result = JudgeResult(
            action="final_ruling", ruling="uphold_charge",
            proposed_action=ProposedAction(amount_cents=0),
            explanation="test",
        )
        issues = validate_amounts(result, self.policy)
        self.assertEqual(issues, [])

    def test_non_final_ruling_skips_amount_check(self):
        result = JudgeResult(
            action="human_review", explanation="test",
        )
        issues = validate_amounts(result, self.policy)
        self.assertEqual(issues, [])


class RebuttalLimitTests(unittest.TestCase):
    """Test that the one-round rebuttal limit is enforced."""

    def setUp(self):
        os.environ["FAIRRIDE_STUB"] = "1"
        self.case = load_case("DISP-002")
        self.policy = load_policy("sample_no_show")

    def test_second_rebuttal_request_overridden(self):
        """If the Judge requests rebuttal twice, the second is overridden."""
        from contracts import JudgeResult as JR

        # First judge call: request_rebuttal (normal stub behavior)
        first_pass = JR(
            action="request_rebuttal",
            question="Do the records identify a designated entrance?",
            rebuttal_roles=["rider_advocate", "driver_advocate"],
            explanation="Entrance is unresolved.",
        )
        # Second judge call: also request_rebuttal (should be overridden)
        second_pass = JR(
            action="request_rebuttal",
            question="Another question?",
            rebuttal_roles=["rider_advocate"],
            explanation="Still unresolved.",
        )

        call_count = [0]
        original_judge = None

        def mock_judge(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return first_pass
            return second_pass

        with patch("workflow.judge", side_effect=mock_judge):
            result = run_review(self.case, self.policy)

        self.assertEqual(result.judge_result.action, "human_review")
        self.assertTrue(
            any("Rebuttal limit" in issue for issue in result.validation_issues)
        )
        # Check the rebuttal_limit_enforced event was logged
        events = [e.event for e in result.activity_log]
        self.assertIn("rebuttal_limit_enforced", events)


class ModelCallFailureTests(unittest.TestCase):
    """Test that model call failures route to human review."""

    def setUp(self):
        os.environ["FAIRRIDE_STUB"] = "1"
        self.case = load_case("DISP-002")
        self.policy = load_policy("sample_no_show")

    def test_advocate_failure_routes_to_human_review(self):
        from agents.client import ModelCallError

        def failing_advocate(*args, **kwargs):
            raise ModelCallError("Simulated API failure")

        with patch("workflow.rider_advocate", side_effect=failing_advocate):
            result = run_review(self.case, self.policy)

        self.assertEqual(result.status, "human_review")
        self.assertTrue(
            any("rider_advocate call failed" in issue for issue in result.validation_issues)
        )


if __name__ == "__main__":
    unittest.main()
