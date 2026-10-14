"""Synthetic contract tests for the read-only real-GTFS acceptance checks."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from route_engine import GeoPoint, RoutePreference, RouteSearchRequest, serialize_route_result
from route_fare_scope import search_with_fare_scope
from fare_policy import decorate_route_result_with_fare
from test_yokohama_municipal_transfer import _feed
from yokohama_municipal_backend import YokohamaMunicipalRouteBackend
from yokohama_municipal_transfer import ExplicitTransferLink
from yokohama_real_gtfs_acceptance import (
    check_real_municipal_od, validate_reviewed_candidate,
)


class RealGtfsAcceptanceContractTests(unittest.TestCase):
    def setUp(self):
        busdir = tempfile.TemporaryDirectory()
        subwaydir = tempfile.TemporaryDirectory()
        self.addCleanup(busdir.cleanup)
        self.addCleanup(subwaydir.cleanup)
        self.bus = _feed(Path(busdir.name), rail=False)
        self.subway = _feed(Path(subwaydir.name), rail=True)
        self.link = ExplicitTransferLink(
            "yokohama_bus:B", "yokohama_subway:S", 120, 3,
            "https://www.city.yokohama.lg.jp/kotsu/",
        )

    def _check(self, *, origin="yokohama_bus:O", destination="yokohama_subway:D",
               minute=0, hour=9, links=None):
        return check_real_municipal_od(
            bus_coverage=self.bus, subway_coverage=self.subway,
            transfer_links=(self.link,) if links is None else links,
            bus_transfer_stop_id=self.link.bus_stop_id,
            subway_transfer_stop_id=self.link.subway_stop_id,
            origin_stop_id=origin, destination_stop_id=destination,
            departure=datetime(2026, 10, 14, hour, minute,
                               tzinfo=ZoneInfo("Asia/Tokyo")),
        )

    def test_both_passes_and_directions_check_source_gtfs(self):
        cases = [
            self._check(),
            self._check(origin="yokohama_subway:D",
                        destination="yokohama_bus:O", hour=9, minute=55),
        ]
        self.assertEqual([x["direction"] for x in cases],
                         ["bus_to_rail", "rail_to_bus"])
        for result in cases:
            self.assertEqual(len(result["policies"]), 2)
            self.assertTrue(result["status"].startswith("PASS_"))
            for policy in result["policies"]:
                self.assertEqual(policy["additional_payment_yen"], 0)
                self.assertEqual(policy["walk_minutes"], 3)
                self.assertEqual(len(policy["trip_ids"]), 2)

    def test_missing_walk_link_does_not_enable_estimate(self):
        with self.assertRaisesRegex(ValueError, "exist exactly once"):
            self._check(links=())

    def test_unreachable_after_last_departure_fails(self):
        with self.assertRaisesRegex(AssertionError, "no reviewed"):
            self._check(hour=22)

    def test_same_feed_origin_destination_fails(self):
        with self.assertRaisesRegex(ValueError, "cross the bus/subway"):
            self._check(destination="yokohama_bus:B")

    def _candidate(self):
        engine = YokohamaMunicipalRouteBackend(
            self.bus, self.subway, transfer_links=(self.link,),
        )
        req = RouteSearchRequest(
            origin=GeoPoint(35.4700, 139.6200),
            destination=GeoPoint(35.4500, 139.6300),
            departure_at=datetime(2026, 10, 14, 9, 0,
                                  tzinfo=ZoneInfo("Asia/Tokyo")),
            preference=RoutePreference.FASTEST,
        )
        result = serialize_route_result(
            search_with_fare_scope(engine, req, "yokohama_welfare_special_pass")
        )
        decorate_route_result_with_fare(
            city_key="yokohama", result=result,
            policy_id="yokohama_welfare_special_pass",
        )
        return result["candidates"][0]

    def _validate(self, candidate):
        return validate_reviewed_candidate(
            candidate, bus_coverage=self.bus, subway_coverage=self.subway,
            transfer=self.link, policy_id="yokohama_welfare_special_pass",
            direction="bus_to_rail",
            service_date=datetime(2026, 10, 14).date(),
            earliest_departure_minute=9 * 60,
        )

    def test_forged_zero_fare_or_missing_evidence_fails(self):
        candidate = self._candidate()
        candidate["fare"]["payNowYen"] = 100
        with self.assertRaisesRegex(AssertionError, "fare not verified"):
            self._validate(candidate)
        candidate = self._candidate()
        transfer_step = next(
            s for s in candidate["steps"] if s.get("walking_connection_verified") is True
        )
        transfer_step.pop("evidence_url")
        with self.assertRaisesRegex(AssertionError, "handoff differs"):
            self._validate(candidate)

    def test_wrong_trip_timetable_fails(self):
        candidate = self._candidate()
        ride = next(s for s in candidate["steps"] if s["kind"] == "bus")
        ride["departure_time"] = "09:06"
        with self.assertRaisesRegex(AssertionError, "disagrees with GTFS"):
            self._validate(candidate)

    def test_reviewed_transfer_cannot_be_too_short_for_timetable(self):
        candidate = self._candidate()
        from dataclasses import replace
        link = replace(self.link, walk_minutes=8)
        with self.assertRaisesRegex(AssertionError, "handoff differs"):
            validate_reviewed_candidate(
                candidate, bus_coverage=self.bus, subway_coverage=self.subway,
                transfer=link, policy_id="yokohama_welfare_special_pass",
                direction="bus_to_rail",
                service_date=datetime(2026, 10, 14).date(),
                earliest_departure_minute=9 * 60,
            )


if __name__ == "__main__":
    unittest.main()
