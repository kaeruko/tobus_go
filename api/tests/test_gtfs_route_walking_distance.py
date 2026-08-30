from datetime import datetime
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from gtfs_route_backend import GtfsRouteBackend
from transit_dataset import TransitStop
from transit_engine import TransitItinerary


class GtfsRouteWalkingDistanceTest(unittest.TestCase):
    def test_aggregate_distance_matches_serialized_walk_steps(self) -> None:
        backend = object.__new__(GtfsRouteBackend)
        backend.dataset = SimpleNamespace(
            metadata=SimpleNamespace(feed_id="test")
        )
        backend.walk_speed_m_per_min = 80.0

        origin = TransitStop(
            id="test:A",
            source_id="A",
            name="Origin",
            lat=35.0,
            lon=139.0,
        )
        destination = TransitStop(
            id="test:B",
            source_id="B",
            name="Destination",
            lat=35.1,
            lon=139.1,
        )
        itinerary = TransitItinerary(
            departure_minute=600,
            arrival_minute=600,
            legs=(),
        )

        payload = backend._serialize(
            itinerary,
            origin,
            166.4,
            destination,
            181.4,
            alat=35.0,
            alon=139.0,
            blat=35.1,
            blon=139.1,
            departure=datetime(
                2026,
                8,
                30,
                10,
                0,
                tzinfo=ZoneInfo("Asia/Tokyo"),
            ),
            preference="time",
        )

        walk_meters = [
            step["meters"]
            for step in payload["steps"]
            if step["kind"] == "walk"
        ]

        self.assertEqual(walk_meters, [166, 181])
        self.assertEqual(
            payload["walking_distance_meters"],
            sum(walk_meters),
        )
        self.assertEqual(payload["walking_distance_meters"], 347)


if __name__ == "__main__":
    unittest.main()
