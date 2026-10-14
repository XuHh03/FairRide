import copy
import unittest
from decimal import Decimal

from agents import ExampleAgentBackend
from case_data import load_case, policy_for_case
from checks import material_case_issues, route_deviation_facts, validate_final_ruling, route_justification
from contracts import JudgeResult
from evaluation import LABELS, run_single_case
from evidence import build_review_input
from workflow import run_review


class RouteScenarioTests(unittest.TestCase):
    def test_existing_fare_totals_are_consistent(self):
        case = load_case("DISP-005")
        total = sum(Decimal(str(r["amount"])) for r in case["fare_items"]
                    if r["component"] not in ("total_charged", "estimated_total"))
        self.assertEqual(total, Decimal(str(case["trip_data"]["charged_fare"])))
        self.assertEqual(route_deviation_facts(case, policy_for_case(case))["excess_distance_cents"], 369)

    def test_justified_small_detour_completes_with_no_refund(self):
        metric = run_single_case("DISP-011", "example")
        self.assertEqual(metric.category, "correct_ruling")
        self.assertEqual(metric.amount_cents, 0)

    def test_conflicting_small_route_gets_one_follow_up(self):
        case = load_case("DISP-012")
        result = run_review(case, policy_for_case(case), ExampleAgentBackend())
        self.assertEqual(result.status, "human_review")
        self.assertIsNone(result.failure_category)
        self.assertEqual(sum(e.actor == "judge" for e in result.activity_log), 2)
        self.assertEqual(LABELS["DISP-012"].expected_ruling, "human_review")

    def test_negative_and_missing_traffic_are_distinct(self):
        case = copy.deepcopy(load_case("DISP-010"))
        self.assertEqual(route_justification(case), "unsupported")
        case["traffic_data"] = []
        self.assertEqual(route_justification(case), "unknown")
        self.assertTrue(material_case_issues(case, policy_for_case(case)))

    def test_historical_record_must_match_route_and_time(self):
        for change in ({"affected_route_id": "OTHER"}, {"valid_until": "2026-09-28T13:59:00+08:00"}):
            with self.subTest(change=change):
                case = copy.deepcopy(load_case("DISP-011"))
                case["traffic_data"][0].update(change)
                self.assertEqual(route_justification(case), "unknown")

    def test_app_alert_cannot_replace_historical_api_evidence(self):
        case = copy.deepcopy(load_case("DISP-011"))
        case["traffic_data"][0]["source"] = "in_app_alert"
        self.assertEqual(route_justification(case), "unknown")

    def test_conflicting_fare_total_and_quantities_are_detected(self):
        for field, value in (("charged_fare", 99),):
            case = copy.deepcopy(load_case("DISP-010"))
            case["trip_data"][field] = value
            self.assertTrue(material_case_issues(case, policy_for_case(case)))
        case = copy.deepcopy(load_case("DISP-010"))
        case["fare_items"][1].update(distance_km=30, amount=16.5)
        case["fare_items"][4]["amount"] = 25
        case["trip_data"]["charged_fare"] = 25
        self.assertTrue(material_case_issues(case, policy_for_case(case)))

    def test_estimate_must_follow_planned_route_rates(self):
        case = copy.deepcopy(load_case("DISP-010"))
        case["fare_items"][5]["breakdown"]["distance_charge"] = 2.58
        case["fare_items"][5]["amount"] = 10.33
        case["trip_data"]["estimated_fare"] = 10.33
        self.assertTrue(material_case_issues(case, policy_for_case(case)))

    def test_fact_provenance_survives_fare_id_changes(self):
        case = copy.deepcopy(load_case("DISP-010"))
        for item in case["fare_items"]:
            item["id"] += "-NEW"
        review = build_review_input(case, policy_for_case(case))
        fact = next(f for f in review.facts if f.name == "excess_distance_cents")
        self.assertTrue(set(fact.evidence_ids) <= {r.id for r in review.evidence})

    def test_entire_trip_refund_is_not_excess_distance_refund(self):
        case = load_case("DISP-010")
        output = JudgeResult(action="final_ruling", ruling="reverse_charge", confidence=0.9,
                             proposed_action={"amount_cents": 1290, "refund_basis": "excess_distance_fare"},
                             explanation="Incorrect full-trip refund", evidence_ids=["TRIP-001"],
                             policy_ids=["POLICY-1.3", "POLICY-7.1"])
        self.assertTrue(validate_final_ruling(case, policy_for_case(case), output))
