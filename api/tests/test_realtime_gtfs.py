import os
import unittest
from unittest.mock import patch

from google.transit import gtfs_realtime_pb2

from gtfs_loader import gtfs_repo
from app.runtime import refresh_realtime_bus_positions
from toei_engine import parse_realtime_gtfs


class ParseRealtimeGtfsTest(unittest.TestCase):
    def test_in_transit_position_uses_most_recently_departed_stop(self):
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        feed.header.timestamp = 1_700_000_000
        entity = feed.entity.add()
        entity.id = "entity-a"
        vehicle = entity.vehicle
        vehicle.trip.trip_id = "trip-a"
        vehicle.vehicle.id = "vehicle-a"
        vehicle.current_stop_sequence = 4
        vehicle.current_status = gtfs_realtime_pb2.VehiclePosition.IN_TRANSIT_TO
        vehicle.stop_id = "stop-4"
        vehicle.timestamp = 1_700_000_010

        def details(_trip_id, sequence):
            if sequence not in (3, 4):
                return None
            return {
                "route_id": "route-a",
                "route_short_name": "A",
                "headsign": "終点",
                "next_stop_name": f"stop-{sequence}",
                "next_stop_id": f"stop-{sequence}",
            }

        with (
            patch.object(gtfs_repo, "get_bus_details", side_effect=details),
            patch.object(
                gtfs_repo,
                "stops",
                {"stop-4": {"name": "Stop 4"}},
            ),
            patch.object(
                gtfs_repo,
                "get_trip_stop_ids",
                return_value=["stop-1", "stop-2", "stop-3", "stop-4"],
            ),
        ):
            buses = parse_realtime_gtfs(feed.SerializeToString())

        self.assertEqual(len(buses), 1)
        self.assertEqual(buses[0]["odpt:fromBusstopPole"], "stop-3")
        self.assertEqual(buses[0]["next_stop_id"], "stop-4")
        self.assertEqual(buses[0]["from_stop_sequence"], 3)
        self.assertEqual(buses[0]["observed_stop_sequence"], 4)
        self.assertEqual(buses[0]["current_status"], "IN_TRANSIT_TO")
        self.assertEqual(buses[0]["raw_stop_id"], "stop-4")
        self.assertEqual(buses[0]["raw_stop_name"], "Stop 4")
        self.assertEqual(buses[0]["feed_timestamp"], 1_700_000_000)
        self.assertEqual(buses[0]["vehicle_timestamp"], 1_700_000_010)


class _FakeRealtimeResponse:
    status_code = 200
    content = b"feed"


class _FakeRealtimeClient:
    def __init__(self):
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url, params):
        self.calls += 1
        return _FakeRealtimeResponse()


class RefreshRealtimeBusPositionsTest(unittest.IsolatedAsyncioTestCase):
    async def test_refreshes_once_and_reuses_fresh_positions(self):
        class FakeTimetableManager:
            latest_bus_positions = []

        tm = FakeTimetableManager()
        client = _FakeRealtimeClient()
        buses = [{"trip_id": "trip-a", "vehicle_id": "vehicle-a"}]

        with (
            patch.dict(os.environ, {"ODPT_API_TOKEN": "test-token"}),
            patch("app.runtime.httpx.AsyncClient", return_value=client),
            patch("app.runtime.parse_realtime_gtfs", return_value=buses),
        ):
            first = await refresh_realtime_bus_positions(
                tm,
                max_age_seconds=0,
            )
            second = await refresh_realtime_bus_positions(tm)

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(tm.latest_bus_positions, buses)
        self.assertEqual(client.calls, 1)


if __name__ == "__main__":
    unittest.main()
