import unittest

from google.transit import gtfs_realtime_pb2

from diagnose_train_vehicle_feed import coverage_summary, parse_vehicle_records


class TrainVehicleDiagnosticTest(unittest.TestCase):
    def test_extracts_fields_needed_for_remaining_station_display(self):
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        entity = feed.entity.add()
        entity.id = "train-entity-1"

        vehicle = entity.vehicle
        vehicle.trip.trip_id = "trip-123"
        vehicle.trip.route_id = "route-asakusa"
        vehicle.trip.direction_id = 1
        vehicle.vehicle.id = "vehicle-5501"
        vehicle.current_stop_sequence = 7
        vehicle.stop_id = "stop-A17"
        vehicle.current_status = gtfs_realtime_pb2.VehiclePosition.IN_TRANSIT_TO
        vehicle.timestamp = 1_700_000_000
        vehicle.position.latitude = 35.695
        vehicle.position.longitude = 139.786

        records = parse_vehicle_records(feed.SerializeToString())

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.entity_id, "train-entity-1")
        self.assertEqual(record.vehicle_id, "vehicle-5501")
        self.assertEqual(record.trip_id, "trip-123")
        self.assertEqual(record.route_id, "route-asakusa")
        self.assertEqual(record.direction_id, 1)
        self.assertEqual(record.current_stop_sequence, 7)
        self.assertEqual(record.stop_id, "stop-A17")
        self.assertEqual(record.current_status, "IN_TRANSIT_TO")
        self.assertEqual(record.timestamp, 1_700_000_000)
        self.assertAlmostEqual(record.latitude, 35.695, places=3)
        self.assertAlmostEqual(record.longitude, 139.786, places=3)

        summary = coverage_summary(records)
        self.assertEqual(summary["vehicle_entities"], 1)
        self.assertEqual(summary["with_trip_id"], 1)
        self.assertEqual(summary["with_current_stop_sequence"], 1)
        self.assertEqual(summary["with_stop_id"], 1)

    def test_optional_fields_are_reported_as_missing_without_fabrication(self):
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        entity = feed.entity.add()
        entity.id = "train-entity-2"
        entity.vehicle.vehicle.id = "vehicle-only"

        records = parse_vehicle_records(feed.SerializeToString())
        summary = coverage_summary(records)

        self.assertEqual(records[0].trip_id, None)
        self.assertEqual(records[0].current_stop_sequence, None)
        self.assertEqual(records[0].stop_id, None)
        self.assertEqual(summary["with_trip_id"], 0)
        self.assertEqual(summary["with_current_stop_sequence"], 0)
        self.assertEqual(summary["with_stop_id"], 0)

    def test_feed_without_vehicle_positions_fails_fast(self):
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        entity = feed.entity.add()
        entity.id = "alert-only"
        entity.alert.header_text.translation.add().text = "test"

        with self.assertRaisesRegex(
            RuntimeError,
            "no VehiclePosition entities",
        ):
            parse_vehicle_records(feed.SerializeToString())


if __name__ == "__main__":
    unittest.main()
