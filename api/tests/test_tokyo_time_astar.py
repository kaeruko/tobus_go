"""Earliest-arrival A* keeps operational clocks and existing search contracts."""

import contextlib
import io
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import networkx as nx

import toei_engine as engine
import tokyo_search_labels as labels
from route_engine import RouteContractError, RouteSearchLimitError
from tokyo_time_bounds import make_time_bounds
from tokyo_timetable_choices import TimetableChoices
from tests import test_tokyo_bus_choices_contract as bus


class _ZeroTimeBound:
    report = {"build_ms": 0.0, "nodes": 0, "max_edge_minutes": 0.0}

    def __call__(self, node):
        return 0.0


def _phys(name):
    return ("phys", name)


def _walk(graph, first, following, minutes, cost=0.0):
    graph.add_edge(first, following, etype="walk", meters=minutes * 80.0, w=cost)


def _search(graph, start, target, *, mode="time", start_minute=600.0,
            virtual=None, max_segment_walk=600.0):
    manager = SimpleNamespace(train_patterns_weekday={}, train_patterns_weekend={},
                              bus_departures_weekday={})
    choices = TimetableChoices(graph, manager, use_realtime=False,
                               deadline=start_minute + 240)
    return labels.search_labels(
        graph, choices, start, target, mode=mode, start_minute=start_minute,
        max_search=1, max_visited=10000, max_expanded=10000,
        max_travel_min=240, time_limit_sec=15.0, max_total_walk=3000,
        max_segment_walk=max_segment_walk, walk_speed=80,
        rail_boarding_minutes=2,
        advance_time=lambda u, v, clock, edge: clock + (
            (edge.get("meters", 0.0) if edge.get("meters", 0.0) > 0 else 1.0)
            / 80.0 if edge.get("etype") == "walk" else 0.0),
        virtual_connections=virtual or {}, edge_uses_rail=lambda u, v: False,
    )


def _first(graph, start, target, **kwargs):
    generator = _search(graph, start, target, **kwargs)
    try:
        return next(generator, None)
    finally:
        generator.close()


class TokyoTimeAStarTest(unittest.TestCase):
    def test_time_alone_builds_elapsed_bound_with_the_query_deadline(self):
        graph = nx.DiGraph()
        start, target = _phys("start"), _phys("target")
        _walk(graph, start, target, 0.3)
        for mode in ("cost", "fewTransfers", "time"):
            with self.subTest(mode=mode), contextlib.redirect_stdout(io.StringIO()), \
                    patch.object(labels, "make_time_bounds", wraps=make_time_bounds) as builder:
                candidate = _first(graph, start, target, mode=mode)
                self.assertEqual(candidate["path"].arrival_minute, 600.3)
                if mode == "time":
                    builder.assert_called_once()
                    self.assertTrue(callable(builder.call_args.kwargs["check_deadline"]))
                else:
                    builder.assert_not_called()

    def test_preparation_is_charged_before_any_pop_and_propagates_original_limit(self):
        graph = nx.DiGraph()
        start, target = _phys("start"), _phys("target")
        _walk(graph, start, target, 1.0)
        clock = {"now": 0.0}

        def delayed_builder(*args, **kwargs):
            clock["now"] = 16.0
            kwargs["check_deadline"]()
            self.fail("The original safety exception must stop preparation")

        with patch.object(labels.time, "monotonic", side_effect=lambda: clock["now"]), \
                patch.object(labels, "make_time_bounds", side_effect=delayed_builder), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RouteSearchLimitError) as raised:
                _first(graph, start, target)
        self.assertEqual(raised.exception.reason, "time_limit_sec")
        self.assertEqual(raised.exception.diagnostics["visited"], 0)
        self.assertEqual(raised.exception.diagnostics["time_limit_sec"], 15.0)

    def test_preparation_cannot_return_after_the_deadline_without_a_recheck(self):
        graph = nx.DiGraph()
        start, target = _phys("start"), _phys("target")
        _walk(graph, start, target, 1.0)
        clock = {"now": 0.0}

        def delayed_builder(*args, **kwargs):
            clock["now"] = 16.0
            return _ZeroTimeBound()

        with patch.object(labels.time, "monotonic", side_effect=lambda: clock["now"]), \
                patch.object(labels, "make_time_bounds", side_effect=delayed_builder), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RouteSearchLimitError, "reason=time_limit_sec visited=0"):
                _first(graph, start, target)

    def test_invalid_bound_remains_a_contract_failure(self):
        graph = nx.DiGraph()
        start, target = _phys("start"), _phys("target")
        _walk(graph, start, target, 1.0)
        with patch.object(labels, "make_time_bounds", side_effect=ValueError("invalid data")), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RouteContractError, "time lower bound is invalid"):
                _first(graph, start, target)

    def test_first_goal_matches_forward_float_arrival_for_reordered_walks(self):
        # The same real duration can produce different binary64 operational
        # arrivals when added to a nonzero service clock in a different order.
        cases = (
            (600.0, [0.12, 0.34, 0.07, 0.02, 0.34, 0.07, 0.07, 0.01, 0.07]),
            (2.0**40, [0.6, 0.1, 0.6, 0.1, 0.6, 0.1, 0.6, 0.1]),
        )
        for start_minute, intervals in cases:
            graph = nx.DiGraph()
            start, target = _phys("start"), _phys("target")
            expected = []
            for branch, durations in enumerate((intervals, list(reversed(intervals)))):
                previous, arrival = start, start_minute
                for index, duration in enumerate(durations):
                    following = (target if index == len(durations) - 1 else
                                 _phys(f"branch-{branch}-{index}"))
                    _walk(graph, previous, following, duration)
                    arrival += graph[previous][following]["meters"] / 80.0
                    previous = following
                expected.append(arrival)
            with self.subTest(start=start_minute), contextlib.redirect_stdout(io.StringIO()):
                actual = _first(graph, start, target, start_minute=start_minute)
                with patch.object(labels, "make_time_bounds", return_value=_ZeroTimeBound()):
                    reference = _first(graph, start, target, start_minute=start_minute)
            self.assertEqual(actual["path"].arrival_minute, min(expected))
            self.assertEqual(actual["path"].arrival_minute, reference["path"].arrival_minute)

    def test_exact_arrival_precedes_display_minute_and_comfort_cost(self):
        graph = nx.DiGraph()
        start, early, late, target = map(_phys, ("start", "early", "late", "target"))
        _walk(graph, start, late, 0.4, cost=0)
        _walk(graph, late, target, 0.4, cost=0)
        _walk(graph, start, early, 0.1, cost=20)
        _walk(graph, early, target, 0.1, cost=20)
        with contextlib.redirect_stdout(io.StringIO()):
            candidate = _first(graph, start, target)
        self.assertEqual(candidate["path"], [start, early, target])
        self.assertAlmostEqual(candidate["path"].arrival_minute, 600.2)
        self.assertEqual(math.ceil(candidate["path"].arrival_minute), 601)
        self.assertEqual(math.ceil(600.8), 601)
        self.assertEqual(candidate["cost"], 40)

    def test_virtual_bound_does_not_relax_the_actual_600_meter_limit(self):
        graph = nx.DiGraph()
        start, first, second, merge, target = map(
            _phys, ("start", "first", "second", "merge", "virtual"))
        graph.add_edge(start, first, etype="approach", w=2)
        graph.add_edge(start, second, etype="approach", w=0)
        _walk(graph, first, merge, 576 / 80.0, cost=2)
        _walk(graph, second, merge, 599 / 80.0, cost=0)
        with contextlib.redirect_stdout(io.StringIO()):
            candidate = _first(graph, start, target, virtual={merge: (2.5, 24.0)})
        self.assertEqual(candidate["path"], [start, first, merge, target])
        self.assertEqual(candidate["walk_m"], 600.0)
        self.assertEqual(candidate["path"].arrival_minute, 607.5)
        self.assertNotIn(target, graph)

    def test_fractional_realtime_bus_delay_keeps_the_later_faster_concrete_trip(self):
        graph = bus._graph(("A", "B"))
        repository = bus._repository(
            ("slow", "active", (("A", 600, 600), ("B", 620, 620))),
            ("fast", "active", (("A", 601, 601), ("B", 610, 610))),
        )
        for delay in (0.3, -0.3, 28.281880106322717):
            manager = engine.TimetableManager()
            manager.bus_realtime_delays[bus.ROUTE] = delay
            with self.subTest(delay=delay), patch.object(engine, "gtfs_repo", repository), \
                    contextlib.redirect_stdout(io.StringIO()):
                arrival, path = engine.find_fastest_path(
                    graph, manager, bus._phys("A"), bus._phys("B"),
                    start_time_str="09:58", day_type=bus._day("active"), use_realtime=True)
                with patch.object(labels, "make_time_bounds", return_value=_ZeroTimeBound()):
                    reference, _ = engine.find_fastest_path(
                        graph, manager, bus._phys("A"), bus._phys("B"),
                        start_time_str="09:58", day_type=bus._day("active"), use_realtime=True)
            self.assertEqual(arrival, reference)
            self.assertTrue(all(state.trip_id == "fast" for state in path.edge_rides.values()))
            boarded = path.edge_rides[0]
            pinned_delay = boarded.departure_minute - 601.0
            self.assertEqual(arrival, 610.0 + pinned_delay)

    def test_unboarded_line_start_does_not_use_a_concrete_trip_bound(self):
        graph = bus._graph(("A", "B"), ("B", "C"))
        repository = bus._repository(
            ("slow", "active", (("A", 600, 600), ("B", 610, 610), ("C", 620, 620))),
        )
        for first, following in (("A", "B"), ("B", "C")):
            graph[bus._line(first)][bus._line(following)]["meters"] = 250.0
        _walk(graph, bus._line("A"), bus._phys("C"), 7.0)
        with patch.object(engine, "gtfs_repo", repository), contextlib.redirect_stdout(io.StringIO()):
            with patch.object(labels, "make_time_bounds", return_value=_ZeroTimeBound()):
                reference, _ = engine.find_fastest_path(
                    graph, engine.TimetableManager(), bus._line("A"), bus._phys("C"),
                    start_time_str="09:58", day_type=bus._day("active"), use_realtime=False)
            actual, path = engine.find_fastest_path(
                graph, engine.TimetableManager(), bus._line("A"), bus._phys("C"),
                start_time_str="09:58", day_type=bus._day("active"), use_realtime=False)
        self.assertEqual(actual, reference)
        self.assertLess(actual, 605.0)
        self.assertEqual(path.edge_rides, {})

    def test_nonboarding_entry_into_a_line_does_not_invent_a_run(self):
        graph = bus._graph(("A", "B"), ("B", "C"))
        repository = bus._repository(
            ("slow", "active", (("A", 600, 600), ("B", 610, 610), ("C", 620, 620))),
        )
        start = _phys("outside")
        graph.add_node(start, name="outside", lat=35.0, lon=139.0)
        graph.add_edge(start, bus._line("A"), etype="approach", w=0.0)
        for first, following in (("A", "B"), ("B", "C")):
            graph[bus._line(first)][bus._line(following)]["meters"] = 250.0
        _walk(graph, start, bus._phys("C"), 7.0)
        with patch.object(engine, "gtfs_repo", repository), contextlib.redirect_stdout(io.StringIO()):
            with patch.object(labels, "make_time_bounds", return_value=_ZeroTimeBound()):
                reference, _ = engine.find_fastest_path(
                    graph, engine.TimetableManager(), start, bus._phys("C"),
                    start_time_str="09:58", day_type=bus._day("active"), use_realtime=False)
            actual, path = engine.find_fastest_path(
                graph, engine.TimetableManager(), start, bus._phys("C"),
                start_time_str="09:58", day_type=bus._day("active"), use_realtime=False)
        self.assertEqual(actual, reference)
        self.assertLess(actual, 605.0)
        self.assertEqual(path.edge_rides, {})


if __name__ == "__main__":
    unittest.main()
