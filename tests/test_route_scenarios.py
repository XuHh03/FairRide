import copy
import unittest
from decimal import Decimal

from agents import ExampleAgentBackend
from case_data import load_case, policy_for_case
from checks import material_case_issues, route_deviation_facts, validate_final_ruling
from contracts import JudgeResult
from evaluation import LABELS, run_single_case
from evidence import build_review_input
from workflow import run_review


class RouteScenarioTests(unittest.TestCase):
    def test_existing_fare_totals_are_consistent(self):
        case = load_case("DISP-005")
        total = sum(Decimal(str(item["amount"])) for item in case["fare_items"]
                    if item["component"] not in ("total_charged", "estimated_total"))
        self.assertEqual(total, Decimal(str(case["trip_data"]["charged_fare"])))
        self.assertEqual(route_deviation_facts(case, policy_for_case(case))["fare_difference_cents"], 693)

    def test_justified_detour_completes_with_no_refund(self):
        case = load_case("DISP-008")
        policy = policy_for_case(case)
        self.assertTrue(route_deviation_facts(case, policy)["deviation_significant"])
        result = run_review(case, policy, ExampleAgentBackend())
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.judge_result.ruling, "uphold_charge")
        self.assertEqual(result.judge_result.proposed_action.amount_cents, 0)
        self.assertEqual(run_single_case("DISP-008", "example").category, "correct_ruling")

    def test_conflicting_alerts_escalate_after_one_round(self):
        case = load_case("DISP-009")
        result = run_review(case, policy_for_case(case), ExampleAgentBackend())
        self.assertEqual(result.status, "human_review")
        self.assertIsNone(result.failure_category)
        self.assertTrue(any("conflict" in issue.lower() for issue in result.validation_issues))
        self.assertEqual(sum(entry.actor == "judge" for entry in result.activity_log), 2)
        self.assertEqual(LABELS["DISP-009"].expected_ruling, "human_review")
        self.assertEqual(run_single_case("DISP-009", "example").category, "appropriate_escalation")

    def test_confirmed_closure_does_not_allow_partial_refund(self):
        case = load_case("DISP-008")
        decision = JudgeResult(action="final_ruling", ruling="partial_refund",
                               proposed_action={"amount_cents": 693}, explanation="Refund",
                               evidence_ids=["ROUTE-002"], policy_ids=["POLICY-004"])
        self.assertTrue(validate_final_ruling(case, policy_for_case(case), decision))

    def test_negative_alert_evidence_does_not_justify_deviation(self):
        case = load_case("DISP-005")
        policy = policy_for_case(case)
        decision = JudgeResult(action="final_ruling", ruling="uphold_charge",
                               proposed_action={"amount_cents": 0}, explanation="Keep charge",
                               evidence_ids=["EVENT-008"], policy_ids=["POLICY-003"])
        self.assertTrue(validate_final_ruling(case, policy, decision))
        self.assertEqual(run_single_case("DISP-005", "example").category, "correct_ruling")

    def test_alert_must_match_route_and_time(self):
        for change in ({"affected_route_id": "UNRELATED-ROUTE"},
                       {"valid_until": "2026-09-28T13:59:00+08:00"}):
            with self.subTest(change=change):
                case = copy.deepcopy(load_case("DISP-008"))
                case["app_events"][-1].update(change)
                decision = JudgeResult(action="final_ruling", ruling="uphold_charge",
                                       proposed_action={"amount_cents": 0}, explanation="Keep fare",
                                       evidence_ids=["EVENT-008"], policy_ids=["POLICY-003"])
                self.assertTrue(validate_final_ruling(case, policy_for_case(case), decision))

    def test_explicit_rider_route_change_is_a_permitted_exception(self):
        case = copy.deepcopy(load_case("DISP-008"))
        case["app_events"][-1].update(event_type="rider_route_change", details="Recorded rider request for this detour")
        decision = JudgeResult(action="final_ruling", ruling="uphold_charge",
                               proposed_action={"amount_cents": 0}, explanation="Requested detour",
                               evidence_ids=["EVENT-008"], policy_ids=["POLICY-003"])
        self.assertEqual(validate_final_ruling(case, policy_for_case(case), decision), [])

    def test_conflicting_total_is_detected(self):
        case = copy.deepcopy(load_case("DISP-005"))
        case["trip_data"]["charged_fare"] = 99
        self.assertTrue(any("fare" in issue.lower() for issue in material_case_issues(case, policy_for_case(case))))

    def test_fact_sources_follow_fare_record_ids(self):
        case = copy.deepcopy(load_case("DISP-005"))
        for item in case["fare_items"]:
            item["id"] += "-NEW"
        review = build_review_input(case, policy_for_case(case))
        fact = next(fact for fact in review.facts if fact.id == "FACT-005")
        source_ids = {record.id for record in review.evidence}
        self.assertTrue(set(fact.evidence_ids) <= source_ids)

    def test_billed_distance_must_match_actual_route(self):
        case = copy.deepcopy(load_case("DISP-008"))
        case["fare_items"][1].update(distance_km=30, amount=16.50)
        case["fare_items"][4]["amount"] = 29.25
        case["trip_data"]["charged_fare"] = 29.25
        self.assertTrue(material_case_issues(case, policy_for_case(case)))

    def test_estimate_must_match_planned_route_rates(self):
        case = copy.deepcopy(load_case("DISP-005"))
        case["fare_items"][5]["breakdown"]["distance_charge"] = 9.18
        case["fare_items"][5]["amount"] = 18.68
        case["trip_data"]["estimated_fare"] = 18.68
        self.assertTrue(material_case_issues(case, policy_for_case(case)))

    def test_no_rider_change_does_not_contradict_a_closure(self):
        case = copy.deepcopy(load_case("DISP-008"))
        event = copy.deepcopy(case["app_events"][-1])
        event.update(id="EVENT-009", event_type="rider_route_change", status="none")
        case["app_events"].append(event)
        self.assertEqual(material_case_issues(case, policy_for_case(case)), [])
