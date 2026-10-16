import asyncio
import copy
import json
import unittest

from agents import ExampleAgentBackend, ModelAgentBackend
from case_data import load_case, policy_for_case
from contracts import AdvocateResult, JudgeResult
from evidence import build_evidence_index, build_policy_index, build_review_input, fact_assertion_issues
from review_summary import build_decision_summary, build_review_report
from workflow import run_review


class DecisionSummaryTests(unittest.TestCase):
    def review(self, case_id):
        case = load_case(case_id)
        policy = policy_for_case(case)
        result = run_review(case, policy, ExampleAgentBackend())
        return case, policy, result, build_decision_summary(case, policy, result)

    def test_wait_uses_nine_post_schedule_minutes_and_recorded_cancellation(self):
        _, _, _, summary = self.review("DISP-004")
        wait = summary["checklist"][0]
        self.assertIn("9 min:", wait["observation"])
        self.assertIn("09:00:00+08:00", wait["observation"])
        self.assertIn("09:09:00+08:00", wait["observation"])
        self.assertEqual(summary["calculations"][0]["value"], 9)

    def test_party_messages_share_grounded_reason_and_actual_recommendation(self):
        for case_id, amount, component in (
            ("DISP-003", "5.00", "cancellation fee"),
            ("DISP-004", "0.00", "cancellation fee"),
            ("DISP-010", "0.83", "excess-distance fare"),
            ("DISP-011", "0.00", "fare"),
        ):
            with self.subTest(case=case_id):
                case, policy, result, summary = self.review(case_id)
                messages = summary.get("party_messages")
                self.assertIsNotNone(messages)
                self.assertEqual(set(messages), {"rider", "driver"})
                for message in messages.values():
                    self.assertEqual(message["explanation"], result.final_explanation)
                    self.assertIn(f"SGD {amount}", message["action"])
                    self.assertIn(component, message["action"])
                    self.assertNotIn("has been refunded", message["action"])
                self.assertIn("your", messages["rider"]["action"])
                self.assertIn("rider", messages["driver"]["action"])
                self.assertEqual(build_review_report(case, policy, result, "Example walkthrough")["summary"]["party_messages"], messages)

    def test_party_messages_do_not_present_referral_or_failure_as_a_final_ruling(self):
        case, policy, result, summary = self.review("DISP-012")
        self.assertIsNone(summary.get("party_messages"))
        result.failure_category = "model"
        self.assertIsNone(build_decision_summary(case, policy, result).get("party_messages"))

    def test_inclusive_arrival_boundary_is_not_reported_as_late(self):
        case = load_case("DISP-003")
        for record in case["gps_telemetry"][2:]:
            record.update({key: case["trip_data"]["pickup_location"][key] for key in ("lat", "lng")})
        policy = policy_for_case(case)
        result = run_review(case, policy, ExampleAgentBackend())
        summary = build_decision_summary(case, policy, result)
        arrival = next(row for row in summary["checklist"] if row["condition"].startswith("Arrival by"))
        self.assertEqual(arrival["status"], "met")
        self.assertEqual(summary["refund_cents"], 500)  # Missing call still voids the fee.

    def test_contact_after_free_wait_still_meets_before_cancellation_rule(self):
        case = load_case("DISP-004")
        for record in case["chat_logs"]:
            if record["sender"] == "driver":
                record["timestamp"] = "2026-09-25T09:08:30+08:00"
        for record in case["app_events"]:
            if record["event_type"] == "driver_called_rider":
                record["timestamp"] = "2026-09-25T09:08:30+08:00"
        policy = policy_for_case(case)
        result = run_review(case, policy, ExampleAgentBackend())
        summary = build_decision_summary(case, policy, result)
        contacts = [row for row in summary["checklist"] if row["condition"].startswith("At least one")]
        self.assertEqual([row["status"] for row in contacts], ["met", "met"])
        self.assertEqual(summary["refund_cents"], 0)

    def test_excess_distance_refunds_full_component_without_deducting_tolerance(self):
        for case_id, distance, cents in (("DISP-006", 2, 110), ("DISP-010", 1.5, 83)):
            with self.subTest(case=case_id):
                _, _, _, summary = self.review(case_id)
                self.assertEqual(summary["calculations"][0]["value"], distance)
                self.assertEqual(summary["calculations"][1]["value"], cents)
                self.assertEqual(summary["refund_cents"], cents)
                self.assertIn("tolerance is not deducted", summary["calculations"][1]["formula"])

    def test_justified_agreed_route_retains_charge_despite_extra_distance(self):
        _, _, _, summary = self.review("DISP-011")
        self.assertEqual(summary["calculations"][1]["value"], 83)
        self.assertEqual(summary["refund_cents"], 0)
        self.assertEqual(summary["outcome"], "Retain the charge")
        self.assertEqual([row["status"] for row in summary["checklist"]][-3:], ["met"] * 3)

    def test_bad_generated_prose_cannot_overwrite_authoritative_summary(self):
        for case_id, prose in (
            ("DISP-004", "Cancelled at 09:05 after 8 minutes; messages must be within the free-wait window."),
            ("DISP-006", "Refund 55 cents, or 110 cents."),
            ("DISP-010", "Refund 28 cents, or 83 cents; only 0.5 km is billable."),
            ("DISP-011", "Even a justified, notified and agreed detour requires a refund."),
        ):
            with self.subTest(case=case_id):
                case, policy, result, expected = self.review(case_id)
                result.judge_result.explanation = prose
                actual = build_decision_summary(case, policy, result)
                self.assertEqual(actual, expected)
                self.assertNotIn(prose, json.dumps(actual))
                report = build_review_report(case, policy, result, "Example walkthrough")
                self.assertEqual(report["workflow"]["judge_result"]["explanation"], prose)
                self.assertIn("not semantically certified", report["explanation_validation"])

    def test_referrals_and_failures_never_display_calculated_component_as_refund(self):
        for case_id in ("DISP-005", "DISP-008", "DISP-009", "DISP-012"):
            with self.subTest(case=case_id):
                case, policy, result, summary = self.review(case_id)
                self.assertIsNone(summary["refund_cents"])
                self.assertIsNone(summary["goodwill_credit_cents"])
                self.assertTrue(summary["review_issues"])
                result.failure_category = "model"
                summary = build_decision_summary(case, policy, result)
                self.assertEqual(summary["outcome"], "Review could not be completed")
                self.assertIsNone(summary["refund_cents"])

    def test_summary_sources_resolve_and_timeline_is_chronological_for_all_cases(self):
        from datetime import datetime

        for number in range(2, 13):
            with self.subTest(case=number):
                case, policy, _, summary = self.review(f"DISP-{number:03d}")
                evidence, clauses = build_evidence_index(case), build_policy_index(policy)
                for row in summary["checklist"] + summary["calculations"] + summary["timeline"]:
                    self.assertTrue(row["evidence_ids"])
                    self.assertTrue(set(row["evidence_ids"]) <= evidence.keys())
                    self.assertTrue(set(row.get("policy_ids", [])) <= clauses.keys())
                timestamps = [datetime.fromisoformat(row["timestamp"]) for row in summary["timeline"]]
                self.assertEqual(timestamps, sorted(timestamps))

    def test_report_serializes_without_profiles_and_preserves_fact_sources(self):
        case, policy, result, summary = self.review("DISP-004")
        report = build_review_report(case, policy, result, "Example walkthrough")
        serialized = json.dumps(report)
        self.assertNotIn("rider_profile", serialized)
        self.assertNotIn("driver_profile", serialized)
        self.assertNotIn(case["rider_profile"]["name"], serialized)
        self.assertEqual(report["summary"], summary)
        self.assertEqual(report["mode"], "Example walkthrough")
        self.assertTrue(report["facts"][0]["evidence_ids"])

    def test_result_cannot_be_reused_for_another_case(self):
        _, _, result, _ = self.review("DISP-004")
        case = load_case("DISP-003")
        with self.assertRaisesRegex(ValueError, "different case"):
            build_decision_summary(case, policy_for_case(case), result)


class FactAssertionTests(unittest.TestCase):
    def test_repair_payload_lists_canonical_assertions_for_advocates_and_judge(self):
        case = load_case("DISP-004")
        review = build_review_input(case, policy_for_case(case))
        examples = ExampleAgentBackend().examples["DISP-004"]
        for role in ("rider_advocate", "driver_advocate", "judge"):
            original = copy.deepcopy(examples["judge_final_ruling" if role == "judge" else role])
            class Client:
                def __init__(self):
                    self.payloads = []
                async def complete_json(self, instructions, payload):
                    self.payloads.append(copy.deepcopy(payload))
                    output = copy.deepcopy(original)
                    assertions = ([{"fact_id": "FACT-001", "value": 8}, {"fact_id": "FACT-002", "value": True},
                                   {"fact_id": "FACT-UNKNOWN", "value": 99}] if len(self.payloads) == 1
                                  else payload["schema_correction"]["required_fact_assertions"])
                    target = output if role == "judge" else output["claims"][0]
                    target["fact_assertions"] = assertions
                    return output, {"total_tokens": 5}
            client = Client()
            backend = ModelAgentBackend(client)
            if role == "judge":
                rider = AdvocateResult.model_validate(examples["rider_advocate"])
                driver = AdvocateResult.model_validate(examples["driver_advocate"])
                call = asyncio.run(backend.judge(review, rider, driver))
            else:
                call = asyncio.run(backend.advocate(review, role))
            with self.subTest(role=role):
                required = client.payloads[1]["schema_correction"]["required_fact_assertions"]
                self.assertEqual(required, [{"fact_id": "FACT-001", "value": 9}, {"fact_id": "FACT-002", "value": True}])
                self.assertIs(type(required[1]["value"]), bool)
                self.assertEqual(len(client.payloads), 2)
                self.assertEqual(call.usage["total_tokens"], 10)

    def test_repair_keeps_computed_credit_and_unresolved_entitlement_distinct(self):
        case = load_case("DISP-004")
        case["chat_logs"] = []
        case["app_events"] = []
        for point in case["gps_telemetry"]:
            point["lat"] += 0.01
        review = build_review_input(case, policy_for_case(case))
        original = {"role": "rider_advocate", "claims": [{"statement": "The separate goodwill entitlement is unresolved.",
            "evidence_ids": ["TRIP-001"], "policy_ids": ["POLICY-2.4"]}], "counterpoints": [], "unanswered_questions": []}
        class Client:
            def __init__(self):
                self.payloads = []
            async def complete_json(self, instructions, payload):
                self.payloads.append(copy.deepcopy(payload))
                output = copy.deepcopy(original)
                output["claims"][0]["fact_assertions"] = ([{"fact_id": "FACT-005", "value": 500},
                    {"fact_id": "FACT-011", "value": False}] if len(self.payloads) == 1
                    else payload["schema_correction"]["required_fact_assertions"])
                return output, {}
        client = Client()
        call = asyncio.run(ModelAgentBackend(client).advocate(review, "rider_advocate"))
        self.assertEqual(call.result.claims[0].fact_assertions[0].value, 0)
        self.assertFalse(call.result.claims[0].fact_assertions[1].value)
        repair = client.payloads[1]["schema_correction"]
        self.assertIn("unresolved", client.payloads[1]["policy_application"])
        self.assertIn("entitlement", repair["instruction"])

    def test_recorded_numeric_defects_are_rejected_even_with_real_citations(self):
        for case_id, name, wrong in (
            ("DISP-004", "waited_minutes", 8),
            ("DISP-006", "excess_distance_cents", 55),
            ("DISP-010", "deviation_km", 0.5),
            ("DISP-010", "excess_distance_cents", 28),
            ("DISP-011", "justification", "unsupported"),
            ("DISP-004", "timely_presence", False),
        ):
            with self.subTest(case=case_id, fact=name):
                case = load_case(case_id)
                review = build_review_input(case, policy_for_case(case))
                fact = next(fact for fact in review.facts if fact.name == name)
                output = copy.deepcopy(ExampleAgentBackend().examples[case_id]["judge_final_ruling"])
                output["fact_assertions"] = [{"fact_id": fact.id, "value": wrong}]
                self.assertTrue(fact_assertion_issues(JudgeResult.model_validate(output), review))
                output["fact_assertions"][0]["value"] = fact.value
                self.assertEqual(fact_assertion_issues(JudgeResult.model_validate(output), review), [])

    def test_unknown_fact_and_boolean_number_confusion_are_rejected(self):
        case = load_case("DISP-004")
        review = build_review_input(case, policy_for_case(case))
        output = copy.deepcopy(ExampleAgentBackend().examples["DISP-004"]["judge_final_ruling"])
        output["fact_assertions"] = [{"fact_id": "FACT-999", "value": 9}, {"fact_id": "FACT-002", "value": 1}]
        self.assertEqual(len(fact_assertion_issues(JudgeResult.model_validate(output), review)), 2)

    def test_live_fact_correction_shares_one_retry_and_persistent_errors_fail(self):
        case = load_case("DISP-004")
        review = build_review_input(case, policy_for_case(case))
        examples = ExampleAgentBackend().examples["DISP-004"]

        class Client:
            def __init__(self, persistent):
                self.persistent = persistent
                self.judge_payloads = []

            async def complete_json(self, instructions, payload):
                if "rider_argument" not in payload:
                    role = "rider_advocate" if "rider_advocate" in instructions else "driver_advocate"
                    return copy.deepcopy(examples[role]), {}
                self.judge_payloads.append(copy.deepcopy(payload))
                output = copy.deepcopy(examples["judge_final_ruling"])
                value = 8 if self.persistent or len(self.judge_payloads) == 1 else 9
                output["fact_assertions"] = [{"fact_id": "FACT-001", "value": value}]
                return output, {"total_tokens": 5}

        for persistent in (False, True):
            with self.subTest(persistent=persistent):
                client = Client(persistent)
                result = run_review(case, policy_for_case(case), ModelAgentBackend(client))
                self.assertEqual(len(client.judge_payloads), 2)
                self.assertIn("must equal 9", client.judge_payloads[1]["schema_correction"]["errors"][0])
                if persistent:
                    self.assertEqual(result.failure_category, "validation")
                    self.assertIsNone(result.judge_result.proposed_action)
                else:
                    self.assertEqual(result.status, "completed")
                    entry = next(entry for entry in result.activity_log if entry.actor == "judge")
                    self.assertEqual(entry.output["schema_retries"], 1)
                    self.assertEqual(entry.output["usage"]["total_tokens"], 10)

    def test_advocate_assertions_are_checked_before_judge(self):
        case = load_case("DISP-004")
        review = build_review_input(case, policy_for_case(case))
        output = copy.deepcopy(ExampleAgentBackend().examples["DISP-004"]["rider_advocate"])
        output["claims"][0]["fact_assertions"] = [{"fact_id": "FACT-001", "value": 8}]

        class Client:
            calls = 0

            async def complete_json(self, instructions, payload):
                self.calls += 1
                return output, {}

        client = Client()
        with self.assertRaisesRegex(ValueError, "Fact assertion correction failed"):
            asyncio.run(ModelAgentBackend(client).advocate(review, "rider_advocate"))
        self.assertEqual(client.calls, 2)

    def test_correction_cannot_hide_a_known_wrong_fact_by_dropping_its_assertion(self):
        case = load_case("DISP-004")
        review = build_review_input(case, policy_for_case(case))
        output = copy.deepcopy(ExampleAgentBackend().examples["DISP-004"]["rider_advocate"])

        class Client:
            calls = 0

            async def complete_json(self, instructions, payload):
                self.calls += 1
                response = copy.deepcopy(output)
                if self.calls == 1:
                    response["claims"][0]["fact_assertions"] = [{"fact_id": "FACT-001", "value": 8}]
                return response, {}

        client = Client()
        with self.assertRaisesRegex(ValueError, "must retain FACT-001"):
            asyncio.run(ModelAgentBackend(client).advocate(review, "rider_advocate"))
        self.assertEqual(client.calls, 2)
