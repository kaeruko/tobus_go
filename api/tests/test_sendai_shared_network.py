"""Independent finite timetable oracle; no other city audit helpers."""
import contextlib
from dataclasses import replace
from datetime import date, datetime, timezone
from fractions import Fraction
import io
import random
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fare_policy import get_fare_policy, list_fare_policies
from reviewed_walk_time import ReviewedWalkingLink
from route_engine import RouteSearchLimitError
from sendai_shared_network import (
    FreeSegmentReview, SendaiFureaiPassPolicy, build_sendai_free_network, search_sendai_free_network,
)
from transit_adapters.sendai_subway import Evidence
from transit_adapters.gtfs import GtfsTransitAdapter
from tests.test_sendai_subway import synthetic_input, normalize
from transit_dataset import (
    FeedMetadata, ServiceCalendar, ServiceException, TransitDataset, TransitMode,
    TransitRoute, TransitStop, TransitStopTime, TransitTrip,
)
from transit_network import DirectedWalkLink, NetworkCosts
from transit_timetable_choices import NetworkSearchParameters, NetworkRideEvent

DAY = date(2026, 10, 15)
E = Evidence("https://www.city.sendai.jp/synthetic-test-evidence", "a" * 64)
PARAMS = NetworkSearchParameters(max_candidates=1, max_boardings=3,
    rail_boarding_minutes=1, max_travel_minutes=120)


def feed(name, services, *, mode, exceptions=()):
    prefix = name + ":"
    stops = {stop for rows in services.values() for stop, _, _ in rows}
    return TransitDataset(FeedMetadata(name, "synthetic", E.uri, "fixture-v1",
        datetime(2026, 10, 15, tzinfo=timezone.utc)),
        {prefix + s: TransitStop(prefix + s, s, s, 38.26, 140.88) for s in stops},
        {prefix + "route": TransitRoute(prefix + "route", "route", "", "", mode)},
        {prefix + t: TransitTrip(prefix + t, t, prefix + "route", prefix + "service", "") for t in services},
        tuple(TransitStopTime(prefix + t, prefix + stop, i, a // 60 + (a % 60 >= 30), d // 60 + (d % 60 >= 30),
            arrival_service_seconds=a, departure_service_seconds=d)
            for t, rows in services.items() for i, (stop, a, d) in enumerate(rows)),
        {prefix + "service": ServiceCalendar(prefix + "service", "service", (True,) * 7, DAY, DAY)},
        tuple(exceptions))


def reviews_for(*datasets):
    result = []
    for dataset in datasets:
        for trip in dataset.trips.values():
            rows = sorted((r for r in dataset.stop_times if r.trip_id == trip.id), key=lambda r: r.sequence)
            for a, b in zip(rows, rows[1:]):
                result.append(FreeSegmentReview(trip.id, dataset.metadata.version,
                    a.sequence, b.sequence, a.stop_id, b.stop_id, "SendaiMunicipal", "local", "04100", E))
    return tuple(result)


def link(a, b, minutes=3):
    return DirectedWalkLink(ReviewedWalkingLink(a, b, 80, minutes, E.uri, True), "fixture-v1", "fixture-v1")


def build(*datasets, reviews=None, links=()):
    return build_sendai_free_network(datasets,
        segment_reviews=reviews_for(*datasets) if reviews is None else reviews,
        reviewed_days={DAY}, walking_links=links, costs=NetworkCosts())


def query(network, a, b, start=590, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return search_sendai_free_network(network, a, b, service_date=DAY,
            departure_minute=start, parameters=PARAMS, **kwargs)


def oracle(datasets, links, allowed, origin, destination, start):
    """Exhaustively enumerate board/alight positions and directed walks.

    No shared graph, label dominance, priority, bounds or timetable adapter.
    Seconds are integer source facts. Small acyclic test networks only.
    """
    runs = []
    for dataset in datasets:
        for trip in dataset.trips.values():
            if trip.id not in allowed or trip.service_id not in dataset.active_service_ids(DAY): continue
            rows = sorted((r for r in dataset.stop_times if r.trip_id == trip.id), key=lambda r: r.sequence)
            runs.append((dataset.routes[trip.route_id].mode, rows))
    best = None
    stack = [(origin, start * 60, 0, frozenset())]
    while stack:
        stop, ready, boarded, walked = stack.pop()
        if stop == destination:
            best = ready if best is None else min(best, ready)
        for pinned in links:
            edge = pinned.link
            key = edge.from_stop_id, edge.to_stop_id
            if stop == edge.from_stop_id and key not in walked:
                stack.append((edge.to_stop_id, ready + edge.walk_minutes * 60, boarded, walked | {key}))
        if boarded == 3: continue
        for mode, rows in runs:
            for i, row in enumerate(rows[:-1]):
                buffer = 60 if mode == TransitMode.RAIL else 0
                if row.stop_id != stop or row.departure_service_seconds < ready + buffer: continue
                for following in rows[i + 1:]:
                    if following.arrival_service_seconds <= (start + 120) * 60:
                        stack.append((following.stop_id, following.arrival_service_seconds, boarded + 1, walked))
    return None if best is None else Fraction(best, 60)


class SendaiSharedNetworkTest(unittest.TestCase):
    def setUp(self):
        self.bus = feed("sendai_bus", {
            "out": [("home", 600 * 60, 600 * 60), ("station", 610 * 60, 610 * 60)],
            "back": [("station", 650 * 60, 650 * 60), ("home", 660 * 60, 660 * 60)],
        }, mode=TransitMode.BUS)
        self.rail = feed("sendai_subway", {
            "out": [("platform", 614 * 60, 614 * 60), ("end", 625 * 60 + 20, 625 * 60 + 40)],
            "back": [("end", 630 * 60, 630 * 60), ("platform", 640 * 60, 640 * 60)],
        }, mode=TransitMode.RAIL)
        self.links = (link("sendai_bus:station", "sendai_subway:platform"),
                      link("sendai_subway:platform", "sendai_bus:station", 4))

    def test_four_route_categories_against_independent_oracle(self):
        net = build(self.bus, self.rail, links=self.links)
        for a, b, start in [("sendai_bus:home", "sendai_bus:station", 590),
                            ("sendai_subway:platform", "sendai_subway:end", 610),
                            ("sendai_bus:home", "sendai_subway:end", 590),
                            ("sendai_subway:end", "sendai_bus:home", 628)]:
            with self.subTest(a=a, b=b):
                results = query(net, a, b, start)
                self.assertTrue(results)
                journey, quote = results[0]
                self.assertEqual(journey.arrival_minute, oracle((self.bus, self.rail), self.links, net.allowed_trip_ids, a, b, start))
                self.assertEqual(quote.pay_now_yen, 0)
                self.assertIsNone(quote.normal_fare_yen)
        mixed = query(net, "sendai_bus:home", "sendai_subway:end")[0][0]
        self.assertEqual([e.trip_id for e in mixed.events if isinstance(e, NetworkRideEvent)],
                         ["sendai_bus:out", "sendai_subway:out"])

    def test_transfer_time_boundary_and_no_implicit_walk(self):
        a, b = "sendai_bus:home", "sendai_subway:end"
        self.assertFalse(query(build(self.bus, self.rail), a, b))
        # 610 + 4 min walk + 1 min platform buffer misses the 614 departure.
        self.assertFalse(query(build(self.bus, self.rail, links=(link("sendai_bus:station", "sendai_subway:platform", 4),)), a, b))
        self.assertTrue(query(build(self.bus, self.rail, links=(self.links[0],)), a, b))
        self.assertFalse(query(build(self.bus, self.rail, links=(self.links[0],)), "sendai_subway:end", "sendai_bus:home", 628))

    def test_calendar_exception_and_midnight_seconds(self):
        night = feed("sendai_bus", {"night": [("a", 1439 * 60, 1439 * 60), ("b", 1442 * 60 + 7, 1442 * 60 + 7)]}, mode=TransitMode.BUS)
        self.assertEqual(query(build(night), "sendai_bus:a", "sendai_bus:b", 1438)[0][0].arrival_minute, Fraction(1442 * 60 + 7, 60))
        removed = replace(night, service_exceptions=(ServiceException("sendai_bus:service", DAY, 2),))
        self.assertFalse(query(build(removed), "sendai_bus:a", "sendai_bus:b", 1438))
        with self.assertRaisesRegex(ValueError, "service date"):
            search_sendai_free_network(build(night), "sendai_bus:a", "sendai_bus:b",
                service_date=date(2026, 10, 16), departure_minute=1, parameters=PARAMS)

    def test_unknown_outside_partial_loop_and_unsupported_operators_excluded(self):
        loop = feed("sendai_bus", {"loop": [("inside", 600*60, 600*60),
            ("outside", 610*60, 610*60), ("inside", 620*60, 620*60)]}, mode=TransitMode.BUS)
        partial = reviews_for(loop)[:1]
        with self.assertRaisesRegex(ValueError, "no completely"): build(loop, reviews=partial)
        for change in ({"entire_path_municipality": "04209"}, {"operator_id": "MiyagiKotsu"},
                       {"service_kind": "airport"}, {"feed_version": "old"}):
            bad = (replace(reviews_for(self.bus)[0], **change),)
            with self.subTest(change=change), self.assertRaises(ValueError): build(self.bus, reviews=bad)
        # Unknown bus trips never enter the graph, even when faster than reviewed rail.
        net = build(self.bus, self.rail, reviews=reviews_for(self.rail), links=self.links)
        self.assertNotIn("sendai_bus:out", net.allowed_trip_ids)
        self.assertFalse(query(net, "sendai_bus:home", "sendai_subway:end"))
        miyagi = feed("miyagi", {"run": [("a", 600*60, 600*60), ("b", 610*60, 610*60)]}, mode=TransitMode.BUS)
        with self.assertRaises(ValueError): build(miyagi, reviews=())

    def test_static_only_and_public_defaults_not_activated(self):
        with self.assertRaisesRegex(ValueError, "static only"):
            query(build(self.bus), "sendai_bus:home", "sendai_bus:station", realtime=True)
        self.assertEqual([p.policy_id for p in list_fare_policies("sendai")],
                         ["normal"])
        for policy_id in ("sendai_fureai_pass", "sendai_keiro_pass"):
            with self.subTest(policy_id=policy_id), self.assertRaises(ValueError):
                get_fare_policy("sendai", policy_id)
        self.assertEqual(SendaiFureaiPassPolicy().policy_id, "sendai_fureai_pass")

    def test_search_errors_propagate_and_forged_ride_is_not_quoted(self):
        net = build(self.bus)
        error = RuntimeError("independent injected search failure")
        with patch("sendai_shared_network.search_network", side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                query(net, "sendai_bus:home", "sendai_bus:station")
            self.assertIs(caught.exception, error)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RouteSearchLimitError):
            search_sendai_free_network(net, "sendai_bus:home", "sendai_bus:station", service_date=DAY,
                departure_minute=590, parameters=replace(PARAMS, max_visited=1))
        journey = query(net, "sendai_bus:home", "sendai_bus:station")[0][0]
        ride = journey.events[0]
        with self.assertRaisesRegex(ValueError, "clock"):
            SendaiFureaiPassPolicy().quote(net, replace(journey, events=(replace(ride, arrival_minute=0),)))

    def test_explicit_sendai_walking_authority_only(self):
        link("sendai_bus:station", "sendai_subway:platform")
        with self.assertRaises(ValueError):
            ReviewedWalkingLink("a", "b", 80, 2, "https://city.sendai.jp.example.com/map", True)

    def test_both_adapters_integrate_gtfs_jp_with_subway_and_cross_midnight(self):
        # Completely synthetic GTFS-JP; the real bus feed is not available here.
        files = {
            "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nhome,Home,38.26,140.88\nstation,Station,38.26,140.88\n",
            "routes.txt": "route_id,route_short_name,route_long_name,route_type\nr,R,Fixture,3\n",
            "trips.txt": "route_id,service_id,trip_id\nr,s,bus\n",
            "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nbus,23:37:00,23:37:00,home,1\nbus,23:42:00,23:42:00,station,2\n",
            "calendar_dates.txt": "service_id,date,exception_type\ns,20261015,1\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, content in files.items(): (Path(directory) / name).write_text(content, encoding="utf-8")
            bus = GtfsTransitAdapter.load(directory, metadata=FeedMetadata("sendai_bus", "gtfs", E.uri,
                "fixture-v1", datetime(2026, 10, 15, tzinfo=timezone.utc)))
        rail = normalize(*synthetic_input())
        walk = DirectedWalkLink(ReviewedWalkingLink("sendai_bus:station", "sendai_subway:namboku/泉中央",
            80, 3, E.uri, True), bus.metadata.version, rail.metadata.version)
        net = build(bus, rail, links=(walk,))
        journey, quote = query(net, "sendai_bus:home", "sendai_subway:namboku/富沢", 1415)[0]
        self.assertEqual(journey.arrival_minute, oracle((bus, rail), (walk,), net.allowed_trip_ids,
            "sendai_bus:home", "sendai_subway:namboku/富沢", 1415))
        self.assertGreater(journey.arrival_minute, 1440)
        self.assertEqual(quote.pay_now_yen, 0)
        rail_event = next(e for e in journey.events if isinstance(e, NetworkRideEvent) and e.mode == "rail")
        self.assertIn("row-2", rail_event.source_trip_id)

    def test_gtfs_no_pickup_flag_is_preserved(self):
        rows = tuple(replace(row, pickup_type=1) if row.trip_id == "sendai_bus:out" and row.sequence == 0
                     else row for row in self.bus.stop_times)
        bus = replace(self.bus, stop_times=rows)
        self.assertFalse(query(build(bus), "sendai_bus:home", "sendai_bus:station"))

    def test_randomized_small_transfer_oracle(self):
        randomizer = random.Random(171148)
        for attempt in range(24):
            departure = randomizer.randint(612, 620)
            rail = feed("sendai_subway", {"out": [("platform", departure*60, departure*60),
                ("end", (departure+10)*60+17, (departure+10)*60+17)]}, mode=TransitMode.RAIL)
            walk = randomizer.randint(1, 5)
            links = (link("sendai_bus:station", "sendai_subway:platform", walk),)
            net = build(self.bus, rail, links=links)
            expected = oracle((self.bus, rail), links, net.allowed_trip_ids,
                              "sendai_bus:home", "sendai_subway:end", 590)
            result = query(net, "sendai_bus:home", "sendai_subway:end")
            with self.subTest(attempt=attempt):
                self.assertEqual(result[0][0].arrival_minute if result else None, expected)


if __name__ == "__main__": unittest.main()
