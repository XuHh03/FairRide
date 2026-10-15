import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from case_data import load_case, policy_for_case
from evidence import build_evidence_index, build_policy_index
from workflow import run_review


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
