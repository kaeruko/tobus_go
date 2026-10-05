"""Tokyo elapsed bounds against independently enumerated legal continuations.

Fixtures use small ordinary ODPT/GTFS data.  The reference enumeration below
does not call the search, boarding choices, timetable interval index or bound.
"""

from __future__ import annotations

import math
import random
from types import SimpleNamespace
import unittest

import networkx as nx

from route_engine import RouteSearchLimitError
from tokyo_time_bounds import (
    invalidate_static_time_index,
    make_time_bounds,
    prepare_static_time_index,
)
from tokyo_timetable_choices import TimetableChoices
from tests import test_tokyo_bus_choices_contract as bus
from tests import test_tokyo_waiting_contract as rail


def _unused_repository():
    return bus._repository(("unrelated", "active", (("X", 600, 600), ("Y", 601, 601))))


def _rail_choices(graph, manager, *, realtime=False, deadline=838):
    return TimetableChoices(
        graph, manager, day_type="weekday", use_realtime=realtime,
        deadline=deadline, bus_repository=_unused_repository(),
    )


def _empty_choices(graph):
    return TimetableChoices(
        graph, rail.engine.TimetableManager(), use_realtime=False,
        bus_repository=_unused_repository(),
    )


def _bound(graph, choices, target, virtual=None, *,
           blocked=lambda _u, _v: False, check_deadline=lambda: None, **kwargs):
    return make_time_bounds(
        graph, choices, target, virtual or {}, edge_uses_rail=blocked,
        check_deadline=check_deadline, **kwargs,
    )


def _legal_suffix_arrivals(origin, target, current, schedules, walks=(), *,
                           total_walk=0.0, segment_walk=0.0, deadline=838):
    """Enumerate every legal suffix on these forward-only physical networks.

    Each schedule is (provider, ((stop, arrival, departure), ...)).  Waiting
    may select any future departure, and riding may alight at any later stop
    of that same run.  This explicitly preserves dwell and does not combine
    neighboring intervals from different vehicles.  Resources stay exact.
    """
    if origin == target:
        return [current]
    arrivals = []
    for first, following, meters in walks:
        if first != origin or total_walk + meters > 3000 or segment_walk + meters > 600:
            continue
        next_time = current + meters / 80.0
        if next_time <= deadline:
            arrivals.extend(_legal_suffix_arrivals(
                following, target, next_time, schedules, walks,
                total_walk=total_walk + meters, segment_walk=segment_walk + meters,
                deadline=deadline,
            ))
    for provider, stops in schedules:
        preparation = 2.0 if provider == "rail" else 0.0
        alighting = 1.0 if provider == "rail" else 0.0
        for index, (station, _arrival, departure) in enumerate(stops[:-1]):
            if station != origin or departure < current + preparation:
                continue
            for following, arrival, _departure in stops[index + 1:]:
                next_time = arrival + alighting
                if next_time <= deadline:
                    arrivals.extend(_legal_suffix_arrivals(
                        following, target, next_time, schedules, walks,
                        total_walk=total_walk, segment_walk=0.0, deadline=deadline,
                    ))
    return arrivals


def _exact_walk_suffixes(graph, node, target, *, total=0.0, segment=0.0):
    """Independent forward accumulation and exact resources on small DAGs."""
    if node == target:
        return [0.0]
    elapsed = []
    for following, edge in graph[node].items():
        meters = edge["meters"] if edge["meters"] > 0 else 1.0
        if total + meters > 3000 or segment + meters > 600:
            continue
        for rest in _exact_walk_suffixes(
                graph, following, target, total=total + meters, segment=segment + meters):
            elapsed.append(meters / 80.0 + rest)
    return elapsed


class TokyoTimeBoundsTest(unittest.TestCase):
    def test_admissible_against_every_independently_enumerated_rail_suffix(self):
        raw = (
            (("A", 600), ("B", 620), ("C", 630)),
            (("A", 602), ("B", 610), ("C", 615)),
            (("B", 622), ("C", 625)),
        )
        schedules = tuple(("rail", tuple((stop, clock, clock) for stop, clock in stops))
                          for stops in raw)
        graph = rail._graph(("A", "B"), ("B", "C"))
        rail._walk(graph, rail._physical("A"), rail._physical("B"), 160)
        manager = rail._manager(*(rail._run(f"raw-{i}", stops) for i, stops in enumerate(raw)))
        bound = _bound(graph, _rail_choices(graph, manager), rail._physical("C"))
        checked = 0
        for origin in ("A", "B", "C"):
            for ready in (598.0, 600.0, 603.0, 610.0, 613.0, 620.0):
                for total, segment in ((0.0, 0.0), (2300.0, 576.0), (2999.0, 599.0)):
                    arrivals = _legal_suffix_arrivals(
                        origin, "C", ready, schedules, (("A", "B", 160),),
                        total_walk=total, segment_walk=segment,
                    )
                    for arrival in arrivals:
                        self.assertLessEqual(bound(rail._physical(origin)), arrival - ready + 1e-12)
                        checked += 1
        self.assertGreater(checked, 60)
        self.assertEqual(bound(rail._physical("C")), 0.0)

    def test_admissible_against_bus_suffixes_with_dwell_and_later_fast_run(self):
        raw = (
            ("slow", "active", (("A", 600, 600), ("B", 610, 615), ("C", 620, 620))),
            ("later-fast", "active", (("A", 601, 601), ("B", 606, 607), ("C", 610, 610))),
        )
        graph = bus._graph(("A", "B"), ("B", "C"))
        choices, _ = bus._choices(graph, bus._repository(*raw))
        bound = _bound(graph, choices, bus._phys("C"))
        checked = 0
        for origin in ("A", "B", "C"):
            for ready in (598.0, 600.0, 601.0, 605.0, 610.0, 616.0):
                schedules = tuple(("bus", stops) for _identity, _service, stops in raw)
                for arrival in _legal_suffix_arrivals(origin, "C", ready, schedules):
                    self.assertLessEqual(bound(bus._phys(origin)), arrival - ready + 1e-12)
                    checked += 1
        self.assertGreater(checked, 10)

    def test_seeded_walk_dags_relax_exact_hard_resources(self):
        generator = random.Random(20261006)
        checked = 0
        for case in range(24):
            graph = nx.DiGraph()
            graph.add_nodes_from(range(7))
            for first in range(6):
                for following in range(first + 1, 7):
                    if following == first + 1 or generator.random() < 0.35:
                        graph.add_edge(first, following, etype="walk",
                                       meters=generator.choice((0.0, -2.0, 1.0, 24.0, 80.0, 576.0, 599.0)))
            bound = _bound(graph, _empty_choices(graph), 6)
            for origin in graph:
                for total, segment in ((0.0, 0.0), (2300.0, 576.0), (2999.0, 599.0)):
                    for actual in _exact_walk_suffixes(graph, origin, 6, total=total, segment=segment):
                        self.assertLessEqual(bound(origin), actual + 1e-12,
                                             f"case={case}, origin={origin}, total={total}, segment={segment}")
                        checked += 1
        self.assertGreater(checked, 100)

    def test_later_and_other_calendar_departures_supply_optimistic_rail_minimum(self):
        graph = rail._graph(("A", "B"))
        manager = rail._manager(
            rail._run("slow", (("A", 600), ("B", 620))),
            rail._run("later-fast", (("A", 601), ("B", 610))),
            rail._run("other-day", (("A", 700), ("B", 701)), calendar="SaturdayHoliday"),
        )
        bound = _bound(graph, _rail_choices(graph, manager), rail._physical("B"))
        self.assertAlmostEqual(bound(rail._physical("A")), 4.0)
        self.assertEqual(bound.report["known_ride_edges"], 1)

    def test_bus_adjacent_minimum_subtracts_departure_after_dwell_and_relaxes_service(self):
        graph = bus._graph(("A", "B"), ("B", "C"))
        repository = bus._repository(
            ("active", "active", (("A", 600, 600), ("B", 610, 615), ("C", 620, 620))),
            ("other", "inactive", (("A", 600, 600), ("B", 601, 602), ("C", 603, 603))),
        )
        choices, _ = bus._choices(graph, repository)
        bound = _bound(graph, choices, bus._phys("C"))
        self.assertAlmostEqual(bound(bus._line("B")), 1.0)
        self.assertAlmostEqual(bound(bus._phys("A")), 2.0)
        self.assertEqual(bound.report["known_ride_edges"], 2)

    def test_bus_loop_occurrences_and_sequence_gaps_do_not_create_nonadjacent_minima(self):
        graph = bus._graph(("A", "B"), ("B", "A"), ("A", "C"))
        repository = bus._repository(
            ("loop", "active", (("A", 1450, 1450), ("B", 1455, 1456),
                                   ("A", 1460, 1461), ("C", 1465, 1465))),
        )
        sequence_map = dict(zip((1, 2, 3, 4), (1, 7, 11, 15)))
        repository.stop_times["loop"] = {
            sequence_map[sequence]: stop
            for sequence, stop in repository.stop_times["loop"].items()
        }
        for key, entries in repository.timetable_index.items():
            repository.timetable_index[key] = [
                (departure, sequence_map[sequence], trip_id)
                for departure, sequence, trip_id in entries
            ]
        choices, options = bus._choices(graph, repository, ready=1449, deadline=1470)
        bound = _bound(graph, choices, bus._phys("C"))
        arrival, state = options[0]
        for first, following in (("A", "B"), ("B", "A"), ("A", "C")):
            self.assertLessEqual(bound(bus._line(first)), 1465 - arrival + 1e-12)
            arrival, state = choices.ride_options(bus._line(first), bus._line(following), arrival, state)[0]
        self.assertEqual((arrival, state.sequence), (1465, 15))
        self.assertAlmostEqual(bound(bus._line("B")), 8.0)

    def test_realtime_uses_static_intervals_from_same_uniformly_shifted_run(self):
        graph = rail._graph(("A", "B"))
        manager = rail._manager(rail._run("train", (("A", 600), ("B", 610))))
        manager.realtime_delays["train"] = 180
        choices = _rail_choices(graph, manager, realtime=True)
        bound = _bound(graph, choices, rail._physical("B"))
        self.assertAlmostEqual(bound(rail._physical("A")), 13.0)
        self.assertAlmostEqual(bound(rail._line("A")), 11.0)
        self.assertEqual(bound.report["known_ride_edges"], 1)
        departure, state = choices.board_options(rail._physical("A"), rail._line("A"), 602)[0]
        arrival, _ = choices.ride_options(rail._line("A"), rail._line("B"), departure, state)[0]
        self.assertEqual((departure, arrival), (603, 613))
        self.assertLessEqual(bound(rail._line("A")), arrival + 1 - departure)

    def test_empty_concrete_and_opaque_timelines_do_not_invent_ride_duration(self):
        graph = rail._graph(("A", "B"))
        bound = _bound(graph, _rail_choices(graph, rail._manager()), rail._physical("B"))
        self.assertEqual(bound(rail._physical("A")), 3.0)
        self.assertEqual(bound.report["known_ride_edges"], 0)
        for choices in (TimetableChoices(graph, object(), use_realtime=False),
                        SimpleNamespace(manager=object(), repository=None, use_realtime=False)):
            with self.subTest(choices=type(choices).__name__):
                opaque = _bound(graph, choices, rail._physical("B"))
                self.assertEqual(opaque(rail._physical("A")), 0.0)
                self.assertEqual(opaque(rail._line("A")), 0.0)

    def test_zero_duration_and_unknown_edges_are_optimistic(self):
        graph = rail._graph(("A", "B"))
        manager = rail._manager(rail._run("instant", (("A", 600), ("B", 600))))
        bound = _bound(graph, _rail_choices(graph, manager), rail._physical("B"))
        self.assertEqual(bound(rail._physical("A")), 3.0)
        unknown = nx.DiGraph()
        unknown.add_edge("start", "target", etype="unknown", w=10000)
        self.assertEqual(_bound(unknown, _empty_choices(unknown), "target")("start"), 0.0)

    def test_overridden_choices_are_not_assumed_to_have_standard_elapsed_transitions(self):
        graph = nx.DiGraph()
        graph.add_edge("start", "target", etype="walk", meters=800)
        for method in ("board_options", "ride_options"):
            with self.subTest(method=method):
                choices = _empty_choices(graph)
                setattr(choices, method, lambda *_args: ())
                bound = _bound(graph, choices, "target")
                self.assertEqual(bound("start"), 0.0)

    def test_line_with_opaque_bus_boarding_cannot_use_concrete_trip_interval(self):
        graph = bus._graph(("A", "B"))
        unmapped = bus._phys("unmapped")
        graph.add_node(unmapped, name="unmapped")
        graph.add_edge(unmapped, bus._line("A"), etype="board", w=1.0)
        repository = bus._repository(("concrete", "active", (("A", 600, 600), ("B", 610, 610))))
        manager = rail.engine.TimetableManager()
        manager.get_next_bus_departure = lambda *_args, **_kwargs: (600.0, "opaque-fixture")
        choices, _ = bus._choices(graph, repository, manager=manager)
        departure, state = choices.board_options(unmapped, bus._line("A"), 598)[0]
        self.assertEqual(state.provider, "opaque-bus")
        arrival, _ = choices.ride_options(bus._line("A"), bus._line("B"), departure, state)[0]
        bound = _bound(graph, choices, bus._phys("B"))
        self.assertEqual(bound(bus._line("A")), 0.0)
        self.assertLessEqual(bound(bus._line("A")), arrival - departure)

    def test_prepared_indexes_are_reused_by_frozen_choices_and_new_queries(self):
        graph = rail._graph(("A", "B"))
        manager = rail._manager(rail._run("train", (("A", 600), ("B", 610))))
        repository = _unused_repository()
        prepare_static_time_index(manager, repository)
        for _query in range(2):
            choices = TimetableChoices(graph, manager, use_realtime=False, bus_repository=repository)
            bound = _bound(graph, choices, rail._physical("B"))
            self.assertAlmostEqual(bound(rail._physical("A")), 13.0)
            self.assertTrue(bound.report["rail_index_reused"])
            self.assertTrue(bound.report["bus_index_reused"])
            self.assertEqual(bound.report["rail_records_scanned"], 0)
            self.assertEqual(bound.report["bus_trips_scanned"], 0)
            self.assertEqual(bound.report["bus_stops_scanned"], 0)

    def test_replacing_rail_source_tables_invalidates_prepared_minima(self):
        graph = rail._graph(("A", "B"))
        manager = rail._manager(rail._run("train", (("A", 600), ("B", 610))))
        repository = _unused_repository()
        prepare_static_time_index(manager, repository)
        replacement = rail._manager(rail._run("replacement", (("A", 600), ("B", 601))))
        manager.train_patterns_weekday = replacement.train_patterns_weekday
        manager.train_patterns_weekend = replacement.train_patterns_weekend
        choices = TimetableChoices(graph, manager, use_realtime=False, bus_repository=repository)
        bound = _bound(graph, choices, rail._physical("B"))
        self.assertAlmostEqual(bound(rail._physical("A")), 4.0)
        self.assertFalse(bound.report["rail_index_reused"])
        self.assertGreater(bound.report["rail_records_scanned"], 0)

    def test_replacing_bus_source_containers_invalidates_prepared_minima(self):
        graph = bus._graph(("A", "B"))
        manager = rail.engine.TimetableManager()
        repository = bus._repository(("old", "active", (("A", 600, 600), ("B", 610, 610))))
        prepare_static_time_index(manager, repository)
        replacement = bus._repository(("new", "active", (("A", 600, 600), ("B", 601, 601))))
        repository.trips = replacement.trips
        repository.stop_times = replacement.stop_times
        repository.timetable_index = replacement.timetable_index
        choices, _ = bus._choices(graph, repository, manager=manager)
        bound = _bound(graph, choices, bus._phys("B"))
        self.assertAlmostEqual(bound(bus._phys("A")), 1.0)
        self.assertFalse(bound.report["bus_index_reused"])
        self.assertGreater(bound.report["bus_trips_scanned"], 0)

    def test_explicit_invalidation_refreshes_same_size_in_place_rail_edit(self):
        graph = rail._graph(("A", "B"))
        manager = rail._manager(rail._run("train", (("A", 600), ("B", 610))))
        repository = _unused_repository()
        prepare_static_time_index(manager, repository)
        manager.train_patterns_weekday[rail._station("A")][0]["arr"] = 601
        invalidate_static_time_index(manager=manager)
        choices = TimetableChoices(graph, manager, use_realtime=False, bus_repository=repository)
        bound = _bound(graph, choices, rail._physical("B"))
        self.assertAlmostEqual(bound(rail._physical("A")), 4.0)
        self.assertFalse(bound.report["rail_index_reused"])
        self.assertGreater(bound.report["rail_records_scanned"], 0)

    def test_explicit_invalidation_refreshes_same_size_in_place_bus_edit(self):
        graph = bus._graph(("A", "B"))
        manager = rail.engine.TimetableManager()
        repository = bus._repository(("trip", "active", (("A", 600, 600), ("B", 610, 610))))
        prepare_static_time_index(manager, repository)
        repository.stop_times["trip"][2] = ("B", 601, 601)
        invalidate_static_time_index(repository=repository)
        choices, _ = bus._choices(graph, repository, manager=manager)
        bound = _bound(graph, choices, bus._phys("B"))
        self.assertAlmostEqual(bound(bus._phys("A")), 1.0)
        self.assertFalse(bound.report["bus_index_reused"])
        self.assertGreater(bound.report["bus_trips_scanned"], 0)

    def test_interrupted_index_preparation_does_not_publish_partial_reusable_state(self):
        manager = rail._manager(rail._run("train", (("A", 600), ("B", 610))))
        repository = _unused_repository()
        expected = RouteSearchLimitError("index deadline", reason="time_limit_sec")
        calls = []

        def check():
            calls.append(True)
            if len(calls) == 3:
                raise expected

        with self.assertRaises(RouteSearchLimitError) as raised:
            prepare_static_time_index(manager, repository, check_deadline=check)
        self.assertIs(raised.exception, expected)
        completed = prepare_static_time_index(manager, repository)
        self.assertFalse(completed["rail_index_reused"])
        self.assertFalse(completed["bus_index_reused"])
        self.assertGreater(completed["rail_records_scanned"], 0)
        self.assertGreater(completed["bus_trips_scanned"], 0)

    def test_virtual_destination_walk_and_bus_only_filter(self):
        graph = rail._graph(("A", "B"))
        manager = rail._manager(rail._run("train", (("A", 600), ("B", 610))))
        target = ("phys", "dest:test")
        virtual = {rail._physical("B"): (9.0, 160.0)}
        bound = _bound(graph, _rail_choices(graph, manager), target, virtual)
        self.assertAlmostEqual(bound(rail._physical("A")), 15.0)
        self.assertEqual(bound(target), 0.0)
        blocked = _bound(graph, _rail_choices(graph, manager), target, virtual,
                         blocked=lambda _u, _v: True)
        self.assertEqual(blocked(rail._physical("A")), 0.0)
        self.assertEqual(blocked(rail._physical("B")), 2.0)

    def test_existing_graph_target_and_virtual_shortcut_both_seed_reverse_search(self):
        graph = nx.DiGraph()
        graph.add_edge("start", "target", etype="walk", meters=800)
        bound = _bound(graph, _empty_choices(graph), "target", {"start": (0.0, 80.0)})
        self.assertEqual(bound("start"), 1.0)
        self.assertEqual(bound("target"), 0.0)

    def test_unreachable_unknown_and_missing_virtual_nodes_return_zero(self):
        graph = nx.DiGraph()
        graph.add_node("unreachable")
        graph.add_edge("start", "target", etype="walk", meters=80)
        bound = _bound(graph, _empty_choices(graph), "target", {"missing": (0.0, 80.0)})
        self.assertEqual(bound("unreachable"), 0.0)
        self.assertEqual(bound(("unknown", 42)), 0.0)
        self.assertEqual(bound("missing"), 0.0)
        self.assertEqual(bound.report["missing_virtual_nodes"], 1)

    def test_nonpositive_walk_fallback_and_mixed_node_types(self):
        for meters, expected in ((80.0, 1.0), (0.0, 1 / 80), (-2.0, 1 / 80)):
            with self.subTest(meters=meters):
                graph = nx.DiGraph()
                graph.add_edge(1, ("target", 2), etype="walk", meters=meters)
                graph.add_edge("same-priority", ("target", 2), etype="walk", meters=meters)
                bound = _bound(graph, _empty_choices(graph), ("target", 2))
                self.assertEqual(bound(1), expected)
                self.assertEqual(bound("same-priority"), expected)

    def test_nonfinite_walking_inputs_and_invalid_configuration_are_rejected(self):
        graph = nx.DiGraph()
        graph.add_edge("start", "target", etype="walk", meters=80)
        for bad in (math.nan, math.inf, -math.inf):
            with self.subTest(value=bad, field="meters"):
                graph["start"]["target"]["meters"] = bad
                with self.assertRaises(ValueError):
                    _bound(graph, _empty_choices(graph), "target")
        graph["start"]["target"]["meters"] = 80
        for bad in (0.0, -1.0, math.nan, math.inf):
            with self.subTest(value=bad, field="walk_speed"), self.assertRaises(ValueError):
                _bound(graph, _empty_choices(graph), "target", walk_speed=bad)
        for bad in (-1.0, math.nan, math.inf):
            with self.subTest(value=bad, field="rail_boarding_minutes"), self.assertRaises(ValueError):
                _bound(graph, _empty_choices(graph), "target", rail_boarding_minutes=bad)

    def test_invalid_virtual_cost_or_distance_is_rejected(self):
        graph = nx.DiGraph()
        graph.add_node("start")
        for bad in (-1.0, math.nan, math.inf):
            for virtual in ({"start": (bad, 80.0)}, {"start": (0.0, bad)}):
                with self.subTest(virtual=virtual), self.assertRaises(ValueError):
                    _bound(graph, _empty_choices(graph), "target", virtual)

    def test_preparation_deadline_exception_is_preserved_and_can_interrupt_scan(self):
        graph = nx.DiGraph()
        for first in range(4096):
            graph.add_edge(first, first + 1, etype="walk", meters=1)
        expected = RouteSearchLimitError("time bound deadline", reason="time_limit_sec")
        visited_edges = []

        def blocked(first, following):
            visited_edges.append((first, following))
            return False

        def check():
            if len(visited_edges) >= 1024:
                raise expected

        with self.assertRaises(RouteSearchLimitError) as raised:
            _bound(graph, _empty_choices(graph), 4096, blocked=blocked, check_deadline=check)
        self.assertIs(raised.exception, expected)
        self.assertGreaterEqual(len(visited_edges), 1024)
        self.assertLess(len(visited_edges), len(graph.edges))


if __name__ == "__main__":
    unittest.main()
