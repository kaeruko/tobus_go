"""Query-local reuse must preserve exact concrete choices and opaque behavior."""

from dataclasses import asdict
import unittest
from unittest.mock import patch

import networkx as nx

import toei_engine as engine
import tokyo_timetable_choices as choices_module
from gtfs_loader import GtfsRepository
from tokyo_timetable_choices import TimetableChoices
from tests.test_tokyo_bus_choices_contract import (
    LINE, ROUTE, _day, _graph as _bus_graph, _line as _bus_line,
    _phys as _bus_phys, _repository,
)
from tests.test_tokyo_bus_circular_pattern import (
    LINE as CIRCULAR_LINE, POLES, _fixture as _circular_fixture,
)
from tests.test_tokyo_waiting_contract import (
    _graph as _rail_graph, _line as _rail_line,
    _manager as _rail_manager, _physical as _rail_phys, _run,
)
from tests.test_tokyo_zero_ride_boarding import MODES, _search


def _fixture(provider, *, choices_class=TimetableChoices):
    if provider == "bus":
        graph = _bus_graph(("A", "B"), ("B", "C"))
        manager = engine.TimetableManager()
        repository = _repository(
            ("slow", "active", (("A", 600, 600), ("B", 610, 610), ("C", 620, 620))),
            ("fast", "active", (("A", 605, 605), ("B", 608, 608), ("C", 611, 611))),
            ("inactive", "inactive", (("A", 601, 601), ("B", 606, 606), ("C", 612, 612))),
        )
        day, physical, line = _day("active"), _bus_phys, _bus_line
    else:
        graph = _rail_graph(("A", "B"), ("B", "C"))
        manager = _rail_manager(
            _run("slow", (("A", 600), ("B", 610), ("C", 620))),
            _run("fast", (("A", 605), ("B", 608), ("C", 611))),
        )
        repository = GtfsRepository("tokyo-test")
        day, physical, line = "weekday", _rail_phys, _rail_line
    choices = choices_class(graph, manager, day, use_realtime=False,
                            deadline=630, bus_repository=repository)
    return graph, manager, repository, choices, physical, line


def _identities(options):
    return [(clock, state.trip_id or state.train_number) for clock, state in options]


def _snapshot(candidates):
    return [{"cost": candidate["cost"], "walk_m": candidate["walk_m"],
             "nodes": list(candidate["path"]), "clocks": candidate["path"].edge_times,
             "arrival": candidate["path"].arrival_minute,
             "selected_states": {index: asdict(state)
                                 for index, state in candidate["path"].edge_rides.items()}}
            for candidate in candidates]


class _UncachedChoices(TimetableChoices):
    def _cached_concrete_board_options(self, u, v, ready, evaluate):
        return evaluate(u, v, ready)

    def _compatible_bus_boarding(self, u, v, trip_id, sequence, terminal):
        # Re-evaluate the complete compatibility predicate on every call. This
        # is the cache-free oracle used by the all-mode path comparison below.
        saved = self._bus_boarding_compatibility
        self._bus_boarding_compatibility = {}
        try:
            return super()._compatible_bus_boarding(
                u, v, trip_id, sequence, terminal
            )
        finally:
            self._bus_boarding_compatibility = saved

    def _bus_option_stream(self, u, v):
        saved = self._bus_option_streams
        self._bus_option_streams = {}
        try:
            return super()._bus_option_stream(u, v)
        finally:
            self._bus_option_streams = saved


class TokyoTimetableChoiceCacheTest(unittest.TestCase):
    def test_repeated_inputs_keep_order_exact_readiness_and_empty_results(self):
        for provider in ("bus", "rail"):
            _, _, _, choices, physical, line = _fixture(provider)
            method = "_bus_options" if provider == "bus" else "_rail_options"
            with self.subTest(provider=provider), \
                    patch.object(choices, method, wraps=getattr(choices, method)) as evaluate:
                first = choices.board_options(physical("A"), line("A"), 599)
                self.assertEqual(_identities(first), [(600.0, "slow"), (605.0, "fast")])
                self.assertIs(choices.board_options(physical("A"), line("A"), 599), first)
                self.assertEqual(evaluate.call_count, 1)
                # Exact departure remains boardable; any later float does not.
                self.assertEqual(_identities(choices.board_options(physical("A"), line("A"), 600)),
                                 [(600.0, "slow"), (605.0, "fast")])
                self.assertEqual(_identities(choices.board_options(physical("A"), line("A"), 600.000001)),
                                 [(605.0, "fast")])
                self.assertEqual(choices.board_options(physical("A"), line("A"), 606), ())
                self.assertEqual(choices.board_options(physical("A"), line("A"), 606), ())
                self.assertEqual(evaluate.call_count, 4)

    def test_ride_continuation_does_not_mutate_shared_boarding_state(self):
        for provider in ("bus", "rail"):
            _, _, _, choices, physical, line = _fixture(provider)
            with self.subTest(provider=provider):
                options = choices.board_options(physical("A"), line("A"), 599)
                before = [(clock, asdict(state)) for clock, state in options]
                clock, state = options[1]
                arrival, moved = choices.ride_options(line("A"), line("B"), clock, state)[0]
                self.assertEqual(arrival, 608)
                self.assertNotEqual(moved.sequence, state.sequence)
                self.assertEqual(moved.board_sequence, state.board_sequence)
                self.assertEqual(moved.run_id, state.run_id)
                self.assertEqual(choices.metadata(moved)["actual_arrival_minute"], 608)
                cached = choices.board_options(physical("A"), line("A"), 599)
                self.assertIs(cached, options)
                self.assertEqual([(time, asdict(ride)) for time, ride in cached], before)

    def test_patterns_and_repeated_stop_occurrences_have_distinct_choices(self):
        short, through = "buspat:short", "buspat:through"
        graph = nx.compose(_bus_graph(("A", "B"), line=short),
                           _bus_graph(("A", "B"), ("B", "C"), line=through))
        repository = _repository(
            ("short", "active", (("A", 600, 600), ("B", 610, 610))),
            ("through", "active", (("A", 600, 600), ("B", 605, 605), ("C", 610, 610))),
        )
        choices = TimetableChoices(graph, engine.TimetableManager(), _day("active"),
                                   use_realtime=False, deadline=630, bus_repository=repository)
        self.assertEqual(_identities(choices.board_options(_bus_phys("A"), _bus_line("A", short), 599)),
                         [(600.0, "short")])
        self.assertEqual(_identities(choices.board_options(_bus_phys("A"), _bus_line("A", through), 599)),
                         [(600.0, "through")])
        _, _, _, circular = _circular_fixture()
        start = circular.board_options(_bus_phys(POLES[0]), _bus_line(POLES[0], CIRCULAR_LINE), 598)
        midpoint = circular.board_options(_bus_phys(POLES[1]), _bus_line(POLES[1], CIRCULAR_LINE), 598)
        self.assertEqual((start[0][0], start[0][1].sequence), (600, 1))
        self.assertEqual((midpoint[0][0], midpoint[0][1].sequence), (605, 2))
        self.assertEqual(circular.board_options(
            _bus_phys(POLES[0]), _bus_line(POLES[0], CIRCULAR_LINE), 620), ())

    def test_new_query_rechecks_realtime_service_day_and_deadline(self):
        graph, manager, repository, _, physical, line = _fixture("bus")
        manager.bus_realtime_delays[ROUTE] = 3.0
        frozen = TimetableChoices(graph, manager, _day("active"), use_realtime=True,
                                  deadline=630, bus_repository=repository)
        original = frozen.board_options(physical("A"), line("A"), 599)
        self.assertEqual(_identities(original), [(603.0, "slow"), (608.0, "fast")])
        manager.bus_realtime_delays[ROUTE] = 10.0
        self.assertIs(frozen.board_options(physical("A"), line("A"), 599), original)
        refreshed = TimetableChoices(graph, manager, _day("active"), use_realtime=True,
                                     deadline=610, bus_repository=repository)
        self.assertEqual(_identities(refreshed.board_options(physical("A"), line("A"), 599)),
                         [(610.0, "slow")])
        different_calendar = TimetableChoices(graph, manager, _day("inactive"),
                                              use_realtime=False, deadline=630,
                                              bus_repository=repository)
        self.assertEqual(_identities(different_calendar.board_options(physical("A"), line("A"), 599)),
                         [(601.0, "inactive")])

    def test_concrete_evaluation_errors_are_propagated_and_not_cached(self):
        for provider in ("bus", "rail"):
            _, _, _, choices, physical, line = _fixture(provider)
            method = "_bus_options" if provider == "bus" else "_rail_options"
            with self.subTest(provider=provider), \
                    patch.object(choices, method, side_effect=RuntimeError("invalid timetable")) as evaluate:
                for _ in range(2):
                    with self.assertRaisesRegex(RuntimeError, "invalid timetable"):
                        choices.board_options(physical("A"), line("A"), 599)
                self.assertEqual(evaluate.call_count, 2)
            self.assertEqual(_identities(choices.board_options(physical("A"), line("A"), 599)),
                             [(600.0, "slow"), (605.0, "fast")])

    def test_bus_pattern_compatibility_is_reused_across_readiness_windows(self):
        _, _, _, choices, physical, line = _fixture("bus")
        with patch.object(
            choices,
            "_compatible_bus_boarding",
            wraps=choices._compatible_bus_boarding,
        ) as compatibility:
            self.assertEqual(
                _identities(choices.board_options(physical("A"), line("A"), 599)),
                [(600.0, "slow"), (605.0, "fast")],
            )
            first_calls = compatibility.call_count
            # The timetable index also contains one inactive-service row. It
            # is rejected by compatibility and that rejection is reusable.
            self.assertEqual(first_calls, 3)
            self.assertEqual(
                _identities(choices.board_options(physical("A"), line("A"), 600)),
                [(600.0, "slow"), (605.0, "fast")],
            )
            self.assertEqual(
                _identities(choices.board_options(physical("A"), line("A"), 600.000001)),
                [(605.0, "fast")],
            )
            # Later readiness windows bisect the already validated active-day
            # stream.  They do not rescan timetable rows or recheck patterns.
            self.assertEqual(compatibility.call_count, first_calls)
            self.assertEqual(len(choices._bus_boarding_compatibility), 3)

    def test_time_skyline_removes_only_strictly_worse_later_bus(self):
        graph = _bus_graph(("A", "B"), ("B", "C"))
        repository = _repository(
            ("first", "active", (("A", 600, 600), ("B", 610, 610), ("C", 620, 620))),
            ("strictly-worse", "active", (("A", 602, 602), ("B", 612, 612), ("C", 622, 622))),
            # Equality at B keeps the concrete identity available for a B goal.
            ("equal-at-b", "active", (("A", 603, 603), ("B", 610, 610), ("C", 623, 623))),
            # A later express is not removed by an earlier, slower occurrence.
            ("overtaking", "active", (("A", 605, 605), ("B", 608, 608), ("C", 611, 611))),
        )
        choices = TimetableChoices(
            graph, engine.TimetableManager(), _day("active"),
            use_realtime=False, deadline=630, bus_repository=repository,
        )

        ordinary = choices.board_options(_bus_phys("A"), _bus_line("A"), 599)
        self.assertEqual(
            _identities(ordinary),
            [(600.0, "first"), (602.0, "strictly-worse"),
             (603.0, "equal-at-b"), (605.0, "overtaking")],
        )
        choices.search_mode = "time"
        self.assertEqual(
            _identities(choices.board_options(_bus_phys("A"), _bus_line("A"), 599)),
            [(600.0, "first"), (603.0, "equal-at-b"), (605.0, "overtaking")],
        )
        # Once the dominating first trip is no longer boardable, the later
        # trip remains.  Readiness is never rounded or bucketed.
        self.assertEqual(
            _identities(choices.board_options(_bus_phys("A"), _bus_line("A"), 600.000001)),
            [(602.0, "strictly-worse"), (603.0, "equal-at-b"),
             (605.0, "overtaking")],
        )

    def test_time_skyline_never_changes_few_transfer_choices(self):
        _, _, _, choices, physical, line = _fixture("bus")
        choices.search_mode = "fewTransfers"
        self.assertEqual(
            _identities(choices.board_options(physical("A"), line("A"), 599)),
            [(600.0, "slow"), (605.0, "fast")],
        )

    def test_bus_compatibility_errors_are_not_cached(self):
        _, _, repository, choices, physical, line = _fixture("bus")
        original = repository.get_stop_time_boarding

        def malformed_once(trip_id, sequence):
            if trip_id == "slow":
                raise ValueError("malformed boarding flags")
            return original(trip_id, sequence)

        with patch.object(
            repository, "get_stop_time_boarding", side_effect=malformed_once
        ) as boarding:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "malformed boarding flags"):
                    choices.board_options(physical("A"), line("A"), 599)
            self.assertEqual(boarding.call_count, 2)
            self.assertNotIn(
                (physical("A"), line("A"), "slow", 1),
                choices._bus_boarding_compatibility,
            )

        self.assertEqual(
            _identities(choices.board_options(physical("A"), line("A"), 599)),
            [(600.0, "slow"), (605.0, "fast")],
        )

    def test_query_floor_does_not_validate_unreachable_past_occurrences(self):
        graph, _, repository, _, physical, line = _fixture("bus")
        choices = TimetableChoices(
            graph, engine.TimetableManager(), _day("active"),
            use_realtime=False, deadline=630, bus_repository=repository,
            search_mode="time", earliest_ready_minute=604,
        )
        original = repository.get_stop_time_boarding

        def reject_past(trip_id, sequence):
            if trip_id == "slow":
                raise AssertionError("past occurrence was evaluated")
            return original(trip_id, sequence)

        with patch.object(repository, "get_stop_time_boarding", side_effect=reject_past):
            self.assertEqual(
                _identities(choices.board_options(physical("A"), line("A"), 604)),
                [(605.0, "fast")],
            )

    def test_opaque_fallback_is_evaluated_for_each_request(self):
        events = []

        class OpaqueManager:
            def get_next_bus_departure(self, *args, **kwargs):
                events.append((args, kwargs))
                return 600 + len(events), f"opaque-{len(events)}"

        for provider in ("bus", "rail"):
            graph, _, _, _, physical, line = _fixture(provider)
            choices = TimetableChoices(graph, OpaqueManager(), "weekday", use_realtime=False,
                                       deadline=630, bus_repository=None)
            with self.subTest(provider=provider), \
                    patch.object(choices, "_fallback_options", wraps=choices._fallback_options) as evaluate:
                first = choices.board_options(physical("A"), line("A"), 599)
                second = choices.board_options(physical("A"), line("A"), 599)
                self.assertEqual(evaluate.call_count, 2)
                self.assertEqual(first[0][1].provider, "opaque-" + provider)
                if provider == "bus":
                    self.assertEqual((first[0][0], second[0][0]), (601, 602))
                    self.assertNotEqual(first[0][1].run_id, second[0][1].run_id)
        self.assertEqual(len(events), 2)

    def test_only_pure_odpt_identity_parsing_is_reused(self):
        _, _, repository, choices, _, _ = _fixture("bus")
        pole = "odpt.BusstopPole:Toei.HiraiNanachome.1000.1"
        malformed = "odpt.BusstopPole:Toei.Invalid"
        with patch.object(choices_module, "_BUS_POLE_STOP_PATTERN",
                          wraps=choices_module._BUS_POLE_STOP_PATTERN) as parser:
            for _ in range(3):
                self.assertEqual(choices._stop_id(pole), "1000-01")
                self.assertIsNone(choices._stop_id(malformed))
            self.assertEqual(parser.search.call_count, 2)
        self.assertIsNone(choices._stop_id(None))
        self.assertIsNone(choices._stop_id([]))
        # Repository membership is not a pure parsing operation and retains
        # its ordinary lookup behavior for canonical synthetic/GTFS keys.
        self.assertIsNone(choices._stop_id("new-stop"))
        repository.stops["new-stop"] = {}
        self.assertEqual(choices._stop_id("new-stop"), "new-stop")

    def test_all_modes_preserve_ordered_paths_clocks_walk_and_selected_runs(self):
        for provider in ("bus", "rail"):
            for mode in MODES:
                snapshots = []
                for choices_class in (_UncachedChoices, TimetableChoices):
                    graph, _, _, choices, physical, line = _fixture(provider, choices_class=choices_class)
                    # Warm the exact readiness that the search will request.
                    choices.board_options(physical("A"), line("A"), 598 if provider == "bus" else 600)
                    candidates = _search(graph, choices, {}, mode=mode, start=physical("A"),
                                         target=physical("C"), start_minute=598)
                    snapshots.append(_snapshot(candidates))
                with self.subTest(provider=provider, mode=mode):
                    self.assertEqual(snapshots[0], snapshots[1])
                    # A bus can alight at B and reboard that same trip after
                    # an actual A->B ride. Cost/transfer search retains that
                    # distinct boarding history; reuse must preserve it too.
                    self.assertEqual(len(snapshots[1]),
                                     2 if provider == "bus" and mode != "time" else 1)
                    self.assertEqual(snapshots[1][0]["nodes"],
                                     [physical("A"), line("A"), line("B"), line("C"), physical("C")])
                    self.assertEqual(snapshots[1][0]["arrival"], 611 if provider == "bus" else 612)
                    self.assertEqual(snapshots[1][0]["walk_m"], 0)


if __name__ == "__main__":
    unittest.main()
