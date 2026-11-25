"""Street topology, stop access, and transit timetable regressions for Tokyo."""

from __future__ import annotations

import hashlib
import json
import os
import unittest
import zlib
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import networkx as nx
from toei_engine import SpatialIndex, TimetableManager
from tokyo_metro_gtfs import add_tokyo_metro_to_graph
from tokyo_osm_build import _blocked_node, bind_network, load_config, way_profile
from tokyo_osm_walk import (
    RECORD,
    SCHEMA,
    cells_between,
    coordinate_routes,
    endpoint_graph,
    loaded_network,
    network_required,
    routes,
    snap,
)
from tokyo_route_engine import TokyoRouteEngine
from transport_scope import TOEI_SUBWAY, TOKYO_METRO
from walking_access import haversine_m

from tests import test_tokyo_search_correctness_audit as audit
from tests.test_tokyo_metro_gtfs import _fixture


def network(points, links, stations=None):
    bins = defaultdict(bytearray)
    for u, v, direction, ground in links:
        a, b = points[u], points[v]
        row = RECORD.pack(u, v, *(round(c * 1e7) for c in (*a, *b)), direction, ground)
        for key in cells_between(a, b):
            bins[key].extend(row)
    return {
        "schema": SCHEMA,
        "bounds": [139.60, 35.59, 139.90, 35.71],
        "source": {
            "source_date": "2026-01-01",
            "attribution": "© OpenStreetMap contributors",
        },
        "tiles": {k: zlib.compress(v) for k, v in bins.items()},
        "station_nodes": {
            s: {"node": n, "evidence_url": "https://example.org/fixture"}
            for s, n in (stations or {}).items()
        },
        "station_positions": {n: points[n] for n in (stations or {}).values()},
    }


def pole(name):
    return "phys", f"odpt.BusstopPole:Toei.{name}"


def add_pole(graph, name, point):
    node = pole(name)
    graph.add_node(node, lat=point[0], lon=point[1], name=name, name_en=name)
    return node


class TokyoOsmWalkingTest(unittest.TestCase):
    def test_access_direction_barriers_and_separate_sidewalks(self):
        self.assertEqual(
            way_profile({"highway": "residential", "oneway": "yes"}), (3, True)
        )
        self.assertEqual(
            way_profile({"highway": "steps", "oneway:foot": "-1"}), (2, True)
        )
        self.assertEqual(
            way_profile({"highway": "path", "foot:forward": "no"}), (2, True)
        )
        self.assertEqual(
            way_profile({"highway": "footway", "bridge": "yes"}), (3, False)
        )
        for tags in (
            {"foot": "use_sidepath"},
            {"access": "private"},
            {"foot:conditional": "yes @ (Mo)"},
            {"sidewalk:left": "separate"},
            {"indoor": "yes"},
            {"area": "yes"},
        ):
            self.assertIsNone(way_profile({"highway": "residential", **tags}))
        self.assertEqual(
            way_profile({"highway": "steps", "conveying": "backward"}), (2, True)
        )
        self.assertIsNone(way_profile({"highway": "steps", "conveying": "reversible"}))
        self.assertTrue(_blocked_node({"barrier": "fence"}))
        self.assertTrue(_blocked_node({"barrier": "gate", "locked": "yes"}))
        self.assertFalse(_blocked_node({"barrier": "bollard"}))

    def test_selected_osm_dataset_is_required_and_malformed_data_stops(self):
        graph = nx.DiGraph()
        self.assertIsNone(loaded_network(graph))
        with (
            patch.dict(os.environ, {"REQUIRE_TOKYO_OSM_WALK": "1"}),
            self.assertRaisesRegex(ValueError, "no required OSM"),
        ):
            loaded_network(graph, required=network_required())
        graph.graph["tokyo_osm_walk"] = {"schema": SCHEMA}
        with self.assertRaisesRegex(ValueError, "incompatible prebuilt"):
            loaded_network(graph)
        with (
            patch.dict(os.environ, {"REQUIRE_TOKYO_OSM_WALK": "true"}),
            self.assertRaisesRegex(ValueError, "must be 0 or 1"),
        ):
            network_required()

    def test_input_is_pinned_before_compilation(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp)
            f = p / "input.osm.pbf"
            f.write_bytes(b"fixture")
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            path = p / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "pbf": f.name,
                        "sha256": digest,
                        "source_date": "2026-01-01",
                        "source_url": "https://example.org/input.pbf",
                        "bounds": [139, 35, 140, 36],
                    }
                )
            )
            self.assertEqual(load_config(path)["pbf"], f)
            f.write_bytes(b"changed")
            with self.assertRaisesRegex(
                ValueError, "SHA-256 mismatch.*expected.*found"
            ):
                load_config(path)

    def test_directed_projection_and_crossing_need_shared_osm_node(self):
        points = {
            1: (35.65, 139.698),
            2: (35.65, 139.702),
            3: (35.648, 139.70),
            4: (35.652, 139.70),
        }
        net = network(points, [(1, 2, 1, True), (3, 4, 3, True)])
        a, b, c = (
            snap(net, p) for p in ((35.65, 139.699), (35.65, 139.701), points[3])
        )
        self.assertIsNone(snap(net, (35.65, 139.70)))
        forward = routes(net, a, {"b": b, "c": c}, 600)
        self.assertEqual(set(forward), {"b"})
        self.assertAlmostEqual(
            forward["b"][0], haversine_m(*a.point, *b.point), places=4
        )
        self.assertEqual(forward["b"][1], (a.point, b.point))
        self.assertFalse(routes(net, b, {"a": a}, 600))
        self.assertEqual(routes(net, b, {"a": a}, 600, reverse=True)["a"], forward["b"])
        self.assertEqual(routes(net, a, {"a": a}, 0)["a"][0], 0.0)

    def test_precompute_detours_keep_directed_review_and_hours(self):
        points = {
            1: (35.65, 139.70),
            2: (35.653, 139.70),
            3: (35.653, 139.701),
            4: (35.65, 139.701),
        }
        net = network(points, [(1, 2, 3, True), (2, 3, 3, True), (3, 4, 3, True)])
        graph = nx.DiGraph()
        a, b = add_pole(graph, "a", points[1]), add_pole(graph, "b", points[4])
        c = add_pole(graph, "c", (35.6507, 139.70))
        for source, target in ((b, a), (a, c)):
            graph.add_edge(source, target, etype="walk", meters=75, w=2)
        graph[a][c]["transfer_available_windows"] = [(600, 700)]
        graph.add_edge(a, b, etype="walk", meters=125, reviewed_walk_minutes=3, w=4.5)
        stat = bind_network(graph, net, 300)
        self.assertEqual(
            stat, {"matched_stops": 3, "routed_walks": 1, "excluded_walks": 1}
        )
        self.assertEqual(graph[a][b]["reviewed_walk_minutes"], 3)
        self.assertNotIn("osm_points", graph[a][b])
        self.assertFalse(graph.has_edge(b, a))
        self.assertGreater(graph[a][c]["meters"], 75)
        self.assertEqual(graph[a][c]["transfer_available_windows"], [(600, 700)])
        paths = coordinate_routes(graph.graph["tokyo_osm_walk"], graph, points[1], 600)[
            0
        ]
        self.assertNotIn(b, paths)

    def test_query_overlay_immutable_egress_direction_and_no_coverage_fallback(self):
        a, b = (35.65, 139.70), (35.65, 139.701)
        net = network({1: a, 2: b}, [(1, 2, 1, True)])
        graph = nx.DiGraph()
        stop = add_pole(graph, "p", b)
        bind_network(graph, net, 300)
        net = graph.graph["tokyo_osm_walk"]
        access, status = coordinate_routes(net, graph, a, 600)
        self.assertEqual(status, "connected")
        self.assertEqual(
            coordinate_routes(net, graph, a, 600, reverse=True)[1],
            "no_walkable_connection",
        )
        egress, _ = coordinate_routes(net, graph, b, 600, reverse=True)
        view, start, end = endpoint_graph(graph, a, b, access, egress)
        self.assertEqual(nx.shortest_path(view, start, end), [start, stop, end])
        self.assertEqual(graph.number_of_edges(), 0)
        self.assertEqual(set(graph), {stop})
        self.assertEqual(
            coordinate_routes(net, graph, (0, 0), 600)[1], "outside_coverage"
        )
        self.assertEqual(
            coordinate_routes(net, graph, (35.66, 139.70), 600)[1], "no_ground_match"
        )
        self.assertEqual(
            coordinate_routes(net, nx.DiGraph(), a, 600)[1], "no_scoped_stop_in_range"
        )

    def test_station_reference_is_not_ground_access(self):
        p = (35.65, 139.70)
        net = network({1: p, 2: (35.65, 139.701)}, [(1, 2, 3, True)])
        g = nx.DiGraph()
        node = ("phys", "odpt.Station:Toei.Oedo.Shinjuku")
        g.add_node(node, lat=p[0], lon=p[1])
        self.assertEqual(bind_network(g, net, 300)["matched_stops"], 0)

    def test_zero_osm_walk_cycle_and_exact_segment_cap_with_independent_oracle(self):
        for length, arrival in ((600.0, 607.5), (600.01, None)):
            g = audit._walk_graph(
                (("S", "A", 0), ("A", "S", 0), ("A", "B", length), ("B", "T", 0))
            )
            for _, _, edge in g.edges(data=True):
                edge["osm_points"] = ((35.65, 139.70), (35.65, 139.70))
            q = audit.Query(audit.bus._phys("S"), audit.bus._phys("T"), 600.0, 240.0)
            self.assertEqual(audit._audit(g, (), q)["arrival_minute"], arrival)

    def test_access_and_egress_charge_same_total_as_transfers(self):
        trips, runs, graph = [], [], nx.DiGraph()
        for i in range(5):
            a, b = f"a{i}", f"b{i}"
            graph = nx.compose(graph, audit.bus._graph((a, b)))
            dep = 610 + 9 * i
            rows = ((a, dep, dep, 0), (b, dep + 1, dep + 1, 0))
            runs.append(audit._run_bus(f"r{i}", rows))
            trips.append((f"r{i}", "active", tuple((s, a, d) for s, a, d, _ in rows)))
            audit.rail._walk(
                graph,
                audit.bus._phys("S" if i == 0 else f"b{i - 1}"),
                audit.bus._phys(a),
                600,
            )
        audit.rail._walk(graph, audit.bus._phys("b4"), audit.bus._phys("T"), 0)
        for _, _, edge in graph.edges(data=True):
            if edge["etype"] == "walk":
                edge["osm_points"] = ((35.65, 139.70), (35.65, 139.70))
        q = audit.Query(audit.bus._phys("S"), audit.bus._phys("T"), 600, 240)
        choices = audit._choices(graph, q, repository=audit.bus._repository(*trips))
        self.assertEqual(
            audit._audit(graph, tuple(runs), q, choices=choices)["arrival_minute"],
            647.0,
        )
        graph[audit.bus._phys("b4")][q.target]["meters"] = 0.01
        changed_choices = audit._choices(
            graph, q, repository=audit.bus._repository(*trips)
        )
        self.assertIsNone(
            audit._audit(graph, tuple(runs), q, choices=changed_choices)[
                "arrival_minute"
            ]
        )

    def test_toei_subway_access_changes_which_train_can_be_boarded(self):
        graph = audit.rail._identity_graph(("A", "B"))
        tm = audit.rail._manager(
            audit.rail._run("early", (("A", 604), ("B", 608))),
            audit.rail._run("later", (("A", 606), ("B", 610))),
        )
        points = {
            1: (35.648, 139.70),
            2: (35.65, 139.70),
            3: (35.67, 139.73),
            4: (35.67, 139.7303),
        }
        ids = {audit.rail._station("A"): 2, audit.rail._station("B"): 3}
        for node, data in graph.nodes(data=True):
            data["lat"], data["lon"] = points[ids[node[1]]]
        net = network(points, [(1, 2, 3, True), (3, 4, 3, True)], ids)
        bind_network(graph, net, 300)
        engine = TokyoRouteEngine(
            SimpleNamespace(
                state=SimpleNamespace(
                    G=graph,
                    TM=tm,
                    SI=SpatialIndex(graph),
                    WALK_RAD=300,
                )
            )
        )
        candidate = engine.search_legacy(
            alat=points[1][0],
            alon=points[1][1],
            blat=points[4][0],
            blon=points[4][1],
            start_time="10:00",
            date_str="2026-09-24",
            pref="time",
            transport_scope=frozenset({TOEI_SUBWAY}),
            limit=1,
        )["candidates"][0]
        rail = next(step for step in candidate["steps"] if step["kind"] == "rail")
        self.assertEqual(rail["departure_time"], "10:06")
        self.assertEqual(candidate["steps"][0]["meters"], 222)
        self.assertEqual(
            candidate["steps"][-1]["arrival_time"], candidate["arrival_time"]
        )

    def test_metro_timetable_uses_true_access_time_for_each_preference(self):
        with TemporaryDirectory() as tmp:
            gtfs, stations, lines = _fixture(Path(tmp))
            times = gtfs / "stop_times.txt"
            times.write_text(times.read_text().replace("24:10:00", "24:08:00"))
            graph = nx.DiGraph()
            tm = TimetableManager()
            add_tokyo_metro_to_graph(
                graph,
                tm,
                gtfs_dir=str(gtfs),
                stations_path=str(stations),
                railways_path=str(lines),
            )
            origin = (35.65, 139.70)
            end = (35.67, 139.73)
            points = {
                1: origin,
                2: (35.6525, 139.70),
                3: (35.6525, 139.701),
                4: (35.6506, 139.701),
                5: (35.67, 139.7295),
                6: end,
            }
            ids = {
                "odpt.Station:TokyoMetro.Hanzomon.C": 4,
                "odpt.Station:TokyoMetro.Hanzomon.D": 5,
            }
            net = network(
                points,
                [(1, 2, 3, True), (2, 3, 3, True), (3, 4, 3, True), (5, 6, 3, True)],
                ids,
            )
            bind_network(graph, net, 300)
            engine = TokyoRouteEngine(
                SimpleNamespace(
                    state=SimpleNamespace(
                        G=graph, TM=tm, SI=SpatialIndex(graph), WALK_RAD=300
                    )
                )
            )
            # 579 m approach + 2 min boarding. 24:08 is too early, 24:12 works.
            for pref in ("time", "cost", "fewTransfers"):
                with self.subTest(pref=pref):
                    result = engine.search_legacy(
                        alat=origin[0],
                        alon=origin[1],
                        blat=end[0],
                        blon=end[1],
                        pref=pref,
                        transport_scope=frozenset({TOKYO_METRO}),
                        start_time="23:59",
                        date_str="2026-09-24",
                        limit=1,
                    )
                    c = result["candidates"][0]
                    rail = next(s for s in c["steps"] if s["kind"] == "rail")
                    self.assertEqual(rail["trip_id"], "tokyo_metro:z-after-transfer")
                    self.assertEqual(c["arrival_time"], c["steps"][-1]["arrival_time"])
                    self.assertGreater(c["walking_distance_meters"], 600)
                    self.assertTrue(
                        all(
                            s.get("source") == "openstreetmap"
                            for s in c["route_geometry"]
                            if s["kind"] == "walk"
                        )
                    )
                    self.assertEqual(
                        result["meta"]["walking_network"]["destination"], "connected"
                    )
