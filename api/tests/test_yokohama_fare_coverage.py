from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fare_policy import YOKOHAMA_WELFARE_PASS_SOURCE, evaluate_candidate_fare
from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata
from transit_engine import TransitRouteEngine
from yokohama_fare_coverage import YokohamaFareCoverage


class YokohamaFareCoverageTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        files = {
            "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nA,Origin,35,139\nB,Goal,35.1,139.1\n",
            "routes.txt": "route_id,route_short_name,route_long_name,route_type\nR,8,Ordinary,3\nX,A,Excluded,3\n",
            "trips.txt": "route_id,service_id,trip_id\nR,ALL,T\nX,ALL,XT\n",
            "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT,10:00:00,10:00:00,A,1\nT,10:30:00,10:30:00,B,2\nXT,10:00:00,10:00:00,A,1\nXT,10:10:00,10:10:00,B,2\n",
            "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nALL,1,1,1,1,1,1,1,20260101,20261231\n",
        }
        for name, text in files.items():
            (self.root / name).write_text(text, encoding="utf-8")
        self.dataset = GtfsTransitAdapter.load(self.root, metadata=FeedMetadata(
            feed_id="yokohama_bus", source_type="gtfs-jp",
            source_uri="https://api.odpt.org/api/v4/files/odpt/YokohamaMunicipal/Bus.zip?date=current",
            version="fixture-v1", fetched_at=datetime(2026, 10, 14, tzinfo=timezone.utc),
        ))
        self.raw = {
            "schema_version": 1, "city": "yokohama", "feed_id": "yokohama_bus",
            "feed_version": "fixture-v1", "feed_source_uri": self.dataset.metadata.source_uri,
            "operator_id": "yokohama_municipal_bus", "policy_source_uri": YOKOHAMA_WELFARE_PASS_SOURCE,
            "reviewed_on": "2026-10-14", "routes": {"yokohama_bus:R": "local", "yokohama_bus:X": "sightseeing"},
            "stop_municipalities": {},
        }

    def _load(self, raw=None):
        path = self.root / "coverage.json"
        path.write_text(json.dumps(self.raw if raw is None else raw), encoding="utf-8")
        return YokohamaFareCoverage.load(path, dataset=self.dataset)

    def test_filter_finds_slower_free_route_before_search(self):
        departure = datetime(2026, 10, 14, 9, 55, tzinfo=timezone.utc)
        original = TransitRouteEngine(self.dataset).search_fastest(
            "yokohama_bus:A", "yokohama_bus:B", departure=departure,
        )
        selected = self._load().municipal_free_coverage()
        free = TransitRouteEngine(selected.dataset).search_fastest(
            "yokohama_bus:A", "yokohama_bus:B", departure=departure,
        )
        self.assertEqual(original.arrival_minute, 610)
        self.assertEqual(free.arrival_minute, 630)
        self.assertEqual(free.legs[0].route_id, "yokohama_bus:R")
        self.assertIs(selected.dataset.metadata, self.dataset.metadata)
        self.assertIn("yokohama_bus:X", self.dataset.routes)
        self.assertNotIn("yokohama_bus:XT", selected.dataset.trips)

    def test_step_context_connects_reviewed_feed_to_fare_quote(self):
        coverage = self._load()
        step = {"kind": "bus", "route_id": "yokohama_bus:R", "departureStopId": "yokohama_bus:A",
                "arrivalPoleId": "yokohama_bus:B"}
        step["fare_context"] = coverage.context_for_step(step)
        quote = evaluate_candidate_fare(city_key="yokohama", candidate={"steps": [step]},
                                        policy_id="yokohama_welfare_special_pass", normal_fare_yen=None)
        self.assertEqual(quote.pay_now_yen, 0)

    def test_manifest_identity_must_match_installed_feed(self):
        changes = {"feed_version": "old", "feed_id": "other", "operator_id": "tokyu_bus",
                   "feed_source_uri": "https://example.invalid/feed", "city": "tokyo",
                   "policy_source_uri": "https://example.invalid/rules", "schema_version": True}
        for field, value in changes.items():
            raw = copy.deepcopy(self.raw)
            raw[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self._load(raw)

    def test_new_route_requires_explicit_review(self):
        raw = copy.deepcopy(self.raw)
        del raw["routes"]["yokohama_bus:X"]
        with self.assertRaisesRegex(ValueError, "every route"):
            self._load(raw)

    def test_unreviewed_route_stays_in_feed_but_cannot_enter_free_search(self):
        raw = copy.deepcopy(self.raw)
        raw["routes"]["yokohama_bus:X"] = "unreviewed"
        coverage = self._load(raw)
        filtered = coverage.municipal_free_coverage()
        self.assertIn("yokohama_bus:X", self.dataset.routes)
        self.assertNotIn("yokohama_bus:X", filtered.dataset.routes)
        context = coverage.context_for_step({
            "kind": "bus", "route_id": "yokohama_bus:X",
            "departureStopId": "yokohama_bus:A",
            "arrivalPoleId": "yokohama_bus:B",
        })
        quote = evaluate_candidate_fare(
            city_key="yokohama",
            candidate={"steps": [{
                "kind": "bus", "route_id": "yokohama_bus:X",
                "departureStopId": "yokohama_bus:A",
                "arrivalPoleId": "yokohama_bus:B",
                "fare_context": context,
            }]},
            policy_id="yokohama_welfare_special_pass",
            normal_fare_yen=None,
        )
        self.assertIsNone(quote.pay_now_yen)
        self.assertEqual(quote.status, "unavailable")

    def test_route_category_is_not_defaulted_to_ordinary(self):
        raw = copy.deepcopy(self.raw)
        raw["routes"]["yokohama_bus:R"] = "unknown"
        with self.assertRaisesRegex(ValueError, "unreviewed"):
            self._load(raw)

    def test_unknown_stop_cannot_receive_a_city_classification(self):
        raw = copy.deepcopy(self.raw)
        raw["stop_municipalities"]["other:A"] = "14100"
        with self.assertRaisesRegex(ValueError, "invalid stop_municipalities"):
            self._load(raw)

    def test_unreviewed_step_is_not_emitted_as_free(self):
        with self.assertRaisesRegex(ValueError, "unreviewed route"):
            self._load().context_for_step({"route_id": "yokohama_bus:unknown"})

    def test_all_excluded_routes_yield_no_free_dataset(self):
        raw = copy.deepcopy(self.raw)
        raw["routes"]["yokohama_bus:R"] = "airport"
        self.assertIsNone(self._load(raw).municipal_free_coverage())


if __name__ == "__main__":
    unittest.main()
