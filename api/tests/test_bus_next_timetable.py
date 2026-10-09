import unittest
from types import SimpleNamespace
from unittest.mock import patch

import networkx as nx

from fastapi import HTTPException

from app.routes import (
    _gtfs_bus_timetable_destinations,
    _resolve_bus_timetable_day_type,
)


class _FakeGtfsRepository:
    def __init__(self):
        self.timetable_index = {
            "070|1414-04": [
                (600, 1, "trip-1"),
                (700, 1, "trip-2"),
            ]
        }
        self.trips = {
            "trip-1": {"route_id": "070", "service_id": "WK"},
            "trip-2": {"route_id": "070", "service_id": "WK"},
        }
        self.stop_times = {
            "trip-1": {
                1: ("1414-04", 600, 600),
                2: ("0131-05", 620, 620),
                3: ("0000-01", 640, 640),
            },
            "trip-2": {
                1: ("1414-04", 700, 700),
                2: ("0131-05", 720, 720),
                3: ("0000-01", 740, 740),
            },
        }
        self.stops = {
            "1414-04": {
                "name": "本所吾妻橋",
                "name_en": "Honjo-azumabashi",
            },
            "0131-05": {
                "name": "押上",
                "name_en": "Oshiage",
            },
            "0000-01": {
                "name": "上野松坂屋前",
                "name_en": "Ueno-matsuzakaya",
            },
        }

    def get_trip_stop_time_after(
        self,
        trip_id,
        stop_id,
        after_sequence=-1,
    ):
        for sequence, stop_time in sorted(self.stop_times[trip_id].items()):
            if sequence > after_sequence and stop_time[0] == stop_id:
                return sequence, stop_time[1], stop_time[2]
        return None


class BusNextTimetableTest(unittest.TestCase):
    def test_day_type_selector_finds_requested_schedule(self):
        def fake_determine_day_type(value):
            if value.weekday() == 5:
                return "saturday"
            if value.weekday() == 6:
                return "holiday"
            return "weekday"

        with patch(
            "app.routes.determine_day_type",
            side_effect=fake_determine_day_type,
        ):
            result = _resolve_bus_timetable_day_type(None, "Saturday")

        self.assertEqual(result, "saturday")

    def test_day_type_selector_rejects_ambiguous_date_and_day_type(self):
        with self.assertRaises(HTTPException) as raised:
            _resolve_bus_timetable_day_type("2026-09-28", "weekday")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(
            raised.exception.detail["code"],
            "bus_timetable_day_selector_conflict",
        )

    def test_day_type_selector_rejects_invalid_date(self):
        with self.assertRaises(HTTPException) as raised:
            _resolve_bus_timetable_day_type("2026/09/28", None)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(
            raised.exception.detail["code"],
            "bus_timetable_date_invalid",
        )

    def test_day_type_selector_rejects_unknown_value(self):
        with self.assertRaises(HTTPException) as raised:
            _resolve_bus_timetable_day_type(None, "weekend")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(
            raised.exception.detail["code"],
            "bus_timetable_day_type_invalid",
        )

    def test_missing_gtfs_english_name_uses_exact_odpt_pole_id(self):
        fake_repo = _FakeGtfsRepository()
        fake_repo.timetable_index = {"093|0751-02": [(520, 1, "trip-toyomi")]}
        fake_repo.trips = {
            "trip-toyomi": {"route_id": "093", "service_id": "WK"},
        }
        fake_repo.stop_times = {
            "trip-toyomi": {
                1: ("0751-02", 520, 520),
                2: ("0785-02", 535, 535),
                3: ("1035-01", 550, 550),
            },
        }
        fake_repo.stops = {
            "0751-02": {"name": "十間橋", "name_en": "Jukkembashi"},
            "0785-02": {
                "name": "都営両国駅前",
                "name_en": "Toei-Ryōgoku Sta.",
            },
            "1035-01": {"name": "豊海水産埠頭", "name_en": None},
        }
        graph = nx.DiGraph()
        graph.add_node(
            ("phys", "odpt.BusstopPole:Toei.ToyomiSuisanFuto.1035.1"),
            name="豊海水産埠頭",
            name_en="Toyomi-Suisan-Futō",
        )
        day_type = SimpleNamespace(
            has_gtfs_calendar=True,
            active_service_ids=frozenset({"WK"}),
        )

        with patch("app.routes.gtfs_repo", fake_repo):
            destinations = _gtfs_bus_timetable_destinations(
                route_id="093",
                pole_id="0751-02",
                target_pole_id="0785-02",
                day_type=day_type,
                current_minute=8 * 60 + 40,
                limit=3,
                include_all=False,
                delay_min=0,
                graph=graph,
            )

        self.assertEqual(destinations[0]["destination_pole_id"], "1035-01")
        self.assertEqual(destinations[0]["destination_name"], "豊海水産埠頭")
        self.assertEqual(
            destinations[0]["destination_name_en"],
            "Toyomi-Suisan-Futō",
        )

    def test_odpt_pole_identity_does_not_use_japanese_name(self):
        fake_repo = _FakeGtfsRepository()
        fake_repo.timetable_index = {"093|0751-02": [(520, 1, "trip-toyomi")]}
        fake_repo.trips = {
            "trip-toyomi": {"route_id": "093", "service_id": "WK"},
        }
        fake_repo.stop_times = {
            "trip-toyomi": {
                1: ("0751-02", 520, 520),
                2: ("1035-01", 550, 550),
            },
        }
        fake_repo.stops = {
            "0751-02": {"name": "十間橋", "name_en": "Jukkembashi"},
            "1035-01": {"name": "豊海水産埠頭", "name_en": None},
        }
        graph = nx.DiGraph()
        graph.add_node(
            ("phys", "odpt.BusstopPole:Toei.ToyomiSuisanFuto.1035.1"),
            name="この名前は識別に使わない",
            name_en="Toyomi-Suisan-Futō",
        )
        day_type = SimpleNamespace(
            has_gtfs_calendar=True,
            active_service_ids=frozenset({"WK"}),
        )

        with patch("app.routes.gtfs_repo", fake_repo):
            destinations = _gtfs_bus_timetable_destinations(
                route_id="093",
                pole_id="0751-02",
                target_pole_id=None,
                day_type=day_type,
                current_minute=8 * 60 + 40,
                limit=3,
                include_all=False,
                delay_min=0,
                graph=graph,
            )

        self.assertEqual(
            destinations[0]["destination_name_en"],
            "Toyomi-Suisan-Futō",
        )

    def test_odpt_pole_identity_rejects_same_name_with_different_id(self):
        fake_repo = _FakeGtfsRepository()
        fake_repo.timetable_index = {"093|0751-02": [(520, 1, "trip-toyomi")]}
        fake_repo.trips = {
            "trip-toyomi": {"route_id": "093", "service_id": "WK"},
        }
        fake_repo.stop_times = {
            "trip-toyomi": {
                1: ("0751-02", 520, 520),
                2: ("1035-01", 550, 550),
            },
        }
        fake_repo.stops = {
            "0751-02": {"name": "十間橋", "name_en": "Jukkembashi"},
            "1035-01": {"name": "豊海水産埠頭", "name_en": None},
        }
        graph = nx.DiGraph()
        graph.add_node(
            ("phys", "odpt.BusstopPole:Toei.OtherStop.1036.1"),
            name="豊海水産埠頭",
            name_en="Wrong stop with same Japanese name",
        )
        day_type = SimpleNamespace(
            has_gtfs_calendar=True,
            active_service_ids=frozenset({"WK"}),
        )

        with patch("app.routes.gtfs_repo", fake_repo):
            with self.assertRaisesRegex(
                RuntimeError,
                "no exact ODPT pole ID match",
            ):
                _gtfs_bus_timetable_destinations(
                    route_id="093",
                    pole_id="0751-02",
                    target_pole_id=None,
                    day_type=day_type,
                    current_minute=8 * 60 + 40,
                    limit=3,
                    include_all=False,
                    delay_min=0,
                    graph=graph,
                )

    def test_pattern_trip_keeps_different_stop_sequences_separate(self):
        fake_repo = _FakeGtfsRepository()
        fake_repo.timetable_index = {
            "096|1269-01": [
                (900, 1, "trip-asakusa"),
                (920, 1, "trip-ueno"),
            ]
        }
        fake_repo.trips = {
            "trip-asakusa": {"route_id": "096", "service_id": "WK"},
            "trip-ueno": {"route_id": "096", "service_id": "WK"},
        }
        fake_repo.stop_times = {
            "trip-asakusa": {
                1: ("1269-01", 900, 900),
                2: ("1268-01", 902, 902),
                3: ("0035-06", 930, 930),
            },
            "trip-ueno": {
                1: ("1269-01", 920, 920),
                2: ("1268-01", 922, 922),
                3: ("0035-06", 950, 950),
                4: ("0131-01", 958, 958),
                5: ("2000-07", 965, 965),
            },
        }
        fake_repo.stops = {
            "1269-01": {
                "name": "東向島六丁目",
                "name_en": "Higashi-mukojima 6-chome",
            },
            "1268-01": {
                "name": "東向島五丁目",
                "name_en": "Higashi-mukojima 5-chome",
            },
            "0035-06": {
                "name": "浅草寿町",
                "name_en": "Asakusa-Kotobukicho",
            },
            "0131-01": {
                "name": "上野駅前",
                "name_en": "Ueno Sta.",
            },
            "2000-07": {
                "name": "上野松坂屋前",
                "name_en": "Ueno-Matsuzakaya",
            },
        }
        day_type = SimpleNamespace(
            has_gtfs_calendar=True,
            active_service_ids=frozenset({"WK"}),
        )

        with patch("app.routes.gtfs_repo", fake_repo):
            asakusa = _gtfs_bus_timetable_destinations(
                route_id="096",
                pole_id="1269-01",
                target_pole_id="1268-01",
                pattern_trip_id="trip-asakusa",
                day_type=day_type,
                current_minute=14 * 60,
                limit=3,
                include_all=True,
                delay_min=0,
            )
            ueno = _gtfs_bus_timetable_destinations(
                route_id="096",
                pole_id="1269-01",
                target_pole_id="1268-01",
                pattern_trip_id="trip-ueno",
                day_type=day_type,
                current_minute=14 * 60,
                limit=3,
                include_all=True,
                delay_min=0,
            )

        self.assertEqual(
            [group["destination_name"] for group in asakusa],
            ["浅草寿町"],
        )
        self.assertEqual(asakusa[0]["all_times"], ["15:00"])
        self.assertEqual(
            [group["destination_name"] for group in ueno],
            ["上野松坂屋前"],
        )
        self.assertEqual(ueno[0]["all_times"], ["15:20"])

    def test_full_day_remains_visible_after_last_upcoming_bus(self):
        fake_repo = _FakeGtfsRepository()
        day_type = SimpleNamespace(
            has_gtfs_calendar=True,
            active_service_ids=frozenset({"WK"}),
        )

        with patch("app.routes.gtfs_repo", fake_repo):
            destinations = _gtfs_bus_timetable_destinations(
                route_id="070",
                pole_id="1414-04",
                target_pole_id="0131-05",
                day_type=day_type,
                current_minute=23 * 60,
                limit=3,
                include_all=True,
                delay_min=0,
            )

        self.assertEqual(len(destinations), 1)
        self.assertEqual(destinations[0]["destination_pole_id"], "0000-01")
        self.assertEqual(destinations[0]["destination_name"], "上野松坂屋前")
        self.assertEqual(
            destinations[0]["destination_name_en"],
            "Ueno-matsuzakaya",
        )
        self.assertEqual(destinations[0]["times"], [])
        self.assertEqual(destinations[0]["all_times"], ["10:00", "11:40"])


if __name__ == "__main__":
    unittest.main()
