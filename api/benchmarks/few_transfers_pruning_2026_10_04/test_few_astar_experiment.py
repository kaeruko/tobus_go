"""Offline A* checks; production search and timetable code remain untouched.

The reference enumerator knows exact walking distances and accumulates the
lexicographic objective directly. It does not reuse the reverse-bound builder.
Existing timetable/identity regressions also run under the in-memory clone.
"""

from __future__ import annotations

import contextlib
from dataclasses import replace
import hashlib
import inspect
import io
import math
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
API = HERE.parents[1]
sys.path.insert(0, str(API))
sys.path.insert(0, str(HERE))

import networkx as nx

import tokyo_search_labels as labels
from tokyo_timetable_choices import RideState
from route_engine import RouteSearchLimitError
from few_astar_bounds import make_bounds
from few_astar_experiment import make_search_variant
from tests import test_tokyo_bus_board_phase_regression as bus_phase
from tests import test_tokyo_bus_choices_contract as bus_choices
from tests import test_tokyo_heap_compaction as heap_fixture
from tests import test_tokyo_search_dominance_regression as dominance
from tests import test_tokyo_waiting_contract as waiting


def _phys(name):
    return ("phys", name)


def _edge(graph, left, right, kind, cost, meters=None):
    attributes = {"etype": kind, "w": float(cost)}
    if meters is not None:
        attributes["meters"] = float(meters)
    graph.add_edge(left, right, **attributes)


def _continuations(graph, node, target, segment=0.0, total=0.0,
                   virtual=None, blocked=lambda u, v: False):
    """Enumerate every exact-resource continuation in these small DAGs."""
    if node == target:
        return [(0, 0.0)]
    paths = []
    if node in (virtual or {}):
        cost, meters = virtual[node]
        if segment + meters <= 600 and total + meters <= 3000:
            paths.append((0, float(cost)))
    for following, edge in graph[node].items():
        if blocked(node, following):
            continue
        walk = edge["etype"] == "walk"
        meters = edge.get("meters", 0.0)
        consumed = meters if meters > 0 else 1.0
        next_segment = segment + consumed if walk else 0.0
        next_total = total + consumed if walk else total
        if next_segment > 600 or next_total > 3000:
            continue
        for boardings, cost in _continuations(
                graph, following, target, next_segment, next_total,
                virtual, blocked):
            paths.append((int(edge["etype"] == "board") + boardings,
                          float(edge.get("w", 0.0)) + cost))
    return paths


def _lex_less_equal(first, second):
    return first[0] < second[0] or (
        first[0] == second[0]
        and (first[1] <= second[1]
             or math.isclose(first[1], second[1], rel_tol=1e-12, abs_tol=1e-12)))


class RelaxedLowerBoundTest(unittest.TestCase):
    def _assert_admissible(self, graph, target, *, virtual=None,
                           blocked=lambda u, v: False):
        bound = make_bounds(graph, target, virtual or {}, edge_uses_rail=blocked)
        tested = 0
        for node in graph:
            for segment in (0.0, 1.0, 24.99, 25.0, 575.0, 576.0, 599.0, 600.0):
                estimate = bound(node, segment)
                for objective in _continuations(
                        graph, node, target, segment, virtual=virtual, blocked=blocked):
                    self.assertTrue(
                        _lex_less_equal(estimate, objective),
                        f"overestimated {node=} {segment=}: {estimate} > {objective}",
                    )
                    tested += 1
        self.assertGreater(tested, 0)
        return bound

    def test_cost_component_is_conditional_on_minimum_boardings(self):
        start, line, target = map(_phys, ("start", "line", "target"))
        graph = nx.DiGraph()
        _edge(graph, start, target, "walk", 50, 100)
        _edge(graph, start, line, "board", 2)
        _edge(graph, line, target, "ride", 1)
        bound = self._assert_admissible(graph, target)
        self.assertEqual(bound(start, 0), (0, 50.0))
        # Scalar minimum cost is 3; 50 is the minimum cost among zero-board paths.
        self.assertEqual(min(_continuations(graph, start, target), key=lambda x: x[1]),
                         (1, 3.0))

    def test_walk_bucket_relaxes_576_and_599_without_equating_real_labels(self):
        prefix, merge, target = map(_phys, ("prefix", "merge", "target"))
        graph = nx.DiGraph()
        _edge(graph, prefix, merge, "walk", 1, 576)
        _edge(graph, merge, target, "walk", 2, 10)
        bound = self._assert_admissible(graph, target)
        self.assertEqual(bound(merge, 576), (0, 2.0))
        self.assertEqual(bound(merge, 599), (0, 2.0))
        self.assertEqual(_continuations(graph, merge, target, 576), [(0, 2.0)])
        self.assertEqual(_continuations(graph, merge, target, 599), [])
        first = labels._Label(merge, 2.0, 10.0, 599.0, 599.0, 0)
        second = labels._Label(merge, 3.0, 9.0, 576.0, 576.0, 0)
        frontier = labels._Frontier(target, "fewTransfers", True)
        self.assertTrue(frontier.add(first))
        self.assertTrue(frontier.add(second))
        self.assertTrue(first.active)
        self.assertTrue(second.active)

    def test_600_m_boundary_sub_25_m_steps_and_nonpositive_walk_fallback(self):
        # Two 24m edges consume zero relaxed buckets, but exact resource checks
        # still reject them after a 576m prefix (624m actual segment).
        prefix, a, b, target = map(_phys, ("prefix", "a", "b", "target"))
        graph = nx.DiGraph()
        _edge(graph, prefix, a, "walk", 1, 576)
        _edge(graph, a, b, "walk", 1, 24)
        _edge(graph, b, target, "walk", 1, 24)
        bound = self._assert_admissible(graph, target)
        self.assertEqual(bound(a, 576), (0, 2.0))
        self.assertEqual(_continuations(graph, a, target, 576), [])
        self.assertEqual(_continuations(graph, b, target, 576), [(0, 1.0)])
        self.assertEqual(_continuations(graph, b, target, 576.01), [])
        for meters in (0, -2):
            with self.subTest(meters=meters):
                fallback = nx.DiGraph()
                _edge(fallback, prefix, b, "walk", 1, 575)
                _edge(fallback, b, target, "walk", 1, meters)
                self._assert_admissible(fallback, target)
                self.assertEqual(_continuations(fallback, b, target, 599), [(0, 1.0)])
                self.assertEqual(_continuations(fallback, b, target, 600), [])

    def test_virtual_destination_consumes_exact_walk_and_has_zero_goal_bound(self):
        start, stop, target = map(_phys, ("start", "stop", "virtual-target"))
        graph = nx.DiGraph()
        _edge(graph, start, stop, "walk", 3, 576)
        direct = {stop: (2.5, 24.0)}
        bound = self._assert_admissible(graph, target, virtual=direct)
        self.assertEqual(bound(stop, 576), (0, 2.5))
        self.assertEqual(bound(target, 600), (0, 0.0))
        self.assertEqual(_continuations(graph, stop, target, 576, virtual=direct),
                         [(0, 2.5)])
        self.assertEqual(_continuations(graph, stop, target, 599, virtual=direct), [])

    def test_bus_only_bound_cannot_use_filtered_rail_edges(self):
        start, bus, rail, target = map(_phys, ("start", "bus", "rail", "target"))
        graph = nx.DiGraph()
        _edge(graph, start, rail, "board", 1)
        _edge(graph, rail, target, "ride", 1)
        _edge(graph, start, bus, "board", 2)
        _edge(graph, bus, target, "ride", 3)
        rail_edges = {(start, rail), (rail, target)}
        blocked = lambda u, v: (u, v) in rail_edges
        full = self._assert_admissible(graph, target)
        bus_only = self._assert_admissible(graph, target, blocked=blocked)
        self.assertEqual(full(start, 0), (1, 2.0))
        self.assertEqual(bus_only(start, 0), (1, 5.0))

    def test_all_nonwalk_edges_reset_continuous_walk_as_production_does(self):
        prefix, stop, following, target = map(_phys, ("prefix", "stop", "following", "target"))
        for kind in ("board", "ride", "alight", "xfer", "approach"):
            with self.subTest(kind=kind):
                graph = nx.DiGraph()
                _edge(graph, prefix, stop, "walk", 1, 599)
                _edge(graph, stop, following, kind, 2)
                _edge(graph, following, target, "walk", 1, 600)
                bound = self._assert_admissible(graph, target)
                self.assertEqual(bound(stop, 599), (int(kind == "board"), 3.0))
                self.assertEqual(_continuations(graph, stop, target, 599),
                                 [(int(kind == "board"), 3.0)])

    def test_seeded_dags_match_independent_exact_resource_enumeration(self):
        generator = random.Random(20261005)
        for case in range(40):
            with self.subTest(case=case):
                nodes = [_phys(f"node-{i}") for i in range(7)]
                graph = nx.DiGraph()
                graph.add_nodes_from(nodes)
                for left in range(6):
                    for right in range(left + 1, 7):
                        if generator.random() < 0.42 or right == left + 1:
                            kind = generator.choice(("walk", "walk", "board", "ride", "alight"))
                            cost = generator.randrange(0, 31) / 4.0
                            meters = generator.choice((0, 1, 10, 24, 25, 26, 576, 599, 600, 601))
                            _edge(graph, nodes[left], nodes[right], kind, cost, meters)
                self._assert_admissible(graph, nodes[-1])

    def test_unsafe_cost_values_are_rejected_including_virtual_edges(self):
        start, target = map(_phys, ("start", "target"))
        for cost in (-1.0, math.inf, -math.inf, math.nan):
            with self.subTest(cost=cost, kind="graph"):
                graph = nx.DiGraph()
                _edge(graph, start, target, "walk", cost, 1)
                with self.assertRaises(ValueError):
                    make_bounds(graph, target, {})
            with self.subTest(cost=cost, kind="virtual"):
                graph = nx.DiGraph()
                graph.add_node(start)
                with self.assertRaises(ValueError):
                    make_bounds(graph, target, {start: (cost, 1.0)})

    def test_omitted_unreachable_unknown_and_invalid_resource_states_use_zero(self):
        start, target, unreachable = map(_phys, ("start", "target", "unreachable"))
        graph = nx.DiGraph()
        graph.add_node(unreachable)
        _edge(graph, start, target, "board", 3)
        bound = make_bounds(graph, target)
        self.assertEqual(bound(start, 0), (1, 3.0))
        # With no included incoming walk, a positive resource at start cannot
        # arise in a production query. An external probe receives safe zero.
        self.assertEqual(bound(start, 25), (0, 0.0))
        self.assertEqual(bound(unreachable, 0), (0, 0.0))
        self.assertEqual(bound(_phys("unknown"), 0), (0, 0.0))
        for resource in (-1, 601, math.inf, math.nan, "invalid"):
            with self.subTest(resource=resource):
                self.assertEqual(bound(start, resource), (0, 0.0))


class FewAStarContractTest(unittest.TestCase):
    def test_bound_preparation_counts_against_original_fifteen_second_limit(self):
        clock = {"now": 0.0}

        class FakeBound:
            report = {}

            def __call__(self, node, segment):
                return 0, 0.0

        def expensive_builder(*args, **kwargs):
            clock["now"] = 16.0
            return FakeBound()

        graph = heap_fixture._fan_in_graph(branches=5)
        with patch("few_astar_bounds.make_bounds", side_effect=expensive_builder) as builder:
            variant = make_search_variant()
            with patch.object(labels, "search_labels", variant), \
                    patch.object(labels.time, "monotonic", side_effect=lambda: clock["now"]), \
                    patch.object(labels.heapq, "heappop") as forward_pop, \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RouteSearchLimitError, "reason=time_limit_sec"):
                    list(heap_fixture._search(graph, mode="fewTransfers"))
        builder.assert_called_once()
        forward_pop.assert_not_called()

    def test_existing_pareto_waiting_bus_phase_and_identity_regressions(self):
        suite = unittest.TestSuite()
        loader = unittest.TestLoader()
        for module in (dominance, waiting, bus_phase, bus_choices):
            suite.addTests(loader.loadTestsFromModule(module))
        captured = io.StringIO()
        variant = make_search_variant()
        with patch.object(labels, "search_labels", variant), \
                contextlib.redirect_stdout(captured):
            result = unittest.TextTestRunner(stream=captured, verbosity=2).run(suite)
        self.assertTrue(result.wasSuccessful(), captured.getvalue())
        self.assertGreaterEqual(result.testsRun, 30)

    def test_cost_and_time_are_unchanged_and_never_build_bounds(self):
        reports = []
        variant = make_search_variant(reports)
        graph = heap_fixture._fan_in_graph(branches=30)
        for mode in ("cost", "time"):
            with self.subTest(mode=mode), contextlib.redirect_stdout(io.StringIO()):
                baseline = list(heap_fixture._search(graph, mode=mode))
                with patch.object(labels, "search_labels", variant):
                    actual = list(heap_fixture._search(graph, mode=mode))
            self.assertEqual(heap_fixture._snapshot(actual), heap_fixture._snapshot(baseline))
        self.assertEqual(reports, [])
        actual_signature = inspect.signature(variant)
        original_signature = inspect.signature(labels.search_labels)
        self.assertEqual(tuple(actual_signature.parameters), tuple(original_signature.parameters))
        for name, parameter in actual_signature.parameters.items():
            original = original_signature.parameters[name]
            self.assertEqual(parameter.kind, original.kind)
            if name == "heuristic":
                # Compiling the unchanged default lambda creates a new function.
                self.assertEqual(parameter.default(_phys("any")), original.default(_phys("any")))
            else:
                self.assertEqual(parameter.default, original.default)
        self.assertIs(variant.__globals__["_Frontier"], labels._Frontier)
        self.assertIs(variant.__globals__["_Label"], labels._Label)
        self.assertIs(variant.__globals__["_path"], labels._path)

    def test_few_transfers_loop_retains_exact_run_occurrences(self):
        graph = waiting._graph(("X", "A"), ("A", "B"), ("B", "A"), ("A", "C"))
        manager = waiting._manager(waiting._run(
            "loop", (("X", 595), ("A", 600), ("B", 605), ("A", 610), ("C", 615)),
        ))
        variant = make_search_variant()
        with patch.object(labels, "search_labels", variant), \
                contextlib.redirect_stdout(io.StringIO()):
            search = waiting.engine.find_few_transfers_paths_generator(
                graph, manager, waiting._physical("X"), waiting._physical("C"),
                start_time_str="09:53", use_realtime=False,
            )
            candidate = next(search)
            search.close()
        path = candidate["path"]
        self.assertEqual(path, [waiting._physical("X"), waiting._line("X"),
                               waiting._line("A"), waiting._line("B"),
                               waiting._line("A"), waiting._line("C"),
                               waiting._physical("C")])
        self.assertEqual(path.arrival_minute, 616)
        self.assertEqual(waiting._boardings(graph, path), 1)
        self.assertEqual([path.edge_rides[i].sequence for i in range(5)],
                         [0, 1, 2, 3, 4])

    def test_relaxation_can_ignore_run_termination_but_search_cannot(self):
        graph = waiting._graph(("A", "B"), ("B", "C"))
        manager = waiting._manager(
            waiting._run("terminating", (("A", 600), ("B", 605))),
            waiting._run("continuation", (("B", 609), ("C", 610))),
        )
        bound = make_bounds(graph, waiting._physical("C"))
        self.assertEqual(bound(waiting._line("A"), 0),
                         (0, 2 * waiting.engine.RAIL_RIDE_COST))
        with patch.object(labels, "search_labels", make_search_variant()), \
                contextlib.redirect_stdout(io.StringIO()):
            search = waiting.engine.find_few_transfers_paths_generator(
                graph, manager, waiting._physical("A"), waiting._physical("C"),
                start_time_str="09:58", use_realtime=False,
            )
            candidate = next(search)
            search.close()
        path = candidate["path"]
        self.assertEqual(waiting._boardings(graph, path), 2)
        self.assertEqual(path.arrival_minute, 611)
        self.assertEqual(path, [waiting._physical("A"), waiting._line("A"),
                               waiting._line("B"), waiting._physical("B"),
                               waiting._line("B"), waiting._line("C"),
                               waiting._physical("C")])

    def test_first_goal_has_exact_lexicographic_optimum_without_extra_boarding(self):
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

        class Choices:
            can_wait_offboard = True
            use_realtime = False
            manager = object()

            def board_options(self, u, v, ready):
                return ((ready, RideState("bus", "day", v[2], v[2], 0, 0, ready)),)

            def ride_options(self, u, v, current, state):
                return ((current + 1, replace(state, sequence=state.sequence + 1)),)

        variant = make_search_variant()
        with contextlib.redirect_stdout(io.StringIO()):
            search = variant(
                graph, Choices(), start, target, mode="fewTransfers", start_minute=0.0,
                max_search=5, max_visited=100000, max_travel_min=240,
                time_limit_sec=15.0, max_total_walk=3000, max_segment_walk=600,
                walk_speed=80.0, rail_boarding_minutes=2.0,
                advance_time=lambda u, v, current, edge: current,
                virtual_connections={}, edge_uses_rail=lambda u, v: False,
            )
            first = next(search)
            search.close()
        expected = min(_continuations(graph, start, target))
        self.assertEqual(expected, (1, 7.0))
        self.assertEqual((waiting._boardings(graph, first["path"]), first["cost"]), expected)

    def test_loading_and_running_experiment_does_not_write_product_sources(self):
        paths = [API / filename for filename in (
            "tokyo_search_labels.py", "tokyo_timetable_choices.py", "toei_engine.py")]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        variant = make_search_variant()
        graph = heap_fixture._fan_in_graph(branches=5)
        with patch.object(labels, "search_labels", variant), \
                contextlib.redirect_stdout(io.StringIO()):
            results = list(heap_fixture._search(graph, mode="fewTransfers"))
        self.assertEqual(len(results), 5)
        self.assertEqual(
            {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}, before,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
