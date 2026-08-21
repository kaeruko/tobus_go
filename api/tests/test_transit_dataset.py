import os
import tempfile
import unittest
from datetime import date, datetime, timezone

from transit_adapters.gtfs import GtfsTransitAdapter
from transit_adapters.odpt import OdptCalendarRule, OdptTransitAdapter
from transit_dataset import FeedMetadata, namespace_id
from transit_engine import TransitRouteEngine


WEEKDAYS = (True, True, True, True, True, False, False)
SERVICE_DAY = datetime(2026, 8, 17, 9, 55, tzinfo=timezone.utc)
FETCHED_AT = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)


class TransitDatasetTest(unittest.TestCase):
    def _metadata(self, feed_id: str, source_type: str) -> FeedMetadata:
        return FeedMetadata(
            feed_id=feed_id,
            source_type=source_type,
            source_uri=f"https://example.invalid/{feed_id}",
            version="2026-08-17",
            fetched_at=FETCHED_AT,
        )

    def _write_gtfs(self, directory: str) -> None:
        files = {
            "stops.txt": (
                "stop_id,stop_name,stop_lat,stop_lon\n"
                "a,A,35.0,139.0\n"
                "b,B,35.1,139.1\n"
                "c,C,35.2,139.2\n"
            ),
            "routes.txt": (
                "route_id,route_short_name,route_long_name,route_type\n"
                "r1,R1,Fast first leg,3\n"
                "r2,R2,Fast second leg,3\n"
                "r3,R3,Direct,3\n"
            ),
            "trips.txt": (
                "route_id,service_id,trip_id,trip_headsign,direction_id\n"
                "r1,weekday,t1,B,0\n"
                "r2,weekday,t2,C,0\n"
                "r3,weekday,t3,C,0\n"
            ),
            "stop_times.txt": (
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                "t1,10:00:00,10:00:00,a,1\n"
                "t1,10:10:00,10:10:00,b,2\n"
                "t2,10:11:00,10:11:00,b,1\n"
                "t2,10:20:00,10:20:00,c,2\n"
                "t3,10:05:00,10:05:00,a,1\n"
                "t3,10:30:00,10:30:00,c,2\n"
            ),
            "calendar.txt": (
                "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                "weekday,1,1,1,1,1,0,0,20260101,20261231\n"
            ),
            "calendar_dates.txt": "service_id,date,exception_type\n",
        }
        for filename, content in files.items():
            with open(
                os.path.join(directory, filename),
                "w",
                encoding="utf-8",
                newline="",
            ) as handle:
                handle.write(content)

    def _gtfs_dataset(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self._write_gtfs(temp_dir.name)
        return GtfsTransitAdapter.load(
            temp_dir.name,
            metadata=self._metadata("gtfs_test", "gtfs-jp"),
        )

    def _odpt_dataset(self):
        poles = [
            {
                "owl:sameAs": "stop-a",
                "dc:title": "A",
                "geo:lat": 35.0,
                "geo:long": 139.0,
            },
            {
                "owl:sameAs": "stop-b",
                "dc:title": "B",
                "geo:lat": 35.1,
                "geo:long": 139.1,
            },
            {
                "owl:sameAs": "stop-c",
                "dc:title": "C",
                "geo:lat": 35.2,
                "geo:long": 139.2,
            },
        ]
        patterns = [
            {
                "owl:sameAs": "pattern-1",
                "odpt:busroute": "route-1",
                "dc:title": "R1",
            },
            {
                "owl:sameAs": "pattern-2",
                "odpt:busroute": "route-2",
                "dc:title": "R2",
            },
            {
                "owl:sameAs": "pattern-3",
                "odpt:busroute": "route-3",
                "dc:title": "R3",
            },
        ]

        def timetable(
            trip_id: str,
            pattern_id: str,
            stops: list[tuple[str, str, int]],
        ) -> dict:
            return {
                "owl:sameAs": trip_id,
                "odpt:busroutePattern": pattern_id,
                "odpt:calendar": "calendar-weekday",
                "dc:title": trip_id,
                "odpt:busTimetableObject": [
                    {
                        "odpt:index": sequence,
                        "odpt:busstopPole": stop_id,
                        "odpt:arrivalTime": clock,
                        "odpt:departureTime": clock,
                    }
                    for stop_id, clock, sequence in stops
                ],
            }

        timetables = [
            timetable(
                "trip-1",
                "pattern-1",
                [("stop-a", "10:00", 1), ("stop-b", "10:10", 2)],
            ),
            timetable(
                "trip-2",
                "pattern-2",
                [("stop-b", "10:11", 1), ("stop-c", "10:20", 2)],
            ),
            timetable(
                "trip-3",
                "pattern-3",
                [("stop-a", "10:05", 1), ("stop-c", "10:30", 2)],
            ),
        ]
        return OdptTransitAdapter.build(
            metadata=self._metadata("odpt_test", "odpt"),
            busstop_poles=poles,
            busroute_patterns=patterns,
            bus_timetables=timetables,
            calendar_rules={
                "calendar-weekday": OdptCalendarRule(
                    weekdays=WEEKDAYS,
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 12, 31),
                )
            },
        )

    def test_gtfs_adapter_tracks_feed_metadata_and_namespaces_ids(self):
        dataset = self._gtfs_dataset()

        self.assertEqual(dataset.metadata.feed_id, "gtfs_test")
        self.assertEqual(dataset.metadata.version, "2026-08-17")
        self.assertEqual(dataset.metadata.fetched_at, FETCHED_AT)
        self.assertIn("gtfs_test:a", dataset.stops)
        self.assertIn("gtfs_test:r1", dataset.routes)
        self.assertIn("gtfs_test:t1", dataset.trips)
        self.assertEqual(
            dataset.active_service_ids(SERVICE_DAY.date()),
            frozenset({"gtfs_test:weekday"}),
        )

    def test_route_engine_is_source_independent_for_fastest_and_fewest(self):
        cases = [
            (
                self._gtfs_dataset(),
                "gtfs_test:a",
                "gtfs_test:c",
            ),
            (
                self._odpt_dataset(),
                "odpt_test:stop-a",
                "odpt_test:stop-c",
            ),
        ]

        for dataset, origin, destination in cases:
            with self.subTest(source=dataset.metadata.source_type):
                engine = TransitRouteEngine(dataset)
                fastest = engine.search_fastest(
                    origin,
                    destination,
                    departure=SERVICE_DAY,
                )
                fewest = engine.search_fewest_transfers(
                    origin,
                    destination,
                    departure=SERVICE_DAY,
                )

                self.assertIsNotNone(fastest)
                self.assertEqual(fastest.arrival_minute, 10 * 60 + 20)
                self.assertEqual(fastest.rides, 2)
                self.assertEqual(fastest.transfers, 1)

                self.assertIsNotNone(fewest)
                self.assertEqual(fewest.arrival_minute, 10 * 60 + 30)
                self.assertEqual(fewest.rides, 1)
                self.assertEqual(fewest.transfers, 0)

    def test_gtfs_calendar_dates_override_regular_calendar(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self._write_gtfs(temp_dir.name)
        with open(
            os.path.join(temp_dir.name, "calendar_dates.txt"),
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            handle.write(
                "service_id,date,exception_type\n"
                "weekday,20260817,2\n"
                "special,20260817,1\n"
            )

        dataset = GtfsTransitAdapter.load(
            temp_dir.name,
            metadata=self._metadata("gtfs_exception", "gtfs-jp"),
        )
        self.assertEqual(
            dataset.active_service_ids(date(2026, 8, 17)),
            frozenset({"gtfs_exception:special"}),
        )

    def test_missing_required_gtfs_file_fails_without_fallback(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self._write_gtfs(temp_dir.name)
        os.remove(os.path.join(temp_dir.name, "trips.txt"))

        with self.assertRaises(FileNotFoundError):
            GtfsTransitAdapter.load(
                temp_dir.name,
                metadata=self._metadata("broken_gtfs", "gtfs-jp"),
            )

    def test_odpt_unknown_calendar_fails_instead_of_guessing(self):
        with self.assertRaisesRegex(ValueError, "Calendar semantics"):
            OdptTransitAdapter.build(
                metadata=self._metadata("odpt_bad", "odpt"),
                busstop_poles=[
                    {
                        "owl:sameAs": "a",
                        "dc:title": "A",
                        "geo:lat": 35.0,
                        "geo:long": 139.0,
                    },
                    {
                        "owl:sameAs": "b",
                        "dc:title": "B",
                        "geo:lat": 35.1,
                        "geo:long": 139.1,
                    },
                ],
                busroute_patterns=[
                    {
                        "owl:sameAs": "p",
                        "odpt:busroute": "r",
                        "dc:title": "R",
                    }
                ],
                bus_timetables=[
                    {
                        "owl:sameAs": "t",
                        "odpt:busroutePattern": "p",
                        "odpt:calendar": "unknown-calendar",
                        "dc:title": "T",
                        "odpt:busTimetableObject": [
                            {
                                "odpt:index": 1,
                                "odpt:busstopPole": "a",
                                "odpt:arrivalTime": "10:00",
                                "odpt:departureTime": "10:00",
                            },
                            {
                                "odpt:index": 2,
                                "odpt:busstopPole": "b",
                                "odpt:arrivalTime": "10:10",
                                "odpt:departureTime": "10:10",
                            },
                        ],
                    }
                ],
                calendar_rules={},
            )

    def test_namespace_id_does_not_normalize_invalid_input(self):
        self.assertEqual(namespace_id("nagoya_bus", "001"), "nagoya_bus:001")
        for invalid_feed in (" nagoya_bus", "nagoya_bus ", "nagoya:bus"):
            with self.subTest(feed=invalid_feed):
                with self.assertRaises(ValueError):
                    namespace_id(invalid_feed, "001")


if __name__ == "__main__":
    unittest.main()
