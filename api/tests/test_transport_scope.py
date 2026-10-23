from __future__ import annotations

import datetime as dt
import unittest
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import networkx as nx
from app.route_endpoint import ApiRouteRequest, to_domain_request
from route_engine import GeoPoint, RoutePreference, RouteSearchRequest
from toei_engine import SpatialIndex, TimetableManager
from tokyo_route_engine import (
    TokyoRouteDependencies,
    TokyoRouteEngine,
    _static_path_is_possible,
)
from transport_scope import (
    ALL_TRANSPORTS,
    LEGACY_DEFAULT_SCOPE,
    TOEI_BUS,
    TOEI_SUBWAY,
    TOKYO_METRO,
    normalize_transport_scope,
)


def _api(**extra):
    values = dict(alat=35.68, alon=139.76, blat=35.69, blon=139.77)
    values.update(extra)
    return ApiRouteRequest(**values)


def _line(graph, stop, line, service):
    phys = ("phys", stop)
    node = ("line", stop, line)
    graph.add_node(
        phys, kind="phys", name=stop, name_en=stop, lat=35.68, lon=139.76,
        transport_services=frozenset((service,)),
    )
    graph.add_node(
        node, kind="line", mode="bus" if service == TOEI_BUS else "rail",
        line=line, transport_service=service,
    )
    graph.add_edge(phys, node, etype="board", w=5)
    graph.add_edge(node, phys, etype="alight", w=0)
    return phys


class TransportScopeTest(unittest.TestCase):
    def test_legacy_bus_only_mapping_is_backward_compatible(self):
        self.assertEqual(to_domain_request(_api(bus_only=True)).transport_scope, frozenset((TOEI_BUS,)))
        self.assertEqual(to_domain_request(_api(bus_only=False)).transport_scope, LEGACY_DEFAULT_SCOPE)

    def test_all_seven_explicit_nonempty_scopes_are_accepted(self):
        identifiers = sorted(ALL_TRANSPORTS)
        scopes = set()
        for mask in range(1, 8):
            scope = [value for index, value in enumerate(identifiers) if mask & (1 << index)]
            bus_only = scope == [TOEI_BUS]
            request = to_domain_request(_api(bus_only=bus_only, transport_scope=scope))
            scopes.add(request.transport_scope)
        self.assertEqual(len(scopes), 7)

    def test_invalid_explicit_scopes_fail_fast(self):
        for scope in ([], ["unknown"], [TOEI_BUS, TOEI_BUS]):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                to_domain_request(_api(transport_scope=scope))

    def test_conflicting_legacy_and_explicit_scope_fails_fast(self):
        with self.assertRaisesRegex(ValueError, "conflicts"):
            to_domain_request(_api(bus_only=True, transport_scope=[TOEI_BUS, TOEI_SUBWAY]))

    def test_scope_view_removes_unselected_physical_and_line_nodes(self):
        graph = nx.DiGraph()
        bus = _line(graph, "bus", "b", TOEI_BUS)
        subway = _line(graph, "subway", "s", TOEI_SUBWAY)
        metro = _line(graph, "metro", "m", TOKYO_METRO)
        graph.add_edge(bus, subway, etype="walk", w=1, meters=10)
        graph.add_edge(subway, metro, etype="walk", w=1, meters=10)
        manager = TimetableManager()
        manager.tokyo_metro_feed_version = "test"
        app = SimpleNamespace(state=SimpleNamespace(
            G=graph, TM=manager, SI=SpatialIndex(graph), WALK_RAD=300
        ))
        engine = TokyoRouteEngine(app)
        view, _ = engine._graph_for_scope(frozenset((TOEI_BUS, TOEI_SUBWAY)))
        self.assertIn(bus, view)
        self.assertIn(subway, view)
        self.assertNotIn(metro, view)

    def test_domain_request_rejects_empty_scope_even_without_api_model(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            RouteSearchRequest(
                origin=GeoPoint(35.68, 139.76),
                destination=GeoPoint(35.69, 139.77),
                departure_at=dt.datetime(2026, 10, 23, 10, tzinfo=ZoneInfo("Asia/Tokyo")),
                preference=RoutePreference.FASTEST,
                transport_scope=frozenset(),
            )

    def test_normalize_rejects_scalar_instead_of_silently_iterating_it(self):
        with self.assertRaisesRegex(ValueError, "list"):
            normalize_transport_scope(TOEI_BUS, bus_only=False)

    def test_static_disconnection_is_a_safe_one_way_impossibility_proof(self):
        graph = nx.DiGraph()
        graph.add_edges_from((("start", "middle"), ("other", "target")))
        nx.set_node_attributes(
            graph,
            {node: {"toei_subway"} for node in graph},
            "transport_services",
        )
        self.assertFalse(_static_path_is_possible(graph, "start", ("target",)))
        graph.add_edge("middle", "target")
        self.assertTrue(_static_path_is_possible(graph, "start", ("target",)))

    def test_static_reachability_does_not_claim_timetable_feasibility(self):
        graph = nx.DiGraph()
        graph.add_edge("start", "target", etype="ride")
        # The helper intentionally knows nothing about whether a concrete run
        # exists; True means only that exact search is still required.
        self.assertTrue(_static_path_is_possible(graph, "start", ("target",)))

    def test_incomplete_synthetic_graph_cannot_prove_disconnection(self):
        graph = nx.DiGraph()
        graph.add_nodes_from(("start", "target"))
        self.assertTrue(_static_path_is_possible(graph, "start", ("target",)))

    def test_disconnected_coordinate_search_does_not_enter_exact_search(self):
        graph = nx.DiGraph()
        origin = ("phys", "origin")
        target = ("phys", "target")
        for node, lat in ((origin, 35.68), (target, 35.69)):
            graph.add_node(node, kind="phys", name=node[1], name_en=node[1],
                           lat=lat, lon=139.76,
                           transport_services={"toei_subway"})
        manager = TimetableManager()
        nearest = iter(((origin, 0.0), (target, 0.0)))
        exact_calls = []
        app = SimpleNamespace(state=SimpleNamespace(
            G=graph, TM=manager, SI=SpatialIndex(graph), WALK_RAD=300,
        ))
        engine = TokyoRouteEngine(app, dependencies=TokyoRouteDependencies(
            nearest_phys=lambda *args, **kwargs: next(nearest),
            get_virtual_connections=lambda *args, **kwargs: (
                ("phys", "dest:test"), [(target, 1.0, 10.0)]
            ),
            search_best_routes_once=lambda *args, **kwargs: exact_calls.append(True),
            rss_mb=lambda: -1.0,
        ))
        result = engine.search_legacy(
            alat=35.68, alon=139.76, blat=35.69, blon=139.76,
            pref="fewTransfers", start_time="10:00", date_str="2026-10-23",
        )
        self.assertEqual(result["candidates"], [])
        self.assertEqual(exact_calls, [])
