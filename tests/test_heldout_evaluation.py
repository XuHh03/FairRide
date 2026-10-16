import copy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agents import ExampleAgentBackend
from case_data import load_case, policy_for_case
from contracts import ActivityEntry, JudgeResult
from workflow import run_review
import heldout_evaluation as evaluation


class HeldoutEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case("DISP-010")
        self.policy = policy_for_case(self.case)
        self.result = run_review(self.case, self.policy, ExampleAgentBackend(), gather_evidence=True)
        self.key = {
            "case_id": "DISP-010", "expected_label": "conditional_refund_excess_distance_fare",
            "expected_refund_cents": 83, "expected_goodwill_credit_cents": 0,
            "refund_basis": "excess_distance_fare", "mandatory_human_review": False,
            "confidence_requirement": {"policy_threshold": 0.8},
            "answer_key_status": "draft_for_independent_human_review",
            "human_confirmation_required_for_expected_answer": False,
        }

    def score(self, result=None, key=None):
        return evaluation.score_result(self.case, self.policy, result or self.result, key or self.key)

    def test_exact_match_retains_draft_oracle_status(self):
        scored = self.score()
        self.assertEqual(scored["verdict"], "PASS")
        self.assertEqual(scored["oracle_status"], self.key["answer_key_status"])
        self.assertTrue(all(scored["checks"].values()))

    def test_no_show_category_uses_separate_fixed_refund_and_credit_labels(self):
        case = load_case("DISP-003")
        policy = policy_for_case(case)
        result = run_review(case, policy, ExampleAgentBackend(), gather_evidence=True)
        key = {**self.key, "case_id": "DISP-003", "expected_label": "reverse_charge",
               "expected_refund_cents": 500, "refund_basis": "cancellation_fee",
               "confidence_requirement": {"policy_threshold": None}}
        self.assertEqual(evaluation.score_result(case, policy, result, key)["verdict"], "PASS")

    def test_fixed_oracle_catches_wrong_amount_basis_and_separate_credit(self):
        for field, wrong in (("amount_cents", 28), ("goodwill_credit_cents", 500), ("refund_basis", "cancellation_fee")):
            result = self.result.model_copy(deep=True)
            setattr(result.judge_result.proposed_action, field, wrong)
            with self.subTest(field=field):
                scored = self.score(result)
                self.assertEqual(scored["verdict"], "FAIL")
                self.assertFalse(scored["checks"][field])

    def test_unexpected_and_operational_referrals_never_pass(self):
        result = self.result.model_copy(deep=True)
        result.status = "human_review"
        result.judge_result = JudgeResult(action="human_review", explanation="Review required.")
        self.assertEqual(self.score(result)["verdict"], "FAIL")
        key = {**self.key, "mandatory_human_review": True, "expected_label": "mandatory_human_review"}
        result.failure_category = "model"
        scored = self.score(result, key)
        self.assertEqual(scored["verdict"], "FAIL")
        self.assertFalse(scored["checks"]["operational_success"])

    def test_policy_preflight_referral_does_not_require_retrieval_or_final_amount(self):
        result = self.result.model_copy(deep=True)
        result.status = "human_review"
        result.mandatory_escalation = True
        result.activity_log = [ActivityEntry(actor="system", event="policy_escalation", output={"reasons": ["Policy limit"]})]
        result.judge_result = JudgeResult(action="human_review", explanation="Policy limit.")
        key = {**self.key, "mandatory_human_review": True, "expected_label": "unresolved_traffic_justification",
               "expected_refund_cents": None, "refund_basis": None}
        scored = self.score(result, key)
        self.assertEqual(scored["verdict"], "PASS")
        self.assertIsNone(scored["checks"]["amount_cents"])
        self.assertIsNone(scored["checks"]["retrieval"])
        self.assertIsNone(scored["checks"]["argument_completion"])

    def test_complete_retrieval_and_failed_arguments_are_separate_checks(self):
        result = self.result.model_copy(deep=True)
        result.activity_log = [e for e in result.activity_log if e.event == "evidence_request"]
        result.status = "human_review"
        result.failure_category = "validation"
        result.validation_issues = ["Fact assertion correction must retain FACT-005"]
        result.judge_result = JudgeResult(action="human_review", explanation="Agent response failed validation.")
        scored = self.score(result)
        self.assertTrue(scored["checks"]["retrieval"])
        self.assertEqual(scored["retrieval_issues"], [])
        self.assertFalse(scored["checks"]["argument_completion"])
        self.assertEqual(len(scored["argument_issues"]), 2)
        self.assertFalse(scored["checks"]["operational_success"])
        self.assertEqual(scored["verdict"], "FAIL")

    def test_one_missing_argument_is_reported_for_that_role_only(self):
        result = self.result.model_copy(deep=True)
        result.activity_log = [e for e in result.activity_log if not (e.actor == "rider_advocate" and e.event == "initial_argument")]
        scored = self.score(result)
        self.assertTrue(scored["checks"]["retrieval"])
        self.assertFalse(scored["checks"]["argument_completion"])
        self.assertEqual(scored["argument_issues"], ["rider_advocate: missing validated initial argument"])

    def test_conditional_referral_requires_an_actual_below_threshold_assessment(self):
        result = self.result.model_copy(deep=True)
        result.status = "human_review"
        result.judge_result = JudgeResult(action="human_review", explanation="Low confidence.", confidence=0.7)
        self.assertEqual(self.score(result)["verdict"], "PASS")
        result.judge_result.confidence = 0.9
        self.assertEqual(self.score(result)["verdict"], "FAIL")
        result.judge_result.confidence = None
        self.assertEqual(self.score(result)["verdict"], "FAIL")

    def test_missing_low_final_confidence_and_unknown_citations_fail(self):
        for defect in ("low", "missing", "citation"):
            result = self.result.model_copy(deep=True)
            if defect == "citation":
                result.judge_result.evidence_ids.append("UNKNOWN-001")
            else:
                result.judge_result.confidence = 0.79 if defect == "low" else None
            with self.subTest(defect=defect):
                self.assertEqual(self.score(result)["verdict"], "FAIL")

    def test_retrieval_requires_both_roles_all_records_before_arguments_and_budget(self):
        for defect in ("missing_role", "missing_record", "after_argument", "budget"):
            result = self.result.model_copy(deep=True)
            requests = [e for e in result.activity_log if e.event == "evidence_request"]
            if defect == "missing_role":
                result.activity_log.remove(requests[0])
            elif defect == "missing_record":
                requests[0].output["record_ids"].pop()
            elif defect == "after_argument":
                result.activity_log.remove(requests[0])
                result.activity_log.append(requests[0])
            else:
                result.activity_log[0:0] = [requests[0].model_copy(deep=True) for _ in range(3)]
            with self.subTest(defect=defect):
                self.assertFalse(self.score(result)["checks"]["retrieval"])

    def test_bad_oracle_is_not_guessed(self):
        for change in ({"case_id": "OTHER"}, {"expected_label": "unknown"}, {"expected_refund_cents": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.score(key={**self.key, **change})

    def dataset(self, root, case_id="FHE-TEST-001"):
        cases, keys = root / "cases", root / "answer_key"
        cases.mkdir()
        keys.mkdir()
        case = copy.deepcopy(self.case)
        case["dispute_ticket"]["dispute_id"] = case_id
        (cases / f"{case_id}.json").write_text(json.dumps(case))
        (keys / f"{case_id}.json").write_text(json.dumps({**self.key, "case_id": case_id}))
        return cases, keys

    def test_batch_keeps_key_out_of_workflow_reports_progress_and_checkpoints_each_run(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases, keys = self.dataset(root)
            output = root / "report.json"
            observed = []
            def review(case, policy, backend, *, gather_evidence, on_progress):
                self.assertTrue(gather_evidence)
                self.assertIsNone(backend)
                self.assertNotIn("expected_label", json.dumps(case))
                self.assertNotIn("independently_calculated_facts", json.dumps(case))
                observed.append(len(json.loads(output.read_text())["cases"]) if output.exists() else 0)
                # Keys are not read until after this call returns.
                self.assertEqual(key_reader.call_count, len(observed) - 1)
                on_progress("Judge is reviewing initial arguments")
                return self.result.model_copy(update={"case_id": "FHE-TEST-001"})
            with patch("heldout_evaluation.run_review", side_effect=review), \
                 patch("heldout_evaluation.load_answer_key", wraps=evaluation.load_answer_key) as key_reader, \
                 patch("sys.stdout", new_callable=io.StringIO) as console:
                report = evaluation.run_dataset(cases, keys, output, runs=2)
            self.assertEqual(observed, [0, 1])
            self.assertEqual(report["summary"]["passed"], 2)
            self.assertEqual(json.loads(output.read_text())["cases"], report["cases"])
            self.assertIn("[1/2] FHE-TEST-001", console.getvalue())
            self.assertIn("Judge is reviewing", console.getvalue())
            self.assertIn("PASS", console.getvalue())
            self.assertNotIn("rider_profile", output.read_text())

    def test_batch_continues_after_provider_exception_and_malformed_key(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases, keys = self.dataset(root)
            (keys / "FHE-TEST-001.json").write_text("{")
            result = self.result.model_copy(update={"case_id": "FHE-TEST-001"})
            with patch("heldout_evaluation.run_review", side_effect=[RuntimeError("Unavailable"), result]), \
                 patch("sys.stdout", new_callable=io.StringIO):
                report = evaluation.run_dataset(cases, keys, root / "report.json", runs=2)
            self.assertEqual(report["summary"]["failed"], 2)
            self.assertEqual(report["cases"][0]["error_category"], "review")
            self.assertEqual(report["cases"][1]["error_category"], "answer_key")

    def test_dry_run_loads_all_inputs_without_provider_or_answer_key_content(self):
        with TemporaryDirectory() as directory:
            cases, keys = self.dataset(Path(directory))
            (keys / "FHE-TEST-001.json").write_text("{")
            with patch("heldout_evaluation.run_review") as review, \
                 patch("heldout_evaluation.load_answer_key") as key_reader, \
                 patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(evaluation.main(["--cases-dir", str(cases), "--answer-key-dir", str(keys), "--dry-run"]), 0)
            review.assert_not_called()
            key_reader.assert_not_called()

    def test_cli_requires_explicit_live_opt_in_and_valid_pairing(self):
        with TemporaryDirectory() as directory:
            cases, keys = self.dataset(Path(directory))
            for extra in ([], ["--runs", "0"]):
                with self.subTest(extra=extra), patch("heldout_evaluation.run_review") as reviewer, \
                     patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                    evaluation.main(["--cases-dir", str(cases), "--answer-key-dir", str(keys)] + extra)
                reviewer.assert_not_called()
            (keys / "FHE-TEST-001.json").unlink()
            with self.assertRaises(ValueError):
                evaluation.dataset_inputs(cases, keys)

    def test_report_cannot_overwrite_a_case_or_answer_key(self):
        with TemporaryDirectory() as directory:
            cases, keys = self.dataset(Path(directory))
            for output in (cases / "FHE-TEST-001.json", keys / "FHE-TEST-001.json"):
                original = output.read_bytes()
                with self.subTest(output=output), patch("heldout_evaluation.run_review") as review, self.assertRaises(ValueError):
                    evaluation.run_dataset(cases, keys, output)
                review.assert_not_called()
                self.assertEqual(output.read_bytes(), original)

    def test_report_cannot_overwrite_an_unpaired_key(self):
        with TemporaryDirectory() as directory:
            cases, keys = self.dataset(Path(directory))
            output = keys / "UNPAIRED.json"
            output.write_text('{"case_id": "UNPAIRED"}')
            original = output.read_bytes()
            with patch("heldout_evaluation.run_review") as review, self.assertRaises(ValueError):
                evaluation.run_dataset(cases, keys, output)
            review.assert_not_called()
            self.assertEqual(output.read_bytes(), original)

    def test_unwritable_report_fails_before_any_model_calls(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases, keys = self.dataset(root)
            for defect in ("directory", "permission"):
                with self.subTest(defect=defect), patch("heldout_evaluation.run_review") as review:
                    with self.assertRaises(OSError):
                        if defect == "directory":
                            evaluation.run_dataset(cases, keys, root)
                        else:
                            with patch.object(Path, "write_text", side_effect=PermissionError("Cannot write report")):
                                evaluation.run_dataset(cases, keys, root / "report.json")
                    review.assert_not_called()

    def test_cli_returns_failure_status_for_failed_batch(self):
        with TemporaryDirectory() as directory:
            cases, keys = self.dataset(Path(directory))
            for failures, expected_exit in ((0, 0), (1, 1)):
                with self.subTest(failures=failures), \
                     patch.dict("os.environ", {"FAIRRIDE_API_KEY": "test", "FAIRRIDE_MODEL": "test"}), \
                     patch("heldout_evaluation.run_dataset", return_value={"summary": {"failed": failures}}):
                    actual = evaluation.main(["--cases-dir", str(cases), "--answer-key-dir", str(keys), "--live"])
                self.assertEqual(actual, expected_exit)
