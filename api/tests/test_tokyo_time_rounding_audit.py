"""Independent bounded legal continuations, exact rational error budgets.

The enumerator reads only these raw schedules and graph edges. It never calls
the route search, TimetableChoices board/ride, or an interval/bound builder to
produce its operational arrival clocks. Bounds are tested separately against
every prefix of every completed enumerated continuation, with no epsilon.
"""
from __future__ import annotations

from datetime import date
from fractions import Fraction
import itertools
import math
import unittest
from unittest.mock import patch

import networkx as nx

from route_engine import RouteContractError
from tokyo_destination_bounds_audit import project_common_graph, common_destination_bounds
from tokyo_time_rounding import TimeRoundingGuard
from tokyo_time_rounding_audit import float_bits, verify_guard_coefficients, verify_guard_equivalence
from tokyo_timetable_choices import TimetableChoices
from tests import test_tokyo_bus_choices_contract as bus
from tests import test_tokyo_waiting_contract as rail


def _enumerate(graph, runs, start, target, clock, virtual, *, deadline, step_bound):
    # State: node, stored clock, run index, position, boarding position,
    # total walking meters, segment walking meters. Occurrence, not stop ID,
    # identifies a position in a loop. All synthetic runs are active today.
    initial = (start, clock, None, None, None, 0.0, 0.0)

    def visit(state, trace):
        node, current, riding, position, boarded, total, segment = state
        if node == target:
            yield trace
            return
        if len(trace) - 1 >= step_bound:
            return
        options = []
        if node in virtual:
            _cost, meters = virtual[node]
            options.append((target, current + meters / 80.0, None, None, None,
                            total + meters, segment + meters))
        for following, edge in graph[node].items():
            kind = edge.get("etype")
            if kind == "walk":
                meters = edge["meters"] if edge["meters"] > 0 else 1.0
                options.append((following, current + meters / 80.0, None, None, None,
                                total + meters, segment + meters))
            elif kind == "board" and riding is None:
                mode = graph.nodes[following]["mode"]
                ready = current + (2.0 if mode == "rail" else 0.0)
                for run_index, (provider, _identity, line, stops) in enumerate(runs):
                    if provider != mode or following[2] != line:
                        continue
                    for index, (stop, _arrival, departure, pickup) in enumerate(stops[:-1]):
                        if stop == node[1] and pickup == 0 and departure >= ready:
                            options.append((following, departure, run_index, index, index, total, 0.0))
            elif kind == "ride" and riding is not None:
                provider, _identity, line, stops = runs[riding]
                if position + 1 >= len(stops):
                    continue
                _stop, _arrival, departure, _pickup = stops[position]
                stop, arrival, _departure, _pickup = stops[position + 1]
                if (following[1] == stop and following[2] == line
                        and departure >= current and arrival >= departure):
                    options.append((following, arrival, riding, position + 1, boarded, total, 0.0))
            elif kind in ("alight", "xfer") and riding is not None and position != boarded:
                provider = runs[riding][0]
                options.append((following, current + (1.0 if provider == "rail" else 0.0),
                                None, None, None, total, 0.0))
        for candidate in options:
            if (current <= candidate[1] <= deadline
                    and candidate[5] <= 3000.0 and candidate[6] <= 600.0):
                yield from visit(candidate, trace + (candidate,))

    return tuple(visit(initial, (initial,)))


def _rational_distances(projection, target, virtual):
    """Synchronous rational path-length DP, not binary64 reverse Dijkstra."""
    distances = {target: Fraction()} if target in projection.reverse else {}
    for node, (_cost, meters) in virtual.items():
        if node in projection.reverse:
            value = Fraction.from_float(meters / 80.0)
            distances[node] = min(value, distances.get(node, value))
    for _ in projection.nodes:
        previous = distances
        distances = dict(previous)
        for node, edges in projection.reverse.items():
            if node in previous:
                for earlier, weight in edges:
                    value = previous[node] + Fraction.from_float(weight)
                    distances[earlier] = min(value, distances.get(earlier, value))
    return distances


def _mixed_fixture(offset):
    raw_rail = (
        ("loop", (("A", 600, 600), ("B", 603, 604), ("A", 606, 606), ("C", 608, 608))),
        ("later_fast", (("A", 601, 601), ("C", 605, 605))),
        ("finish", (("E", 616, 616), ("Z", 619, 619))),
    )
    raw_bus = (
        ("through", (("bus_C", 610, 610, 0), ("Q", 611, 612, 1), ("D", 614, 614, 0))),
        ("later_bus", (("bus_C", 611, 611, 0), ("D", 613, 613, 0))),
    )
    source_runs, runs = [], []
    rail_pairs = []
    for identity, stops in raw_rail:
        source = rail._run(identity, tuple((name, arrival + offset) for name, arrival, _ in stops))
        for row, (_name, _arrival, departure) in zip(source["odpt:trainTimetableObject"], stops):
            row["odpt:departureTime"] = rail._time(departure + offset)
        source_runs.append(source)
        rail_pairs.extend((a[0], b[0]) for a, b in zip(stops, stops[1:]))
        runs.append(("rail", identity, rail.RAILWAY,
                     tuple((rail._station(name), float(arrival + offset), float(departure + offset), 0)
                           for name, arrival, departure in stops)))
    repository = bus._repository(*(tuple((identity, "active", tuple(
        (name, arrival + offset, departure + offset) for name, arrival, departure, _ in stops)))
        for identity, stops in raw_bus))
    repository.stop_time_boarding["through"][2] = (1, 0)
    for identity, stops in raw_bus:
        runs.append(("bus", identity, bus.LINE,
                     tuple((name, float(arrival + offset), float(departure + offset), pickup)
                           for name, arrival, departure, pickup in stops)))
    graph = nx.compose(rail._graph(*rail_pairs),
                       bus._graph(("bus_C", "Q"), ("Q", "D"), ("bus_C", "D")))
    rail._walk(graph, rail._physical("C"), bus._phys("bus_C"), 2.0)
    rail._walk(graph, bus._phys("D"), rail._physical("E"), 4.0)
    manager = rail._manager(*source_runs)
    day = bus.engine.ServiceDayType("weekday", date(2026, 9, 4), frozenset(("active",)), True)
    choices = TimetableChoices(graph, manager, day_type=day, use_realtime=False,
                               deadline=offset + 840, bus_repository=repository)
    rail_minima, bus_minima = {}, {}
    for mode, _identity, _line, stops in runs:
        for first, second in zip(stops, stops[1:]):
            exact = Fraction.from_float(second[1]) - Fraction.from_float(first[2])
            value = max(0.0, math.nextafter(float(exact), -math.inf)) if exact else 0.0
            key = (first[0], second[0]) if mode == "rail" else (bus.ROUTE, first[0], second[0])
            minima = rail_minima if mode == "rail" else bus_minima
            minima[key] = min(value, minima.get(key, value))
    return graph, choices, tuple(runs), rail_minima, bus_minima


class TokyoTimeRoundingAuditTest(unittest.TestCase):
    def test_exact_coefficients_near_clock_binades_subnormals_and_large_counts(self):
        cases = ((0.0, 240.0, 0, 1, 0.0),
                 (0.0, math.ulp(0.0) * 20, 5, 4, math.ulp(0.0)),
                 (600.0, 840.0, 100000, 18985, 200.0),
                 (1439.0, 1679.0, 100000, 18985, 200.0),
                 (1e16, 1e16 + 240, 12, 13, 0.6),
                 (math.nextafter(1024.0, -math.inf), 1024.0, 20, 1000, 0.1),
                 (1024.0, math.nextafter(2048.0, math.inf), 2**30, 100000, 1.0))
        for start, upper, nf, nr, weight in cases:
            args = dict(start_minute=start, deadline=upper, max_forward_steps=nf,
                        max_reverse_steps=nr, max_edge_minutes=weight)
            guard = TimeRoundingGuard(**args)
            report = verify_guard_coefficients(guard, **args)
            self.assertTrue(report["conditional_error_coefficients_verified"])
            self.assertFalse(report["unconditional_priority_admissibility_verified"])

    def test_insufficient_error_enclosure_or_disabled_guard_fails(self):
        args = dict(start_minute=600.0, deadline=840.0, max_forward_steps=100,
                    max_reverse_steps=100, max_edge_minutes=1.0)
        for field in ("reverse_error_minutes", "transition_error_minutes", "priority_error_minutes"):
            guard = TimeRoundingGuard(**args)
            guard.report[field] = 0.0
            with self.assertRaisesRegex(RouteContractError, "too small"):
                verify_guard_coefficients(guard, **args)
        guard = TimeRoundingGuard(**args)
        guard._error = 0.0
        with self.assertRaisesRegex(RouteContractError, "too small"):
            verify_guard_coefficients(guard, **args)
        guard = TimeRoundingGuard(**{**args, "max_edge_minutes": 1e308})
        with self.assertRaisesRegex(RouteContractError, "disabled"):
            verify_guard_coefficients(guard, **args)
        guard = TimeRoundingGuard(**args)
        guard._enabled = False
        with self.assertRaisesRegex(RouteContractError, "disabled"):
            verify_guard_coefficients(guard, **args)

    def test_coefficient_one_ulp_difference_is_not_accepted(self):
        args = dict(start_minute=600.0, deadline=840.0, max_forward_steps=100,
                    max_reverse_steps=100, max_edge_minutes=1.0)
        reference, changed = TimeRoundingGuard(**args), TimeRoundingGuard(**args)
        changed.report["fixed_error_minutes"] = math.nextafter(changed._error, math.inf)
        with self.assertRaisesRegex(RouteContractError, "coefficient differs"):
            verify_guard_equivalence(reference, changed)
        with self.assertRaises(RouteContractError):
            float_bits(math.nan)

    def test_two_static_walk_edges_are_a_minimal_absolute_clock_counterexample(self):
        start, first, second = 600.0, 2 / 80, 4 / 80
        arrival = (start + first) + second
        remaining = first + second
        self.assertEqual(arrival, 600.0749999999999)
        self.assertEqual(start + remaining, 600.075)
        self.assertGreater(start + remaining, arrival)
        guard = TimeRoundingGuard(start_minute=start, deadline=840, max_forward_steps=2,
                                 max_reverse_steps=4, max_edge_minutes=second)
        self.assertLessEqual(guard(start, remaining), arrival)

    def test_reverse_addition_counterexample_and_every_small_walk_prefix(self):
        self.assertGreater(0.3 + (0.2 + 0.1), (0.3 + 0.2) + 0.1)
        checked = 0
        for start in (0.0, 600.0, math.nextafter(1024.0, -math.inf), 1439.0, 1e16):
            for weights in itertools.product((0.0, 0.0125, 0.025, 0.05, 0.1, 0.6), repeat=3):
                clocks = [start]
                for weight in weights:
                    clocks.append(clocks[-1] + weight)
                guard = TimeRoundingGuard(start_minute=start, deadline=start + 240,
                                         max_forward_steps=3, max_reverse_steps=4,
                                         max_edge_minutes=max(weights))
                for index, current in enumerate(clocks):
                    remaining = 0.0
                    for weight in reversed(weights[index:]):
                        remaining += weight
                    self.assertLessEqual(guard(current, remaining), clocks[-1])
                    checked += 1
        self.assertEqual(checked, 4320)

    def test_underdeclared_forward_step_count_cannot_prove_unconditional_safety(self):
        start, weights = 1e16, (0.6,) * 12
        arrival, remaining = start, 0.0
        for weight in weights:
            arrival += weight
        for weight in reversed(weights):
            remaining += weight
        args = dict(start_minute=start, deadline=start + 240,
                    max_reverse_steps=13, max_edge_minutes=0.6)
        underdeclared = TimeRoundingGuard(max_forward_steps=1, **args)
        self.assertGreater(underdeclared(start, remaining), arrival)
        report = verify_guard_coefficients(underdeclared, max_forward_steps=1, **args)
        self.assertFalse(report["unexpanded_suffix_step_bound_verified"])
        covered = TimeRoundingGuard(max_forward_steps=len(weights), **args)
        self.assertLessEqual(covered(start, remaining), arrival)

    def test_raw_mixed_run_occurrence_oracle_checks_every_completed_prefix_without_epsilon(self):
        checked, paths = 0, 0
        for offset in (0, 839):
            graph, choices, runs, rail_minima, bus_minima = _mixed_fixture(offset)
            target = ("virtual", "goal")
            virtual = {rail._physical("Z"): (0.0, 5.0),
                       bus._phys("D"): (0.0, 800.0),
                       rail._physical("C"): (0.0, 16000.0)}
            with (patch.object(TimetableChoices, "board_options", side_effect=AssertionError("old board")),
                  patch.object(TimetableChoices, "ride_options", side_effect=AssertionError("old ride")),
                  patch("toei_engine._tokyo_label_search", side_effect=AssertionError("search"))):
                projection = project_common_graph(graph, choices, rail_minima, bus_minima,
                                                 edge_uses_rail=lambda u, v: False)
                bounds = common_destination_bounds(projection, target, virtual)
                exact = _rational_distances(projection, target, virtual)
                for start in (offset + 598.0, math.nextafter(offset + 598.0, math.inf), offset + 599.0):
                    traces = _enumerate(graph, runs, rail._physical("A"), target, start, virtual,
                                        deadline=offset + 840.0, step_bound=24)
                    self.assertTrue(traces)
                    guard = TimeRoundingGuard(
                        start_minute=start, deadline=offset + 840.0, max_forward_steps=24,
                        max_reverse_steps=len(graph) + 1,
                        max_edge_minutes=bounds.report["max_edge_minutes"])
                    minima = {}
                    for trace in traces:
                        paths += 1
                        self.assertLessEqual(len(trace) - 1, 24)
                        for state in trace:
                            node, current, *_ = state
                            minima[state] = min(trace[-1][1], minima.get(state, trace[-1][1]))
                            self.assertLessEqual(guard(current, bounds(node)), trace[-1][1])
                            checked += 1
                    for state, earliest in minima.items():
                        self.assertLessEqual(guard(state[1], bounds(state[0])), earliest)
                    for node, rational_minimum in exact.items():
                        self.assertLessEqual(Fraction.from_float(bounds(node)), rational_minimum
                                             + Fraction.from_float(guard.report["reverse_error_minutes"]))
                    # Every board of the through bus at Q is forbidden, while
                    # the run may still pass Q after boarding at bus_C.
                    for trace in traces:
                        for state in trace:
                            if state[2] is not None and runs[state[2]][1] == "through":
                                self.assertNotEqual(state[4], 1)
        self.assertGreater(paths, 6)
        self.assertGreater(checked, 100)


if __name__ == "__main__":
    unittest.main()
