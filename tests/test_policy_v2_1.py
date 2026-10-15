import copy
import unittest

from agents import ExampleAgentBackend
from case_data import load_case, policy_for_case
from checks import no_show_facts, route_deviation_facts, validate_final_ruling, escalation_issues, account_review_flags
from contracts import JudgeResult
from workflow import run_review


def decision(ruling="uphold_charge", amount=0, confidence=0.98, basis="cancellation_fee"):
    return JudgeResult(action="final_ruling", ruling=ruling,
                       proposed_action={"amount_cents": amount, "refund_basis": basis},
                       confidence=confidence, explanation="Apply supplied v2.1 policy.",
                       evidence_ids=["TRIP-001"], policy_ids=["POLICY-2.3", "POLICY-7.3"])


class PolicyV21Tests(unittest.TestCase):
    def test_governing_policy_is_source_linked_v21(self):
        policy = policy_for_case(load_case("DISP-002"))
        self.assertEqual(policy["version"], "2.1")
        self.assertEqual(policy["wait_start_event"], "scheduled_time")
        self.assertEqual(policy["no_show_threshold_min"], 5)
        self.assertIn("Document 2", policy["source_reference"])

    def test_early_arrival_does_not_count_before_schedule(self):
        case = load_case("DISP-002")
        facts = no_show_facts(case, policy_for_case(case))
        self.assertEqual(facts["waited_minutes"], 6)
        self.assertTrue(facts["fee_eligible"])

    def test_both_contacts_must_precede_cancellation(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["chat_logs"] = [r for r in case["chat_logs"] if r["type"] != "call"]
        case["app_events"] = [r for r in case["app_events"] if r["event_type"] != "driver_called_rider"]
        facts = no_show_facts(case, policy_for_case(case))
        self.assertFalse(facts["fee_eligible"])
        self.assertTrue(validate_final_ruling(case, policy_for_case(case), decision("no_action")))

    def test_missing_call_voids_fee_even_at_five_minutes(self):
        case = load_case("DISP-007")
        self.assertFalse(no_show_facts(case, policy_for_case(case))["fee_eligible"])

    def test_missing_message_also_voids_fee_with_calls_present(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["chat_logs"] = [r for r in case["chat_logs"] if r["type"] != "message"]
        facts = no_show_facts(case, policy_for_case(case))
        self.assertEqual(facts["message_count"], 0)
        self.assertEqual(facts["call_count"], 2)
        self.assertFalse(facts["fee_eligible"])

    def test_driver_arrival_five_minute_boundary_is_inclusive(self):
        case = copy.deepcopy(load_case("DISP-003"))
        self.assertFalse(no_show_facts(case, policy_for_case(case))["driver_no_show"])
        case["trip_data"]["driver_arrival_time"] = "2026-09-20T08:50:01+08:00"
        self.assertTrue(no_show_facts(case, policy_for_case(case))["driver_no_show"])

    def test_exact_two_km_is_allowed_but_any_excess_requires_referral(self):
        case = copy.deepcopy(load_case("DISP-006"))
        self.assertEqual(escalation_issues(case, policy_for_case(case), 0.99), [])
        actual = next(r for r in case["route_data"] if r["type"] == "actual")
        actual["distance_km"] += 0.001
        self.assertTrue(any("above 2 km" in issue for issue in escalation_issues(case, policy_for_case(case), 0.99)))

    def test_goodwill_credit_is_separate_from_refund(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["trip_data"]["driver_arrival_time"] = None
        case["trip_data"]["driver_no_show_confirmed"] = True
        case["gps_telemetry"] = []
        case["chat_logs"] = []
        case["app_events"] = []
        facts = no_show_facts(case, policy_for_case(case))
        self.assertEqual(facts["goodwill_credit_cents"], 500)
        self.assertFalse(facts["fee_eligible"])

    def test_above_two_km_is_mandatory_referral_before_agents(self):
        class MustNotCall(ExampleAgentBackend):
            async def advocate(self, *args, **kwargs):
                raise AssertionError("Mandatory referral must not call agents")
        case = load_case("DISP-008")
        result = run_review(case, policy_for_case(case), MustNotCall())
        self.assertEqual(result.status, "human_review")
        self.assertTrue(result.mandatory_escalation)
        self.assertIsNone(result.failure_category)

    def test_safety_indicator_overrides_selected_category(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["dispute_ticket"]["description"] = "The driver threatened me and I felt unsafe."
        result = run_review(case, policy_for_case(case), ExampleAgentBackend())
        self.assertTrue(result.mandatory_escalation)
        self.assertEqual(result.activity_log[0].actor, "system")

    def test_fraud_flag_raises_confidence_not_fault(self):
        case = load_case("DISP-002")
        self.assertTrue(escalation_issues(case, policy_for_case(case), 0.94))
        self.assertEqual(escalation_issues(case, policy_for_case(case), 0.95), [])

    def test_unjustified_small_route_refunds_excess_distance_only(self):
        case = load_case("DISP-010")
        facts = route_deviation_facts(case, policy_for_case(case))
        self.assertEqual(facts["deviation_km"], 1.5)
        self.assertEqual(facts["excess_distance_cents"], 83)
        self.assertNotEqual(facts["excess_distance_cents"], facts["fare_difference_cents"])
        output = decision("partial_refund", 83, 0.9, "excess_distance_fare")
        output.policy_ids = ["POLICY-1.3", "POLICY-7.1"]
        self.assertEqual(validate_final_ruling(case, policy_for_case(case), output), [])

    def test_justified_but_unnotified_route_has_no_invented_formula(self):
        case = copy.deepcopy(load_case("DISP-011"))
        case["chat_logs"] = []
        result = run_review(case, policy_for_case(case), ExampleAgentBackend())
        self.assertTrue(result.mandatory_escalation)
        self.assertTrue(any("formula" in issue for issue in result.validation_issues))

    def test_route_confidence_threshold_and_monetry_boundary(self):
        case = load_case("DISP-010")
        self.assertTrue(escalation_issues(case, policy_for_case(case), 0.79))
        self.assertEqual(escalation_issues(case, policy_for_case(case), 0.8), [])
        case["dispute_ticket"]["disputed_amount_cents"] = 5001
        self.assertTrue(escalation_issues(case, policy_for_case(case), 1))

    def test_contacts_at_or_after_cancel_do_not_count(self):
        case = copy.deepcopy(load_case("DISP-004"))
        cancelled = case["trip_data"]["cancellation_time"]
        for row in case["chat_logs"]:
            if row["sender"] == "driver":
                row["timestamp"] = cancelled
        case["app_events"] = []
        self.assertFalse(no_show_facts(case, policy_for_case(case))["fee_eligible"])

    def test_wait_and_distance_boundaries(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["trip_data"]["cancellation_time"] = "2026-09-25T09:05:00+08:00"
        self.assertTrue(no_show_facts(case, policy_for_case(case))["fee_eligible"])
        case["trip_data"]["cancellation_time"] = "2026-09-25T09:04:59+08:00"
        self.assertFalse(no_show_facts(case, policy_for_case(case))["fee_eligible"])
        route = copy.deepcopy(load_case("DISP-010"))
        route["route_data"][1]["distance_km"] = 7.5
        self.assertFalse(route_deviation_facts(route, policy_for_case(route))["deviation_significant"])
        self.assertEqual(escalation_issues(route, policy_for_case(route), 0.8), [])

    def test_contact_call_records_are_deduplicated(self):
        case = load_case("DISP-002")
        self.assertEqual(no_show_facts(case, policy_for_case(case))["call_count"], 1)

    def test_wrong_no_show_charge_cannot_be_retained(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["trip_data"]["cancellation_fee"] = 8
        self.assertTrue(validate_final_ruling(case, policy_for_case(case), decision()))

    def test_safety_escalates_even_with_incomplete_trip_data(self):
        case = load_case("DISP-004")
        policy = policy_for_case(case)
        case["trip_data"] = {}
        case["dispute_ticket"]["description"] = "The driver threatened me."
        result = run_review(case, policy, ExampleAgentBackend())
        self.assertTrue(result.mandatory_escalation)
        self.assertIsNone(result.failure_category)

    def test_notification_order_uses_actual_time_not_string_order(self):
        case = copy.deepcopy(load_case("DISP-011"))
        case["chat_logs"][0]["timestamp"] = "2026-09-28T06:03:00+00:00"
        self.assertFalse(route_deviation_facts(case, policy_for_case(case))["rider_informed"])

    def test_repeat_no_shows_need_three_unique_records_in_rolling_window(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["rider_profile"]["no_show_cancellations"] = [
            {"trip_id": "A", "timestamp": "2026-09-01T09:00:00+08:00"},
            {"trip_id": "B", "timestamp": "2026-09-10T09:00:00+08:00"},
            {"trip_id": "C", "timestamp": "2026-09-20T09:00:00+08:00"},
            {"trip_id": "OLD", "timestamp": "2026-08-01T09:00:00+08:00"}]
        self.assertTrue(account_review_flags(case))
        self.assertTrue(no_show_facts(case, policy_for_case(case))["fee_eligible"])
        case["rider_profile"]["no_show_cancellations"][2]["trip_id"] = "B"
        self.assertEqual(account_review_flags(case), [])

    def test_verbal_abuse_and_inappropriate_behavior_are_safety_indicators(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["dispute_ticket"]["description"] = "The driver behaved inappropriately and verbally abused me."
        self.assertTrue(escalation_issues(case, policy_for_case(case)))

    def test_car_accident_and_threat_require_referral_without_agent_calls(self):
        class MustNotCall(ExampleAgentBackend):
            async def advocate(self, *args, **kwargs):
                raise AssertionError("Safety incidents must not call agents")

        for description in ("The driver was in a car accident during the trip.", "The driver made a threat against me."):
            with self.subTest(description=description):
                case = copy.deepcopy(load_case("DISP-004"))
                case["dispute_ticket"]["description"] = description
                result = run_review(case, policy_for_case(case), MustNotCall())
                self.assertTrue(result.mandatory_escalation)
                self.assertIsNone(result.failure_category)
                self.assertIsNone(result.judge_result.proposed_action)

    def test_safety_app_event_requires_referral_before_agents(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["app_events"].append({"id": "EVENT-SAFETY", "event_type": "safety_incident", "details": "Traffic accident during the trip."})
        result = run_review(case, policy_for_case(case), ExampleAgentBackend())
        self.assertTrue(result.mandatory_escalation)
        self.assertEqual(len(result.activity_log), 1)

    def test_safety_indicators_in_event_details_are_checked(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["app_events"].append({"id": "EVENT-SAFETY", "event_type": "rider_report", "details": "The driver made a threat against me."})
        self.assertTrue(escalation_issues(case, policy_for_case(case)))

    def test_explicit_rider_refusal_is_not_agreement(self):
        case = copy.deepcopy(load_case("DISP-011"))
        case["chat_logs"][1].update(content="I do not agree.", route_change_acknowledged=False)
        self.assertFalse(route_deviation_facts(case, policy_for_case(case))["rider_agreed"])

    def test_departure_before_free_wait_ends_invalidates_fee(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["gps_telemetry"] = [case["gps_telemetry"][2], {
            "id": "GPS-DEPARTED", "timestamp": "2026-09-25T09:00:00+08:00",
            "lat": 1.33, "lng": 103.87, "speed_kmh": 30, "status": "departed"}]
        self.assertFalse(no_show_facts(case, policy_for_case(case))["fee_eligible"])

    def test_missing_arrival_metadata_does_not_prove_driver_no_show(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["trip_data"]["driver_arrival_time"] = None
        case["chat_logs"] = []
        case["app_events"] = []
        self.assertEqual(no_show_facts(case, policy_for_case(case))["goodwill_credit_cents"], 0)
        case["trip_data"]["driver_arrival_time"] = "2026-09-25T09:07:00+08:00"
        facts = no_show_facts(case, policy_for_case(case))
        self.assertFalse(facts["driver_no_show"])
        self.assertEqual(facts["goodwill_credit_cents"], 0)

    def test_wait_does_not_start_before_first_verified_presence(self):
        case = copy.deepcopy(load_case("DISP-004"))
        case["gps_telemetry"] = [
            {"id": "GPS-AWAY", "timestamp": "2026-09-25T09:00:00+08:00", "lat": 1.33, "lng": 103.87},
            dict(case["gps_telemetry"][2], timestamp="2026-09-25T09:08:00+08:00")]
        facts = no_show_facts(case, policy_for_case(case))
        self.assertEqual(facts["waited_minutes"], 1)
        self.assertFalse(facts["fee_eligible"])
        case["trip_data"]["cancellation_time"] = "2026-09-25T09:15:00+08:00"
        facts = no_show_facts(case, policy_for_case(case))
        self.assertTrue(facts["driver_no_show"])
        self.assertFalse(facts["fee_eligible"])

    def test_later_refusal_overrides_earlier_agreement(self):
        case = copy.deepcopy(load_case("DISP-011"))
        case["chat_logs"].append({"id": "CHAT-REFUSAL", "sender": "rider", "type": "message",
            "timestamp": "2026-09-28T14:01:00+08:00", "content": "I do not agree.", "route_change_acknowledged": False})
        self.assertFalse(route_deviation_facts(case, policy_for_case(case))["rider_agreed"])
