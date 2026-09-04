from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import networkx as nx

from gtfs_route_backend import GtfsRouteEngine
from nagoya_transit import NAGOYA_FEED_ID, NagoyaRouteBackend
from route_engine import (
    GeoPoint,
    RouteCandidate,
    RouteContractError,
    RouteEngine,
    RoutePreference,
    RouteSearchLimitError,
    RouteSearchRequest,
    RouteSearchResult,
    WalkStep,
    serialize_route_candidate,
    serialize_route_result,
)
from sendai_transit import SENDAI_FEED_ID, SendaiRouteBackend
from tokyo_route_engine import TokyoRouteDependencies, TokyoRouteEngine
from transit_dataset import (
    FeedMetadata,
    ServiceCalendar,
    TransitDataset,
    TransitMode,
    TransitRoute,
    TransitStop,
    TransitStopTime,
    TransitTrip,
)
from transit_engine import (
    BatchSearchRequest,
    PythonTransitSearchCore,
    SearchCore,
    SearchEndpoint,
    SearchLimits,
)
from yokohama_transit import YOKOHAMA_BUS_FEED_ID, YokohamaBusRouteBackend


SERVICE_DAY = datetime(2026, 9, 4, 9, 55, tzinfo=ZoneInfo("Asia/Tokyo"))


def _dataset(feed_id: str) -> TransitDataset:
    stop_a = f"{feed_id}:A"
    stop_b = f"{feed_id}:B"
    route_id = f"{feed_id}:R1"
    trip_id = f"{feed_id}:T1"
    service_id = f"{feed_id}:WK"
    return TransitDataset(
        metadata=FeedMetadata(
            feed_id=feed_id,
            source_type="test",
            source_uri="https://example.test/feed.zip",
            version="test",
            fetched_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        ),
        stops={
            stop_a: TransitStop(stop_a, "A", "Origin", 35.0, 139.0),
            stop_b: TransitStop(stop_b, "B", "Destination", 35.1, 139.1),
        },
        routes={
            route_id: TransitRoute(
                route_id,
                "R1",
                "1",
                "Origin - Destination",
                TransitMode.BUS,
            )
        },
        trips={
            trip_id: TransitTrip(trip_id, "T1", route_id, service_id, "Destination")
        },
        stop_times=(
            TransitStopTime(trip_id, stop_a, 1, 600, 600),
            TransitStopTime(trip_id, stop_b, 2, 620, 620),
        ),
        calendars={
            service_id: ServiceCalendar(
                service_id,
                "WK",
                (True, True, True, True, True, True, True),
                date(2026, 1, 1),
                date(2026, 12, 31),
            )
        },
    )


def _request() -> RouteSearchRequest:
    return RouteSearchRequest(
        origin=GeoPoint(35.0, 139.0),
        destination=GeoPoint(35.1, 139.1),
        departure_at=SERVICE_DAY,
        preference=RoutePreference.FASTEST,
    )


class RouteEngineContractTest(unittest.TestCase):
    def test_gtfs_city_engines_share_the_same_typed_contract(self) -> None:
        engines = (
            GtfsRouteEngine(_dataset("generic"), walk_radius_m=100),
            NagoyaRouteBackend(_dataset(NAGOYA_FEED_ID), walk_radius_m=100),
            SendaiRouteBackend(_dataset(SENDAI_FEED_ID), walk_radius_m=100),
            YokohamaBusRouteBackend(
                _dataset(YOKOHAMA_BUS_FEED_ID),
                walk_radius_m=100,
            ),
        )
        for engine in engines:
            with self.subTest(engine=type(engine).__name__):
                self.assertIsInstance(engine, RouteEngine)
                payload = serialize_route_result(engine.search(_request()))
                candidate = payload["candidates"][0]
                self.assertEqual(candidate["boards"], 1)
                self.assertEqual(candidate["transfers"], 0)
                self.assertEqual(candidate["walking_distance_meters"], 0)
                self.assertEqual(candidate["walking_segment_count"], 0)

    def test_tokyo_adapter_implements_the_same_typed_contract(self) -> None:
        origin = ("phys", "origin")
        destination = ("phys", "destination")
        virtual_destination = ("phys", "dest:test")
        graph = nx.DiGraph()
        graph.add_node(origin, name="Origin", lat=35.0, lon=139.0)
        graph.add_node(destination, name="Destination", lat=35.1, lon=139.1)
        app = SimpleNamespace(
            state=SimpleNamespace(G=graph, TM=object(), WALK_RAD=500, SI=object())
        )
        nearest = iter(((origin, 0.0), (destination, 0.0)))
        candidate = {
            "id": "Fastest",
            "lines": ["1"],
            "boards": 1,
            "transfers": 0,
            "rides": 1,
            "total": 20,
            "total_time": 20,
            "walking_distance_meters": 0,
            "walking_segment_count": 0,
            "steps": [
                {
                    "kind": "bus",
                    "title": "1",
                    "from_": "Origin",
                    "to": "Destination",
                    "minutes": 20,
                }
            ],
            "points": [[35.0, 139.0], [35.1, 139.1]],
            "arrival_time": "10:20",
        }
        engine = TokyoRouteEngine(
            app,
            dependencies=TokyoRouteDependencies(
                nearest_phys=lambda *args, **kwargs: next(nearest),
                haversine=lambda *args: 0.0,
                get_virtual_connections=lambda *args, **kwargs: (
                    virtual_destination,
                    [(destination, 0.0, 0.0)],
                ),
                search_best_routes_once=lambda *args, **kwargs: [candidate],
                time_str_to_min=lambda value: 595,
                min_to_time_str=lambda value: "09:55",
                determine_day_type=lambda value: "weekday",
                assign_candidate_step_ids=lambda value: None,
                rss_mb=lambda: -1.0,
            ),
        )

        self.assertIsInstance(engine, RouteEngine)
        payload = serialize_route_result(engine.search(_request()))
        self.assertEqual(payload["candidates"][0]["boards"], 1)
        self.assertEqual(payload["candidates"][0]["transfers"], 0)

    def test_contract_violation_fails_fast(self) -> None:
        candidate = RouteCandidate(
            id="broken",
            lines=[],
            boards=0,
            transfers=0,
            total_time=1,
            walking_distance_meters=99,
            walking_segment_count=1,
            steps=[WalkStep("Walk", "A", "B", 1, 10)],
            points=[GeoPoint(35.0, 139.0)],
            arrival_time="10:01",
        )
        with self.assertRaisesRegex(RouteContractError, "walk step meters"):
            serialize_route_result(RouteSearchResult(candidates=[candidate]))

    def test_serializer_preserves_existing_flutter_step_shape(self) -> None:
        raw = {
            "id": "compatible",
            "lines": ["1"],
            "boards": 1,
            "transfers": 0,
            "rides": 1,
            "total": 20,
            "total_time": 20,
            "walking_distance_meters": 0,
            "walking_segment_count": 0,
            "steps": [
                {
                    "kind": "bus",
                    "title": "1",
                    "from_": "Origin",
                    "to": "Destination",
                    "minutes": 20,
                    "route_id": "R1",
                }
            ],
            "points": [[35.0, 139.0], [35.1, 139.1]],
            "arrival_time": "10:20",
        }
        self.assertEqual(
            serialize_route_candidate(RouteCandidate.from_mapping(raw)),
            raw,
        )

    def test_python_search_core_exposes_diagnostics_hook(self) -> None:
        diagnostics = []
        core = PythonTransitSearchCore(
            _dataset("diagnostics"),
            diagnostics_callback=diagnostics.append,
        )
        self.assertIsInstance(core, SearchCore)
        result = core.search_fastest(
            "diagnostics:A",
            "diagnostics:B",
            departure=SERVICE_DAY,
        )
        self.assertIsNotNone(result)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].preference, "fastest")
        self.assertTrue(diagnostics[0].route_found)

    def test_python_search_core_searches_multiple_destinations_in_one_run(self) -> None:
        core = PythonTransitSearchCore(_dataset("batch"))
        result = core.search(
            BatchSearchRequest(
                service_date=SERVICE_DAY.date(),
                departure_minute=SERVICE_DAY.hour * 60 + SERVICE_DAY.minute,
                origins=(SearchEndpoint("batch:A"),),
                destinations=(
                    SearchEndpoint("batch:A"),
                    SearchEndpoint("batch:B"),
                ),
                preference="fastest",
            )
        )

        self.assertEqual(
            [(pair.origin_index, pair.destination_index) for pair in result.pairs],
            [(0, 0), (0, 1)],
        )
        self.assertEqual(result.pairs[0].itinerary.legs, ())
        self.assertEqual(result.pairs[1].itinerary.arrival_minute, 620)
        self.assertEqual(result.diagnostics.origin_searches, 1)
        self.assertGreaterEqual(result.diagnostics.visited_states, 2)
        self.assertGreaterEqual(result.diagnostics.queue_peak, 1)
        self.assertEqual(result.diagnostics.termination_reason, "completed")

    def test_python_search_core_stops_at_the_visited_state_limit(self) -> None:
        diagnostics = []
        core = PythonTransitSearchCore(
            _dataset("limited"),
            diagnostics_callback=diagnostics.append,
        )
        request = BatchSearchRequest(
            service_date=SERVICE_DAY.date(),
            departure_minute=SERVICE_DAY.hour * 60 + SERVICE_DAY.minute,
            origins=(SearchEndpoint("limited:A"),),
            destinations=(SearchEndpoint("limited:B"),),
            preference="fastest",
            limits=SearchLimits(max_visited_states=1),
        )

        with self.assertRaisesRegex(
            RouteSearchLimitError,
            "reason=max_visited_states",
        ):
            core.search(request)

        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].termination_reason, "limit")


if __name__ == "__main__":
    unittest.main()
