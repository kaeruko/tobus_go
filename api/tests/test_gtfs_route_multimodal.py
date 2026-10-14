"""Contract checks for reusable GTFS bus/rail search, distinct stop IDs.

No cross-feed walking connections or fare approval are inferred here.
Existing Tokyo runtime and Yokohama API routing remain unchanged.
"""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gtfs_route_backend import GtfsRouteEngine
from route_engine import GeoPoint, RouteInputError, RoutePreference, RouteSearchRequest
from transit_engine import PythonTransitSearchCore
from test_yokohama_municipal_transfer import _feed

JST = ZoneInfo("Asia/Tokyo")


def _request(origin, destination, hour, minute, *, bus_only=False):
    return RouteSearchRequest(
        origin=GeoPoint(*origin),
        destination=GeoPoint(*destination),
        departure_at=datetime(2026, 10, 14, hour, minute, tzinfo=JST),
        preference=RoutePreference.FASTEST,
        bus_only=bus_only,
    )


class ReusableGtfsBusRailBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        bus_dir = tempfile.TemporaryDirectory()
        rail_dir = tempfile.TemporaryDirectory()
        self.addCleanup(bus_dir.cleanup)
        self.addCleanup(rail_dir.cleanup)
        self.bus = _feed(Path(bus_dir.name), rail=False).dataset
        self.rail = _feed(Path(rail_dir.name), rail=True).dataset

    @staticmethod
    def _backend(dataset):
        return GtfsRouteEngine(
            dataset,
            walk_radius_m=100,
            endpoint_candidate_limit=3,
            search_core=PythonTransitSearchCore(dataset),
        )

    def test_rail_uses_same_coordinate_time_search_without_bus_label(self):
        result = self._backend(self.rail).search(
            _request((35.4651, 139.6251), (35.4500, 139.6300), 9, 20)
        )
        self.assertEqual(len(result.candidates), 1)
        mapping = result.candidates[0].to_mapping()
        rides = [step for step in mapping["steps"] if step["kind"] in ("bus", "rail")]
        self.assertEqual(len(rides), 1)
        self.assertEqual(rides[0]["kind"], "rail")
        self.assertEqual(rides[0]["route_id"], "yokohama_subway:BLUE")
        self.assertEqual(rides[0]["trip_id"], "yokohama_subway:TRAIN1")
        self.assertEqual(rides[0]["departureStopId"], "yokohama_subway:S")
        self.assertEqual(rides[0]["arrivalPoleId"], "yokohama_subway:D")
        self.assertEqual(mapping["arrival_time"], "09:40")
        self.assertNotIn("fare_context", rides[0])  # never automatically 0 yen

    def test_bus_only_cannot_silently_return_a_train(self):
        with self.assertRaisesRegex(RouteInputError, "bus_only"):
            self._backend(self.rail).search(
                _request(
                    (35.4651, 139.6251), (35.4500, 139.6300),
                    9, 20, bus_only=True,
                )
            )

    def test_bus_backend_remains_bus_for_existing_pass_trip(self):
        result = self._backend(self.bus).search(
            _request(
                (35.4700, 139.6200), (35.4650, 139.6250),
                9, 0, bus_only=True,
            )
        )
        self.assertEqual(len(result.candidates), 1)
        ride = next(
            step for step in result.candidates[0].to_mapping()["steps"]
            if step["kind"] == "bus"
        )
        self.assertEqual(ride["trip_id"], "yokohama_bus:BUS1")

    def test_same_named_opposite_direction_poles_use_stop_ids_not_names(self):
        # No city-specific name normalization or numbered bay registry.
        # The GTFS trip's stop IDs already encode the actual direction.
        original = self.bus.stops
        same_name = {
            stop_id: replace(stop, name="高島町")
            for stop_id, stop in original.items()
        }
        dataset = replace(self.bus, stops=same_name)
        backend = self._backend(dataset)
        outward = backend.search(
            _request((35.4700, 139.6200), (35.4650, 139.6250), 9, 0)
        )
        inbound = backend.search(
            _request((35.4650, 139.6250), (35.4700, 139.6200), 10, 20)
        )
        self.assertEqual(len(outward.candidates), 1)
        self.assertEqual(len(inbound.candidates), 1)
        out_ride = next(step for step in outward.candidates[0].to_mapping()["steps"] if step["kind"] == "bus")
        in_ride = next(step for step in inbound.candidates[0].to_mapping()["steps"] if step["kind"] == "bus")
        self.assertEqual((out_ride["departureStopId"], out_ride["arrivalPoleId"]),
                         ("yokohama_bus:O", "yokohama_bus:B"))
        self.assertEqual((in_ride["departureStopId"], in_ride["arrivalPoleId"]),
                         ("yokohama_bus:B", "yokohama_bus:O"))
        self.assertEqual(out_ride["trip_id"], "yokohama_bus:BUS1")
        self.assertEqual(in_ride["trip_id"], "yokohama_bus:BUS2")


if __name__ == "__main__":
    unittest.main()
