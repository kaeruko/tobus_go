"""Admissibility of query-local lexicographic few-transfers lower bounds.

The reference enumerator checks exact walking resources without using the
reverse-bound implementation. Its DAGs include every legal continuation.
"""

import math
import random
import unittest

import networkx as nx

import tokyo_search_labels as labels
from tokyo_few_transfers_bounds import CostRoundingGuard, make_bounds


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
    def test_deadline_callback_can_stop_large_preparation_and_exception_propagates(self):
        graph = nx.DiGraph()
        for node in range(4096):
            graph.add_edge(node, node + 1, etype="walk", meters=1.0, w=1.0)
        checks = []

        class DeadlineExpired(Exception):
            pass

        def check_deadline():
            checks.append(True)
            if len(checks) == 3:
                raise DeadlineExpired("preparation deadline")

        with self.assertRaisesRegex(DeadlineExpired, "preparation deadline"):
            make_bounds(graph, 4096, check_deadline=check_deadline)
        self.assertEqual(len(checks), 3)

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

    def test_virtual_shortcut_is_included_even_when_target_exists_in_graph(self):
        start, stop, target = map(_phys, ("start", "stop", "target"))
        graph = nx.DiGraph()
        _edge(graph, start, stop, "approach", 0)
        _edge(graph, stop, target, "walk", 100, 24)
        virtual = {stop: (1.0, 24.0)}
        bound = self._assert_admissible(graph, target, virtual=virtual)
        self.assertIn(target, graph)
        self.assertEqual(bound(stop, 0), (0, 1.0))
        self.assertEqual(bound(start, 0), (0, 1.0))
        self.assertEqual(bound(target, 0), (0, 0.0))

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



class CostRoundingGuardTest(unittest.TestCase):
    def test_guard_is_below_independently_accumulated_forward_costs(self):
        generator = random.Random(20261005)
        scales = (math.ulp(0.0), 1e-220, 1e-12, 1.0, 1e12, 1e16, 1e220)
        for case in range(400):
            count = generator.randrange(2, 61)
            selected_scale = generator.choice(scales)
            weights = [(selected_scale if case % 2 == 0 else generator.choice(scales))
                       * generator.choice((0.0, 0.1, 0.2, 0.6, 0.7, 1.2, 3.4))
                       for _ in range(count)]
            split = generator.randrange(1, count)
            prefix = 0.0
            for weight in weights[:split]:
                prefix += weight
            reverse = 0.0
            for weight in reversed(weights[split:]):
                reverse += weight
            actual_forward = prefix
            for weight in weights[split:]:
                actual_forward += weight
            guard = CostRoundingGuard(
                max_edge_cost=max(weights), max_forward_steps=count,
                max_reverse_steps=count + 1,
            )
            with self.subTest(case=case):
                # Strict comparison detects the few-ULP queue-order regression.
                self.assertLessEqual(guard(prefix, reverse), actual_forward)
                self.assertGreaterEqual(guard(prefix, reverse), prefix)

    def test_zero_cost_continuation_preserves_prefix_and_overflow_uses_prefix(self):
        guard = CostRoundingGuard(3.4, 100000, 1000000)
        for prefix in (0.0, 0.1, 11.099999999999998, 1e16, 1e220):
            with self.subTest(prefix=prefix):
                self.assertEqual(guard(prefix, 0.0), prefix)
        overflow = CostRoundingGuard(1e308, 100000, 1000000)
        self.assertEqual(overflow(1e308, 1e308), 1e308)
        self.assertEqual(overflow(7.0, 1.0), 7.0)
        disabled = CostRoundingGuard(math.inf, 10, 10)
        self.assertEqual(disabled(7.0, 1.0), 7.0)


if __name__ == "__main__":
    unittest.main()
