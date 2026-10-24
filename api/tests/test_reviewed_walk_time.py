"""Directed, evidence-scoped Tokyo/Sendai walking-time correction tests."""
from __future__ import annotations

import contextlib
import io
from types import SimpleNamespace
import unittest

import networkx as nx

from reviewed_walk_time import (
    ReviewedWalkingLink, validate_reviewed_walk_timing, walk_edge_elapsed_minutes,
    walk_edge_is_available, walk_edge_resource_meters,
)
from toei_engine import (
    WALK_COST, advance_time, apply_reviewed_walking_links, find_fastest_path,
    segments_detailed,
)
from tokyo_search_labels import SelectedPath


def _link(first="pole-A", second="station-B", meters=392, minutes=10, access=True):
    return ReviewedWalkingLink(
        first, second, meters, minutes,
        "https://www.kotsu.metro.tokyo.jp/subway/", access,
    )


def _graph():
    g = nx.DiGraph()
    a, b = ("phys", "pole-A"), ("phys", "station-B")
    c = ("phys", "station-C")
    for node, name, lat, lon in (
        (a, "バス停A", 35.0000, 139.0000),
        (b, "地下鉄B", 35.0004, 139.0000),
        (c, "地下鉄C", 35.0008, 139.0000),
    ):
        g.add_node(node, name=name, name_en=name, lat=lat, lon=lon, kind="phys")
    for origin, destination in ((a, b), (b, a), (b, c)):
        g.add_edge(origin, destination, etype="walk", meters=80,
                   w=WALK_COST * 1.0)
    return g


class ReviewedWalkingTimeTests(unittest.TestCase):
    def test_common_geometry_fallback_is_unchanged_without_override(self):
        self.assertEqual(walk_edge_elapsed_minutes({"meters": 80}), 1.0)
        self.assertEqual(walk_edge_elapsed_minutes({"meters": 0}), 1 / 80)
        self.assertEqual(walk_edge_elapsed_minutes({"meters": -2}), 1 / 80)
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            walk_edge_elapsed_minutes({"meters": -2, "reviewed_walk_minutes": 2})
        self.assertEqual(walk_edge_elapsed_minutes(
            {"meters": 392, "reviewed_walk_minutes": 10}
        ), 10.0)

    def test_unknown_physical_distance_uses_separate_conservative_resource(self):
        edge = {
            "meters": 0.0,
            "walk_resource_meters": 600.0,
            "reviewed_walk_minutes": 15,
            "transfer_time_estimated": True,
        }
        self.assertEqual(walk_edge_elapsed_minutes(edge), 15.0)
        self.assertEqual(walk_edge_resource_meters(edge), 600.0)
        self.assertEqual(edge["meters"], 0.0)

    def test_known_transfer_closure_must_cover_the_complete_walk(self):
        edge = {"transfer_available_windows": ((300, 610),)}
        self.assertTrue(walk_edge_is_available(
            edge, departure_minute=595, elapsed_minutes=15
        ))
        self.assertFalse(walk_edge_is_available(
            edge, departure_minute=596, elapsed_minutes=15
        ))
        self.assertTrue(walk_edge_is_available(
            {}, departure_minute=596, elapsed_minutes=15
        ))

    def test_tokyo_correction_changes_routing_and_walk_display(self):
        graph = _graph()
        first, second = ("phys", "pole-A"), ("phys", "station-B")
        untouched_reverse = dict(graph.edges[second, first])
        self.assertEqual(advance_time(graph, object(), first, second, 600), 601)
        apply_reviewed_walking_links(graph, (_link(),))
        self.assertEqual(graph.edges[first, second]["meters"], 392)
        self.assertEqual(graph.edges[first, second]["w"], WALK_COST * 10)
        self.assertEqual(advance_time(graph, object(), first, second, 600), 610)
        self.assertEqual(dict(graph.edges[second, first]), untouched_reverse)
        with contextlib.redirect_stdout(io.StringIO()):
            result = segments_detailed(graph, [first, second], object(), start_time_str="10:00")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["minutes"], 10)
        self.assertEqual(result[0]["meters"], 392)
        self.assertEqual((result[0]["departure_time"], result[0]["arrival_time"]),
                         ("10:00", "10:10"))
        self.assertTrue(result[0]["walking_connection_verified"])
        self.assertEqual(result[0]["walking_time_basis"], "official_reviewed")
        self.assertEqual(result[0]["evidence_urls"], [
            "https://www.kotsu.metro.tokyo.jp/subway/"
        ])

    def test_mixed_walk_shows_unverified_estimated_tail_and_sums_time(self):
        graph = _graph()
        first, second, third = (("phys", x) for x in ("pole-A", "station-B", "station-C"))
        apply_reviewed_walking_links(graph, (_link(),))
        with contextlib.redirect_stdout(io.StringIO()):
            result = segments_detailed(
                graph, [first, second, third], object(), start_time_str="10:00"
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["minutes"], 11)
        self.assertEqual(result[0]["meters"], 472)
        self.assertEqual((result[0]["departure_time"], result[0]["arrival_time"]),
                         ("10:00", "10:11"))
        self.assertFalse(result[0]["walking_connection_verified"])
        self.assertEqual(result[0]["walking_time_basis"], "mixed_estimated")

    def test_walk_clocks_keep_fractional_selected_timing_across_midnight(self):
        graph = _graph()
        nodes = [("phys", name) for name in ("pole-A", "station-B", "station-C")]
        graph.edges[nodes[0], nodes[1]]["meters"] = 75
        graph.edges[nodes[1], nodes[2]]["meters"] = 307
        start = 23 * 60 + 58
        clocks = [start + 75 / 80, start + 75 / 80 + 307 / 80]
        selected = SelectedPath(
            nodes, clocks, {},
            SimpleNamespace(manager=object(), use_realtime=False), start,
        )
        for path in (nodes, selected):
            with self.subTest(selected=isinstance(path, SelectedPath)), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = segments_detailed(graph, path, object(), start_time_str="23:58")
            self.assertEqual(len(result), 1)
            self.assertEqual((result[0]["departure_time"], result[0]["arrival_time"]),
                             ("23:58", "24:02"))
            self.assertEqual(result[0]["meters"], 382)
            self.assertEqual(result[0]["minutes"], 5)
        self.assertEqual(selected.edge_times, clocks)

    def test_walk_after_train_uses_the_selected_arrival_and_alighting_clock(self):
        from tests.test_tokyo_waiting_contract import (
            _identity_graph, _manager, _physical, _run, _walk,
        )

        graph = _identity_graph(("A", "B"))
        _walk(graph, _physical("B"), _physical("destination"), 307)
        manager = _manager(_run("evening", (("A", 1260), ("B", 1270))))
        with contextlib.redirect_stdout(io.StringIO()):
            arrival, path = find_fastest_path(
                graph, manager, _physical("A"), _physical("destination"),
                start_time_str="20:58", use_realtime=False,
            )
            steps = segments_detailed(
                graph, path, manager, start_time_str="20:58", use_realtime=False,
            )
        self.assertAlmostEqual(arrival, 1271 + 307 / 80)
        self.assertEqual([step["kind"] for step in steps], ["rail", "walk"])
        self.assertEqual((steps[0]["departure_time"], steps[0]["arrival_time"]),
                         ("21:00", "21:10"))
        self.assertEqual((steps[1]["departure_time"], steps[1]["arrival_time"]),
                         ("21:11", "21:14"))

    def test_invalid_or_stale_batch_never_partially_changes_tokyo_graph(self):
        for bad in (
            _link(second="unknown"),
            _link(first="station-B", second="pole-A", meters=1),
        ):
            graph = _graph()
            baseline = dict(graph.edges[("phys", "pole-A"), ("phys", "station-B")])
            with self.assertRaises(ValueError):
                apply_reviewed_walking_links(graph, (_link(), bad))
            self.assertEqual(
                dict(graph.edges[("phys", "pole-A"), ("phys", "station-B")]),
                baseline,
            )
        graph = _graph()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            apply_reviewed_walking_links(graph, (_link(), _link()))

    def test_accessibility_scope_or_fake_url_never_auto_approves(self):
        for params in (
            {"access": False},
            {"meters": 392, "minutes": 4},
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                _link(**params)
        with self.assertRaisesRegex(ValueError, "official government"):
            ReviewedWalkingLink(
                "a", "b", 100, 3, "https://example.com/approvals", True,
            )

    def test_sendai_link_uses_same_distance_minimum(self):
        self.assertIsNone(validate_reviewed_walk_timing(392, 10))
        valid = ReviewedWalkingLink(
            "fixture_bus:3018_02", "fixture_subway:B19", 392, 10,
            "https://www.kotsu.city.sendai.jp/", True
        )
        self.assertEqual(valid.walk_minutes, 10)
        with self.assertRaises(ValueError):
            ReviewedWalkingLink(
                "fixture_bus:3018_02", "fixture_subway:B19", 392, 4,
                "https://www.kotsu.city.sendai.jp/", True
            )


if __name__ == "__main__":
    unittest.main()

