import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from agents import ExampleAgentBackend
from case_data import load_case, policy_for_case
from workflow import run_review


APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")


class CaseImportUITests(unittest.TestCase):
    def upload(self, app, case, name="unseen.json"):
        return app.sidebar.file_uploader[0].set_value((name, json.dumps(case).encode(), "application/json")).run()

    def test_incompatible_records_are_rejected_before_overview_or_review(self):
        for defect in ("missing_fee", "fact_collision"):
            case = load_case("DISP-004")
            if defect == "missing_fee":
                case["trip_data"]["charged_fare"] = case["trip_data"].pop("cancellation_fee")
            else:
                case["chat_logs"][0]["id"] = "FACT-001"
            with self.subTest(defect=defect), patch("workflow.run_review") as reviewer:
                app = AppTest.from_file(APP_PATH).run()
                self.upload(app, case)
                self.assertFalse(app.exception)
                self.assertTrue(any("Import rejected" in item.value for item in app.error))
                reviewer.assert_not_called()

    def test_import_exposes_complaint_and_only_live_review_without_automatic_calls(self):
        case = load_case("DISP-004")
        case["dispute_ticket"]["dispute_id"] = "FHE-TEST-001"
        with patch("workflow.run_review") as reviewer:
            app = AppTest.from_file(APP_PATH).run()
            self.upload(app, case)
            self.assertFalse(app.exception)
            reviewer.assert_not_called()
        self.assertEqual(app.sidebar.radio[0].options, ["Live model"])
        self.assertEqual(app.sidebar.selectbox[0].value, case["dispute_ticket"]["trip_id"])
        self.assertEqual(app.sidebar.text_area[0].value, case["dispute_ticket"]["description"])
        self.assertTrue(any("FHE-TEST-001" in item.value for item in app.caption))

    def test_imported_case_uses_uploaded_records_and_existing_retrieval_pipeline(self):
        for original_id in ("DISP-004", "DISP-010"):
            with self.subTest(category=original_id):
                case = load_case(original_id)
                result = run_review(case, policy_for_case(case), ExampleAgentBackend(), gather_evidence=True)
                case["dispute_ticket"]["dispute_id"] = "FHE-TEST-001"
                result.case_id = "FHE-TEST-001"
                with patch.dict(os.environ, {"FAIRRIDE_API_KEY": "test", "FAIRRIDE_MODEL": "test"}), \
                     patch("workflow.run_review", return_value=result) as reviewer:
                    app = AppTest.from_file(APP_PATH).run()
                    self.upload(app, case)
                    app.sidebar.text_area[0].set_value("Please review my charge.").run()
                    app.sidebar.button[0].click().run()
                    self.assertFalse(app.exception)
                    self.assertEqual(reviewer.call_count, 1)
                    submitted = reviewer.call_args.args[0]
                    self.assertEqual(submitted["dispute_ticket"]["dispute_id"], "FHE-TEST-001")
                    self.assertEqual(submitted["dispute_ticket"]["description"], "Please review my charge.")
                    self.assertEqual(submitted["gps_telemetry"], case["gps_telemetry"])
                    self.assertIsNone(reviewer.call_args.args[2])
                    self.assertTrue(reviewer.call_args.kwargs["gather_evidence"])
                    self.assertTrue(app.get("download_button"))
                    app.sidebar.radio(key="dashboard_view").set_value("Agent activity").run()
                    self.assertFalse(app.exception)
                    self.assertTrue(any("Unverified model argument" in item.value for item in app.caption))
                    self.assertTrue(any("Unverified Judge analysis" in item.value for item in app.caption))
                    self.assertEqual(reviewer.call_count, 1)
                    app.sidebar.file_uploader[0].clear().run()
                    self.assertFalse(app.exception)
                    self.assertNotIn("review_result", app.session_state)
                    self.assertFalse(app.get("download_button"))

    def test_replacing_same_id_file_or_uploading_invalid_data_clears_old_review(self):
        case = load_case("DISP-004")
        result = run_review(case, policy_for_case(case), ExampleAgentBackend())
        with patch.dict(os.environ, {"FAIRRIDE_API_KEY": "test", "FAIRRIDE_MODEL": "test"}), \
             patch("workflow.run_review", return_value=result) as reviewer:
            app = AppTest.from_file(APP_PATH).run()
            self.upload(app, case)
            app.sidebar.button[0].click().run()
            self.assertIn("review_result", app.session_state)
            replacement = copy.deepcopy(case)
            replacement["chat_logs"][0]["content"] = "Updated evidence with the same case and trip IDs."
            self.upload(app, replacement)
            self.assertNotIn("review_result", app.session_state)
            self.assertFalse(app.get("download_button"))
            app.sidebar.button[0].click().run()
            self.assertIn("review_result", app.session_state)
            app.sidebar.file_uploader[0].set_value(("answers.json", b'{"expected_ruling":"uphold_charge"}', "application/json")).run()
            self.assertFalse(app.exception)
            self.assertNotIn("review_result", app.session_state)
            self.assertTrue(app.error)
            self.assertFalse(app.get("download_button"))
            self.assertEqual(reviewer.call_count, 2)
