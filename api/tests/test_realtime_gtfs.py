import unittest
from unittest.mock import patch

from google.transit import gtfs_realtime_pb2

from gtfs_loader import gtfs_repo
from toei_engine import parse_realtime_gtfs


class ParseRealtimeGtfsTest(unittest.TestCase):
    def test_in_transit_position_uses_most_recently_departed_stop(self):
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        entity = feed.entity.add()
        entity.id = "entity-a"
        vehicle = entity.vehicle
        vehicle.trip.trip_id = "trip-a"
        vehicle.vehicle.id = "vehicle-a"
        vehicle.current_stop_sequence = 4
        vehicle.current_status = gtfs_realtime_pb2.VehiclePosition.IN_TRANSIT_TO

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


if __name__ == "__main__":
    unittest.main()
