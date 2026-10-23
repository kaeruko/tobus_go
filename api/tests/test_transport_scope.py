from __future__ import annotations

import datetime as dt
import unittest
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import networkx as nx
from app.route_endpoint import ApiRouteRequest, to_domain_request
from route_engine import GeoPoint, RoutePreference, RouteSearchRequest
from toei_engine import SpatialIndex, TimetableManager
from tokyo_route_engine import TokyoRouteEngine
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
