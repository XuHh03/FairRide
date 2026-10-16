import copy
import json
import unittest

from case_data import file_dispute, load_case
from case_import import parse_case_upload
from evidence import build_review_input
from case_data import policy_for_case


class CaseImportTests(unittest.TestCase):
    def encode(self, case):
        return json.dumps(case).encode()

    def test_both_categories_preserve_external_ids_and_source_data(self):
        for case_id in ("DISP-004", "DISP-010"):
            with self.subTest(case=case_id):
                case = load_case(case_id)
                case["dispute_ticket"]["dispute_id"] = "FHE-NEW-001"
                imported = parse_case_upload(self.encode(case))
                self.assertEqual(imported, case)
                review = build_review_input(imported, policy_for_case(imported))
                self.assertEqual(review.case_id, "FHE-NEW-001")
                self.assertNotIn("rider_profile", review.model_dump_json())

    def test_imported_trip_can_be_filed_without_loading_or_modifying_fixtures(self):
        case = load_case("DISP-010")
        case["dispute_ticket"]["dispute_id"] = "FHE-NEW-001"
        original = copy.deepcopy(case)
        filed = file_dispute(case["trip_data"]["trip_id"], " A different complaint. ", imported_case=case)
        self.assertEqual(filed["dispute_ticket"]["description"], "A different complaint.")
        self.assertEqual(filed["dispute_ticket"]["dispute_id"], "FHE-NEW-001")
        self.assertEqual(case, original)
        with self.assertRaises(ValueError):
            file_dispute("WRONG-TRIP", "A complaint.", imported_case=case)

    def test_invalid_json_root_and_oversized_file_are_rejected(self):
        for data in (b"{", b"[]", b"null", b"x" * (2 * 1024 * 1024 + 1),
                     b'{"dispute_ticket":{},"dispute_ticket":{}}'):
            with self.subTest(data=data[:60]), self.assertRaises(ValueError):
                parse_case_upload(data)

    def test_answer_keys_and_embedded_expected_labels_are_rejected(self):
        case = load_case("DISP-004")
        inputs = [{"case_id": "FHE-001", "expected_ruling": "uphold_charge"},
                  {**case, "answer_key": {"ruling": "uphold_charge"}}]
        embedded = copy.deepcopy(case)
        embedded["dispute_ticket"]["expected_ruling"] = "uphold_charge"
        inputs.append(embedded)
        for data in inputs:
            with self.subTest(keys=list(data)), self.assertRaises(ValueError):
                parse_case_upload(self.encode(data))

    def test_bad_ids_trip_links_timestamps_and_record_shapes_are_rejected(self):
        for defect in ("duplicate_id", "trip_id", "category", "timestamp", "timezone", "record_shape", "missing_field", "nonfinite", "money_type"):
            case = load_case("DISP-004")
            if defect == "duplicate_id": case["gps_telemetry"][0]["id"] = case["trip_data"]["id"]
            elif defect == "trip_id": case["trip_data"]["trip_id"] = "WRONG-TRIP"
            elif defect == "category": case["dispute_ticket"]["dispute_type"] = "surge_pricing"
            elif defect == "timestamp": case["chat_logs"][0]["timestamp"] = "yesterday"
            elif defect == "timezone": case["trip_data"]["scheduled_time"] = "2026-09-25T09:00:00"
            elif defect == "record_shape": case["chat_logs"] = {"id": "CHAT-001"}
            elif defect == "missing_field": case["trip_data"].pop("scheduled_time")
            elif defect == "nonfinite": case["gps_telemetry"][0]["lat"] = float("inf")
            elif defect == "money_type": case["trip_data"]["cancellation_fee"] = "5.00"
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                parse_case_upload(self.encode(case))

    def test_missing_traffic_and_empty_contact_logs_remain_valid_uncertain_inputs(self):
        case = load_case("DISP-012")
        case.pop("traffic_data", None)
        self.assertEqual(parse_case_upload(self.encode(case)), case)
        case = load_case("DISP-004")
        case["chat_logs"] = []
        case["app_events"] = []
        self.assertEqual(parse_case_upload(self.encode(case)), case)

    def test_no_show_requires_the_cancellation_fee_displayed_in_overview(self):
        case = load_case("DISP-004")
        case["trip_data"]["charged_fare"] = case["trip_data"].pop("cancellation_fee")
        with self.assertRaisesRegex(ValueError, "cancellation_fee"):
            parse_case_upload(self.encode(case))

    def test_source_ids_cannot_collide_with_derived_fact_ids(self):
        for case_id in ("DISP-004", "DISP-010"):
            case = load_case(case_id)
            case["chat_logs"][0]["id"] = "FACT-001"
            with self.subTest(case=case_id), self.assertRaisesRegex(ValueError, "FACT-001"):
                parse_case_upload(self.encode(case))
