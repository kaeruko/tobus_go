"""Fresh boarding must not manufacture a transit leg or walking break.

The quota fixture puts five invalid same-stop endings ahead of five useful
rides by cost and arrival. The returned paths must still fill the same five
slots with rides that moved, rather than losing them during detail validation.
"""

import contextlib
from dataclasses import replace
import io
import itertools
import json
import unittest
from unittest.mock import patch

import networkx as nx

import toei_engine as engine
from gtfs_loader import GtfsRepository
from tokyo_search_labels import search_labels
from tokyo_timetable_choices import TimetableChoices
from tests.test_tokyo_bus_choices_contract import (
    _day, _graph as _bus_graph, _phys as _bus_phys, _repository,
)
from tests.test_tokyo_waiting_contract import (
    _graph as _rail_graph, _line as _rail_line, _manager as _rail_manager,
    _physical as _rail_phys, _run,
)
from tests.test_tokyo_walk_boarding_access import (
    MODES, START, TARGET, _ScheduledChoices, _final_walk, _leg, _walk,
)


ACCESS = ("phys", "access")


def _fixture(provider, *, routes=1, fresh_exit="alight", finish_walk=100.0):
    graph = nx.DiGraph()
    _walk(graph, START, ACCESS, 600.0)
    virtual = {ACCESS: _final_walk(100.0)}
    expected = []
    for index in range(routes):
        finish = ("phys", f"finish-{index}")
        leg = _leg(graph, ACCESS, finish, f"route-{index}", mode=provider,
                   departure=10.0, arrival=20.0 + index)
        graph.add_edge(leg[1], ACCESS, etype=fresh_exit, w=0.0)
        if finish_walk is not None:
            virtual[finish] = _final_walk(finish_walk)
            expected.append([START, *leg, TARGET])
    return graph, virtual, expected


def _search(graph, choices, virtual, *, mode, quota=5, start=START,
            target=TARGET, start_minute=0.0, max_total_walk=3000.0):
    # islice mirrors the caller's fixed candidate quota. fewTransfers may
    # continue to diagnose an exhausted quota if a caller requests more.
    iterator = search_labels(
        graph, choices, start, target, mode=mode, start_minute=start_minute,
        max_search=quota, max_visited=2000, max_travel_min=240.0,
        time_limit_sec=10.0, max_total_walk=max_total_walk,
        max_segment_walk=600.0, walk_speed=80.0, rail_boarding_minutes=2.0,
        advance_time=lambda u, v, clock, edge: clock + (
            edge.get("meters", 0.0) / 80.0 if edge.get("etype") == "walk" else 1.0
        ),
        virtual_connections=virtual, edge_uses_rail=lambda u, v: False,
    )
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return list(itertools.islice(iterator, quota))
    finally:
        iterator.close()


class _OpaqueChoices(_ScheduledChoices):
    can_wait_offboard = False

    def board_options(self, u, v, ready):
        return tuple((clock, replace(state, provider="opaque-" + state.provider,
                                     sequence=0, board_sequence=0))
                     for clock, state in super().board_options(u, v, ready))

    def ride_options(self, *args):
        raise AssertionError("Opaque continuations use the injected graph clock")


class TokyoZeroRideBoardingTest(unittest.TestCase):
    def assert_all_transit_legs_moved(self, graph, path):
        active = None
        for index, (left, right) in enumerate(zip(path, path[1:])):
            edge = graph.get_edge_data(left, right) or {}
            if edge.get("etype") == "board":
                self.assertIsNone(active)
                active = path.edge_rides[index]
            elif edge.get("etype") in ("alight", "xfer"):
                self.assertIsNotNone(active)
                final = path.edge_rides[index - 1]
                self.assertEqual(final.run_id, active.run_id)
                self.assertNotEqual(final.sequence, active.board_sequence)
                active = None
        self.assertIsNone(active)

    def test_zero_ride_endings_do_not_spend_five_candidate_slots(self):
        for provider in ("bus", "rail"):
            graph, virtual, expected = _fixture(provider, routes=5)
            for mode in MODES:
                with self.subTest(provider=provider, mode=mode):
                    # Time mode retains its single fastest representative for
                    # a shared walking bucket; cost/transfer modes fill five.
                    count = 1 if mode == "time" else 5
                    candidates = _search(graph, _ScheduledChoices(graph), virtual,
                                         mode=mode, quota=count)
                    self.assertEqual(len(candidates), count)
                    self.assertEqual({tuple(item["path"]) for item in candidates},
                                     {tuple(path) for path in expected[:count]})
                    for candidate in candidates:
                        self.assertEqual(candidate["walk_m"], 700.0)
                        self.assert_all_transit_legs_moved(graph, candidate["path"])

    def test_fresh_alight_and_xfer_cannot_restart_the_600m_walking_limit(self):
        for provider in ("bus", "rail"):
            for exit_type in ("alight", "xfer"):
                graph, virtual, _ = _fixture(provider, fresh_exit=exit_type, finish_walk=None)
                virtual[ACCESS] = _final_walk(1.0)
                for mode in MODES:
                    with self.subTest(provider=provider, exit_type=exit_type, mode=mode):
                        self.assertEqual(_search(graph, _ScheduledChoices(graph), virtual,
                                                 mode=mode), [])

    def test_exact_600m_walk_remains_available_without_dummy_boarding(self):
        for provider in ("bus", "rail"):
            graph, virtual, _ = _fixture(provider, finish_walk=None)
            virtual[ACCESS] = _final_walk(0.0)
            for mode in MODES:
                with self.subTest(provider=provider, mode=mode):
                    candidates = _search(graph, _ScheduledChoices(graph), virtual, mode=mode)
                    self.assertEqual([item["path"] for item in candidates],
                                     [[START, ACCESS, TARGET]])
                    self.assertEqual(candidates[0]["walk_m"], 600.0)

    def test_actual_ride_allows_a_new_walk_but_keeps_total_walking_limit(self):
        for provider in ("bus", "rail"):
            graph, virtual, expected = _fixture(provider)
            for mode in MODES:
                with self.subTest(provider=provider, mode=mode):
                    candidates = _search(graph, _ScheduledChoices(graph), virtual,
                                         mode=mode, max_total_walk=700.0)
                    self.assertEqual([item["path"] for item in candidates], expected)
                    self.assert_all_transit_legs_moved(graph, candidates[0]["path"])
                    self.assertEqual(_search(graph, _ScheduledChoices(graph), virtual,
                                             mode=mode, max_total_walk=699.0), [])

    def test_opaque_bus_and_rail_allow_alighting_only_after_a_ride_edge(self):
        for provider in ("bus", "rail"):
            graph, virtual, expected = _fixture(provider)
            virtual[ACCESS] = _final_walk(1.0)
            for mode in MODES:
                with self.subTest(provider=provider, mode=mode):
                    candidates = _search(graph, _OpaqueChoices(graph), virtual, mode=mode)
                    self.assertEqual([item["path"] for item in candidates], expected)
                    self.assert_all_transit_legs_moved(graph, candidates[0]["path"])

    def test_fresh_rail_boarding_cannot_remove_a_continuing_transfer_state(self):
        graph = _rail_graph(("A", "B"), ("B", "C"), ("D", "E"))
        manager = _rail_manager(
            _run("access", (("A", 610), ("B", 611), ("C", 620))),
            _run("last-connection", (("D", 615), ("E", 616))),
        )
        _walk(graph, START, _rail_phys("A"), 600.0)
        _walk(graph, START, _rail_phys("B"), 576.0)
        _walk(graph, _rail_phys("B"), _rail_phys("D"), 50.0)
        repository = GtfsRepository("tokyo-test")
        # Starting by foot at B cannot take the 50m connecting walk (626m).
        # Riding A->B permits that new segment. Both boardings reach the same
        # run/stop at 611, but only the continuing state may alight there.
        expected = [START, _rail_phys("A"), _rail_line("A"), _rail_line("B"),
                    _rail_phys("B"), _rail_phys("D"), _rail_line("D"), _rail_line("E"),
                    _rail_phys("E")]
        control = graph.copy()
        control.remove_edge(_rail_phys("B"), _rail_line("B"))
        for mode in MODES:
            with self.subTest(mode=mode):
                control_choices = TimetableChoices(control, manager, "weekday", use_realtime=False,
                                                   deadline=840.0, bus_repository=repository)
                control_candidates = _search(control, control_choices, {}, mode=mode,
                                             target=_rail_phys("E"), start_minute=600.0)
                self.assertEqual([item["path"] for item in control_candidates], [expected])
                choices = TimetableChoices(graph, manager, "weekday", use_realtime=False,
                                           deadline=840.0, bus_repository=repository)
                candidates = _search(graph, choices, {}, mode=mode, target=_rail_phys("E"),
                                     start_minute=600.0)
                self.assertEqual([item["path"] for item in candidates], [expected])
                self.assertEqual(candidates[0]["path"].arrival_minute, 617.0)
                self.assert_all_transit_legs_moved(graph, candidates[0]["path"])

    def test_real_bus_and_rail_transfer_and_waiting_keep_valid_selected_details(self):
        for provider in ("bus", "rail"):
            if provider == "bus":
                graph = _bus_graph(("A", "B"), ("B", "C"))
                repository = _repository(
                    ("first", "active", (("A", 610, 610), ("B", 611, 611))),
                    ("second", "active", (("B", 620, 620), ("C", 621, 621))),
                )
                manager = engine.TimetableManager()
                day_type = _day("active")
                start, target = _bus_phys("A"), _bus_phys("C")
            else:
                graph = _rail_graph(("A", "B"), ("B", "C"))
                manager = _rail_manager(
                    _run("first", (("A", 610), ("B", 611))),
                    _run("second", (("B", 620), ("C", 621))),
                )
                repository = GtfsRepository("tokyo-test")
                day_type = "weekday"
                start, target = _rail_phys("A"), _rail_phys("C")
                for index, name in enumerate(("A", "B", "C"), 1):
                    graph.nodes[_rail_phys(name)].update(station_code=f"A{index:02}", name_en=name)
            for mode in MODES:
                with self.subTest(provider=provider, mode=mode):
                    choices = TimetableChoices(graph, manager, day_type, use_realtime=False,
                                               deadline=840.0, bus_repository=repository)
                    candidates = _search(graph, choices, {}, mode=mode, start=start,
                                         target=target, start_minute=600.0)
                    self.assertEqual(len(candidates), 1)
                    path = candidates[0]["path"]
                    self.assert_all_transit_legs_moved(graph, path)
                    self.assertEqual(path.arrival_minute, 621 if provider == "bus" else 622)
                    with patch.object(engine, "gtfs_repo", repository), \
                            contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(engine.calculate_real_arrival_time(
                            graph, manager, path, "10:00", day_type, use_realtime=False),
                            path.arrival_minute)
                        steps = engine.segments_detailed(graph, path, manager, "10:00", day_type,
                                                         use_realtime=False)
                    steps = json.loads(json.dumps(steps))
                    legs = [step for step in steps if step["kind"] == provider]
                    self.assertEqual(len(legs), 2)
                    self.assertEqual([leg["departure_time"] for leg in legs], ["10:10", "10:20"])
                    self.assertEqual([leg["arrival_time"] for leg in legs], ["10:11", "10:21"])
                    boards = [index for index, (left, right) in enumerate(zip(path, path[1:]))
                              if graph[left][right].get("etype") == "board"]
                    self.assertEqual([path.edge_times[index] for index in boards], [610, 620])
                    previous_arrival = path.edge_times[boards[1] - 1]
                    self.assertGreater(620 - previous_arrival, 2.0)
                    if provider == "bus":
                        self.assertTrue(any(step["kind"] == "wait" for step in steps))
                        self.assertEqual([leg["trip_id"] for leg in legs], ["first", "second"])
                    else:
                        self.assertEqual([leg["selected_run"]["train_number"] for leg in legs],
                                         ["first", "second"])
                    self.assertTrue(all(leg["edges"] >= 1 for leg in legs))


if __name__ == "__main__":
    unittest.main()
