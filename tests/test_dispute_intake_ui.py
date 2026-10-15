import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from case_data import load_case
from workflow import run_review


APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")


class DisputeIntakeUITests(unittest.TestCase):
    def test_filing_requires_complaint_and_runs_retrieval_for_both_categories(self):
        app = AppTest.from_file(APP_PATH, default_timeout=15).run()
        app.sidebar.checkbox(key="filing_mode").check().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.sidebar.selectbox[0].label, "Select a trip")
        self.assertTrue(app.sidebar.button[0].disabled)
        for case_id, complaint in (("DISP-004", "I was charged a cancellation fee."),
                                   ("DISP-010", "The route was longer and I was overcharged.")):
            with self.subTest(case=case_id):
                trip_id = load_case(case_id)["dispute_ticket"]["trip_id"]
                app.sidebar.selectbox[0].select(trip_id).run()
                app.sidebar.text_area[0].set_value(complaint).run()
                self.assertFalse(app.sidebar.button[0].disabled)
                with patch("workflow.run_review", wraps=run_review) as reviewer:
                    app.sidebar.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertEqual(reviewer.call_args.args[0]["dispute_ticket"]["description"], complaint)
                self.assertTrue(reviewer.call_args.kwargs["gather_evidence"])
                result = app.session_state["review_result"]
                self.assertEqual(result.status, "completed")
                self.assertEqual(len([entry for entry in result.activity_log if entry.event == "evidence_request"]), 2)
                app.sidebar.radio(key="dashboard_view").set_value("Agent activity").run()
                self.assertFalse(app.exception)
                text = " ".join(item.value for item in app.caption)
                self.assertIn("Scripted evidence retrieval", text)
                events = [item for item in app.expander if "evidence request" in item.label]
                self.assertEqual(len(events), 2)
                for event in events:
                    self.assertTrue(event.get("popover"))
                    self.assertTrue(any(trip_id in item.value for item in event.caption))

    def test_editing_complaint_trip_or_mode_clears_previous_result(self):
        app = AppTest.from_file(APP_PATH, default_timeout=15).run()
        app.sidebar.checkbox(key="filing_mode").check().run()
        app.sidebar.text_area[0].set_value("I dispute the fee.").run()
        app.sidebar.button[0].click().run()
        self.assertIn("review_result", app.session_state)
        app.sidebar.text_area[0].set_value("I dispute the fee and pickup records.").run()
        self.assertNotIn("review_result", app.session_state)
        self.assertFalse(app.get("download_button"))
        app.sidebar.button[0].click().run()
        self.assertIn("review_result", app.session_state)
        trip = load_case("DISP-010")["dispute_ticket"]["trip_id"]
        app.sidebar.selectbox[0].select(trip).run()
        self.assertNotIn("review_result", app.session_state)
        app.sidebar.text_area[0].set_value("The detour was unnecessary.").run()
        app.sidebar.button[0].click().run()
        app.sidebar.checkbox(key="filing_mode").uncheck().run()
        self.assertNotIn("review_result", app.session_state)
        self.assertFalse(app.exception)
