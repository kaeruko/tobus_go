import io
import unittest
import zipfile

from app.services.train_realtime import (
    StaticTrainGtfs,
    StaticTrainStop,
    StaticTrainTrip,
    TrainRealtimeError,
    TrainVehicleRecord,
    build_location_response,
    parse_static_gtfs,
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


    def test_parses_official_english_translations(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "stops.txt",
                "stop_id,stop_name,stop_lat,stop_lon\n"
                "115,東日本橋,35.0,139.0\n"
                "116,浅草橋,35.1,139.1\n",
            )
            archive.writestr(
                "trips.txt",
                "route_id,service_id,trip_id,trip_headsign\n"
                "1,WK,trip-1,青砥\n",
            )
            archive.writestr(
                "stop_times.txt",
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                "trip-1,10:00:00,10:00:30,115,1\n"
                "trip-1,10:02:00,10:02:30,116,2\n",
            )
            archive.writestr(
                "translations.txt",
                "table_name,field_name,language,translation,record_id,record_sub_id,field_value\n"
                "stops,stop_name,en,Higashi-nihombashi,115,,\n"
                "stops,stop_name,en,Asakusabashi,,,浅草橋\n"
                "trips,trip_headsign,en,Aoto,,,青砥\n",
            )

        parsed = parse_static_gtfs(buffer.getvalue())
        trip = parsed.trips["trip-1"]

        self.assertEqual(trip.headsign_en, "Aoto")
        self.assertEqual(trip.stops[0].stop_name_en, "Higashi-nihombashi")
        self.assertEqual(trip.stops[1].stop_name_en, "Asakusabashi")


if __name__ == "__main__":
    unittest.main()
