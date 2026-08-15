import unittest

from app.services.train_realtime import (
    StaticTrainGtfs,
    StaticTrainStop,
    StaticTrainTrip,
    TrainRealtimeError,
    TrainVehicleRecord,
    build_location_response,
    resolve_train_vehicle,
)


class TrainRealtimeResolverTest(unittest.TestCase):
    def setUp(self):
        self.trip = StaticTrainTrip(
            trip_id="121603T0",
            route_id="1",
            headsign="成田空港",
            stops=(
                StaticTrainStop(9, "115", "東日本橋", "16:20:00", "16:20:30"),
                StaticTrainStop(10, "116", "浅草橋", "16:22:00", "16:22:30"),
                StaticTrainStop(11, "117", "蔵前", "16:24:00", "16:24:30"),
            ),
        )
        self.gtfs = StaticTrainGtfs(trips={self.trip.trip_id: self.trip})
        self.vehicle = TrainVehicleRecord(
            trip_id="121603T0",
            vehicle_id="121603T0",
            current_stop_sequence=10,
            current_status="IN_TRANSIT_TO",
            timestamp=1_700_000_000,
            latitude=35.69,
            longitude=139.78,
        )

    def test_resolves_exact_reporting_trip_from_plan(self):
        resolved = resolve_train_vehicle(
            (self.vehicle,),
            self.gtfs,
            trip_id=None,
            from_name="東日本橋",
            to_name="蔵前",
            arrival_time="16:24",
        )

        self.assertEqual(resolved.trip.trip_id, "121603T0")
        self.assertEqual(resolved.boarding_sequence, 9)
        self.assertEqual(resolved.destination_sequence, 11)

    def test_does_not_guess_when_arrival_time_does_not_match(self):
        with self.assertRaises(TrainRealtimeError) as raised:
            resolve_train_vehicle(
                (self.vehicle,),
                self.gtfs,
                trip_id=None,
                from_name="東日本橋",
                to_name="蔵前",
                arrival_time="16:25",
            )

        self.assertEqual(raised.exception.code, "train_trip_not_found")

    def test_exact_trip_id_still_requires_requested_segment(self):
        with self.assertRaises(TrainRealtimeError) as raised:
            resolve_train_vehicle(
                (self.vehicle,),
                self.gtfs,
                trip_id="121603T0",
                from_name="存在しない駅",
                to_name="蔵前",
                arrival_time="16:24",
            )

        self.assertEqual(raised.exception.code, "train_static_segment_missing")

    def test_response_contains_sequences_and_trip_stops(self):
        resolved = resolve_train_vehicle(
            (self.vehicle,),
            self.gtfs,
            trip_id=None,
            from_name="東日本橋",
            to_name="蔵前",
            arrival_time="16:24",
        )
        response = build_location_response(
            resolved,
            realtime_fetched_at=1_700_000_001,
        )

        self.assertEqual(response["current_stop_sequence"], 10)
        self.assertEqual(response["current_stop_name"], "浅草橋")
        self.assertEqual(response["boarding_sequence"], 9)
        self.assertEqual(response["destination_sequence"], 11)
        self.assertEqual(
            [stop["sequence"] for stop in response["trip_stops"]],
            [9, 10, 11],
        )


if __name__ == "__main__":
    unittest.main()
