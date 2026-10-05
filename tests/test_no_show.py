import copy
import unittest
from decimal import Decimal

from case_data import load_case, load_policy
from checks import no_show_facts


class NoShowFactsTests(unittest.TestCase):
    def test_sample_case_uses_arrival_and_cancellation_times(self):
        case = load_case("DISP-002")
        policy = load_policy("sample_no_show")

        facts = no_show_facts(case, policy)

        self.assertEqual(facts["waited_minutes"], 8)
        self.assertEqual(facts["minutes_before_scheduled_pickup"], 2)
        self.assertTrue(facts["fee_eligible"])
        self.assertEqual(facts["policy_fee"], Decimal("5.00"))

    def test_profile_history_does_not_change_fee_eligibility(self):
        case = load_case("DISP-002")
        policy = load_policy("sample_no_show")
        changed = copy.deepcopy(case)
        changed["rider_profile"]["fraud_flags"] = 100
        changed["driver_profile"]["avg_rating"] = 1.0

        self.assertEqual(
            no_show_facts(case, policy)["fee_eligible"],
            no_show_facts(changed, policy)["fee_eligible"],
        )


if __name__ == "__main__":
    unittest.main()
