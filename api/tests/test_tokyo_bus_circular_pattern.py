"""Closed ODPT bus patterns keep their declared terminal and GTFS occurrence."""

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from tokyo_search_labels import SelectedPath
from tokyo_timetable_choices import TimetableChoices
import toei_engine as engine
from tests.test_tokyo_bus_choices_contract import _day, _graph, _line, _phys, _repository


PATTERN = "odpt.BusroutePattern:Toei.CH01.12101.3"
LINE = f"buspat:{PATTERN}"
POLES = (
    "odpt.BusstopPole:Toei.ShinjukuStationNishiguchi.702.7",
    "odpt.BusstopPole:Toei.TochoDaiichiHonchosha.2248.1",
    "odpt.BusstopPole:Toei.TochoDainiHonchosha.2249.1",
    "odpt.BusstopPole:Toei.TogikaiGijido.2250.1",
)
STOPS = ("0702-07", "2248-01", "2249-01", "2250-01")
ORDERED_POLES = (*POLES, POLES[0])
LOOP_TIMES = tuple((stop, minute, minute) for stop, minute in
                   zip((*STOPS, STOPS[0]), (600, 605, 610, 615, 620)))


def _fixture(*trips, ordered=True, deadline=660):
    graph = _graph(*zip(ORDERED_POLES, ORDERED_POLES[1:]), line=LINE)
    repository = _repository(*(trips or (("loop", "active", LOOP_TIMES),)))
    manager = engine.TimetableManager()
    if ordered:
        manager.pattern_stops_map[PATTERN] = list(ORDERED_POLES)
    choices = TimetableChoices(
        graph, manager, _day("active"), use_realtime=False,
        deadline=deadline, bus_repository=repository,
    )
    return graph, repository, manager, choices


class TokyoCircularBusPatternTest(unittest.TestCase):
    def test_declared_terminal_is_the_same_from_start_and_every_midpoint(self):
        _, _, _, choices = _fixture()
        for index, pole in enumerate(POLES):
            with self.subTest(pole=pole):
                self.assertEqual(choices._bus_pattern_terminal_stop_id(_line(pole, LINE)), STOPS[0])
                options = choices.board_options(_phys(pole), _line(pole, LINE), 598)
                self.assertEqual([(time, state.trip_id, state.sequence) for time, state in options],
                                 [(600 + 5 * index, "loop", index + 1)])
        # The graph has an outgoing edge at the final occurrence, but the
        # concrete run has finished and cannot be boarded for another lap.
        self.assertEqual(choices.board_options(_phys(POLES[0]), _line(POLES[0], LINE), 620), ())

    def test_selected_run_closes_the_loop_at_its_exact_final_occurrence(self):
        _, _, _, choices = _fixture()
        clock, state = choices.board_options(_phys(POLES[0]), _line(POLES[0], LINE), 600)[0]
        run_id = state.run_id
        for index, (left, right) in enumerate(zip(ORDERED_POLES, ORDERED_POLES[1:]), 2):
            clock, state = choices.ride_options(_line(left, LINE), _line(right, LINE), clock, state)[0]
            self.assertEqual((clock, state.run_id, state.trip_id, state.board_sequence, state.sequence),
                             (600 + 5 * (index - 1), run_id, "loop", 1, index))
        metadata = choices.metadata(state)
        self.assertEqual(metadata["stops"], (*STOPS, STOPS[0]))
        self.assertEqual((metadata["origin_stop_id"], metadata["destination_stop_id"]),
                         (STOPS[0], STOPS[0]))
        self.assertEqual((metadata["scheduled_departure_minute"], metadata["actual_arrival_minute"]),
                         (600, 620))
        self.assertEqual(choices.ride_options(_line(POLES[0], LINE), _line(POLES[1], LINE),
                                              clock, state), ())

    def test_midpoint_boarding_preserves_terminal_and_selected_stop_sequence(self):
        _, _, _, choices = _fixture()
        clock, state = choices.board_options(_phys(POLES[1]), _line(POLES[1], LINE), 605)[0]
        for left, right in zip(ORDERED_POLES[1:], ORDERED_POLES[2:]):
            clock, state = choices.ride_options(_line(left, LINE), _line(right, LINE), clock, state)[0]
        metadata = choices.metadata(state)
        self.assertEqual((clock, state.board_sequence, state.sequence), (620, 2, 5))
        self.assertEqual((metadata["origin_stop_id"], metadata["destination_stop_id"]),
                         (STOPS[1], STOPS[0]))
        self.assertEqual((metadata["actual_departure_minute"], metadata["actual_arrival_minute"]),
                         (605, 620))

    def test_selected_circular_path_is_validated_and_serialized_without_reselection(self):
        graph, repository, manager, choices = _fixture()
        clock, state = choices.board_options(_phys(POLES[0]), _line(POLES[0], LINE), 600)[0]
        clocks = [clock]
        rides = {0: state}
        for index, (left, right) in enumerate(zip(ORDERED_POLES, ORDERED_POLES[1:]), 1):
            clock, state = choices.ride_options(_line(left, LINE), _line(right, LINE), clock, state)[0]
            clocks.append(clock)
            rides[index] = state
        path = SelectedPath([_phys(POLES[0]), *(_line(pole, LINE) for pole in ORDERED_POLES),
                             _phys(POLES[0])], [*clocks, clock], rides, choices, 598)
        with patch.object(engine, "gtfs_repo", repository), \
                patch.object(engine, "_resolve_gtfs_bus_leg",
                             side_effect=AssertionError("A selected circular path must not reselect its run")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(engine.calculate_real_arrival_time(
                graph, manager, path, "09:58", _day("active"), use_realtime=False), 620)
            steps = engine.segments_detailed(graph, path, manager, "09:58", _day("active"),
                                             use_realtime=False)
        serialized = json.loads(json.dumps(steps))
        buses = [step for step in serialized if step["kind"] == "bus"]
        self.assertEqual(len(buses), 1)
        bus = buses[0]
        self.assertEqual((bus["trip_id"], bus["route_id"], bus["title"]),
                         ("loop", "R", f"Test {STOPS[0]}行"))
        self.assertEqual((bus["departure_time"], bus["arrival_time"]), ("10:00", "10:20"))
        self.assertEqual([stop["id"] for stop in bus["stops"]], [*STOPS, STOPS[0]])
        self.assertTrue(bus["stops"][0]["is_origin"])
        self.assertTrue(bus["stops"][-1]["is_destination"])

    def test_terminal_and_direction_filter_still_reject_other_trips(self):
        short = tuple((stop, minute, minute) for stop, minute in
                      zip(STOPS, (601, 606, 611, 616)))
        reverse = tuple((stop, minute, minute) for stop, minute in
                        zip((STOPS[0], STOPS[3], STOPS[2], STOPS[1], STOPS[0]),
                            (602, 607, 612, 617, 622)))
        _, _, _, choices = _fixture(("loop", "active", LOOP_TIMES),
                                    ("short", "active", short),
                                    ("reverse", "active", reverse),
                                    ("inactive", "inactive", LOOP_TIMES))
        options = choices.board_options(_phys(POLES[0]), _line(POLES[0], LINE), 598)
        self.assertEqual([state.trip_id for _, state in options], ["loop"])

    def test_common_deadline_still_limits_the_closing_ride(self):
        _, _, _, choices = _fixture(deadline=619)
        clock, state = choices.board_options(_phys(POLES[2]), _line(POLES[2], LINE), 610)[0]
        clock, state = choices.ride_options(_line(POLES[2], LINE), _line(POLES[3], LINE),
                                           clock, state)[0]
        self.assertEqual(clock, 615)
        self.assertEqual(choices.ride_options(_line(POLES[3], LINE), _line(POLES[0], LINE),
                                              clock, state), ())

    def test_declared_pattern_with_extra_graph_branch_raises_explicitly(self):
        graph, _, _, choices = _fixture()
        graph.add_edge(_line(POLES[0], LINE), _line(POLES[2], LINE),
                       etype="ride", mode="bus", w=engine.BUS_RIDE_COST)
        with self.assertRaisesRegex(RuntimeError, "branches unexpectedly"):
            choices.board_options(_phys(POLES[0]), _line(POLES[0], LINE), 598)

    def test_cycle_without_known_ordered_identity_does_not_guess_terminal(self):
        _, _, _, choices = _fixture(ordered=False)
        with self.assertRaisesRegex(RuntimeError, "ride cycle without ordered stops"):
            choices.board_options(_phys(POLES[0]), _line(POLES[0], LINE), 598)

    def test_declared_pattern_disagreement_with_graph_raises_explicitly(self):
        graph, _, _, choices = _fixture()
        graph.remove_edge(_line(POLES[2], LINE), _line(POLES[3], LINE))
        with self.assertRaisesRegex(RuntimeError, "disagrees with its ordered pattern"):
            choices.board_options(_phys(POLES[0]), _line(POLES[0], LINE), 598)

    def test_declared_pattern_missing_graph_pole_raises_explicitly(self):
        graph, _, _, choices = _fixture()
        graph.remove_node(_line(POLES[2], LINE))
        with self.assertRaisesRegex(RuntimeError, "ordered pattern stop is absent from the graph"):
            choices.board_options(_phys(POLES[0]), _line(POLES[0], LINE), 598)

    def test_cached_pattern_still_rejects_unknown_boarding_identity(self):
        _, _, _, choices = _fixture()
        self.assertEqual(choices._bus_pattern_terminal_stop_id(_line(POLES[0], LINE)), STOPS[0])
        with self.assertRaisesRegex(RuntimeError, "boarding node is absent from its ordered pattern"):
            choices._bus_pattern_terminal_stop_id(_line("unknown-boarding-pole", LINE))

    def test_declared_unknown_terminal_identity_raises_explicitly(self):
        graph, repository, manager, _ = _fixture()
        manager.pattern_stops_map[PATTERN] = [*POLES, "unknown-terminal"]
        choices = TimetableChoices(graph, manager, _day("active"),
                                   use_realtime=False, bus_repository=repository)
        with self.assertRaisesRegex(RuntimeError, "terminal has no GTFS stop identity"):
            choices.board_options(_phys(POLES[0]), _line(POLES[0], LINE), 598)

    def test_metadata_free_acyclic_pattern_keeps_exact_graph_terminal(self):
        graph, repository, manager, _ = _fixture(ordered=False)
        graph.remove_edge(_line(POLES[3], LINE), _line(POLES[0], LINE))
        choices = TimetableChoices(graph, manager, _day("active"),
                                   use_realtime=False, bus_repository=repository)
        self.assertEqual(choices._bus_pattern_terminal_stop_id(_line(POLES[1], LINE)), STOPS[3])


class TokyoLegacyCircularBusPatternTest(unittest.TestCase):
    def _bare_path(self, poles):
        return [_phys(poles[0]), *(_line(pole, LINE) for pole in poles),
                _phys(poles[-1])]

    def _evaluate(self, graph, repository, manager, path, start="09:58"):
        with patch.object(engine, "gtfs_repo", repository), \
                contextlib.redirect_stdout(io.StringIO()):
            arrival = engine.calculate_real_arrival_time(
                graph, manager, path, start, _day("active"), use_realtime=False)
            steps = engine.segments_detailed(
                graph, path, manager, start, _day("active"), use_realtime=False)
        return arrival, steps

    def _assert_contract_error(self, graph, repository, manager, path, message):
        with patch.object(engine, "gtfs_repo", repository), \
                contextlib.redirect_stdout(io.StringIO()):
            for name, function in (
                ("calculate_real_arrival_time", lambda: engine.calculate_real_arrival_time(
                    graph, manager, path, "09:58", _day("active"), use_realtime=False)),
                ("segments_detailed", lambda: engine.segments_detailed(
                    graph, path, manager, "09:58", _day("active"), use_realtime=False)),
            ):
                with self.subTest(function=name), \
                        self.assertRaisesRegex(engine.RouteContractError, message) as raised:
                    function()
                self.assertIsInstance(raised.exception.__cause__, RuntimeError)

    def test_bare_circular_path_keeps_the_closing_stop_occurrence_and_trip(self):
        graph, repository, manager, _ = _fixture()
        arrival, steps = self._evaluate(
            graph, repository, manager, self._bare_path(ORDERED_POLES))
        self.assertEqual(arrival, 620)
        buses = [step for step in steps if step["kind"] == "bus"]
        self.assertEqual(len(buses), 1)
        self.assertEqual((buses[0]["trip_id"], buses[0]["departure_time"],
                          buses[0]["arrival_time"]), ("loop", "10:00", "10:20"))
        self.assertEqual([stop["id"] for stop in buses[0]["stops"]], [*STOPS, STOPS[0]])

    def test_bare_midpoint_boarding_uses_the_declared_terminal(self):
        graph, repository, manager, _ = _fixture()
        arrival, steps = self._evaluate(
            graph, repository, manager, self._bare_path(ORDERED_POLES[1:]))
        self.assertEqual(arrival, 620)
        self.assertEqual([step["kind"] for step in steps], ["wait", "bus"])
        bus = steps[1]
        self.assertEqual((bus["trip_id"], bus["departure_time"], bus["arrival_time"]),
                         ("loop", "10:05", "10:20"))
        self.assertEqual([stop["id"] for stop in bus["stops"]], [*STOPS[1:], STOPS[0]])

    def test_bare_path_does_not_board_a_finished_loop_for_an_extra_lap(self):
        graph, repository, manager, _ = _fixture()
        self.assertEqual(self._evaluate(
            graph, repository, manager, self._bare_path(ORDERED_POLES), "10:20"),
            (None, []))

    def test_bare_partial_ride_retains_terminal_and_active_service_filters(self):
        short = tuple((stop, minute, minute) for stop, minute in
                      zip(STOPS, (599, 604, 609, 614)))
        inactive = tuple((stop, minute, minute) for stop, minute in
                         zip((*STOPS, STOPS[0]), (599, 604, 609, 614, 619)))
        graph, repository, manager, _ = _fixture(
            ("short", "active", short), ("inactive", "inactive", inactive),
            ("loop", "active", LOOP_TIMES))
        arrival, steps = self._evaluate(
            graph, repository, manager, self._bare_path(ORDERED_POLES[:2]))
        self.assertEqual(arrival, 605)
        bus = next(step for step in steps if step["kind"] == "bus")
        self.assertEqual((bus["trip_id"], bus["departure_time"], bus["arrival_time"]),
                         ("loop", "10:00", "10:05"))

    def test_bare_cycle_without_ordered_metadata_still_raises(self):
        graph, repository, manager, _ = _fixture(ordered=False)
        self._assert_contract_error(graph, repository, manager,
                                    self._bare_path(ORDERED_POLES),
                                    "ride cycle without ordered stops")

    def test_bare_declared_pattern_graph_disagreement_still_raises(self):
        graph, repository, manager, _ = _fixture()
        graph.remove_edge(_line(POLES[2], LINE), _line(POLES[3], LINE))
        self._assert_contract_error(graph, repository, manager,
                                    self._bare_path(ORDERED_POLES[:2]),
                                    "disagrees with its ordered pattern")

    def test_bare_unknown_declared_terminal_still_raises(self):
        graph, repository, manager, _ = _fixture()
        manager.pattern_stops_map[PATTERN] = [*POLES, "unknown-terminal"]
        self._assert_contract_error(graph, repository, manager,
                                    self._bare_path(ORDERED_POLES[:2]),
                                    "terminal has no GTFS stop identity")

    def test_metadata_free_acyclic_bare_path_keeps_exact_trip_and_clock(self):
        short = tuple((stop, minute, minute) for stop, minute in
                      zip(STOPS, (600, 605, 610, 615)))
        graph, repository, manager, _ = _fixture(("short", "active", short), ordered=False)
        graph.remove_edge(_line(POLES[3], LINE), _line(POLES[0], LINE))
        arrival, steps = self._evaluate(
            graph, repository, manager, self._bare_path(POLES))
        self.assertEqual(arrival, 615)
        bus = next(step for step in steps if step["kind"] == "bus")
        self.assertEqual((bus["trip_id"], bus["departure_time"], bus["arrival_time"]),
                         ("short", "10:00", "10:15"))
        self.assertEqual([stop["id"] for stop in bus["stops"]], list(STOPS))

    def test_graph_only_terminal_helper_still_requires_ordered_data_for_a_cycle(self):
        graph, _, _, _ = _fixture()
        with self.assertRaisesRegex(engine.RouteContractError, "contains a ride cycle"):
            engine._bus_pattern_terminal_gtfs_stop_id(graph, _line(POLES[0], LINE))


if __name__ == "__main__":
    unittest.main()
