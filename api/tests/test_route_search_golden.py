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
from transit_engine import (
    BatchSearchRequest,
    PythonTransitSearchCore,
    SearchEndpoint,
    SearchLimits,
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


def _endpoint(feed_id: str, row: list[Any], rank: int) -> SearchEndpoint:
    stop_id, walk_minutes, walk_meters = row
    return SearchEndpoint(
        stop_id=namespace_id(feed_id, stop_id),
        walk_minutes=walk_minutes,
        walk_meters=walk_meters,
        rank=rank,
    )


def _source_id(value: str) -> str:
    return value.split(":", 1)[1]


def _summarize(pair: Any, destinations: tuple[SearchEndpoint, ...]) -> dict[str, Any]:
    itinerary = pair.itinerary
    stop_ids: list[str] = []
    for leg in itinerary.legs:
        for stop_id in leg.stop_ids:
            source_id = _source_id(stop_id)
            if not stop_ids or stop_ids[-1] != source_id:
                stop_ids.append(source_id)
    return {
        "origin_index": pair.origin_index,
        "destination_index": pair.destination_index,
        "trip_ids": [_source_id(leg.trip_id) for leg in itinerary.legs],
        "route_ids": [_source_id(leg.route_id) for leg in itinerary.legs],
        "stop_ids": stop_ids,
        "departure_minute": itinerary.departure_minute,
        "arrival_minute": itinerary.arrival_minute,
        "final_arrival_minute": (
            itinerary.arrival_minute
            + destinations[pair.destination_index].walk_minutes
        ),
        "rides": itinerary.rides,
        "transfers": itinerary.transfers,
    }


class RouteSearchGoldenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset, cls.fixture = load_golden_fixture()

    def test_python_core_matches_all_golden_cases(self) -> None:
        core = PythonTransitSearchCore(self.dataset)
        feed_id = self.fixture["feed_id"]
        service_date = date.fromisoformat(self.fixture["service_date"])

        for case in self.fixture["cases"]:
            with self.subTest(case=case["name"]):
                origins = tuple(
                    _endpoint(feed_id, row, rank)
                    for rank, row in enumerate(case["origins"])
                )
                destinations = tuple(
                    _endpoint(feed_id, row, rank)
                    for rank, row in enumerate(case["destinations"])
                )
                result = core.search(
                    BatchSearchRequest(
                        service_date=service_date,
                        departure_minute=case["departure_minute"],
                        origins=origins,
                        destinations=destinations,
                        preference=case["preference"],
                        max_rides=case["max_rides"],
                    )
                )
                actual = [
                    _summarize(pair, destinations) for pair in result.pairs
                ]
                self.assertEqual(actual, case["expected"])
                self.assertEqual(result.diagnostics.route_found, bool(actual))
                self.assertGreaterEqual(result.diagnostics.visited_states, 0)
                self.assertGreaterEqual(result.diagnostics.queue_peak, 0)

    @unittest.skipUnless(
        importlib.util.find_spec("_transit_search_core") is not None,
        "Rust extension is not installed",
    )
    def test_rust_core_matches_python_for_all_golden_cases(self) -> None:
        from rust_transit_search_core import RustTransitSearchCore

        python_core = PythonTransitSearchCore(self.dataset)
        rust_core = RustTransitSearchCore(self.dataset)
        feed_id = self.fixture["feed_id"]
        service_date = date.fromisoformat(self.fixture["service_date"])

        for case in self.fixture["cases"]:
            with self.subTest(case=case["name"]):
                origins = tuple(
                    _endpoint(feed_id, row, rank)
                    for rank, row in enumerate(case["origins"])
                )
                destinations = tuple(
                    _endpoint(feed_id, row, rank)
                    for rank, row in enumerate(case["destinations"])
                )
                request = BatchSearchRequest(
                    service_date=service_date,
                    departure_minute=case["departure_minute"],
                    origins=origins,
                    destinations=destinations,
                    preference=case["preference"],
                    max_rides=case["max_rides"],
                )
                python_result = python_core.search(request)
                rust_result = rust_core.search(request)

                self.assertEqual(
                    [
                        _summarize(pair, destinations)
                        for pair in rust_result.pairs
                    ],
                    [
                        _summarize(pair, destinations)
                        for pair in python_result.pairs
                    ],
                )
                self.assertEqual(
                    (
                        rust_result.diagnostics.visited_states,
                        rust_result.diagnostics.queue_peak,
                        rust_result.diagnostics.generated_labels,
                        rust_result.diagnostics.origin_searches,
                        rust_result.diagnostics.termination_reason,
                    ),
                    (
                        python_result.diagnostics.visited_states,
                        python_result.diagnostics.queue_peak,
                        python_result.diagnostics.generated_labels,
                        python_result.diagnostics.origin_searches,
                        python_result.diagnostics.termination_reason,
                    ),
                )

    def test_fixture_covers_required_regression_cases(self) -> None:
        names = {case["name"] for case in self.fixture["cases"]}
        self.assertTrue(
            {
                "fastest_prefers_transfer",
                "fewest_transfers_prefers_direct",
                "access_and_egress_walk",
                "calendar_dates_override",
                "after_midnight_gtfs_time",
                "initial_walk_crosses_midnight",
                "stable_tie_break",
                "max_rides_blocks_transfer",
                "route_not_found",
                "origin_is_destination",
                "batched_origin_destination_pairs",
            }.issubset(names)
        )

    @unittest.skipUnless(
        importlib.util.find_spec("_transit_search_core") is not None,
        "Rust extension is not installed",
    )
    def test_rust_matches_python_without_active_services(self) -> None:
        from rust_transit_search_core import RustTransitSearchCore
        from search_core_factory import _result_signature

        for preference in ("fastest", "fewest_transfers"):
            for destinations in (
                (SearchEndpoint("golden:D"),),
                (SearchEndpoint("golden:A"), SearchEndpoint("golden:D")),
            ):
                with self.subTest(preference=preference, destinations=destinations):
                    request = BatchSearchRequest(
                        service_date=date(2027, 1, 1),
                        departure_minute=595,
                        origins=(SearchEndpoint("golden:A", 2), SearchEndpoint("golden:B")),
                        destinations=destinations,
                        preference=preference,
                        limits=SearchLimits(max_visited_states=1),
                    )
                    python_result = PythonTransitSearchCore(self.dataset).search(request)
                    rust_result = RustTransitSearchCore(self.dataset).search(request)
                    self.assertEqual(
                        _result_signature(rust_result, request),
                        _result_signature(python_result, request),
                    )

    @unittest.skipUnless(
        importlib.util.find_spec("_transit_search_core") is not None,
        "Rust extension is not installed",
    )
    def test_rust_matches_python_with_exception_only_unused_service(self) -> None:
        from rust_transit_search_core import RustTransitSearchCore
        from search_core_factory import _result_signature

        day = date(2027, 1, 1)
        dataset = replace(
            self.dataset,
            service_exceptions=(ServiceException("golden:unused", day, 1),),
        )
        request = BatchSearchRequest(
            service_date=day,
            departure_minute=595,
            origins=(SearchEndpoint("golden:A"),),
            destinations=(SearchEndpoint("golden:D"),),
            preference="fastest",
        )
        self.assertEqual(
            _result_signature(RustTransitSearchCore(dataset).search(request), request),
            _result_signature(PythonTransitSearchCore(dataset).search(request), request),
        )

    def test_safety_limit_uses_shared_error_and_diagnostics(self) -> None:
        diagnostics = []
        core = PythonTransitSearchCore(
            self.dataset,
            diagnostics_callback=diagnostics.append,
        )
        with self.assertRaises(RouteSearchLimitError):
            core.search(
                BatchSearchRequest(
                    service_date=date.fromisoformat(
                        self.fixture["service_date"]
                    ),
                    departure_minute=595,
                    origins=(SearchEndpoint("golden:A"),),
                    destinations=(SearchEndpoint("golden:G"),),
                    preference="fastest",
                    limits=SearchLimits(max_visited_states=1),
                )
            )

        self.assertEqual(diagnostics[-1].termination_reason, "limit")
        self.assertGreater(diagnostics[-1].visited_states, 1)

    @unittest.skipUnless(
        importlib.util.find_spec("_transit_search_core") is not None,
        "Rust extension is not installed",
    )
    def test_rust_safety_limit_uses_shared_error_and_diagnostics(self) -> None:
        from rust_transit_search_core import RustTransitSearchCore

        diagnostics = []
        core = RustTransitSearchCore(
            self.dataset,
            diagnostics_callback=diagnostics.append,
        )
        with self.assertRaisesRegex(
            RouteSearchLimitError,
            "reason=max_visited_states",
        ):
            core.search(
                BatchSearchRequest(
                    service_date=date.fromisoformat(
                        self.fixture["service_date"]
                    ),
                    departure_minute=595,
                    origins=(SearchEndpoint("golden:A"),),
                    destinations=(SearchEndpoint("golden:G"),),
                    preference="fastest",
                    limits=SearchLimits(max_visited_states=1),
                )
            )

        self.assertEqual(diagnostics[-1].termination_reason, "limit")
        self.assertGreater(diagnostics[-1].visited_states, 1)


if __name__ == "__main__":
    unittest.main()
