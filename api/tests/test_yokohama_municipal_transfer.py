"""Synthetic bus/subway handoff regression tests (no runtime/ODPT IO)."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fare_policy import YOKOHAMA_WELFARE_PASS_SOURCE
from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata
from yokohama_fare_coverage import YokohamaFareCoverage
from yokohama_municipal_transfer import (
    ExplicitTransferLink, search_explicit_municipal_transfer,
)

JST = ZoneInfo("Asia/Tokyo")
DAY = "2026-10-14"


def _feed(root: Path, *, rail: bool) -> YokohamaFareCoverage:
    feed = "yokohama_subway" if rail else "yokohama_bus"
    if rail:
        inputs = {
            "stops.txt": (
                "stop_id,stop_name,stop_lat,stop_lon\n"
                "S,桜木町,35.4651,139.6251\nD,関内,35.4500,139.6300\n"
            ),
            "routes.txt": "route_id,route_short_name,route_long_name,route_type\nBLUE,ブルーライン,市営地下鉄,1\n",
            "trips.txt": "route_id,service_id,trip_id\nBLUE,ALL,TRAIN1\nBLUE,ALL,TRAIN2\n",
            "stop_times.txt": (
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                "TRAIN1,09:25:00,09:25:00,S,1\n"
                "TRAIN1,09:40:00,09:40:00,D,2\n"
                "TRAIN2,10:00:00,10:00:00,D,1\n"
                "TRAIN2,10:20:00,10:20:00,S,2\n"
            ),
        }
        operator = "yokohama_municipal_subway"
        routes = {"yokohama_subway:BLUE": "local"}
    else:
        inputs = {
            "stops.txt": (
                "stop_id,stop_name,stop_lat,stop_lon\n"
                "O,横浜駅前,35.4700,139.6200\nB,桜木町,35.4650,139.6250\n"
            ),
            "routes.txt": (
                "route_id,route_short_name,route_long_name,route_type\n"
                "BUS,008系統,市営バス,3\nX,あかいくつ,観光,3\n"
            ),
            "trips.txt": (
                "route_id,service_id,trip_id\n"
                "BUS,ALL,BUS1\nBUS,ALL,BUS2\nX,ALL,EXPRESS\n"
            ),
            "stop_times.txt": (
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                "BUS1,09:05:00,09:05:00,O,1\n"
                "BUS1,09:20:00,09:20:00,B,2\n"
                "BUS2,10:26:00,10:26:00,B,1\n"
                "BUS2,10:41:00,10:41:00,O,2\n"
                "EXPRESS,09:01:00,09:01:00,O,1\n"
                "EXPRESS,09:10:00,09:10:00,B,2\n"
            ),
        }
        operator = "yokohama_municipal_bus"
        routes = {"yokohama_bus:BUS": "local", "yokohama_bus:X": "sightseeing"}
    inputs["calendar.txt"] = (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "ALL,1,1,1,1,1,1,1,20260101,20261231\n"
    )
    for name, contents in inputs.items():
        (root / name).write_text(contents, encoding="utf-8")
    metadata = FeedMetadata(
        feed_id=feed,
        source_type="gtfs",
        source_uri="https://api.odpt.org/api/v4/files/odpt/YokohamaMunicipal/",
        version="synthetic-v1",
        fetched_at=datetime(2026, 10, 14, tzinfo=JST),
    )
    dataset = GtfsTransitAdapter.load(root, metadata=metadata)
    raw = {
        "schema_version": 1,
        "city": "yokohama",
        "feed_id": feed,
        "feed_version": metadata.version,
        "feed_source_uri": metadata.source_uri,
        "operator_id": operator,
        "policy_source_uri": YOKOHAMA_WELFARE_PASS_SOURCE,
        "reviewed_on": DAY,
        "routes": routes,
        "stop_municipalities": {},
    }
    path = root / "coverage.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return YokohamaFareCoverage.load(path, dataset=dataset)


class ExplicitTransferTests(unittest.TestCase):
    def setUp(self):
        bus_dir = tempfile.TemporaryDirectory()
        subway_dir = tempfile.TemporaryDirectory()
        self.addCleanup(bus_dir.cleanup)
        self.addCleanup(subway_dir.cleanup)
        self.bus = _feed(Path(bus_dir.name), rail=False)
        self.subway = _feed(Path(subway_dir.name), rail=True)
        self.link = ExplicitTransferLink(
            bus_stop_id="yokohama_bus:B",
            subway_stop_id="yokohama_subway:S",
            walk_meters=120,
            walk_minutes=3,
            official_evidence_url="https://www.city.yokohama.lg.jp/kotsu/",
        )

    def test_bus_to_subway_obeys_walk_and_filters_faster_excluded_bus(self):
        for policy in ("yokohama_welfare_special_pass", "yokohama_senior_special_pass"):
            with self.subTest(policy=policy):
                plan = search_explicit_municipal_transfer(
                    bus_coverage=self.bus, subway_coverage=self.subway,
                    origin_stop_id="yokohama_bus:O",
                    destination_stop_id="yokohama_subway:D",
                    depart_at=datetime(2026, 10, 14, 9, 0, tzinfo=JST),
                    transfer=self.link, policy_id=policy,
                )
                self.assertIsNotNone(plan)
                self.assertEqual(plan.first_mode, "bus")
                self.assertEqual(plan.second_mode, "rail")
                self.assertEqual(plan.first_legs[0].trip_id, "yokohama_bus:BUS1")
                self.assertEqual(plan.second_legs[0].trip_id, "yokohama_subway:TRAIN1")
                self.assertEqual(plan.transfer_arrival_minute, 9 * 60 + 20)
                self.assertEqual(plan.onward_ready_minute, 9 * 60 + 23)
                self.assertEqual(plan.final_arrival_minute, 9 * 60 + 40)
                self.assertEqual(plan.additional_payment_yen, 0)

    def test_subway_to_bus_and_local_clock(self):
        result = search_explicit_municipal_transfer(
            bus_coverage=self.bus, subway_coverage=self.subway,
            origin_stop_id="yokohama_subway:D",
            destination_stop_id="yokohama_bus:O",
            depart_at=datetime(2026, 10, 14, 9, 55, tzinfo=JST),
            transfer=self.link, policy_id="yokohama_senior_special_pass",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.first_mode, "rail")
        self.assertEqual(result.first_legs[0].trip_id, "yokohama_subway:TRAIN2")
        self.assertEqual(result.second_legs[0].trip_id, "yokohama_bus:BUS2")
        self.assertEqual(result.onward_ready_minute, 10 * 60 + 23)
        self.assertEqual(result.final_arrival_minute, 10 * 60 + 41)

    def test_insufficient_connection_is_not_reported_free(self):
        slow_walk = ExplicitTransferLink(
            bus_stop_id=self.link.bus_stop_id,
            subway_stop_id=self.link.subway_stop_id,
            walk_meters=400, walk_minutes=10,
            official_evidence_url=self.link.official_evidence_url,
        )
        result = search_explicit_municipal_transfer(
            bus_coverage=self.bus, subway_coverage=self.subway,
            origin_stop_id="yokohama_bus:O",
            destination_stop_id="yokohama_subway:D",
            depart_at=datetime(2026, 10, 14, 9, 0, tzinfo=JST),
            transfer=slow_walk, policy_id="yokohama_welfare_special_pass",
        )
        self.assertIsNone(result)

    def test_unreviewed_rail_route_is_not_enabled(self):
        from dataclasses import replace
        subway = replace(
            self.subway,
            route_service_kinds={"yokohama_subway:BLUE": "unreviewed"},
        )
        result = search_explicit_municipal_transfer(
            bus_coverage=self.bus, subway_coverage=subway,
            origin_stop_id="yokohama_bus:O",
            destination_stop_id="yokohama_subway:D",
            depart_at=datetime(2026, 10, 14, 9, 0, tzinfo=JST),
            transfer=self.link, policy_id="yokohama_welfare_special_pass",
        )
        self.assertIsNone(result)

    def test_unsupported_policy_timezone_and_unregistered_stop_are_rejected(self):
        args = {
            "bus_coverage": self.bus,
            "subway_coverage": self.subway,
            "origin_stop_id": "yokohama_bus:O",
            "destination_stop_id": "yokohama_subway:D",
            "depart_at": datetime(2026, 10, 14, 9, 0, tzinfo=JST),
            "transfer": self.link,
            "policy_id": "yokohama_welfare_special_pass",
        }
        with self.assertRaisesRegex(ValueError, "explicit welfare/senior"):
            search_explicit_municipal_transfer(**{**args, "policy_id": "normal"})
        with self.assertRaisesRegex(ValueError, "aware JST"):
            search_explicit_municipal_transfer(**{**args, "depart_at": datetime(2026, 10, 14, 9, 0)})
        with self.assertRaisesRegex(ValueError, "one bus and one subway"):
            search_explicit_municipal_transfer(**{**args, "destination_stop_id": "yokohama_subway:UNKNOWN"})

    def test_transfer_link_rejects_fake_mode_and_understated_walking_time(self):
        with self.assertRaisesRegex(ValueError, "feed-namespaced"):
            ExplicitTransferLink(
                "same_name", self.link.subway_stop_id, 100, 2,
                self.link.official_evidence_url,
            )
        with self.assertRaisesRegex(ValueError, "less than"):
            ExplicitTransferLink(
                self.link.bus_stop_id, self.link.subway_stop_id, 400, 1,
                self.link.official_evidence_url,
            )
        with self.assertRaisesRegex(ValueError, "official HTTPS"):
            ExplicitTransferLink(
                self.link.bus_stop_id, self.link.subway_stop_id, 100, 2,
                "https://example.org/claim",
            )


if __name__ == "__main__":
    unittest.main()
