from datetime import datetime, timedelta
import unittest

from agents import AgentCall, ExampleAgentBackend, _policy_application
from case_data import load_case, policy_for_case
from checks import material_case_issues, no_show_facts, validate_final_ruling
from contracts import AdvocateResult, JudgeResult
from evidence import build_review_input
from workflow import run_review


class GoodwillUncertaintyTests(unittest.TestCase):
    def case(self, offset=0):
        case = load_case("DISP-004")
        trip = case["trip_data"]
        scheduled = datetime(2026, 11, 2, 10, 0, tzinfo=datetime.fromisoformat(trip["scheduled_time"]).tzinfo) + timedelta(days=offset)
        trip.update(scheduled_time=scheduled.isoformat(), driver_arrival_time=scheduled.isoformat(),
                    cancellation_time=(scheduled + timedelta(minutes=8)).isoformat())
        case["chat_logs"] = []
        case["app_events"] = []
        case["gps_telemetry"] = [
            {"id": f"POSITION-{i}", "timestamp": (scheduled + timedelta(minutes=i)).isoformat(),
             "lat": trip["pickup_location"]["lat"] + 0.01, "lng": trip["pickup_location"]["lng"]}
            for i in (0, 4, 8)]
        case["dispute_ticket"]["dispute_id"] = f"SYNTHETIC-{offset}"
        return case

    def ruling(self):
        return JudgeResult(action="final_ruling", ruling="reverse_charge", explanation="Refund the invalid fee.",
                           confidence=0.98, proposed_action={"amount_cents": 500, "refund_basis": "cancellation_fee"},
                           evidence_ids=["TRIP-001"], policy_ids=["POLICY-2.3", "POLICY-7.3"])

    def test_conflicting_presence_cannot_settle_goodwill_with_false_flags(self):
        for offset in (0, 7):
            case = self.case(offset)
            case["gps_telemetry"].reverse()
            policy = policy_for_case(case)
            with self.subTest(offset=offset):
                facts = no_show_facts(case, policy)
                self.assertFalse(facts["goodwill_eligibility_resolved"])
                self.assertFalse(facts["fee_eligible"])
                issues = material_case_issues(case, policy)
                self.assertTrue(any("goodwill" in issue.lower() for issue in issues))
                self.assertTrue(validate_final_ruling(case, policy, self.ruling()))
                review = build_review_input(case, policy)
                fact = next(f for f in review.facts if f.name == "goodwill_eligibility_resolved")
                self.assertFalse(fact.value)
                self.assertIn("POSITION-0", fact.evidence_ids)
                self.assertIn("unresolved", _policy_application(review).lower())

    def test_conflict_does_not_require_goodwill_referral_when_contact_excludes_credit(self):
        case = self.case()
        case["chat_logs"] = [{"id": "CONTACT-ONE", "sender": "driver", "type": "message",
                              "timestamp": case["trip_data"]["scheduled_time"], "content": "I am here."}]
        policy = policy_for_case(case)
        self.assertTrue(no_show_facts(case, policy)["goodwill_eligibility_resolved"])
        self.assertEqual(material_case_issues(case, policy), [])
        self.assertEqual(validate_final_ruling(case, policy, self.ruling()), [])

    def test_no_show_window_must_have_elapsed_for_goodwill_uncertainty(self):
        case = self.case()
        at = datetime.fromisoformat(case["trip_data"]["scheduled_time"])
        case["trip_data"]["cancellation_time"] = (at + timedelta(minutes=3)).isoformat()
        self.assertEqual(material_case_issues(case, policy_for_case(case)), [])

    def test_gps_before_reported_arrival_does_not_contradict_that_arrival(self):
        case = self.case()
        scheduled = datetime.fromisoformat(case["trip_data"]["scheduled_time"])
        case["trip_data"]["driver_arrival_time"] = (scheduled + timedelta(minutes=5)).isoformat()
        case["gps_telemetry"] = case["gps_telemetry"][:2]
        self.assertEqual(material_case_issues(case, policy_for_case(case)), [])

    def test_stale_pickup_ping_cannot_resolve_a_current_presence_conflict(self):
        case = self.case()
        scheduled = datetime.fromisoformat(case["trip_data"]["scheduled_time"])
        pickup = case["trip_data"]["pickup_location"]
        case["gps_telemetry"].append({"id": "STALE-POSITION", "timestamp": (scheduled - timedelta(hours=1)).isoformat(),
                                     "lat": pickup["lat"], "lng": pickup["lng"]})
        facts = no_show_facts(case, policy_for_case(case))
        self.assertFalse(facts["goodwill_eligibility_resolved"])
        self.assertTrue(material_case_issues(case, policy_for_case(case)))

    def test_stale_and_post_cancellation_fixes_do_not_establish_presence(self):
        for arrival_recorded in (True, False):
            case = self.case()
            scheduled = datetime.fromisoformat(case["trip_data"]["scheduled_time"])
            if not arrival_recorded:
                case["trip_data"]["driver_arrival_time"] = None
            pickup = case["trip_data"]["pickup_location"]
            case["gps_telemetry"] = [
                {"id": f"FIX-{offset}", "timestamp": (scheduled + timedelta(minutes=offset)).isoformat(),
                 "lat": pickup["lat"], "lng": pickup["lng"]} for offset in (-120, 10)]
            with self.subTest(arrival_recorded=arrival_recorded):
                facts = no_show_facts(case, policy_for_case(case))
                self.assertFalse(facts["timely_presence"])
                self.assertFalse(facts["arrival_verified"])
                self.assertFalse(facts["fee_eligible"])
                self.assertFalse(facts["driver_no_show"])  # Missing verification is not proven absence.

    def test_pre_booking_fix_cannot_corroborate_an_early_arrival(self):
        case = self.case()
        scheduled = datetime.fromisoformat(case["trip_data"]["scheduled_time"])
        early = scheduled - timedelta(minutes=20)
        case["trip_data"]["driver_arrival_time"] = early.isoformat()
        case["app_events"] = [{"id": "BOOKING", "event_type": "booking_confirmed",
                               "timestamp": (scheduled - timedelta(minutes=10)).isoformat()}]
        pickup = case["trip_data"]["pickup_location"]
        case["gps_telemetry"] = [{"id": "PRE-BOOKING", "timestamp": early.isoformat(),
                                  "lat": pickup["lat"], "lng": pickup["lng"]}]
        facts = no_show_facts(case, policy_for_case(case))
        self.assertFalse(facts["timely_presence"])
        self.assertFalse(facts["arrival_verified"])
        review = build_review_input(case, policy_for_case(case))
        for fact in review.facts:
            if fact.name in ("timely_presence", "arrival_verified", "waited_minutes"):
                self.assertIn("BOOKING", fact.evidence_ids)

    def test_presence_window_boundaries_are_inclusive_and_order_independent(self):
        for offset in (0, 5, 5 + 1 / 60):
            case = self.case()
            scheduled = datetime.fromisoformat(case["trip_data"]["scheduled_time"])
            at = scheduled + timedelta(minutes=offset)
            case["trip_data"]["driver_arrival_time"] = at.isoformat()
            case["gps_telemetry"] = [{"id": "PICKUP", "timestamp": at.isoformat(),
                "lat": case["trip_data"]["pickup_location"]["lat"],
                "lng": case["trip_data"]["pickup_location"]["lng"]}]
            case["gps_telemetry"].append({"id": "STALE", "timestamp": (scheduled - timedelta(hours=2)).isoformat(),
                "lat": case["trip_data"]["pickup_location"]["lat"],
                "lng": case["trip_data"]["pickup_location"]["lng"]})
            for reverse in (False, True):
                if reverse:
                    case["gps_telemetry"].reverse()
                with self.subTest(offset=offset, reverse=reverse):
                    facts = no_show_facts(case, policy_for_case(case))
                    self.assertTrue(facts["arrival_verified"])
                    self.assertEqual(facts["timely_presence"], offset <= 5)

    def test_missing_arrival_uses_booking_window_to_preserve_early_pickup(self):
        case = self.case()
        scheduled = datetime.fromisoformat(case["trip_data"]["scheduled_time"])
        case["trip_data"]["driver_arrival_time"] = None
        case["app_events"] = [{"id": "BOOKING", "event_type": "booking_confirmed",
                               "timestamp": (scheduled - timedelta(minutes=10)).isoformat()}]
        pickup = case["trip_data"]["pickup_location"]
        case["gps_telemetry"] = [{"id": f"FIX-{offset}", "timestamp": (scheduled + timedelta(minutes=offset)).isoformat(),
                                  "lat": pickup["lat"], "lng": pickup["lng"]} for offset in (-120, -2, 6)]
        facts = no_show_facts(case, policy_for_case(case))
        self.assertTrue(facts["timely_presence"])
        self.assertTrue(facts["arrival_verified"])
        self.assertFalse(facts["driver_no_show"])
        self.assertEqual(facts["waited_minutes"], 8)
        self.assertEqual(facts["goodwill_credit_cents"], 0)

    def test_current_or_matching_early_pickup_presence_rules_out_goodwill_conflict(self):
        for offset in (-2, 0):
            case = self.case()
            scheduled = datetime.fromisoformat(case["trip_data"]["scheduled_time"])
            at = scheduled + timedelta(minutes=offset)
            if offset < 0:
                case["trip_data"]["driver_arrival_time"] = at.isoformat()
            else:
                case["trip_data"]["driver_arrival_time"] = (scheduled + timedelta(minutes=4)).isoformat()
            pickup = case["trip_data"]["pickup_location"]
            case["gps_telemetry"].append({"id": "VERIFIED-POSITION", "timestamp": at.isoformat(),
                                         "lat": pickup["lat"], "lng": pickup["lng"]})
            with self.subTest(offset=offset):
                self.assertTrue(no_show_facts(case, policy_for_case(case))["goodwill_eligibility_resolved"])
                self.assertEqual(material_case_issues(case, policy_for_case(case)), [])

    def test_verified_presence_missing_gps_and_confirmed_no_show_remain_distinct(self):
        for scenario in ("verified", "missing", "confirmed_absence"):
            case = self.case()
            if scenario == "verified":
                for point in case["gps_telemetry"]:
                    point.update({k: case["trip_data"]["pickup_location"][k] for k in ("lat", "lng")})
            else:
                case["gps_telemetry"] = []
                if scenario == "confirmed_absence":
                    case["trip_data"].update(driver_arrival_time=None, driver_no_show_confirmed=True)
            facts = no_show_facts(case, policy_for_case(case))
            with self.subTest(scenario=scenario):
                self.assertTrue(facts["goodwill_eligibility_resolved"])
                self.assertEqual(facts["goodwill_credit_cents"], 500 if scenario == "confirmed_absence" else 0)
                self.assertEqual(material_case_issues(case, policy_for_case(case)), [])

    def test_workflow_refers_conflict_even_if_judge_returns_a_final_refund(self):
        ruling = self.ruling()
        class Backend:
            async def advocate(self, review, role, question=None):
                return AgentCall(AdvocateResult(role=role, claims=[], counterpoints=[], unanswered_questions=[]))

            async def judge(self, *args, **kwargs):
                return AgentCall(ruling)

        case = self.case()
        result = run_review(case, policy_for_case(case), Backend())
        self.assertEqual(result.status, "human_review")
        self.assertIsNone(result.failure_category)
        self.assertIsNone(result.judge_result.proposed_action)
        self.assertIsNone(result.final_explanation)
        self.assertTrue(any("goodwill" in issue.lower() for issue in result.validation_issues))

    def test_unresolved_credit_does_not_assert_zero_as_the_required_amount(self):
        case = self.case()
        ruling = self.ruling()
        ruling.proposed_action.goodwill_credit_cents = 500
        issues = validate_final_ruling(case, policy_for_case(case), ruling)
        self.assertTrue(any("unresolved" in issue for issue in issues))
        self.assertFalse(any("0 separate goodwill" in issue for issue in issues))

    def test_all_existing_examples_keep_their_decisions(self):
        from evaluation import LABELS
        for case_id, label in LABELS.items():
            case = load_case(case_id)
            result = run_review(case, policy_for_case(case), ExampleAgentBackend())
            actual = result.judge_result.ruling if result.status == "completed" else "human_review"
            with self.subTest(case=case_id):
                self.assertIsNone(result.failure_category)
                self.assertEqual(actual, label.expected_ruling)
