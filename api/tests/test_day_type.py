import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from toei_engine import TimetableManager, determine_day_type


class DetermineDayTypeTest(unittest.TestCase):
    def test_weekday(self):
        self.assertEqual(
            determine_day_type(datetime.date(2026, 8, 10)),
            "weekday",
        )

    def test_saturday(self):
        self.assertEqual(
            determine_day_type(datetime.date(2026, 8, 8)),
            "saturday",
        )

    def test_sunday(self):
        self.assertEqual(
            determine_day_type(datetime.date(2026, 8, 9)),
            "holiday",
        )

    def test_japanese_public_holiday(self):
        # 2026-08-11 is Mountain Day, even though it is a Tuesday.
        self.assertEqual(
            determine_day_type(datetime.date(2026, 8, 11)),
            "holiday",
        )

    def test_calendar_dates_selects_saturday_service_for_ue23_on_wednesday(self):
        active_services = frozenset({"61-160"})
        fake_repo = SimpleNamespace(
            is_loaded=True,
            service_calendar={"61-160": object(), "61-170": object()},
            service_exceptions={"20260812": {"61-160": 1, "61-170": 2}},
            get_active_service_ids=lambda day: active_services,
        )
        manager = TimetableManager()
        manager.bus_departures_by_service = {
            "pole": {
                "odpt.Busroute:Toei.Ue23": {
                    "61-160": [{"dep": 600, "dest": None, "trip": "sat"}],
                    "61-170": [{"dep": 610, "dest": None, "trip": "weekday"}],
                }
            }
        }

        with patch("toei_engine.gtfs_repo", fake_repo):
            day_type = determine_day_type(datetime.date(2026, 8, 12))
            departure, trip = manager.get_next_bus_departure(
                "pole",
                "odpt.Busroute:Toei.Ue23",
                590,
                day_type=day_type,
            )

        # Trains and legacy callers still see Wednesday as a weekday, while
        # the bus lookup uses the exact active GTFS service for this route.
        self.assertEqual(day_type, "weekday")
        self.assertEqual(departure, 600)
        self.assertEqual(trip, "sat")

    def test_removed_weekday_service_does_not_fall_back(self):
        fake_repo = SimpleNamespace(
            is_loaded=True,
            service_calendar={"61-170": object()},
            service_exceptions={"20260812": {"61-170": 2}},
            get_active_service_ids=lambda day: frozenset(),
        )
        manager = TimetableManager()
        manager.bus_departures_weekday = {
            "pole": {
                "route": [{"dep": 610, "dest": None, "trip": "weekday"}]
            }
        }
        manager.bus_departures_by_service = {
            "pole": {
                "route": {
                    "61-170": [
                        {"dep": 610, "dest": None, "trip": "weekday"}
                    ]
                }
            }
        }

        with patch("toei_engine.gtfs_repo", fake_repo):
            day_type = determine_day_type(datetime.date(2026, 8, 12))
            departure, trip = manager.get_next_bus_departure(
                "pole", "route", 590, day_type=day_type
            )

        self.assertIsNone(departure)
        self.assertIsNone(trip)


if __name__ == "__main__":
    unittest.main()
