import asyncio
import unittest

from agents import ExampleAgentBackend, ModelAgentBackend
from case_data import load_case, policy_for_case
from evidence import build_review_input


class AdvocatePolicyContextTests(unittest.TestCase):
    def context(self, case_id):
        output = ExampleAgentBackend().examples[case_id]["rider_advocate"]
        class Client:
            async def complete_json(self, instructions, payload):
                self.payload = payload
                return output, {}
        case = load_case(case_id)
        client = Client()
        asyncio.run(ModelAgentBackend(client).advocate(build_review_input(case, policy_for_case(case)), "rider_advocate"))
        return client.payload["policy_application"]

    def test_no_show_context_uses_actual_contacts_and_eligible_wait(self):
        context = self.context("DISP-004")
        self.assertIn("9 computed waiting minutes", context)
        self.assertIn("4 message(s) and 2 unique call(s) before cancellation", context)
        self.assertIn("Fee eligibility is true", context)
        self.assertIn("do not argue that a required contact is missing", context)

    def test_route_context_does_not_subtract_tolerance_or_overrule_agreement(self):
        context = self.context("DISP-010")
        self.assertIn("1.5 km", context)
        self.assertIn("83 cents", context)
        self.assertIn("do not subtract the 1 km tolerance", context)
        self.assertIn("justification=unsupported", context)
        agreed = self.context("DISP-011")
        self.assertIn("requires no refund", agreed)
        self.assertIn("do not argue that exceeding tolerance alone requires a refund", agreed)
