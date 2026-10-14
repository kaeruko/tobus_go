"""Synthetic GTFS + ODPT: experimental scheduled + directed walking search."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from reviewed_walk_time import ReviewedWalkingLink
from route_engine import RouteSearchLimitError
from transit_adapters import GtfsFeedSource, OdptCalendarRule, OdptFeedSource
from transit_dataset import FeedMetadata
from transit_engine import SearchLimits, TransitLeg
from transit_network_experiment import (
    ExperimentalMultiFeedSearch, PinnedWalkLink, WalkLeg,
)


DAY = date(2026, 10, 14)
META_TIME = datetime(2026, 10, 14, tzinfo=timezone.utc)
OFFICIAL_FIXTURE_ONLY = "https://www.city.yokohama.lg.jp/fake-fixture-not-real"


def metadata(feed, kind, version="demo-v1"):
    return FeedMetadata(
        feed_id=feed, source_type=kind,
        source_uri="https://example.invalid/only-a-test",
        version=version, fetched_at=META_TIME,
    )


def feeds(directory: Path):
    contents = {
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "a,A,35.0,139.0\nb,B,35.0001,139.0\n"
            "c,C,35.0004,139.0\nd,D,35.0005,139.0\n"
        ),
        "routes.txt": (
            "route_id,route_short_name,route_long_name,route_type\n"
            "r1,1,Local,3\nr2,2,Onward,3\nr3,3,Direct,3\n"
        ),
        "trips.txt": (
            "route_id,service_id,trip_id,trip_headsign\n"
            "r1,weekday,t1,B\nr2,weekday,t2,D\nr3,weekday,direct,D\n"
        ),
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "t1,10:00:00,10:00:00,a,1\n"
            "t1,10:10:00,10:10:00,b,2\n"
            "t2,10:46:00,10:46:00,c,1\n"
            "t2,10:55:00,10:55:00,d,2\n"
            "direct,10:15:00,10:15:00,a,1\n"
            "direct,11:20:00,11:20:00,d,2\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "weekday,1,1,1,1,1,0,0,20260101,20261231\n"
        ),
    }
    for name, data in contents.items():
        (directory / name).write_text(data, encoding="utf-8")
    gtfs = GtfsFeedSource(directory=directory, metadata=metadata("demo_bus", "gtfs"))
    poles = tuple(
        {"owl:sameAs": k, "dc:title": k.upper(),
         "geo:lat": lat, "geo:long": 139.0}
        for k, lat in (("x", 35.0002), ("y", 35.0003))
    )
    rail = OdptFeedSource(
        metadata=metadata("demo_rail", "odpt"),
        calendar_rules={"weekday": OdptCalendarRule(
            weekdays=(True, True, True, True, True, False, False),
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )},
        stations=poles,
        railways=({"owl:sameAs": "line", "dc:title": "Rail"},),
        train_timetables=tuple(
            {
                "owl:sameAs": key, "odpt:railway": "line",
                "odpt:calendar": "weekday", "dc:title": key,
                "odpt:trainTimetableObject": [
                    {"odpt:departureStation": "x", "odpt:departureTime": depart,
                     "odpt:arrivalTime": depart},
                    {"odpt:arrivalStation": "y", "odpt:arrivalTime": arrive,
                     "odpt:departureTime": arrive},
                ],
            }
            for key, depart, arrive in (
                ("early", "10:19", "10:29"),
                ("late", "10:21", "10:31"),
            )
        ),
    )
    return gtfs, rail


def pin(first, second, *, minutes=10, meters=240,
        from_ver="demo-v1", to_ver="demo-v1"):
    return PinnedWalkLink(
        ReviewedWalkingLink(
            first, second, meters, minutes,
            OFFICIAL_FIXTURE_ONLY, True,
        ),
        from_feed_version=from_ver, to_feed_version=to_ver,
    )


LINKS = (
    pin("demo_bus:b", "demo_rail:x"),
    pin("demo_rail:y", "demo_bus:c"),
)
RIDES = frozenset(
    {"demo_bus:t1", "demo_bus:t2", "demo_bus:direct",
     "demo_rail:early", "demo_rail:late"}
)


class NetworkExperimentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sources = feeds(Path(self.temp.name))

    def engine(self, *, allow=RIDES, links=LINKS):
        return ExperimentalMultiFeedSearch.from_sources(
            self.sources, allowed_trip_ids=allow, walking_links=links,
        )

    def search(self, engine, start="demo_bus:a", dest="demo_bus:d",
               preference="fastest", date=DAY, **kwargs):
        return engine.search(
            start, dest, service_date=date, departure_minute=9 * 60 + 55,
            preference=preference, **kwargs
        )

    def test_gtfs_and_odpt_two_directed_walks_choose_catchable_train(self):
        journey = self.search(self.engine())
        self.assertIsNotNone(journey)
        self.assertEqual(journey.arrival_minute, 10 * 60 + 55)
        self.assertEqual(journey.rides, 3)
        self.assertEqual(journey.transfers, 2)
        self.assertEqual(journey.walking_minutes, 20)
        self.assertEqual(
            [e.trip_id for e in journey.events if isinstance(e, TransitLeg)],
            ["demo_bus:t1", "demo_rail:late", "demo_bus:t2"],
        )
        self.assertEqual(
            [(e.from_stop_id, e.to_stop_id) for e in journey.events
             if isinstance(e, WalkLeg)],
            [("demo_bus:b", "demo_rail:x"),
             ("demo_rail:y", "demo_bus:c")],
        )
        self.assertTrue(all(
            e.official_evidence_url == OFFICIAL_FIXTURE_ONLY
            for e in journey.events if isinstance(e, WalkLeg)
        ))

    def test_fewest_transfers_keeps_direct_later_route(self):
        journey = self.search(self.engine(), preference="fewest_transfers")
        self.assertEqual(journey.rides, 1)
        self.assertEqual(journey.arrival_minute, 11 * 60 + 20)
        self.assertEqual(
            [e.trip_id for e in journey.events if isinstance(e, TransitLeg)],
            ["demo_bus:direct"],
        )

    def test_no_auto_nearby_links_and_no_reverse(self):
        scoped = RIDES - {"demo_bus:direct"}
        self.assertIsNone(self.search(self.engine(allow=scoped, links=())))
        self.assertIsNone(self.search(
            self.engine(allow=scoped, links=LINKS[:1]),
        ))
        # The exact reverse edge (rail:x to bus:b) is never silently inferred.
        self.assertIsNone(self.search(
            self.engine(), "demo_rail:x", "demo_bus:b",
        ))

    def test_unapproved_trip_cannot_appear_even_if_faster(self):
        scoped = RIDES - {"demo_rail:late", "demo_bus:direct"}
        self.assertIsNone(self.search(self.engine(allow=scoped)))
        result = self.search(self.engine(allow=RIDES - {"demo_bus:direct"}))
        self.assertEqual(result.rides, 3)

    def test_versions_missing_ids_and_duplicate_links_fail_closed(self):
        bad = [
            (pin("demo_bus:b", "demo_rail:x", from_ver="old"), "version mismatch"),
            (pin("demo_bus:missing", "demo_rail:x"), "unknown stop"),
        ]
        for link, message in bad:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.engine(links=(link,))
        with self.assertRaisesRegex(ValueError, "duplicate directed"):
            self.engine(links=(LINKS[0], LINKS[0]))
        with self.assertRaisesRegex(ValueError, "unknown trip"):
            self.engine(allow=RIDES | {"demo_bus:unreviewed"})

    def test_calendar_and_boarding_constraints(self):
        sunday = date(2026, 10, 18)
        self.assertIsNone(self.search(self.engine(), date=sunday))
        with self.assertRaisesRegex(ValueError, "supports"):
            self.search(self.engine(), preference="comfort")
        with self.assertRaisesRegex(ValueError, "positive int"):
            self.search(self.engine(), max_rides=0)

    def test_search_limits_stop_instead_of_truncating(self):
        with self.assertRaises(RouteSearchLimitError):
            self.search(self.engine(), limits=SearchLimits(
                max_visited_states=1, max_queue_size=100,
                max_generated_labels=100, time_limit_seconds=10,
            ))

    def test_same_feed_trip_without_any_link(self):
        result = self.search(
            self.engine(allow={"demo_bus:t1"}, links=()),
            dest="demo_bus:b",
        )
        self.assertEqual(result.arrival_minute, 10 * 60 + 10)
        self.assertEqual(result.rides, 1)
        self.assertEqual(len(result.events), 1)


if __name__ == "__main__":
    unittest.main()
