from __future__ import annotations

import json
import importlib.util
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from route_engine import RouteSearchLimitError
from transit_dataset import (
    FeedMetadata,
    ServiceCalendar,
    ServiceException,
    TransitDataset,
    TransitMode,
    TransitRoute,
    TransitStop,
    TransitStopTime,
    TransitTrip,
    namespace_id,
)


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "route_search" / "golden.json"
)


def load_golden_fixture() -> tuple[TransitDataset, dict[str, Any]]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    feed_id = fixture["feed_id"]

    stops = {
        namespace_id(feed_id, source_id): TransitStop(
            namespace_id(feed_id, source_id),
            source_id,
            name,
            lat,
            lon,
        )
        for source_id, name, lat, lon in fixture["stops"]
    }
    routes = {
        namespace_id(feed_id, source_id): TransitRoute(
            namespace_id(feed_id, source_id),
            source_id,
            short_name,
            short_name,
            TransitMode.BUS,
        )
        for source_id, short_name in fixture["routes"]
    }
    calendars = {
        namespace_id(feed_id, source_id): ServiceCalendar(
            namespace_id(feed_id, source_id),
            source_id,
            tuple(weekdays),
            date(2026, 1, 1),
            date(2026, 12, 31),
        )
        for source_id, weekdays in fixture["services"]
    }

    trips: dict[str, TransitTrip] = {}
    stop_times: list[TransitStopTime] = []
    for trip_id, route_id, service_id, rows in fixture["trips"]:
        namespaced_trip_id = namespace_id(feed_id, trip_id)
        trips[namespaced_trip_id] = TransitTrip(
            namespaced_trip_id,
            trip_id,
            namespace_id(feed_id, route_id),
            namespace_id(feed_id, service_id),
            "Golden fixture",
        )
        for sequence, (stop_id, arrival, departure) in enumerate(rows, start=1):
            stop_times.append(
                TransitStopTime(
                    namespaced_trip_id,
                    namespace_id(feed_id, stop_id),
                    sequence,
                    arrival,
                    departure,
                )
            )

    exceptions = tuple(
        ServiceException(
            namespace_id(feed_id, service_id),
            date.fromisoformat(day),
            exception_type,
        )
        for service_id, day, exception_type in fixture["service_exceptions"]
    )
    dataset = TransitDataset(
        metadata=FeedMetadata(
            feed_id=feed_id,
            source_type="golden-fixture",
            source_uri="tests/fixtures/route_search/golden.json",
            version="1",
            fetched_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        ),
        stops=stops,
        routes=routes,
        trips=trips,
        stop_times=tuple(stop_times),
        calendars=calendars,
        service_exceptions=exceptions,
    )
    return dataset, fixture


class SharedFixtureTest(unittest.TestCase):
    def test_original_fixture_is_valid_input_for_shared_v2(self):
        from transit_network_core import NetworkSearchCore
        from transit_search_dto import BatchSearchRequest, SearchEndpoint
        dataset, fixture = load_golden_fixture()
        core = NetworkSearchCore(dataset)
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                if case["preference"] != "fastest": continue
                origins=tuple(SearchEndpoint(namespace_id(fixture["feed_id"],row[0]),row[1],row[2],i) for i,row in enumerate(case["origins"]))
                destinations=tuple(SearchEndpoint(namespace_id(fixture["feed_id"],row[0]),row[1],row[2],i) for i,row in enumerate(case["destinations"]))
                result=core.search(BatchSearchRequest(date.fromisoformat(fixture["service_date"]),case["departure_minute"],origins,destinations,"fastest",case["max_rides"]))
                self.assertEqual(bool(result.pairs),bool(case["expected"]))
                # v1 lexical ranks are historical data, not a new v2 requirement.
                if result.pairs:
                    self.assertEqual(min(p.itinerary.arrival_minute for p in result.pairs),min(c["arrival_minute"] for c in case["expected"]))
