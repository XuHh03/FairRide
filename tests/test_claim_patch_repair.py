import asyncio
import copy
import unittest

from agents import ModelAgentBackend
from case_data import load_case, policy_for_case
from evidence import build_review_input


class ClaimPatchRepairTests(unittest.TestCase):
    def setUp(self):
        case = load_case("DISP-004")
        self.review = build_review_input(case, policy_for_case(case))
        self.original = {"role": "driver_advocate", "claims": [
            {"statement": "The recorded wait is eight minutes.", "evidence_ids": ["TRIP-001"],
             "fact_assertions": [{"fact_id": "FACT-001", "value": 8}]},
            {"statement": "Both contacts are recorded.", "evidence_ids": ["TRIP-001"]}],
            "counterpoints": [{"statement": "The arrival was recorded.", "evidence_ids": ["TRIP-001"],
                "fact_assertions": [{"fact_id": "FACT-006", "value": self.review.facts[5].value}]}],
            "unanswered_questions": ["Can the parties confirm the timeline?"]}

    def corrected(self):
        claim = copy.deepcopy(self.original["claims"][0])
        claim["statement"] = "The recorded wait is nine minutes."
        claim["fact_assertions"][0]["value"] = 9
        return claim

    def call(self, patches):
        original = self.original
        class Client:
            def __init__(self):
                self.payloads = []
            async def complete_json(self, instructions, payload):
                self.payloads.append(copy.deepcopy(payload))
                return copy.deepcopy(original if len(self.payloads) == 1 else patches), {"total_tokens": 5}
        client = Client()
        self.client = client
        return asyncio.run(ModelAgentBackend(client).advocate(self.review, "driver_advocate"))

    def test_patch_preserves_untouched_claims_counterpoints_role_and_questions(self):
        call = self.call({"patches": [{"section": "claims", "index": 0, "replacement": self.corrected()}]})
        out = call.result.model_dump(mode="json")
        self.assertEqual(out["claims"][0]["statement"], "The recorded wait is nine minutes.")
        self.assertEqual(out["claims"][1]["statement"], self.original["claims"][1]["statement"])
        self.assertEqual(out["counterpoints"][0]["fact_assertions"], self.original["counterpoints"][0]["fact_assertions"])
        self.assertEqual(out["unanswered_questions"], self.original["unanswered_questions"])
        self.assertEqual(out["role"], self.original["role"])
        self.assertEqual(call.usage["total_tokens"], 10)
        self.assertEqual(len(self.client.payloads), 2)
        self.assertEqual(self.client.payloads[1]["output_schema"]["title"], "AdvocateRepair")
        self.assertEqual(self.client.payloads[1]["schema_correction"]["required_fact_assertions"],
                         [{"fact_id": "FACT-001", "value": 9}])
        self.assertIn("assembled_response", call.validation_diagnostics["attempts"][1])

    def test_explicit_withdrawal_removes_only_targeted_claim(self):
        call = self.call({"patches": [{"section": "claims", "index": 0, "replacement": None}]})
        self.assertEqual(len(call.result.claims), 1)
        self.assertEqual(call.result.claims[0].statement, self.original["claims"][1]["statement"])
        self.assertEqual(call.result.counterpoints[0].statement, self.original["counterpoints"][0]["statement"])

    def test_unflagged_duplicate_missing_and_out_of_range_patches_are_rejected(self):
        good = {"section": "claims", "index": 0, "replacement": self.corrected()}
        for patches in ([], [good, good], [{**good, "index": 1}], [{**good, "index": 99}],
                        [{**good, "section": "counterpoints"}], [good, {**good, "index": 1}]):
            with self.subTest(patches=patches), self.assertRaises(ValueError):
                self.call({"patches": patches})
            self.assertEqual(len(self.client.payloads), 2)

    def test_full_argument_cannot_replace_patch_response(self):
        full = copy.deepcopy(self.original)
        full["claims"][0] = self.corrected()
        with self.assertRaisesRegex(ValueError, "Claim repair failed"):
            self.call(full)

    def test_replacement_cannot_drop_its_required_assertion(self):
        corrected = self.corrected()
        corrected["fact_assertions"] = []
        with self.assertRaisesRegex(ValueError, "must retain FACT-001"):
            self.call({"patches": [{"section": "claims", "index": 0, "replacement": corrected}]})

    def test_wrong_fact_and_unknown_citation_in_patch_remain_invalid(self):
        for defect in ("fact", "citation"):
            replacement = self.corrected()
            if defect == "fact":
                replacement["fact_assertions"][0]["value"] = 7
            else:
                replacement["evidence_ids"] = ["UNKNOWN"]
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                self.call({"patches": [{"section": "claims", "index": 0, "replacement": replacement}]})
            self.assertEqual(len(self.client.payloads), 2)

    def test_multiple_withdrawals_use_original_indices(self):
        self.original["claims"].insert(1, copy.deepcopy(self.original["claims"][0]))
        call = self.call({"patches": [{"section": "claims", "index": i, "replacement": None} for i in (0, 1)]})
        self.assertEqual(len(call.result.claims), 1)
        self.assertEqual(call.result.claims[0].statement, "Both contacts are recorded.")

    def test_repair_schema_limits_count_and_addresses_without_resending_full_argument(self):
        self.call({"patches": [{"section": "claims", "index": 0, "replacement": self.corrected()}]})
        payload = self.client.payloads[1]
        self.assertNotIn("previous_response", payload["schema_correction"])
        schema = payload["output_schema"]["properties"]["patches"]
        self.assertEqual(schema["minItems"], 1)
        self.assertEqual(schema["maxItems"], 1)
        address = schema["items"]["oneOf"][0]["properties"]
        self.assertEqual(address["section"]["const"], "claims")
        self.assertEqual(address["index"]["const"], 0)
