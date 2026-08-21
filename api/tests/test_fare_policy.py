import unittest

from fare_policy import (
    FarePolicyContext,
    FreePassFarePolicy,
    PercentageDiscountFarePolicy,
    ReimbursementFarePolicy,
    SettlementType,
    evaluate_candidate_fare,
    get_fare_policy,
)


class FarePolicyTest(unittest.TestCase):
    def test_same_route_can_swap_normal_and_tokyo_free_pass(self):
        candidate = {
            "steps": [
                {"kind": "walk"},
                {"kind": "bus"},
                {"kind": "rail"},
            ]
        }
        normal = evaluate_candidate_fare(
            city_key="tokyo",
            candidate=candidate,
            policy_id="normal",
            normal_fare_yen=430,
        )
        free = evaluate_candidate_fare(
            city_key="tokyo",
            candidate=candidate,
            policy_id="tokyo_toei_transport_pass",
            normal_fare_yen=430,
        )

        self.assertEqual(normal.normal_fare_yen, 430)
        self.assertEqual(normal.pay_now_yen, 430)
        self.assertEqual(normal.effective_fare_yen, 430)
        self.assertEqual(normal.settlement_type, SettlementType.NORMAL)
        self.assertEqual(free.normal_fare_yen, 430)
        self.assertEqual(free.pay_now_yen, 0)
        self.assertEqual(free.effective_fare_yen, 0)
        self.assertEqual(free.settlement_type, SettlementType.FREE_PASS)

    def test_tokyo_free_pass_can_determine_zero_even_if_normal_fare_unknown(self):
        candidate = {"steps": [{"kind": "rail"}]}
        quote = evaluate_candidate_fare(
            city_key="tokyo",
            candidate=candidate,
            policy_id="tokyo_toei_transport_pass",
            normal_fare_yen=None,
        )

        self.assertEqual(quote.status, "available")
        self.assertIsNone(quote.normal_fare_yen)
        self.assertEqual(quote.pay_now_yen, 0)
        self.assertEqual(quote.effective_fare_yen, 0)

    def test_normal_policy_reports_unavailable_instead_of_inventing_fare(self):
        candidate = {"steps": [{"kind": "rail"}]}
        quote = evaluate_candidate_fare(
            city_key="tokyo",
            candidate=candidate,
            policy_id="normal",
            normal_fare_yen=None,
        )

        self.assertEqual(quote.status, "unavailable")
        self.assertIsNone(quote.pay_now_yen)
        self.assertEqual(
            quote.unavailable_reason,
            "normal_fare_not_calculable_from_current_route_data",
        )

    def test_nagoya_welfare_pass_is_city_scoped(self):
        policy = get_fare_policy("nagoya", "nagoya_welfare_special_pass")
        quote = policy.apply(
            FarePolicyContext(
                city_key="nagoya",
                normal_fare_yen=420,
                ride_modes=("bus", "bus"),
            )
        )
        self.assertEqual(quote.pay_now_yen, 0)
        self.assertEqual(quote.effective_fare_yen, 0)

        with self.assertRaisesRegex(ValueError, "city mismatch"):
            policy.apply(
                FarePolicyContext(
                    city_key="tokyo",
                    normal_fare_yen=420,
                    ride_modes=("bus",),
                )
            )

    def test_unknown_policy_fails_fast(self):
        with self.assertRaisesRegex(ValueError, "unsupported fare policy"):
            get_fare_policy("nagoya", "tokyo_toei_transport_pass")

    def test_discount_settlement_is_supported_without_city_specific_logic(self):
        policy = PercentageDiscountFarePolicy(
            city_key="nagoya",
            policy_id="fixture_discount",
            display_name="fixture",
            numerator=1,
            denominator=2,
        )
        quote = policy.apply(
            FarePolicyContext(
                city_key="nagoya",
                normal_fare_yen=420,
                ride_modes=("bus",),
            )
        )
        self.assertEqual(quote.settlement_type, SettlementType.DISCOUNT)
        self.assertEqual(quote.pay_now_yen, 210)
        self.assertEqual(quote.effective_fare_yen, 210)

    def test_reimbursement_keeps_pay_now_and_zeroes_effective_cost(self):
        policy = ReimbursementFarePolicy(
            city_key="nagoya",
            policy_id="fixture_reimbursement",
            display_name="fixture",
            source_uri="https://example.invalid/policy",
        )
        quote = policy.apply(
            FarePolicyContext(
                city_key="nagoya",
                normal_fare_yen=300,
                ride_modes=("rail",),
            )
        )
        self.assertEqual(quote.settlement_type, SettlementType.REIMBURSEMENT)
        self.assertEqual(quote.pay_now_yen, 300)
        self.assertEqual(quote.effective_fare_yen, 0)

    def test_api_shape_uses_explicit_fare_names(self):
        quote = get_fare_policy("nagoya", "normal").apply(
            FarePolicyContext(
                city_key="nagoya",
                normal_fare_yen=210,
                ride_modes=("bus",),
            )
        )
        self.assertEqual(
            quote.to_api_dict(),
            {
                "normalFareYen": 210,
                "payNowYen": 210,
                "effectiveFareYen": 210,
                "policyId": "normal",
                "settlementType": "normal",
                "status": "available",
                "unavailableReason": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
