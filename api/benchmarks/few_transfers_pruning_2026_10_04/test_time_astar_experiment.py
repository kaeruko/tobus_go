"""Offline time-bound/cache contracts; production sources stay untouched."""

from __future__ import annotations

import contextlib
import hashlib
import io
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
API = HERE.parents[1]
sys.path.insert(0, str(API))
sys.path.insert(0, str(HERE))

import networkx as nx

from route_engine import RouteSearchLimitError
import tokyo_search_labels as labels
from tokyo_timetable_choices import TimetableChoices
from time_astar_bounds import make_time_bounds
from time_astar_experiment import make_search_variant
from time_board_cache import install_board_cache
from tests import test_tokyo_bus_choices_contract as bus
from tests import test_tokyo_bus_board_phase_regression as bus_phase
from tests import test_tokyo_waiting_contract as rail


VARIANTS = ("baseline", "cache", "astar", "combined")


def _unused_bus_repository():
    return bus._repository(("unrelated", "active", (("X", 600, 600), ("Y", 601, 601))))


def _rail_choices(graph, manager, *, realtime=False, deadline=838):
    return TimetableChoices(graph, manager, day_type="weekday", use_realtime=realtime,
                            deadline=deadline, bus_repository=_unused_bus_repository())


def _bound(graph, choices, target, virtual=None, *, blocked=lambda _u, _v: False,
           check_deadline=lambda: None):
    return make_time_bounds(graph, choices, target, virtual or {}, edge_uses_rail=blocked,
                            check_deadline=check_deadline)


def _legal_suffix_arrivals(origin, target, current, schedules, walks, *,
                           total_walk=0.0, segment_walk=0.0, deadline=838):
    """Independent physical-stop enumeration on a small forward-only network.

    Raw schedules are separate from the loader's stored records and the bound.
    Any later departure and any later stop on the same run may be selected.
    Every traversed rail leg pays preparation and alighting; walking enforces
    exact resources. No bound/boarding implementation participates here.
    """
    if origin == target:
        return [current]
    result = []
    for first, following, meters in walks:
        if first != origin or total_walk + meters > 3000 or segment_walk + meters > 600:
            continue
        arrival = current + meters / 80.0
        if arrival <= deadline:
            result.extend(_legal_suffix_arrivals(
                following, target, arrival, schedules, walks,
                total_walk=total_walk + meters, segment_walk=segment_walk + meters,
                deadline=deadline))
    for stops in schedules:
        for index, (station, departure) in enumerate(stops[:-1]):
            if station != origin or departure < current + 2:
                continue
            for following, arrival in stops[index + 1:]:
                arrival += 1
                if arrival <= deadline:
                    result.extend(_legal_suffix_arrivals(
                        following, target, arrival, schedules, walks,
                        total_walk=total_walk, segment_walk=0.0, deadline=deadline))
    return result


def _walk_search(graph, start, target, *, variant="astar", mode="time", start_minute=600,
                 reports=None, max_visited=100000):
    choices = SimpleNamespace(
        manager=SimpleNamespace(train_patterns_weekday={}, train_patterns_weekend={}),
        repository=None, use_realtime=False, can_wait_offboard=False,
        board_options=lambda _u, _v, _ready: (),
    )
    search = make_search_variant(variant, reports)
    return search(
        graph, choices, start, target, mode=mode, start_minute=start_minute,
        max_search=5, max_visited=max_visited, max_travel_min=240, time_limit_sec=15,
        max_total_walk=3000, max_segment_walk=600, walk_speed=80,
        rail_boarding_minutes=2,
        advance_time=lambda _u, _v, current, edge: current + edge.get("meters", 0) / 80,
        virtual_connections={}, edge_uses_rail=lambda _u, _v: False,
    )


class TimeLowerBoundTest(unittest.TestCase):
    def test_bound_is_admissible_for_independently_enumerated_legal_suffixes(self):
        schedules = (
            (("A", 600), ("B", 620), ("C", 630)),
            (("A", 602), ("B", 610), ("C", 615)),
            (("B", 622), ("C", 625)),
        )
        graph = rail._graph(("A", "B"), ("B", "C"))
        rail._walk(graph, rail._physical("A"), rail._physical("B"), 160)
        manager = rail._manager(*(rail._run(f"raw-{i}", stops)
                                  for i, stops in enumerate(schedules)))
        bound = _bound(graph, _rail_choices(graph, manager), rail._physical("C"))
        checked = 0
        for origin in ("A", "B", "C"):
            for ready in (598.0, 600.0, 603.0, 610.0, 613.0, 620.0):
                arrivals = _legal_suffix_arrivals(origin, "C", ready, schedules,
                                                   (("A", "B", 160),))
                for arrival in arrivals:
                    self.assertLessEqual(bound(rail._physical(origin)), arrival - ready + 1e-12)
                    checked += 1
        self.assertGreater(checked, 20)
        self.assertEqual(bound(rail._physical("C")), 0.0)

    def test_later_and_other_calendar_runs_supply_the_optimistic_rail_minimum(self):
        graph = rail._graph(("A", "B"))
        manager = rail._manager(
            rail._run("slow", (("A", 600), ("B", 620))),
            rail._run("later-fast", (("A", 601), ("B", 610))),
            rail._run("other-day", (("A", 700), ("B", 701)), calendar="SaturdayHoliday"),
        )
        bound = _bound(graph, _rail_choices(graph, manager), rail._physical("B"))
        self.assertAlmostEqual(bound(rail._physical("A")), 4.0)
        self.assertEqual(bound.report["known_ride_edges"], 1)

    def test_bus_adjacent_minimum_uses_departure_after_dwell_and_relaxes_services(self):
        graph = bus._graph(("A", "B"), ("B", "C"))
        repository = bus._repository(
            ("active", "active", (("A", 600, 600), ("B", 610, 615), ("C", 620, 620))),
            ("other-service", "inactive", (("A", 600, 600), ("B", 601, 602), ("C", 603, 603))),
        )
        choices, _ = bus._choices(graph, repository)
        bound = _bound(graph, choices, bus._phys("C"))
        self.assertAlmostEqual(bound(bus._line("B")), 1.0)
        self.assertAlmostEqual(bound(bus._phys("A")), 2.0)
        self.assertEqual(bound.report["known_ride_edges"], 2)

    def test_realtime_and_missing_intervals_use_zero_ride_bounds(self):
        graph = rail._graph(("A", "B"))
        manager = rail._manager(rail._run("train", (("A", 600), ("B", 610))))
        realtime = _bound(graph, _rail_choices(graph, manager, realtime=True), rail._physical("B"))
        self.assertEqual(realtime(rail._physical("A")), 3.0)
        self.assertEqual(realtime(rail._line("A")), 1.0)
        self.assertEqual(realtime.report["known_ride_edges"], 0)
        empty = _bound(graph, _rail_choices(graph, rail._manager()), rail._physical("B"))
        self.assertEqual(empty(rail._physical("A")), 3.0)

    def test_zero_intervals_and_unknown_edges_never_invent_elapsed_time(self):
        graph = rail._graph(("A", "B"))
        manager = rail._manager(rail._run("instant", (("A", 600), ("B", 600))))
        bound = _bound(graph, _rail_choices(graph, manager), rail._physical("B"))
        self.assertEqual(bound(rail._physical("A")), 3.0)
        unknown = nx.DiGraph()
        unknown.add_edge("start", "target", etype="unrecognized", w=999)
        choices = SimpleNamespace(manager=object(), repository=None, use_realtime=False)
        self.assertEqual(_bound(unknown, choices, "target")("start"), 0.0)

    def test_virtual_destination_filtering_and_zero_fallback(self):
        graph = rail._graph(("A", "B"))
        manager = rail._manager(rail._run("train", (("A", 600), ("B", 610))))
        target = ("phys", "dest:test")
        virtual = {rail._physical("B"): (9.0, 160.0)}
        bound = _bound(graph, _rail_choices(graph, manager), target, virtual)
        self.assertAlmostEqual(bound(rail._physical("A")), 15.0)
        self.assertEqual(bound(target), 0.0)
        self.assertEqual(bound(("phys", "unknown")), 0.0)
        blocked = _bound(graph, _rail_choices(graph, manager), target, virtual,
                         blocked=lambda _u, _v: True)
        self.assertEqual(blocked(rail._physical("A")), 0.0)
        self.assertEqual(blocked(rail._physical("B")), 2.0)

    def test_walk_fallback_and_graph_target_virtual_seed_both_match_forward(self):
        choices = SimpleNamespace(manager=object(), repository=None, use_realtime=False)
        for meters, expected in ((80.0, 1.0), (0.0, 1 / 80), (-2.0, 1 / 80)):
            with self.subTest(meters=meters):
                graph = nx.DiGraph()
                graph.add_edge("start", "target", etype="walk", meters=meters)
                self.assertEqual(_bound(graph, choices, "target")("start"), expected)
        graph = nx.DiGraph()
        graph.add_edge("start", "target", etype="walk", meters=800)
        self.assertEqual(_bound(graph, choices, "target", {"start": (1, 80)})("start"), 1)

    def test_deadline_callback_can_interrupt_builder_with_original_error(self):
        graph = nx.DiGraph()
        graph.add_edge("start", "target", etype="walk", meters=80)
        choices = SimpleNamespace(manager=object(), repository=None, use_realtime=False)
        error = RouteSearchLimitError("stop preprocessing", reason="time_limit_sec")
        with self.assertRaises(RouteSearchLimitError) as raised:
            _bound(graph, choices, "target", check_deadline=lambda: (_ for _ in ()).throw(error))
        self.assertIs(raised.exception, error)


class BoardingCacheTest(unittest.TestCase):
    def test_rail_out_of_order_readiness_keeps_options_and_selected_run_metadata(self):
        graph = rail._graph(("A", "B"), ("B", "C"))
        manager = rail._manager(
            rail._run("slow", (("A", 600), ("B", 620), ("C", 630))),
            rail._run("later", (("A", 601), ("B", 610), ("C", 615))),
            rail._run("outside", (("A", 640), ("B", 650))),
        )
        choices = _rail_choices(graph, manager, deadline=620)
        original = choices.board_options
        queries = (610.0, 600.0, 601.0, 598.0, 597.0, 620.0, 621.0)
        expected = {ready: original(rail._physical("A"), rail._line("A"), ready)
                    for ready in queries}
        report = install_board_cache(choices, 598)
        self.assertTrue(report["enabled"])
        for ready in queries:
            actual = choices.board_options(rail._physical("A"), rail._line("A"), ready)
            self.assertEqual(actual, expected[ready])
            self.assertEqual([choices.metadata(state) for _, state in actual],
                             [choices.metadata(state) for _, state in expected[ready]])
        later = choices.board_options(rail._physical("A"), rail._line("A"), 601)[0]
        arrival, state = choices.ride_options(rail._line("A"), rail._line("B"), *later)[0]
        arrival, state = choices.ride_options(rail._line("B"), rail._line("C"), arrival, state)[0]
        self.assertEqual(arrival, 615)
        self.assertEqual(state.train_number, "later")
        self.assertEqual(state.sequence, 2)
        self.assertEqual(report["keys"], 1)
        self.assertGreater(report["cache_hits"], 0)
        self.assertGreater(report["fallback_calls"], 0)

    def test_bus_out_of_order_loop_options_keep_stop_occurrences_and_deadline(self):
        graph = bus._graph(("A", "B"), ("B", "A"), ("A", "C"))
        repository = bus._repository(
            ("loop", "active", (("A", 1450, 1450), ("B", 1455, 1456),
                                  ("A", 1460, 1461), ("C", 1465, 1465))),
            ("after", "active", (("A", 1480, 1480), ("B", 1485, 1485))),
        )
        choices, _ = bus._choices(graph, repository, ready=1449, deadline=1470)
        original = choices.board_options
        queries = (1462, 1450, 1461, 1448, 1471, 1455)
        expected = {ready: original(bus._phys("A"), bus._line("A"), ready) for ready in queries}
        report = install_board_cache(choices, 1449)
        for ready in queries:
            self.assertEqual(choices.board_options(bus._phys("A"), bus._line("A"), ready), expected[ready])
        first = choices.board_options(bus._phys("A"), bus._line("A"), 1450)[0]
        arrival, state = choices.ride_options(bus._line("A"), bus._line("B"), *first)[0]
        arrival, state = choices.ride_options(bus._line("B"), bus._line("A"), arrival, state)[0]
        arrival, state = choices.ride_options(bus._line("A"), bus._line("C"), arrival, state)[0]
        self.assertEqual((arrival, state.board_sequence, state.sequence), (1465, 1, 4))
        self.assertEqual(state.trip_id, "loop")
        self.assertEqual(report["options_retained"], 2)

    def test_fractional_bus_delay_uses_original_scheduled_bisect_boundary(self):
        graph = bus._graph(("A", "B"))
        repository = bus._repository(("boundary", "active", (("A", 567, 567), ("B", 570, 570))))
        manager = rail.engine.TimetableManager()
        manager.bus_realtime_delays[bus.ROUTE] = 28.281880106322717
        choices, _ = bus._choices(graph, repository, manager=manager, ready=560,
                                  deadline=700, use_realtime=True)
        original = choices.board_options
        actual_clock = original(bus._phys("A"), bus._line("A"), 560)[0][0]
        ready = math.nextafter(actual_clock, math.inf)
        expected = original(bus._phys("A"), bus._line("A"), ready)
        self.assertEqual(len(expected), 1)
        report = install_board_cache(choices, 560)
        self.assertEqual(choices.board_options(bus._phys("A"), bus._line("A"), ready), expected)
        self.assertEqual(report["keys"], 1)

    def test_opaque_edge_and_unestablished_waiting_keep_original_behavior(self):
        graph = rail._graph(("A", "B"))
        choices = TimetableChoices(graph, object(), use_realtime=False, deadline=838)
        original = choices.board_options
        report = install_board_cache(choices, 598)
        self.assertFalse(report["enabled"])
        self.assertEqual(report["disabled_reason"], "waiting_not_established")
        self.assertEqual(choices.board_options, original)
        choices.can_wait_offboard = True
        expected = original(rail._physical("A"), rail._line("A"), 600)
        report = install_board_cache(choices, 598)
        self.assertEqual(choices.board_options(rail._physical("A"), rail._line("A"), 600), expected)
        self.assertEqual(report["keys"], 0)
        self.assertEqual(report["fallback_keys"], 1)
        self.assertEqual(expected[0][1].provider, "opaque-rail")

    def test_cache_miss_deadline_failure_propagates_without_installing_partial_key(self):
        graph = rail._graph(("A", "B"))
        choices = _rail_choices(graph, rail._manager(rail._run("train", (("A", 600), ("B", 610)))))
        error = RouteSearchLimitError("cache preparation exceeded deadline", reason="time_limit_sec")
        calls = []

        def checkpoint():
            calls.append(True)
            if len(calls) == 2:
                raise error

        report = install_board_cache(choices, 598, check_deadline=checkpoint)
        with self.assertRaises(RouteSearchLimitError) as raised:
            choices.board_options(rail._physical("A"), rail._line("A"), 600)
        self.assertIs(raised.exception, error)
        self.assertEqual(report["keys"], 0)


class TimeVariantContractTest(unittest.TestCase):
    def test_later_faster_run_remains_selected_for_every_variant(self):
        graph = rail._graph(("A", "B"))
        manager = rail._manager(
            rail._run("slow", (("A", 600), ("B", 620))),
            rail._run("fast", (("A", 601), ("B", 610))),
        )
        for variant in VARIANTS:
            reports = []
            with self.subTest(variant=variant), patch.object(labels, "search_labels", make_search_variant(variant, reports)), \
                    patch.object(rail.engine, "gtfs_repo", _unused_bus_repository()), \
                    contextlib.redirect_stdout(io.StringIO()):
                arrival, path = rail._fastest(graph, manager, target="B")
            self.assertEqual(arrival, 611)
            self.assertEqual(path.edge_rides[0].train_number, "fast")
            self.assertEqual(path.edge_rides[1].sequence, 1)
            self.assertEqual(path, [rail._physical("A"), rail._line("A"), rail._line("B"), rail._physical("B")])

    def test_loop_retains_the_actual_intermediate_stops_and_occurrences(self):
        graph = rail._graph(("X", "A"), ("A", "B"), ("B", "A"), ("A", "C"))
        manager = rail._manager(rail._run("loop", (("X", 595), ("A", 600), ("B", 605), ("A", 610), ("C", 615))))
        for variant in ("astar", "combined"):
            with self.subTest(variant=variant), patch.object(labels, "search_labels", make_search_variant(variant)), \
                    patch.object(rail.engine, "gtfs_repo", _unused_bus_repository()), \
                    contextlib.redirect_stdout(io.StringIO()):
                arrival, path = rail.engine.find_fastest_path(
                    graph, manager, rail._physical("X"), rail._physical("C"),
                    start_time_str="09:53", use_realtime=False)
            self.assertEqual(arrival, 616)
            self.assertEqual(path, [rail._physical("X"), rail._line("X"), rail._line("A"),
                                   rail._line("B"), rail._line("A"), rail._line("C"), rail._physical("C")])
            self.assertEqual([path.edge_rides[index].sequence for index in range(5)], [0, 1, 2, 3, 4])

    def test_first_goal_preserves_exact_arrival_before_display_ceiling(self):
        start, middle, target = ("phys", "start"), ("phys", "middle"), ("phys", "target")
        graph = nx.DiGraph()
        graph.add_edge(start, target, etype="walk", meters=17.0, w=1.0)
        graph.add_edge(start, middle, etype="walk", meters=8.0, w=10.0)
        graph.add_edge(middle, target, etype="walk", meters=8.0, w=10.0)
        self.assertEqual(math.ceil(600 + 17 / 80), math.ceil(600 + 16 / 80))
        for variant in VARIANTS:
            with self.subTest(variant=variant), contextlib.redirect_stdout(io.StringIO()):
                generator = _walk_search(graph, start, target, variant=variant)
                result = next(generator)
                generator.close()
            self.assertEqual(result["path"], [start, middle, target])
            self.assertEqual(result["path"].arrival_minute, 600.2)

    def test_other_objectives_never_build_time_bounds_or_board_cache(self):
        graph = nx.DiGraph()
        graph.add_edge("start", "target", etype="walk", meters=80, w=1)
        with patch("time_astar_bounds.make_time_bounds", side_effect=AssertionError("time bound outside time")), \
                patch("time_board_cache.install_board_cache", side_effect=AssertionError("time cache outside time")), \
                contextlib.redirect_stdout(io.StringIO()):
            for mode in ("cost", "fewTransfers"):
                expected = list(_walk_search(graph, "start", "target", variant="baseline", mode=mode))
                for variant in ("cache", "astar", "combined"):
                    actual = list(_walk_search(graph, "start", "target", variant=variant, mode=mode))
                    self.assertEqual(actual, expected)

    def test_preparation_counts_against_the_original_fifteen_second_limit(self):
        graph = nx.DiGraph()
        graph.add_edge("start", "target", etype="walk", meters=80, w=1)
        clock = {"now": 0.0}

        class FakeBound:
            report = {"nodes": 2, "max_edge_minutes": 1.0, "build_ms": 16000.0}

            def __call__(self, _node):
                return 0.0

        def expensive_builder(*_args, **_kwargs):
            clock["now"] = 16.0
            return FakeBound()

        with patch("time_astar_bounds.make_time_bounds", side_effect=expensive_builder), \
                patch.object(labels.time, "monotonic", side_effect=lambda: clock["now"]), \
                patch.object(labels.heapq, "heappop") as forward_pop, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RouteSearchLimitError, "time_limit_sec"):
                list(_walk_search(graph, "start", "target"))
        forward_pop.assert_not_called()

    def test_existing_waiting_bus_phase_and_run_contracts_pass_under_combined(self):
        suite = unittest.TestSuite()
        loader = unittest.TestLoader()
        for module in (rail, bus, bus_phase):
            suite.addTests(loader.loadTestsFromModule(module))
        captured = io.StringIO()
        with patch.object(labels, "search_labels", make_search_variant("combined")), \
                contextlib.redirect_stdout(captured):
            result = unittest.TextTestRunner(stream=captured, verbosity=1).run(suite)
        self.assertTrue(result.wasSuccessful(), captured.getvalue())
        self.assertGreaterEqual(result.testsRun, 28)

    def test_variants_do_not_write_production_sources(self):
        paths = [API / filename for filename in ("tokyo_search_labels.py", "tokyo_timetable_choices.py", "toei_engine.py")]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        graph = nx.DiGraph()
        graph.add_edge("start", "target", etype="walk", meters=80, w=1)
        with contextlib.redirect_stdout(io.StringIO()):
            for variant in VARIANTS:
                list(_walk_search(graph, "start", "target", variant=variant))
        self.assertEqual({path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
