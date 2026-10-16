import asyncio
import copy
import unittest

from agents import ExampleAgentBackend, ModelAgentBackend
from case_data import load_case, policy_for_case
from contracts import AdvocateResult
from evidence import build_review_input
from review_summary import build_decision_summary, build_review_report
from workflow import run_review
from claim_repair_fixtures import patch_response


class PR6IntegrationTests(unittest.TestCase):
    def test_dashboard_and_export_use_workflow_final_explanation(self):
        for case_id in ("DISP-004", "DISP-006", "DISP-010", "DISP-011"):
            with self.subTest(case_id=case_id):
                case = load_case(case_id)
                policy = policy_for_case(case)
                result = run_review(case, policy, ExampleAgentBackend())
                self.assertEqual(build_decision_summary(case, policy, result)["reason"], result.final_explanation)
                report = build_review_report(case, policy, result, "Example walkthrough")
                self.assertEqual(report["summary"]["reason"], report["workflow"]["final_explanation"])

    def test_unverified_presence_does_not_pass_physical_wait_checklist(self):
        case = load_case("DISP-004")
        case["gps_telemetry"] = []
        policy = policy_for_case(case)
        result = run_review(case, policy, ExampleAgentBackend())
        summary = build_decision_summary(case, policy, result)
        wait = summary["checklist"][0]
        self.assertEqual(wait["status"], "unresolved")
        self.assertIn("not corroborated", summary["calculations"][0]["formula"])

    def test_argument_reviewer_is_not_given_advocate_fact_assertion_schema_instructions(self):
        class Client:
            async def complete_json(self, instructions, payload):
                self.instructions = instructions
                return {"findings": []}, {}
        case = load_case("DISP-011")
        review = build_review_input(case, policy_for_case(case))
        argument = AdvocateResult.model_validate(ExampleAgentBackend().examples["DISP-011"]["driver_advocate"])
        client = Client()
        call = asyncio.run(ModelAgentBackend(client).review_argument(review, argument))
        self.assertEqual(call.result.findings, [])
        self.assertNotIn("include fact_assertions entries", client.instructions)

    def test_length_fact_and_citation_errors_share_one_correction_budget(self):
        case = load_case("DISP-004")
        review = build_review_input(case, policy_for_case(case))
        valid = copy.deepcopy(ExampleAgentBackend().examples["DISP-004"]["rider_advocate"])
        overlong = copy.deepcopy(valid)
        overlong["claims"][0]["statement"] = "x" * 1501
        wrong_fact = copy.deepcopy(valid)
        wrong_fact["claims"][0]["fact_assertions"] = [{"fact_id": "FACT-001", "value": 8}]
        wrong_citation = copy.deepcopy(valid)
        wrong_citation["claims"][0]["evidence_ids"] = ["GPS-999"]
        corrected_fact_bad_citation = copy.deepcopy(wrong_citation)
        corrected_fact_bad_citation["claims"][0]["fact_assertions"] = [{"fact_id": "FACT-001", "value": 9}]
        for outputs, error in (([overlong, wrong_fact], "Fact assertion correction failed"),
                               ([wrong_fact, overlong], "Claim repair failed"),
                               ([wrong_fact, corrected_fact_bad_citation], "Citation correction failed")):
            with self.subTest(error=error):
                class Client:
                    calls = 0
                    async def complete_json(self, instructions, payload):
                        output = outputs[self.calls]
                        self.calls += 1
                        return patch_response(copy.deepcopy(output), payload), {}
                client = Client()
                with self.assertRaisesRegex(ValueError, error):
                    asyncio.run(ModelAgentBackend(client).advocate(review, "rider_advocate"))
                self.assertEqual(client.calls, 2)
