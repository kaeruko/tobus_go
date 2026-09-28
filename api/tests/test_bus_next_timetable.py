import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_day_type_selector_rejects_unknown_value(self):
        with self.assertRaises(HTTPException) as raised:
            _resolve_bus_timetable_day_type(None, "weekend")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(
            raised.exception.detail["code"],
            "bus_timetable_day_type_invalid",
        )

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
