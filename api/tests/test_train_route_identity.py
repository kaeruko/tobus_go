import unittest

from app.services.train_realtime import (
    StaticTrainGtfs,
    StaticTrainStop,
    StaticTrainTrip,
)
from app.services.train_route_identity import (
    enrich_route_result_train_trip_ids,
)


class _FakeTimetableManager:
    def __init__(self, weekday, *, delays=None, status=None):
        self.train_patterns_weekday = weekday
        self.train_patterns_weekend = weekday
        self.realtime_delays = delays or {}
        self.train_status_text = status or {}


class TrainRouteIdentityTest(unittest.TestCase):
    def _candidate(self, *, arrival_time="16:30"):
        return {
            "id": "Fastest",
            "steps": [
                {
                    "step_id": "rail-1",
                    "kind": "rail",
                    "title": "浅草線",
                    "from_": "東日本橋",
                    "to": "蔵前",
                    "departure_time": "16:22",
                    "arrival_time": arrival_time,
                    "route_id": None,
                    "trip_id": None,
                    "stops": [
                        {"id": "odpt.Station:Toei.Asakusa.HigashiNihombashi", "name": "東日本橋"},
                        {"id": "odpt.Station:Toei.Asakusa.Asakusabashi", "name": "浅草橋"},
                        {"id": "odpt.Station:Toei.Asakusa.Kuramae", "name": "蔵前"},
                    ],
                }
            ],
        }

    def _weekday(self, *, second_train="N1"):
        return {
            "odpt.Station:Toei.Asakusa.HigashiNihombashi": [
                {
                    "dep": 16 * 60 + 25,
                    "arr": 16 * 60 + 27,
                    "next_sta": "odpt.Station:Toei.Asakusa.Asakusabashi",
                    "train_num": "N1",
                }
            ],
            "odpt.Station:Toei.Asakusa.Asakusabashi": [
                {
                    "dep": 16 * 60 + 28,
                    "arr": 16 * 60 + 30,
                    "next_sta": "odpt.Station:Toei.Asakusa.Kuramae",
                    "train_num": second_train,
                }
            ],
        }

    def _weekday_with_two_through_trains(self):
        return {
            "odpt.Station:Toei.Asakusa.HigashiNihombashi": [
                {
                    "dep": 16 * 60 + 25,
                    "arr": 16 * 60 + 27,
                    "next_sta": "odpt.Station:Toei.Asakusa.Asakusabashi",
                    "train_num": "N1",
                },
                {
                    "dep": 16 * 60 + 29,
                    "arr": 16 * 60 + 31,
                    "next_sta": "odpt.Station:Toei.Asakusa.Asakusabashi",
                    "train_num": "N2",
                },
            ],
            "odpt.Station:Toei.Asakusa.Asakusabashi": [
                {
                    "dep": 16 * 60 + 28,
                    "arr": 16 * 60 + 30,
                    "next_sta": "odpt.Station:Toei.Asakusa.Kuramae",
                    "train_num": "N1",
                },
                {
                    "dep": 16 * 60 + 32,
                    "arr": 16 * 60 + 34,
                    "next_sta": "odpt.Station:Toei.Asakusa.Kuramae",
                    "train_num": "N2",
                },
            ],
        }

    def _trip(
        self,
        trip_id="121603T0",
        *,
        departure="16:25:00",
        middle_arrival="16:27:00",
        middle_departure="16:28:00",
        arrival="16:30:00",
    ):
        return StaticTrainTrip(
            trip_id=trip_id,
            route_id="1",
            headsign="青砥",
            stops=(
                StaticTrainStop(
                    9,
                    "A15",
                    "東日本橋",
                    departure,
                    departure,
                ),
                StaticTrainStop(
                    10,
                    "A16",
                    "浅草橋",
                    middle_arrival,
                    middle_departure,
                ),
                StaticTrainStop(
                    11,
                    "A17",
                    "蔵前",
                    arrival,
                    arrival,
                ),
            ),
        )

    def test_assigns_exact_static_gtfs_trip_id_and_route_id(self):
        trip = self._trip()
        result = enrich_route_result_train_trip_ids(
            {"candidates": [self._candidate()], "meta": {}},
            timetable_manager=_FakeTimetableManager(self._weekday()),
            day_type="weekday",
            static_gtfs=StaticTrainGtfs(trips={trip.trip_id: trip}),
        )

        self.assertEqual(len(result["candidates"]), 1)
        rail = result["candidates"][0]["steps"][0]
        self.assertEqual(rail["trip_id"], "121603T0")
        self.assertEqual(rail["route_id"], "1")

    def test_matches_static_schedule_even_when_route_arrival_contains_delay(self):
        trip = self._trip()
        result = enrich_route_result_train_trip_ids(
            {"candidates": [self._candidate(arrival_time="16:35")], "meta": {}},
            timetable_manager=_FakeTimetableManager(
                self._weekday(),
                delays={"N1": 5 * 60},
            ),
            day_type="weekday",
            static_gtfs=StaticTrainGtfs(trips={trip.trip_id: trip}),
        )

        rail = result["candidates"][0]["steps"][0]
        self.assertEqual(rail["trip_id"], "121603T0")

    def test_selects_later_through_train_that_matches_route_arrival(self):
        first_trip = self._trip("first-trip")
        later_trip = self._trip(
            "later-trip",
            departure="16:29:00",
            middle_arrival="16:31:00",
            middle_departure="16:32:00",
            arrival="16:34:00",
        )
        result = enrich_route_result_train_trip_ids(
            {"candidates": [self._candidate(arrival_time="16:34")], "meta": {}},
            timetable_manager=_FakeTimetableManager(
                self._weekday_with_two_through_trains(),
            ),
            day_type="weekday",
            static_gtfs=StaticTrainGtfs(
                trips={
                    first_trip.trip_id: first_trip,
                    later_trip.trip_id: later_trip,
                }
            ),
        )

        rail = result["candidates"][0]["steps"][0]
        self.assertEqual(rail["trip_id"], "later-trip")
        self.assertEqual(rail["route_id"], "1")

    def test_rejects_candidate_that_would_switch_train_without_alighting(self):
        trip = self._trip()
        result = enrich_route_result_train_trip_ids(
            {"candidates": [self._candidate()], "meta": {}},
            timetable_manager=_FakeTimetableManager(
                self._weekday(second_train="N2"),
            ),
            day_type="weekday",
            static_gtfs=StaticTrainGtfs(trips={trip.trip_id: trip}),
        )

        self.assertEqual(result["candidates"], [])
        rejection = result["meta"]["train_identity_rejected_candidates"][0]
        self.assertEqual(rejection["code"], "rail_odpt_run_segment_missing")

    def test_rejects_ambiguous_static_gtfs_trip(self):
        trip1 = self._trip("121603T0")
        trip2 = self._trip("duplicate-trip")
        result = enrich_route_result_train_trip_ids(
            {"candidates": [self._candidate()], "meta": {}},
            timetable_manager=_FakeTimetableManager(self._weekday()),
            day_type="weekday",
            static_gtfs=StaticTrainGtfs(
                trips={trip1.trip_id: trip1, trip2.trip_id: trip2},
            ),
        )

        self.assertEqual(result["candidates"], [])
        rejection = result["meta"]["train_identity_rejected_candidates"][0]
        self.assertEqual(rejection["code"], "rail_static_trip_ambiguous")

    def test_rejects_route_arrival_that_matches_no_complete_odpt_train(self):
        trip = self._trip()
        result = enrich_route_result_train_trip_ids(
            {"candidates": [self._candidate(arrival_time="16:31")], "meta": {}},
            timetable_manager=_FakeTimetableManager(self._weekday()),
            day_type="weekday",
            static_gtfs=StaticTrainGtfs(trips={trip.trip_id: trip}),
        )

        self.assertEqual(result["candidates"], [])
        rejection = result["meta"]["train_identity_rejected_candidates"][0]
        self.assertEqual(rejection["code"], "rail_route_arrival_mismatch")


if __name__ == "__main__":
    unittest.main()
