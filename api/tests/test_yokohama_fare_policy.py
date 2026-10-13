from __future__ import annotations

import unittest
from dataclasses import replace

from fare_policy import (
    FarePolicyContext, RideFareContext, evaluate_candidate_fare,
    get_fare_policy, yokohama_welfare_pass_covers,
)


def _ride(*, operator="yokohama_municipal_bus", mode="bus", service="local",
          boarding="14100", alighting="14100", fare=None):
    return RideFareContext(
        mode=mode, feed_id="source", operator_id=operator,
        route_id="source:R", boarding_stop_id="source:A", alighting_stop_id="source:B",
        service_kind=service, boarding_municipality_code=boarding,
        alighting_municipality_code=alighting, normal_fare_yen=fare,
    )


def _quote(*rides, normal=None):
    return get_fare_policy("yokohama", "yokohama_welfare_special_pass").apply(
        FarePolicyContext("yokohama", normal, tuple(ride.mode for ride in rides), tuple(rides))
    )


class YokohamaFarePolicyTest(unittest.TestCase):
    def test_municipal_bus_free_even_when_ordinary_fare_is_unknown(self):
        quote = _quote(_ride(boarding=None, alighting=None))
        self.assertEqual(quote.pay_now_yen, 0)
        self.assertIsNone(quote.normal_fare_yen)
        self.assertEqual(quote.status, "available")

    def test_municipal_subway_and_seaside_line_cover_all_stations(self):
        for operator in ("yokohama_municipal_subway", "yokohama_seaside_line"):
            with self.subTest(operator=operator):
                self.assertEqual(_quote(_ride(operator=operator, mode="rail",
                                              boarding="14205", alighting="14205")).pay_now_yen, 0)

    def test_private_bus_crosses_city_boundary_in_either_direction(self):
        for operator in ("tokyu_bus", "sotetsu_bus", "kawasaki_tsurumi_rinko_bus", "odakyu_bus"):
            for boarding, alighting in (("14100", "14130"), ("14130", "14100")):
                with self.subTest(operator=operator, boarding=boarding):
                    self.assertEqual(_quote(_ride(operator=operator, boarding=boarding,
                                                  alighting=alighting)).pay_now_yen, 0)

    def test_private_bus_both_endpoints_outside_city_remains_payable(self):
        quote = _quote(_ride(operator="tokyu_bus", boarding="14130", alighting="14213", fare=240))
        self.assertEqual(quote.pay_now_yen, 240)

    def test_bus_operator_is_not_a_rail_pass(self):
        with self.assertRaisesRegex(ValueError, "must be bus"):
            _quote(_ride(operator="tokyu_bus", mode="rail"))

    def test_unknown_private_stop_municipality_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "both stop municipality codes"):
            _quote(_ride(operator="sotetsu_bus", boarding=None))

    def test_target_operator_does_not_make_excluded_service_free(self):
        for kind in ("airport", "highway", "midnight_express", "sightseeing"):
            for operator in ("yokohama_municipal_bus", "tokyu_bus"):
                with self.subTest(kind=kind, operator=operator):
                    self.assertEqual(_quote(_ride(operator=operator, service=kind, fare=600)).pay_now_yen, 600)

    def test_jr_ride_does_not_become_free_because_it_is_rail(self):
        quote = _quote(_ride(operator="jr_east", mode="rail", fare=200))
        self.assertEqual(quote.pay_now_yen, 200)

    def test_mixed_route_charges_only_uncovered_ride(self):
        quote = _quote(_ride(fare=230), _ride(operator="jr_east", mode="rail", fare=200), normal=430)
        self.assertEqual(quote.normal_fare_yen, 430)
        self.assertEqual(quote.pay_now_yen, 200)

    def test_unknown_uncovered_fare_is_not_zeroed(self):
        quote = _quote(_ride(), _ride(operator="jr_east", mode="rail"))
        self.assertEqual(quote.status, "unavailable")
        self.assertIsNone(quote.pay_now_yen)
        self.assertEqual(quote.unavailable_reason, "normal_fare_required_for_noncovered_segment")

    def test_walk_only_candidate_has_no_ride_payment(self):
        self.assertEqual(_quote().pay_now_yen, 0)

    def test_mode_only_context_cannot_claim_a_yokohama_free_pass(self):
        policy = get_fare_policy("yokohama", "yokohama_welfare_special_pass")
        with self.assertRaisesRegex(ValueError, "verified ride contexts"):
            policy.apply(FarePolicyContext("yokohama", None, ("bus",)))

    def test_invalid_feed_or_money_is_not_coerced(self):
        for changes in ({"route_id": "other:R"}, {"normal_fare_yen": True},
                        {"normal_fare_yen": 1.5}, {"service_kind": "unknown"},
                        {"boarding_municipality_code": 14100}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(_ride(), **changes)

    def test_pass_is_city_scoped(self):
        with self.assertRaisesRegex(ValueError, "city mismatch"):
            get_fare_policy("yokohama", "yokohama_welfare_special_pass").apply(
                FarePolicyContext("tokyo", None, ("bus",), (_ride(),))
            )

    def test_api_ride_metadata_must_match_the_exact_step(self):
        step = {
            "kind": "bus", "route_id": "source:R", "departureStopId": "source:A",
            "arrivalPoleId": "source:B", "fare_context": {
                "feed_id": "source", "operator_id": "yokohama_municipal_bus",
                "route_id": "source:R", "boarding_stop_id": "source:A",
                "alighting_stop_id": "source:B", "service_kind": "local",
            },
        }
        arguments = dict(city_key="yokohama", policy_id="yokohama_welfare_special_pass",
                         normal_fare_yen=None)
        self.assertEqual(evaluate_candidate_fare(candidate={"steps": [step]}, **arguments).pay_now_yen, 0)
        step["fare_context"]["boarding_stop_id"] = "source:C"
        with self.assertRaisesRegex(ValueError, "boarding stop does not match"):
            evaluate_candidate_fare(candidate={"steps": [step]}, **arguments)

    def test_missing_step_metadata_stops_instead_of_assuming_city_bus(self):
        with self.assertRaisesRegex(ValueError, "verified fare_context"):
            evaluate_candidate_fare(city_key="yokohama", candidate={"steps": [{"kind": "bus"}]},
                                    policy_id="yokohama_welfare_special_pass", normal_fare_yen=None)

    def test_senior_municipal_bus_and_subway_free(self):
        for operator, mode in (
            ("yokohama_municipal_bus", "bus"),
            ("yokohama_municipal_subway", "rail"),
        ):
            ride = _ride(operator=operator, mode=mode)
            quote = get_fare_policy("yokohama", "yokohama_senior_special_pass").apply(
                FarePolicyContext("yokohama", None, (mode,), (ride,))
            )
            self.assertEqual(quote.pay_now_yen, 0)

    def test_senior_private_bus_not_assumed_free_without_route_review(self):
        ride = _ride(operator="tokyu_bus", fare=240)
        quote = get_fare_policy("yokohama", "yokohama_senior_special_pass").apply(
            FarePolicyContext("yokohama", 240, ("bus",), (ride,))
        )
        self.assertEqual(quote.pay_now_yen, 240)


if __name__ == "__main__":
    unittest.main()
