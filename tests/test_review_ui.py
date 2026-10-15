import unittest
import os
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from agents import AgentCall, ExampleAgentBackend
from contracts import ArgumentReview
from case_data import load_case, policy_for_case
from workflow import run_review

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")


class ReviewUITests(unittest.TestCase):
    def test_completed_review_labels_application_and_model_analysis_with_sources(self):
        case = load_case("DISP-010")
        result = run_review(case, policy_for_case(case), ExampleAgentBackend())
        with patch.dict(os.environ, {"FAIRRIDE_API_KEY": "test", "FAIRRIDE_MODEL": "test"}), patch("workflow.run_review", return_value=result):
            app = AppTest.from_file(APP_PATH).run()
            app.selectbox[0].select("DISP-010").run()
            app.radio[0].set_value("Live model").run()
            app.button[0].click().run()
        self.assertFalse(app.exception)
        captions = " ".join(item.value for item in app.caption)
        self.assertIn("Application-generated explanation", captions)
        self.assertIn("Model-generated argument", captions)
        self.assertIn("Original Judge analysis", captions)
        self.assertIn("Citations validate reference IDs", captions)
        self.assertTrue(any(item.value == "Cited source records" for item in app.subheader))
        self.assertTrue(app.json)
        self.assertTrue(any("SGD 0.83" in item.value for item in app.markdown))

    def test_failed_review_is_not_displayed_as_a_completed_decision(self):
        class BrokenBackend(ExampleAgentBackend):
            async def advocate(self, *args, **kwargs):
                raise ValueError("Invalid model output")
        case = load_case("DISP-002")
        failed = run_review(case, policy_for_case(case), BrokenBackend())
        with patch("workflow.run_review", return_value=failed):
            app = AppTest.from_file(APP_PATH).run()
            app.button[0].click().run()
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
            app.selectbox[0].select("DISP-011").run()
            app.button[0].click().run()
        self.assertFalse(app.exception)
        warnings = " ".join(item.value for item in app.warning)
        self.assertIn("was flagged", warnings)
        self.assertIn("claims.0 · unsupported", warnings)
        self.assertIn("contradicts the supplied policy", warnings)
        self.assertFalse(app.success)
        self.assertTrue(any("POLICY-1.3" in item.value for item in app.caption))
