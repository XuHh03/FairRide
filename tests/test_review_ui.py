import os
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from agents import AgentCall, ExampleAgentBackend
from contracts import ArgumentReview
from case_data import load_case, policy_for_case
from evidence import build_evidence_index, build_policy_index
from workflow import run_review
from review_summary import build_decision_summary


APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")


class ReviewUITests(unittest.TestCase):
    def test_all_example_flows_keep_the_overview_focused_and_support_other_views(self):
        app = AppTest.from_file(APP_PATH, default_timeout=15).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.sidebar.selectbox[0].label, "Select a case")
        self.assertEqual(app.sidebar.radio[0].label, "Review mode")
        self.assertEqual(app.sidebar.button[0].label, "Run review")
        for number in range(2, 13):
            case_id = f"DISP-{number:03d}"
            with self.subTest(case=case_id):
                app.sidebar.selectbox[0].select(case_id).run()
                self.assertFalse(app.exception)
                self.assertNotIn("review_result", app.session_state)
                app.sidebar.button[0].click().run()
                self.assertFalse(app.exception)
                result = app.session_state["review_result"]
                self.assertEqual(result.case_id, case_id)
                self.assertIsNone(result.failure_category)
                self.assertEqual(app.sidebar.radio(key="dashboard_view").value, "Overview")
                headings = [heading.value for heading in app.main.subheader]
                self.assertIn("Decision summary", headings)
                self.assertIn("Policy checklist", headings)
                self.assertIn("Verified calculations", headings)
                self.assertNotIn("Agent activity", headings)
                self.assertNotIn("Sources & policy", headings)
                self.assertEqual(app.sidebar.get("download_button")[0].proto.label, "Download review report (JSON)")
                self.assertEqual(len(app.main.dataframe), 1)
                if number >= 5 and number != 7:
                    self.assertEqual(app.main.metric[0].label, "Additional distance")
                    self.assertEqual(app.main.metric[1].label, "Excess-distance fare component")
                if result.status == "human_review":
                    self.assertFalse(any(metric.label == "Recommended rider refund" for metric in app.main.metric))
                    self.assertFalse(any(tab.label in ("For the rider", "For the driver") for tab in app.tabs))
                else:
                    self.assertEqual([tab.label for tab in app.tabs], ["For the rider", "For the driver"])
                    self.assertTrue(any("Agent-reported confidence:" in item.value for item in app.caption))
                    for tab in app.tabs:
                        content = " ".join(item.value for item in tab.markdown)
                        self.assertIn(result.final_explanation, content)
                        self.assertIn(f"SGD {result.judge_result.proposed_action.amount_cents / 100:.2f}", content)
                for view in ("Evidence", "Agent activity", "Sources & policy"):
                    app.sidebar.radio(key="dashboard_view").set_value(view).run()
                    self.assertFalse(app.exception)
                    self.assertEqual(app.session_state["review_result"].model_dump(), result.model_dump())
                    self.assertEqual([heading.value for heading in app.main.subheader], [view])
                    if view == "Evidence":
                        self.assertEqual([tab.label for tab in app.tabs], ["Policy checks", "Timeline"])
                        case = load_case(case_id)
                        known_ids = set(build_evidence_index(case)) | set(build_policy_index(policy_for_case(case)))
                        popovers = app.get("popover")
                        self.assertTrue(popovers)
                        self.assertTrue(all(item.proto.popover.label in known_ids for item in popovers))
                    if view == "Agent activity":
                        activities = [item for item in app.main.expander if " · " in item.label]
                        self.assertTrue(activities)
                        self.assertTrue(all(not item.proto.expanded for item in activities))
                app.sidebar.radio(key="dashboard_view").set_value("Overview").run()

    def test_switching_cases_clears_the_previous_decision_and_export(self):
        app = AppTest.from_file(APP_PATH, default_timeout=15).run()
        app.sidebar.button[0].click().run()
        self.assertIn("review_result", app.session_state)
        app.sidebar.selectbox[0].select("DISP-010").run()
        self.assertFalse(app.exception)
        self.assertNotIn("review_result", app.session_state)
        self.assertFalse(app.get("download_button"))
        self.assertFalse(any(metric.label == "Recommended rider refund" for metric in app.main.metric))
        self.assertTrue(any("run the review" in item.value for item in app.info))

    def test_navigation_does_not_call_agents_and_new_review_returns_to_overview(self):
        with patch("workflow.run_review", wraps=run_review) as reviewer:
            app = AppTest.from_file(APP_PATH, default_timeout=15).run()
            app.sidebar.button[0].click().run()
            self.assertEqual(reviewer.call_count, 1)
            for view in ("Evidence", "Agent activity", "Sources & policy", "Overview"):
                app.sidebar.radio(key="dashboard_view").set_value(view).run()
                self.assertFalse(app.exception)
            self.assertEqual(reviewer.call_count, 1)
            app.sidebar.radio(key="dashboard_view").set_value("Evidence").run()
            app.sidebar.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.sidebar.radio(key="dashboard_view").value, "Overview")
            self.assertEqual(reviewer.call_count, 2)

    def test_views_work_before_review_and_mode_changes_preserve_result_provenance(self):
        app = AppTest.from_file(APP_PATH, default_timeout=15).run()
        for view in ("Evidence", "Agent activity", "Sources & policy"):
            app.sidebar.radio(key="dashboard_view").set_value(view).run()
            self.assertFalse(app.exception)
        self.assertTrue(app.main.json)
        app.sidebar.button[0].click().run()
        with patch("workflow.run_review") as reviewer:
            app.sidebar.radio[0].set_value("Live model").run()
            self.assertFalse(app.exception)
            reviewer.assert_not_called()
        self.assertEqual(app.session_state["review_mode"], "Example walkthrough")
        self.assertTrue(any("Source: Example walkthrough" in item.value for item in app.caption))


class IntegratedReviewUITests(unittest.TestCase):
    def test_older_summary_without_party_messages_still_displays_decision(self):
        case = load_case("DISP-002")
        policy = policy_for_case(case)
        result = run_review(case, policy, ExampleAgentBackend())
        summary = build_decision_summary(case, policy, result)
        summary.pop("party_messages")
        with patch("workflow.run_review", return_value=result), patch("review_summary.build_decision_summary", return_value=summary):
            app = AppTest.from_file(APP_PATH).run()
            app.sidebar.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any(item.value == summary["reason"] for item in app.markdown))
        self.assertFalse(app.tabs)

    def test_completed_review_labels_application_and_model_analysis_with_sources(self):
        case = load_case("DISP-010")
        result = run_review(case, policy_for_case(case), ExampleAgentBackend())
        with patch.dict(os.environ, {"FAIRRIDE_API_KEY": "test", "FAIRRIDE_MODEL": "test"}), patch("workflow.run_review", return_value=result):
            app = AppTest.from_file(APP_PATH).run()
            app.sidebar.selectbox[0].select("DISP-010").run()
            app.sidebar.radio[0].set_value("Live model").run()
            app.sidebar.button[0].click().run()
        self.assertFalse(app.exception)
        captions = " ".join(item.value for item in app.caption)
        self.assertIn("Application-generated explanation", captions)
        self.assertTrue(any("SGD 0.83" in item.value for item in app.markdown))
        app.sidebar.radio(key="dashboard_view").set_value("Agent activity").run()
        self.assertFalse(app.exception)
        captions = " ".join(item.value for item in app.caption)
        self.assertIn("Model-generated argument", captions)
        self.assertIn("Original Judge analysis", captions)
        self.assertIn("Citation IDs and declared fact values are checked", captions)
        self.assertTrue(app.get("popover"))
        self.assertTrue(app.json)

    def test_failed_review_is_not_displayed_as_a_completed_decision(self):
        class BrokenBackend(ExampleAgentBackend):
            async def advocate(self, *args, **kwargs):
                raise ValueError("Invalid model output")
        case = load_case("DISP-002")
        failed = run_review(case, policy_for_case(case), BrokenBackend())
        with patch("workflow.run_review", return_value=failed):
            app = AppTest.from_file(APP_PATH).run()
            app.sidebar.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any(item.value == "Model response failed validation" for item in app.error))
        self.assertFalse(app.success)
        self.assertFalse(any("Application-generated explanation" in item.value for item in app.caption))

    def test_failed_support_check_displays_flagged_argument_and_cited_findings(self):
        class Backend(ExampleAgentBackend):
            async def review_argument(self, review, argument, question=None):
                return AgentCall(ArgumentReview(findings=[{
                    "section": "claims", "index": 0, "verdict": "unsupported", "explanation": "This statement contradicts the supplied policy.",
                    "evidence_ids": ["TRIP-001"], "policy_ids": ["POLICY-1.3"]}]))
        case = load_case("DISP-011")
        failed = run_review(case, policy_for_case(case), Backend())
        with patch("workflow.run_review", return_value=failed):
            app = AppTest.from_file(APP_PATH).run()
            app.sidebar.selectbox[0].select("DISP-011").run()
            app.sidebar.button[0].click().run()
        app.sidebar.radio(key="dashboard_view").set_value("Agent activity").run()
        self.assertFalse(app.exception)
        warnings = " ".join(item.value for item in app.warning)
        self.assertIn("was flagged", warnings)
        self.assertIn("claims.0 · unsupported", warnings)
        self.assertIn("contradicts the supplied policy", warnings)
        self.assertFalse(app.success)
        self.assertTrue(any("POLICY-1.3" in item.value for item in app.caption))
