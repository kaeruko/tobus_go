"""GTFS/ODPT source wrappers share an entrypoint, without changing routing."""
from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from transit_adapters import (
    GtfsFeedSource, GtfsTransitAdapter,
    OdptCalendarRule, OdptFeedSource, OdptTransitAdapter,
    TransitFeedSource,
)
from transit_dataset import FeedMetadata, TransitDataset, namespace_id
from tests.transit_schedule_oracle import FixtureScheduleOracle


DAY = date(2026, 10, 14)
DEPARTURE = datetime(2026, 10, 14, 9, 50, tzinfo=timezone.utc)
RULES = {
    "weekday": OdptCalendarRule(
        weekdays=(True, True, True, True, True, False, False),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    ),
}


def _metadata(feed_id, source_type):
    return FeedMetadata(
        feed_id=feed_id,
        source_type=source_type,
        source_uri="https://example.invalid/static-fixture",
        version="2026-10-14",
        fetched_at=DEPARTURE,
    )


def _gtfs_source(directory, *, skip=False):
    contents = {
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "a,A,35.0,139.0\nb,B,35.01,139.01\n"
        ),
        "routes.txt": (
            "route_id,route_short_name,route_long_name,route_type\n"
            "r,1,Sample bus route,3\n"
        ),
        "trips.txt": "route_id,service_id,trip_id,trip_headsign\nr,weekday,t,B\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "t,10:02:00,10:02:00,a,1\n"
            "t,10:12:00,10:12:00,b,2\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "weekday,1,1,1,1,1,0,0,20260101,20261231\n"
        ),
    }
    for name, content in contents.items():
        (directory / name).write_text(content, encoding="utf-8")
    return GtfsFeedSource(
        directory=directory,
        metadata=_metadata("gtfs_fixture", "gtfs-jp"),
        skip_untimed_intermediate_stops=skip,
    )


def _odpt_source(*, rules=RULES):
    return OdptFeedSource(
        metadata=_metadata("odpt_fixture", "odpt"),
        calendar_rules=rules,
        busstop_poles=(
            {"owl:sameAs": "a", "dc:title": "A", "geo:lat": 35.0, "geo:long": 139.0},
            {"owl:sameAs": "b", "dc:title": "B", "geo:lat": 35.01, "geo:long": 139.01},
        ),
        busroute_patterns=(
            {"owl:sameAs": "p", "odpt:busroute": "r", "dc:title": "1"},
        ),
        bus_timetables=(
            {
                "owl:sameAs": "t",
                "odpt:busroutePattern": "p",
                "odpt:calendar": "weekday",
                "odpt:busTimetableObject": [
                    {
                        "odpt:index": 1, "odpt:busstopPole": "a",
                        "odpt:arrivalTime": "10:02", "odpt:departureTime": "10:02",
                    },
                    {
                        "odpt:index": 2, "odpt:busstopPole": "b",
                        "odpt:arrivalTime": "10:12", "odpt:departureTime": "10:12",
                    },
                ],
            },
        ),
    )


class TransitFeedSourceTest(unittest.TestCase):
    def test_same_load_interface_and_schedule_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources: tuple[TransitFeedSource, ...] = (
                _gtfs_source(Path(tmp)),
                _odpt_source(),
            )
            for source in sources:
                with self.subTest(source=type(source).__name__):
                    self.assertIsInstance(source, TransitFeedSource)
                    dataset = source.load()
                    self.assertIsInstance(dataset, TransitDataset)
                    prefix = dataset.metadata.feed_id
                    self.assertEqual(
                        set(dataset.stops),
                        {namespace_id(prefix, "a"), namespace_id(prefix, "b")},
                    )
                    self.assertEqual(dataset.metadata.version, "2026-10-14")
                    self.assertEqual(
                        dataset.active_service_ids(DAY),
                        frozenset({namespace_id(prefix, "weekday")}),
                    )
                    engine = FixtureScheduleOracle(dataset)
                    journey = engine.search_fastest(
                        namespace_id(prefix, "a"), namespace_id(prefix, "b"),
                        departure=DEPARTURE,
                    )
                    self.assertIsNotNone(journey)
                    self.assertEqual(journey.arrival_minute, 10 * 60 + 12)
                    self.assertEqual(journey.rides, 1)
                    self.assertEqual(journey.legs[0].trip_id, namespace_id(prefix, "t"))

    def test_wrappers_preserve_existing_adapter_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            gtfs = _gtfs_source(Path(tmp))
            odpt = _odpt_source()
            self.assertEqual(
                gtfs.load(),
                GtfsTransitAdapter.load(gtfs.directory, metadata=gtfs.metadata),
            )
            self.assertEqual(
                odpt.load(),
                OdptTransitAdapter.build(
                    metadata=odpt.metadata,
                    busstop_poles=odpt.busstop_poles,
                    busroute_patterns=odpt.busroute_patterns,
                    bus_timetables=odpt.bus_timetables,
                    stations=odpt.stations,
                    railways=odpt.railways,
                    train_timetables=odpt.train_timetables,
                    calendar_rules=odpt.calendar_rules,
                ),
            )

    def test_explicit_gtfs_compatibility_flag_is_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _gtfs_source(Path(tmp), skip=True)
            self.assertEqual(
                source.load(),
                GtfsTransitAdapter.load(
                    source.directory,
                    metadata=source.metadata,
                    skip_untimed_intermediate_stops=True,
                ),
            )

    def test_missing_gtfs_and_unknown_odpt_calendar_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = GtfsFeedSource(
                directory=Path(tmp) / "missing",
                metadata=_metadata("missing", "gtfs-jp"),
            )
            with self.assertRaises(FileNotFoundError):
                missing.load()
        with self.assertRaisesRegex(ValueError, "Calendar semantics"):
            _odpt_source(rules={}).load()

    def test_distinct_sources_keep_identity_and_do_not_mutate_each_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            gtfs = _gtfs_source(Path(tmp)).load()
            odpt = _odpt_source().load()
            self.assertFalse(set(gtfs.stops).intersection(odpt.stops))
            self.assertFalse(set(gtfs.trips).intersection(odpt.trips))
            self.assertEqual(gtfs.metadata.version, odpt.metadata.version)
            self.assertNotEqual(gtfs.metadata.feed_id, odpt.metadata.feed_id)


if __name__ == "__main__":
    unittest.main()

