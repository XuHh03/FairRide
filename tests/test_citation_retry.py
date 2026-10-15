import asyncio
import copy
import unittest

from agents import ExampleAgentBackend, ModelAgentBackend
from case_data import load_case, policy_for_case
from contracts import AdvocateResult
from evidence import build_review_input, citation_issues, resolve_fact_citations
from workflow import run_review


class ScriptedClient:
    def __init__(self, responses):
        self.responses = responses
        self.payloads = []

    async def complete_json(self, instructions, payload):
        self.payloads.append(copy.deepcopy(payload))
        return copy.deepcopy(self.responses[len(self.payloads) - 1]), {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}


class CitationRetryTests(unittest.TestCase):
    def setUp(self):
        case = load_case("DISP-003")
        self.review = build_review_input(case, policy_for_case(case))
        self.examples = ExampleAgentBackend().examples["DISP-003"]
        self.valid = copy.deepcopy(self.examples["rider_advocate"])

    def advocate(self, client):
        return asyncio.run(ModelAgentBackend(client).advocate(self.review, "rider_advocate"))

    def test_valid_response_needs_only_one_call(self):
        client = ScriptedClient([self.valid])
        self.advocate(client)
        self.assertEqual(len(client.payloads), 1)
        self.assertIn("CHAT-001", client.payloads[0]["allowed_evidence_ids"])
        self.assertNotIn("POLICY-2.4", client.payloads[0]["allowed_evidence_ids"])
        self.assertIn("POLICY-2.4", client.payloads[0]["allowed_policy_ids"])

    def test_fact_citation_is_resolved_without_another_model_call(self):
        invalid = copy.deepcopy(self.valid)
        invalid["claims"][0]["evidence_ids"] = ["FACT-004"]
        client = ScriptedClient([invalid])
        call = self.advocate(client)
        fact = next(f for f in self.review.facts if f.id == "FACT-004")
        self.assertEqual(call.result.claims[0].evidence_ids, fact.evidence_ids)
        self.assertEqual(call.result.claims[0].statement, invalid["claims"][0]["statement"])
        self.assertEqual(call.result.claims[0].policy_ids, invalid["claims"][0]["policy_ids"])
        self.assertEqual(call.usage["total_tokens"], 5)
        self.assertEqual(call.citation_retries, 0)
        self.assertEqual(len(client.payloads), 1)
        self.assertEqual(call.citation_resolutions[0]["fact_id"], "FACT-004")

    def test_both_fact_references_are_expanded_and_sources_deduplicated(self):
        output = copy.deepcopy(self.valid)
        output["claims"][0]["evidence_ids"] = ["TRIP-001", "FACT-001", "FACT-004"]
        client = ScriptedClient([output])
        call = self.advocate(client)
        sources = call.result.claims[0].evidence_ids
        expected = list(dict.fromkeys(["TRIP-001"] + self.review.facts[0].evidence_ids + self.review.facts[3].evidence_ids))
        self.assertEqual(sources, expected)
        self.assertEqual(len(sources), len(set(sources)))
        self.assertEqual(len(call.citation_resolutions), 2)

    def test_judge_fact_citations_are_resolved_without_changing_ruling(self):
        output = copy.deepcopy(self.examples["judge_final_ruling"])
        output["evidence_ids"] = ["FACT-001", "FACT-004"]
        client = ScriptedClient([output])
        rider = AdvocateResult.model_validate(self.valid)
        driver = AdvocateResult.model_validate(self.examples["driver_advocate"])
        call = asyncio.run(ModelAgentBackend(client).judge(self.review, rider, driver))
        self.assertEqual(call.result.ruling, output["ruling"])
        self.assertEqual(call.result.proposed_action.amount_cents, output["proposed_action"]["amount_cents"])
        self.assertEqual(call.result.explanation, output["explanation"])
        self.assertNotIn("FACT-004", call.result.evidence_ids)
        self.assertEqual(len(client.payloads), 1)

    def test_resolution_does_not_mutate_the_original_response(self):
        output = copy.deepcopy(self.valid)
        output["counterpoints"][0]["evidence_ids"] = ["FACT-001"]
        original = AdvocateResult.model_validate(output)
        resolved, mappings = resolve_fact_citations(original, self.review)
        self.assertEqual(original.counterpoints[0].evidence_ids, ["FACT-001"])
        self.assertEqual(resolved.counterpoints[0].evidence_ids, self.review.facts[0].evidence_ids)
        self.assertEqual(resolved.counterpoints[0].statement, original.counterpoints[0].statement)
        self.assertEqual(mappings[0]["location"], "counterpoints.0")

    def test_empty_or_unknown_provenance_is_not_expanded(self):
        for sources in ([], ["GPS-999"]):
            with self.subTest(sources=sources):
                review = self.review.model_copy(deep=True)
                review.facts[3].evidence_ids = sources
                output = copy.deepcopy(self.valid)
                output["claims"][0]["evidence_ids"] = ["FACT-004"]
                resolved, mappings = resolve_fact_citations(AdvocateResult.model_validate(output), review)
                self.assertEqual(mappings, [])
                issues = citation_issues(resolved, {r.id for r in review.evidence}, {c.id for c in review.policy.clauses})
                self.assertIn("Unknown evidence ID: FACT-004", issues)

    def test_judge_policy_in_evidence_field_is_retried(self):
        valid = copy.deepcopy(self.examples["judge_final_ruling"])
        invalid = copy.deepcopy(valid)
        invalid["evidence_ids"].append("POLICY-2.4")
        client = ScriptedClient([invalid, valid])
        rider = AdvocateResult.model_validate(self.valid)
        driver = AdvocateResult.model_validate(self.examples["driver_advocate"])
        call = asyncio.run(ModelAgentBackend(client).judge(self.review, rider, driver))
        self.assertEqual(call.result.evidence_ids, valid["evidence_ids"])
        self.assertIn("Unknown evidence ID: POLICY-2.4", client.payloads[1]["citation_correction"]["errors"])
        self.assertEqual(len(client.payloads), 2)

    def test_retry_is_bounded_and_unknown_sources_remain_invalid(self):
        invalid = copy.deepcopy(self.valid)
        invalid["claims"][0]["evidence_ids"] = ["INVENTED-001"]
        client = ScriptedClient([invalid, invalid])
        with self.assertRaisesRegex(ValueError, "Unknown evidence ID: INVENTED-001"):
            self.advocate(client)
        self.assertEqual(len(client.payloads), 2)

    def test_policy_ids_cannot_contain_evidence_records(self):
        invalid = copy.deepcopy(self.valid)
        invalid["claims"][0]["policy_ids"] = ["CHAT-001"]
        client = ScriptedClient([invalid, self.valid])
        self.advocate(client)
        self.assertIn("Unknown policy ID: CHAT-001", client.payloads[1]["citation_correction"]["errors"])

    def test_missing_fields_get_one_schema_retry_then_fail(self):
        client = ScriptedClient([{"role": "rider_advocate"}, {"role": "rider_advocate"}])
        with self.assertRaisesRegex(ValueError, "Schema correction failed"):
            self.advocate(client)
        self.assertEqual(len(client.payloads), 2)

    def workflow_with_bad_first_citation(self, persistent=False):
        examples = self.examples

        class Client:
            async def complete_json(self, instructions, payload):
                if "argument" in payload:
                    return {"findings": []}, {"total_tokens": 5}
                if "rider_argument" in payload:
                    output = copy.deepcopy(examples["judge_final_ruling"])
                else:
                    role = "rider_advocate" if "rider_advocate" in instructions else "driver_advocate"
                    output = copy.deepcopy(examples[role])
                    if role == "rider_advocate" and (persistent or "citation_correction" not in payload):
                        output["claims"][0]["evidence_ids"] = ["FACT-999" if persistent else "FACT-004"]
                return output, {"total_tokens": 5}

        case = load_case("DISP-003")
        return run_review(case, policy_for_case(case), ModelAgentBackend(Client()))

    def test_corrected_citation_reaches_validated_refund(self):
        result = self.workflow_with_bad_first_citation()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.judge_result.proposed_action.amount_cents, 500)
        entry = next(e for e in result.activity_log if e.actor == "rider_advocate")
        self.assertEqual(entry.output["citation_retries"], 0)
        self.assertEqual(entry.output["usage"]["total_tokens"], 5)
        self.assertEqual(entry.output["citation_resolutions"][0]["fact_id"], "FACT-004")

    def test_persistent_error_remains_operational_validation_failure(self):
        result = self.workflow_with_bad_first_citation(persistent=True)
        self.assertEqual(result.status, "human_review")
        self.assertEqual(result.failure_category, "validation")
        self.assertIsNone(result.judge_result.proposed_action)
        self.assertIn("Citation correction failed", result.validation_issues[0])
