import os
import tempfile
import unittest
from collections import defaultdict

from gtfs_loader import GtfsRepository


class GtfsServiceCalendarTest(unittest.TestCase):
    def test_calendar_dates_additions_and_removals_override_wednesday(self):
        with tempfile.TemporaryDirectory() as directory:
            files = {
                "calendar.txt": (
                    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                    "61-160,0,0,0,0,0,1,0,20260101,20261231\n"
                    "61-170,1,1,1,1,1,0,0,20260101,20261231\n"
                ),
                "calendar_dates.txt": (
                    "service_id,date,exception_type\n"
                    "61-160,20260812,1\n"
                    "61-170,20260812,2\n"
                    "61-160,20260813,1\n"
                    "61-170,20260813,2\n"
                ),
                "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nstop-1,平井七丁目,35.0,139.0\n",
                "routes.txt": "route_id,route_short_name,route_type\n070,上２３,3\n",
                "trips.txt": "route_id,service_id,trip_id\n070,61-160,trip-1\n",
                "stop_times.txt": (
                    "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                    "trip-1,10:00:00,10:00:00,stop-1,1\n"
                ),
            }
            for filename, content in files.items():
                with open(
                    os.path.join(directory, filename),
                    "w",
                    encoding="utf-8",
                    newline="",
                ) as file:
                    file.write(content)

            repository = object.__new__(GtfsRepository)
            repository.stops = {}
            repository.trips = {}
            repository.stop_times = defaultdict(dict)
            repository.routes = {}
            repository.route_name_to_id = {}
            repository.timetable_index = defaultdict(list)
            repository.service_calendar = {}
            repository.service_exceptions = defaultdict(dict)
            repository._active_service_cache = {}
            repository.is_loaded = False

            repository.load_data(directory)

            self.assertEqual(
                repository.get_active_service_ids("2026-08-12"),
                frozenset({"61-160"}),
            )
            self.assertEqual(
                repository.get_active_service_ids("2026-08-13"),
                frozenset({"61-160"}),
            )
            self.assertEqual(
                repository.get_active_service_ids("2026-08-19"),
                frozenset({"61-170"}),
            )


if __name__ == "__main__":
    unittest.main()
