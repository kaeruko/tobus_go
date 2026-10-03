import io
import unittest
import zipfile

from diagnose_train_static_match import (
    build_match_summary,
    describe_record,
    diagnose_target_trip,
    parse_static_gtfs,
)
from diagnose_train_vehicle_feed import TrainVehicleRecord


def _static_gtfs_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "trips.txt",
            "route_id,service_id,trip_id,trip_headsign\n"
            "A,weekday,trip-a,西馬込\n"
            "A,weekday,trip-a2,西馬込\n"
            "S,weekday,trip-s,新宿\n",
        )
        archive.writestr(
            "stop_times.txt",
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "trip-a,10:00:00,10:00:00,A01,1\n"
            "trip-a,10:02:00,10:02:00,A02,2\n"
            "trip-a2,10:05:00,10:05:00,A01,1\n"
            "trip-a2,10:07:00,10:07:00,A02,2\n"
            "trip-s,11:00:00,11:00:00,S01,1\n",
        )
        archive.writestr(
            "stops.txt",
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "A01,浅草橋,35.0,139.0\n"
            "A02,東日本橋,35.1,139.1\n"
            "S01,新宿,35.2,139.2\n",
        )
    return buffer.getvalue()


def _record(
    trip_id: str,
    sequence: int,
) -> TrainVehicleRecord:
    return TrainVehicleRecord(
        entity_id=trip_id,
        vehicle_id=trip_id,
        trip_id=trip_id,
        route_id=None,
        direction_id=None,
        current_stop_sequence=sequence,
        stop_id=None,
        current_status="STOPPED_AT",
        timestamp=1_700_000_000,
        latitude=35.0,
        longitude=139.0,
    )


class ParseStaticGtfsTest(unittest.TestCase):
    def test_parses_trip_sequence_and_stop_name(self):
        static_gtfs = parse_static_gtfs(_static_gtfs_zip())

        trip = static_gtfs.trips["trip-a"]
        self.assertEqual(trip.route_id, "A")
        self.assertEqual(trip.headsign, "西馬込")
        self.assertEqual(trip.stops_by_sequence[2], "A02")
        self.assertEqual(static_gtfs.stop_names["A02"], "東日本橋")


class MatchSummaryTest(unittest.TestCase):
    def test_reports_trip_and_current_sequence_matches(self):
        static_gtfs = parse_static_gtfs(_static_gtfs_zip())
        records = [_record("trip-a", 2), _record("trip-missing", 4)]

        summary = build_match_summary(records, static_gtfs)

        self.assertEqual(summary["vehicle_entities"], 2)
        self.assertEqual(summary["realtime_unique_trip_ids"], 2)
        self.assertEqual(summary["matched_trip_ids"], 1)
        self.assertEqual(summary["unmatched_trip_ids"], 1)
        self.assertEqual(summary["trip_match_rate_percent"], 50.0)
        self.assertEqual(summary["matched_vehicle_entities"], 1)
        self.assertEqual(summary["with_static_current_sequence"], 1)
        self.assertEqual(summary["without_static_current_sequence"], 0)

    def test_describes_stop_missing_from_current_sequence_without_guessing(self):
        static_gtfs = parse_static_gtfs(_static_gtfs_zip())
        record = _record("trip-a", 99)

        described = describe_record(record, static_gtfs)

        self.assertEqual(described["trip_id"], "trip-a")
        self.assertEqual(described["current_stop_sequence"], 99)
        self.assertIsNone(described["static_stop_id"])
        self.assertIsNone(described["static_stop_name"])

    def test_target_diagnosis_distinguishes_static_trip_from_reporting_trip(self):
        static_gtfs = parse_static_gtfs(_static_gtfs_zip())
        records = [_record("trip-a2", 1), _record("trip-s", 1)]

        diagnosis = diagnose_target_trip(
            records,
            static_gtfs,
            trip_id="trip-a",
            from_stop_id="A01",
            to_stop_id="A02",
        )

        self.assertTrue(diagnosis["target_static_present"])
        self.assertFalse(diagnosis["target_reporting"])
        self.assertEqual(diagnosis["target_realtime_count"], 0)
        self.assertEqual(diagnosis["from_stop_sequence"], 1)
        self.assertEqual(diagnosis["to_stop_sequence"], 2)
        self.assertEqual(
            diagnosis["same_route_reporting_trip_ids"],
            ["trip-a2"],
        )

    def test_target_diagnosis_fails_for_wrong_stop_id(self):
        static_gtfs = parse_static_gtfs(_static_gtfs_zip())

        with self.assertRaisesRegex(
            RuntimeError,
            "does not contain exactly one from_stop_id",
        ):
            diagnose_target_trip(
                [_record("trip-a", 1)],
                static_gtfs,
                trip_id="trip-a",
                from_stop_id="missing",
                to_stop_id="A02",
            )


if __name__ == "__main__":
    unittest.main()
