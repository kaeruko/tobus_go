"""Production few-transfers A* keeps exact itineraries and existing limits."""

import contextlib
from dataclasses import replace
import io
import unittest
from unittest.mock import patch

import networkx as nx

from route_engine import RouteSearchLimitError
import tokyo_search_labels as labels
from tokyo_few_transfers_bounds import CostRoundingGuard, make_bounds
from tokyo_timetable_choices import RideState
from tests import test_tokyo_heap_compaction as heap_fixture
from tests.test_tokyo_few_transfers_bounds import _continuations, _edge, _phys


class _ZeroBound:
    report = {"build_ms": 0.0}

    def __call__(self, node, segment):
        return 0, 0.0


class _Choices:
    can_wait_offboard = True
    use_realtime = False
    manager = object()

    def board_options(self, u, v, ready):
        return ((ready, RideState("bus", "day", v[2], v[2], 0, 0, ready)),)

    def ride_options(self, u, v, current, state):
        return ((current + 1, replace(state, sequence=state.sequence + 1)),)


def _search(graph, start, target, virtual=None):
    return labels.search_labels(
        graph, _Choices(), start, target, mode="fewTransfers", start_minute=0.0,
        max_search=5, max_visited=100000, max_travel_min=240,
        time_limit_sec=15.0, max_total_walk=3000.0, max_segment_walk=600.0,
        walk_speed=80.0, rail_boarding_minutes=2.0,
        advance_time=lambda u, v, current, edge: current + edge.get("meters", 0.0) / 80.0,
        virtual_connections=virtual or {}, edge_uses_rail=lambda u, v: False,
    )


class TokyoFewTransfersAStarTest(unittest.TestCase):
    def test_cost_and_time_never_build_few_transfers_bounds(self):
        graph = heap_fixture._fan_in_graph(branches=30)
        for mode in ("cost", "time"):
            with self.subTest(mode=mode), contextlib.redirect_stdout(io.StringIO()):
                baseline = list(heap_fixture._search(graph, mode=mode))
                with patch.object(labels, "make_bounds", side_effect=AssertionError(
                        "Other objectives must not build few-transfers bounds")) as builder:
                    actual = list(heap_fixture._search(graph, mode=mode))
                self.assertEqual(heap_fixture._snapshot(actual), heap_fixture._snapshot(baseline))
                builder.assert_not_called()

    def test_bound_preparation_counts_against_original_fifteen_second_limit(self):
        clock = {"now": 0.0}

        def expensive_builder(*args, **kwargs):
            clock["now"] = 16.0
            return _ZeroBound()

        graph = heap_fixture._fan_in_graph(branches=5)
        with patch.object(labels, "make_bounds", side_effect=expensive_builder) as builder, \
                patch.object(labels.time, "monotonic", side_effect=lambda: clock["now"]), \
                patch.object(labels.heapq, "heappop") as forward_pop, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RouteSearchLimitError, "reason=time_limit_sec"):
                list(heap_fixture._search(graph, mode="fewTransfers"))
        builder.assert_called_once()
        forward_pop.assert_not_called()

    def test_builder_receives_the_same_deadline_and_can_abort_before_search(self):
        clock = {"now": 0.0}
        reached_after_check = []

        def expensive_builder(*args, **kwargs):
            clock["now"] = 16.0
            kwargs["check_deadline"]()
            reached_after_check.append(True)
            return _ZeroBound()

        graph = heap_fixture._fan_in_graph(branches=5)
        with patch.object(labels, "make_bounds", side_effect=expensive_builder), \
                patch.object(labels.time, "monotonic", side_effect=lambda: clock["now"]), \
                patch.object(labels.heapq, "heappop") as forward_pop, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RouteSearchLimitError, "reason=time_limit_sec.*visited=0"):
                list(heap_fixture._search(graph, mode="fewTransfers"))
        self.assertEqual(reached_after_check, [])
        forward_pop.assert_not_called()

    def test_five_candidates_keep_order_clocks_and_selected_runs(self):
        graph = heap_fixture._fan_in_graph(branches=30)
        with contextlib.redirect_stdout(io.StringIO()):
            with patch.object(labels, "make_bounds", return_value=_ZeroBound()):
                reference = list(heap_fixture._search(graph, mode="fewTransfers"))
            with patch.object(labels, "make_bounds", wraps=make_bounds) as builder:
                actual = list(heap_fixture._search(graph, mode="fewTransfers"))
                repeated = list(heap_fixture._search(graph, mode="fewTransfers"))
        self.assertEqual(len(actual), 5)
        self.assertEqual(heap_fixture._snapshot(actual), heap_fixture._snapshot(reference))
        self.assertEqual(heap_fixture._snapshot(repeated), heap_fixture._snapshot(reference))
        # Preparation is query-local; repeated searches build their own bounds.
        self.assertEqual(builder.call_count, 2)

    def test_first_goal_matches_independent_lexicographic_optimum(self):
        graph = nx.DiGraph()
        start, interchange, target = map(_phys, ("start", "interchange", "target"))
        graph.add_nodes_from((start, interchange, target))
        for name, origin, destination, cost in (
                ("one", start, target, 7.0),
                ("first", start, interchange, 1.0),
                ("second", interchange, target, 1.0)):
            left, right = ("line", f"{name}-origin", name), ("line", f"{name}-end", name)
            graph.add_node(left, mode="bus")
            graph.add_node(right, mode="bus")
            _edge(graph, origin, left, "board", cost)
            _edge(graph, left, right, "ride", 0)
            _edge(graph, right, destination, "alight", 0)
        with contextlib.redirect_stdout(io.StringIO()):
            search = _search(graph, start, target)
            first = next(search)
            search.close()
        expected = min(_continuations(graph, start, target))
        boardings = sum(graph[u][v]["etype"] == "board"
                        for u, v in zip(first["path"], first["path"][1:]))
        self.assertEqual(expected, (1, 7.0))
        self.assertEqual((boardings, first["cost"]), expected)

    def test_priority_receives_exact_walk_and_virtual_goal_keeps_hard_limit(self):
        graph = nx.DiGraph()
        start, earlier, cheaper, merge, target = map(
            _phys, ("start", "earlier", "cheaper", "merge", "virtual-target"))
        _edge(graph, start, earlier, "approach", 0)
        _edge(graph, start, cheaper, "approach", 0)
        _edge(graph, earlier, merge, "walk", 3, 576)
        _edge(graph, cheaper, merge, "walk", 2, 599)
        virtual = {merge: (2.5, 24.0)}
        seen = []

        class RecordingBound(_ZeroBound):
            def __call__(self, node, segment):
                seen.append((node, segment))
                return super().__call__(node, segment)

        with patch.object(labels, "make_bounds", return_value=RecordingBound()) as builder, \
                contextlib.redirect_stdout(io.StringIO()):
            candidates = list(_search(graph, start, target, virtual=virtual))
        self.assertNotIn(target, graph)
        self.assertIn((merge, 576.0), seen)
        self.assertIn((merge, 599.0), seen)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["path"], [start, earlier, merge, target])
        self.assertEqual(candidates[0]["walk_m"], 600.0)
        self.assertEqual(candidates[0]["cost"], 5.5)
        self.assertEqual(candidates[0]["path"].arrival_minute, 7.5)
        self.assertEqual(builder.call_args.args[2], virtual)

    def test_rounding_guard_keeps_lowest_forward_float_cost_at_normal_and_large_scales(self):
        cases = (
            ("normal", [1.2, 3.4, 0.7, 0.2, 3.4, 0.7, 0.7, 0.1, 0.7],
             [0.1, 0.7, 3.4, 0.7, 0.2, 1.2, 0.7, 3.4, 0.7]),
            ("large", [1e16] + [0.6] * 10, [1e16 + 2]),
        )
        for name, first_weights, second_weights in cases:
            with self.subTest(case=name):
                graph = nx.DiGraph()
                start, target = map(_phys, ("start", "target"))
                for branch_name, weights in (("first", first_weights), ("second", second_weights)):
                    previous = start
                    for index, weight in enumerate(weights):
                        following = (target if index == len(weights) - 1 else
                                     _phys(f"{branch_name}-{index}"))
                        kind = "board" if name == "large" and index == 0 else "approach"
                        _edge(graph, previous, following, kind, weight)
                        previous = following

                def first_candidate():
                    search = _search(graph, start, target)
                    candidate = next(search)
                    search.close()
                    return candidate

                with contextlib.redirect_stdout(io.StringIO()):
                    with patch.object(labels, "make_bounds", return_value=_ZeroBound()):
                        reference = first_candidate()
                    actual = first_candidate()
                self.assertEqual(actual["cost"], reference["cost"])
                self.assertEqual(actual["path"], reference["path"])
                self.assertIn(_phys("first-0"), actual["path"])
                self.assertEqual(actual["cost"],
                                 11.099999999999998 if name == "normal" else 1e16)

    def test_virtual_connection_cost_is_included_in_rounding_guard_maximum(self):
        graph = nx.DiGraph()
        start, stop, target = map(_phys, ("start", "stop", "virtual-target"))
        _edge(graph, start, stop, "approach", 0.1)
        virtual = {stop: (1e12, 24.0)}
        with patch.object(labels, "CostRoundingGuard", wraps=CostRoundingGuard) as guard, \
                contextlib.redirect_stdout(io.StringIO()):
            candidates = list(_search(graph, start, target, virtual=virtual))
        self.assertEqual(len(candidates), 1)
        guard.assert_called_once()
        maximum = guard.call_args.kwargs.get("max_edge_cost")
        if maximum is None:
            maximum = guard.call_args.args[0]
        self.assertGreaterEqual(maximum, virtual[stop][0])

    def test_existing_graph_target_virtual_shortcut_is_not_overestimated(self):
        graph = nx.DiGraph()
        start, shortcut, other, target = map(_phys, ("start", "shortcut", "other", "target"))
        _edge(graph, start, shortcut, "approach", 0)
        _edge(graph, shortcut, target, "walk", 100, 24)
        _edge(graph, start, other, "approach", 1)
        _edge(graph, other, target, "approach", 1)
        virtual = {shortcut: (1.0, 24.0)}

        def first_candidate():
            search = _search(graph, start, target, virtual=virtual)
            candidate = next(search)
            search.close()
            return candidate

        with contextlib.redirect_stdout(io.StringIO()):
            with patch.object(labels, "make_bounds", return_value=_ZeroBound()):
                reference = first_candidate()
            actual = first_candidate()
        self.assertEqual(actual["cost"], 1.0)
        self.assertEqual(actual["path"], [start, shortcut, target])
        self.assertEqual(actual["cost"], reference["cost"])
        self.assertEqual(actual["path"], reference["path"])


if __name__ == "__main__":
    unittest.main()
