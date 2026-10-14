"""Off-runtime spatial cross-feed transfer regression tests.

All inputs are synthetic GTFS; no ODPT/network access or public API wiring.
"""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from test_yokohama_municipal_transfer import _feed
from yokohama_municipal_transfer import (
    GeometricTransferEstimate, search_geometric_municipal_transfers,
    search_explicit_municipal_transfer,
)

JST = ZoneInfo("Asia/Tokyo")
DAY = datetime(2026, 10, 14, 9, 0, tzinfo=JST)


class GeometricMunicipalTransferTests(unittest.TestCase):
    def setUp(self):
        busdir = tempfile.TemporaryDirectory()
        raildir = tempfile.TemporaryDirectory()
        self.addCleanup(busdir.cleanup)
        self.addCleanup(raildir.cleanup)
        self.bus = _feed(Path(busdir.name), rail=False)
        self.rail = _feed(Path(raildir.name), rail=True)

    def _bus_to_rail(self, **kwargs):
        return search_geometric_municipal_transfers(
            bus_coverage=self.bus, subway_coverage=self.rail,
            origin_stop_id="yokohama_bus:O",
            destination_stop_id="yokohama_subway:D",
            depart_at=DAY,
            policy_id="yokohama_welfare_special_pass",
            **kwargs,
        )

    def test_auto_nearby_bus_to_rail_reuses_timetable_and_fare_scoping(self):
        for policy in ("yokohama_welfare_special_pass", "yokohama_senior_special_pass"):
            with self.subTest(policy=policy):
                plans = search_geometric_municipal_transfers(
                    bus_coverage=self.bus, subway_coverage=self.rail,
                    origin_stop_id="yokohama_bus:O",
                    destination_stop_id="yokohama_subway:D",
                    depart_at=DAY, policy_id=policy,
                )
                self.assertEqual(len(plans), 1)
                p = plans[0]
                self.assertEqual(
                    [leg.trip_id for leg in (*p.first_legs, *p.second_legs)],
                    ["yokohama_bus:BUS1", "yokohama_subway:TRAIN1"],
                )
                self.assertEqual(p.first_mode, "bus")
                self.assertEqual(p.second_mode, "rail")
                self.assertFalse(p.walking_connection_verified)
                self.assertIsInstance(p.transfer, GeometricTransferEstimate)
                self.assertEqual(p.transfer.bus_stop_id, "yokohama_bus:B")
                self.assertEqual(p.transfer.subway_stop_id, "yokohama_subway:S")
                self.assertGreater(p.transfer.walk_meters, 0)
                self.assertGreaterEqual(p.transfer.walk_minutes, 2)
                self.assertLessEqual(p.onward_ready_minute, 9 * 60 + 25)
                self.assertEqual(p.final_arrival_minute, 9 * 60 + 40)
                self.assertEqual(p.additional_payment_yen, 0)

    def test_reverse_rail_to_bus_uses_correct_directional_trips(self):
        plans = search_geometric_municipal_transfers(
            bus_coverage=self.bus, subway_coverage=self.rail,
            origin_stop_id="yokohama_subway:D",
            destination_stop_id="yokohama_bus:O",
            depart_at=DAY.replace(hour=9, minute=55),
            policy_id="yokohama_senior_special_pass",
        )
        self.assertEqual(len(plans), 1)
        p = plans[0]
        self.assertEqual(
            [leg.trip_id for leg in (*p.first_legs, *p.second_legs)],
            ["yokohama_subway:TRAIN2", "yokohama_bus:BUS2"],
        )
        self.assertEqual((p.first_mode, p.second_mode), ("rail", "bus"))
        self.assertFalse(p.walking_connection_verified)
        self.assertEqual(p.final_arrival_minute, 10 * 60 + 41)

    def test_radius_exclusion_and_late_walk_do_not_make_up_a_connection(self):
        self.assertEqual(self._bus_to_rail(radius_m=1), ())
        # Increase rail stop separation while staying inside 600m; the
        # provisional walk then misses the 09:25 train and must return none.
        rail_stops = dict(self.rail.dataset.stops)
        rail_stops["yokohama_subway:S"] = replace(
            rail_stops["yokohama_subway:S"], lat=35.4680, lon=139.6251,
        )
        far_rail = replace(self.rail, dataset=replace(self.rail.dataset, stops=rail_stops))
        plans = search_geometric_municipal_transfers(
            bus_coverage=self.bus, subway_coverage=far_rail,
            origin_stop_id="yokohama_bus:O",
            destination_stop_id="yokohama_subway:D",
            depart_at=DAY,
            policy_id="yokohama_welfare_special_pass",
            radius_m=400,
        )
        self.assertEqual(plans, ())

    def test_no_subway_fare_review_means_no_provisional_free_route(self):
        not_reviewed = replace(
            self.rail, route_service_kinds={"yokohama_subway:BLUE": "unreviewed"}
        )
        result = search_geometric_municipal_transfers(
            bus_coverage=self.bus, subway_coverage=not_reviewed,
            origin_stop_id="yokohama_bus:O",
            destination_stop_id="yokohama_subway:D",
            depart_at=DAY, policy_id="yokohama_welfare_special_pass",
        )
        self.assertEqual(result, ())

    def test_rejects_invalid_policy_inputs_or_radius_without_bypass(self):
        for args in (
            {"radius_m": 0},
            {"radius_m": True},
            {"radius_m": 601},
            {"max_candidate_links": 0},
            {"max_candidate_links": True},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self._bus_to_rail(**args)
        with self.assertRaisesRegex(ValueError, "explicit welfare/senior"):
            search_geometric_municipal_transfers(
                bus_coverage=self.bus, subway_coverage=self.rail,
                origin_stop_id="yokohama_bus:O",
                destination_stop_id="yokohama_subway:D",
                depart_at=DAY, policy_id="normal",
            )
        with self.assertRaisesRegex(ValueError, "aware JST"):
            search_geometric_municipal_transfers(
                bus_coverage=self.bus, subway_coverage=self.rail,
                origin_stop_id="yokohama_bus:O",
                destination_stop_id="yokohama_subway:D",
                depart_at=datetime(2026, 10, 14, 9, 0),
                policy_id="yokohama_welfare_special_pass",
            )

    def test_malformed_estimate_cannot_pass_manual_evidence_entrypoint(self):
        estimate = GeometricTransferEstimate(
            "yokohama_bus:B", "yokohama_subway:S", 10.0, 20, 3
        )
        with self.assertRaisesRegex(ValueError, "ExplicitTransferLink"):
            search_explicit_municipal_transfer(
                bus_coverage=self.bus, subway_coverage=self.rail,
                origin_stop_id="yokohama_bus:O",
                destination_stop_id="yokohama_subway:D",
                depart_at=DAY, transfer=estimate,
                policy_id="yokohama_welfare_special_pass",
            )
        with self.assertRaisesRegex(ValueError, "cannot understate"):
            GeometricTransferEstimate(
                "yokohama_bus:B", "yokohama_subway:S", 300.0, 100, 3
            )


if __name__ == "__main__":
    unittest.main()
