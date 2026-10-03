import unittest

from app.services.train_realtime import StaticTrainGtfs, StaticTrainStop, StaticTrainTrip
from app.services.train_route_identity import enrich_route_result_train_trip_ids


class _FakeTimetableManager:
    def __init__(self, weekday):
        self.train_patterns_weekday = weekday
        self.train_patterns_weekend = weekday
        self.realtime_delays = {}
        self.train_status_text = {}


class TrainRouteIdentityLateNightRegressionTest(unittest.TestCase):
    def test_late_midnight_train_does_not_poison_afternoon_route(self):
        a = "odpt.Station:Toei.Oedo.A"
        b = "odpt.Station:Toei.Oedo.B"
        c = "odpt.Station:Toei.Oedo.C"
        weekday = {
            a: [
                {"dep": 16 * 60 + 20, "arr": 16 * 60 + 25, "next_sta": b, "train_num": "1620A"},
                {"dep": 23 * 60 + 10, "arr": 23 * 60 + 59, "next_sta": b, "train_num": "2302A"},
            ],
            b: [
                {"dep": 16 * 60 + 26, "arr": 16 * 60 + 31, "next_sta": c, "train_num": "1620A"},
                # Mirrors the loaded ODPT shape around midnight: the crossing
                # segment is absent and the next retained segment starts 00:00.
                {"dep": 0, "arr": 2, "next_sta": c, "train_num": "2302A"},
            ],
        }
        candidate = {
            "id": "Fastest",
            "steps": [{
                "step_id": "rail-1",
                "kind": "rail",
                "departure_time": "16:20",
                "arrival_time": "16:31",
                "boarding_minutes": 2,
                "stops": [
                    {"id": "A", "odpt_id": a, "name": "renamed A"},
                    {"id": "B", "odpt_id": b, "name": "renamed B"},
                    {"id": "C", "odpt_id": c, "name": "renamed C"},
                ],
            }],
        }
        trip = StaticTrainTrip(
            trip_id="afternoon-trip",
            route_id="1",
            headsign="C",
            stops=(
                StaticTrainStop(
                    1,
                    "101",
                    "GTFS A",
                    "16:20:00",
                    "16:20:00",
                    stop_code="A",
                ),
                StaticTrainStop(
                    2,
                    "102",
                    "GTFS B",
                    "16:25:00",
                    "16:26:00",
                    stop_code="B",
                ),
                StaticTrainStop(
                    3,
                    "103",
                    "GTFS C",
                    "16:31:00",
                    "16:31:00",
                    stop_code="C",
                ),
            ),
        )

        result = enrich_route_result_train_trip_ids(
            {"candidates": [candidate], "meta": {}},
            timetable_manager=_FakeTimetableManager(weekday),
            day_type="weekday",
            static_gtfs=StaticTrainGtfs(trips={trip.trip_id: trip}),
        )

        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["steps"][0]["trip_id"], "afternoon-trip")
        rail = result["candidates"][0]["steps"][0]
        self.assertEqual(rail["boarding_minutes"], 2)
        self.assertEqual([stop["id"] for stop in rail["stops"]], ["101", "102", "103"])


if __name__ == "__main__":
    unittest.main()
