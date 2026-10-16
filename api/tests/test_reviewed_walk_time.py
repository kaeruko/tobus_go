"""Directed, evidence-scoped Tokyo/Sendai walking-time correction tests."""
from __future__ import annotations

import contextlib
import io
import unittest

import networkx as nx

from reviewed_walk_time import (
    ReviewedWalkingLink, validate_reviewed_walk_timing, walk_edge_elapsed_minutes,
)
from toei_engine import (
    WALK_COST, advance_time, apply_reviewed_walking_links, segments_detailed,
)


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
        self.assertFalse(result[0]["walking_connection_verified"])
        self.assertEqual(result[0]["walking_time_basis"], "mixed_estimated")

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

