"""A feasible final walk must not remove walking access to transit.

Fixtures keep actual walking resources and a selected vehicle run. The control
removes only the origin's direct destination connection, proving that the
same transit continuation remains feasible when that connection is present.
"""

import contextlib
from dataclasses import replace
import io
import unittest

import networkx as nx

from tokyo_search_labels import search_labels
from tokyo_timetable_choices import RideState


START = ("phys", "start")
TARGET = ("phys", "dest:35.0,139.0")
MODES = ("cost", "fewTransfers", "time")


def _physical(graph, node):
    graph.add_node(node, kind="phys", lat=35.0, lon=139.0)


def _walk(graph, left, right, meters, **attributes):
    _physical(graph, left)
    _physical(graph, right)
    graph.add_edge(left, right, etype="walk", meters=meters,
                   w=1.5 * max(1.0, meters / 80.0), **attributes)


def _leg(graph, board, finish, line, *, mode="bus", departure, arrival):
    _physical(graph, board)
    _physical(graph, finish)
    origin = ("line", board[1], line)
    destination = ("line", finish[1], line)
    graph.add_node(origin, kind="line", mode=mode, line=line,
                   departure=departure, lat=35.0, lon=139.0)
    graph.add_node(destination, kind="line", mode=mode, line=line,
                   arrival=arrival, lat=35.0, lon=139.0)
    graph.add_edge(board, origin, etype="board", w=5.0)
    graph.add_edge(origin, destination, etype="ride", mode=mode, w=0.8)
    graph.add_edge(destination, finish, etype="alight", w=0.0)
    return [board, origin, destination, finish]


def _final_walk(meters):
    return 1.5 * meters / 80.0, meters


class _ScheduledChoices:
    can_wait_offboard = True
    use_realtime = False
    manager = object()

    def __init__(self, graph):
        self.graph = graph
        self.boarded = []

    def board_options(self, u, v, ready):
        data = self.graph.nodes[v]
        departure = data["departure"]
        self.boarded.append((u, v, ready))
        if ready > departure:
            return ()
        provider = data["mode"]
        return ((departure, RideState(
            provider, "fixture-day", f"run:{data['line']}", data["line"],
            1, 1, departure,
            trip_id=f"trip:{data['line']}" if provider == "bus" else None,
            train_number=f"train:{data['line']}" if provider == "rail" else None,
        )),)

    def ride_options(self, u, v, clock, state):
        arrival = self.graph.nodes[v]["arrival"]
        return ((arrival, replace(state, sequence=2)),)


def _search(graph, virtual, *, mode, bus_only=False, max_total_walk=3000.0):
    choices = _ScheduledChoices(graph)

    def excludes_rail(u, v):
        return bus_only and any(graph.nodes[node].get("mode") == "rail"
                                for node in (u, v))

    with contextlib.redirect_stdout(io.StringIO()):
        candidates = list(search_labels(
            graph, choices, START, TARGET, mode=mode, start_minute=0.0,
            max_search=1 if mode == "time" else 20, max_visited=1000,
            max_travel_min=240.0, time_limit_sec=15.0,
            max_total_walk=max_total_walk, max_segment_walk=600.0,
            walk_speed=80.0, rail_boarding_minutes=2.0,
            advance_time=lambda u, v, clock, edge: clock + edge.get("meters", 0.0) / 80.0,
            virtual_connections=virtual, edge_uses_rail=excludes_rail,
        ))
    return candidates, choices


def _access_fixture(provider="bus", walks=(10.0,)):
    graph = nx.DiGraph()
    prefix = [START]
    for index, meters in enumerate(walks):
        following = ("phys", f"access-{index}")
        _walk(graph, prefix[-1], following, meters)
        prefix.append(following)
    finish = ("phys", "finish")
    ready = sum(walks) / 80.0 + (2.0 if provider == "rail" else 0.0)
    leg = _leg(graph, prefix[-1], finish, "main", mode=provider,
               departure=ready, arrival=ready + 1.0)
    virtual = {START: _final_walk(600.0), finish: _final_walk(10.0)}
    return graph, virtual, [*prefix, *leg[1:], TARGET]


class TokyoWalkBoardingAccessTest(unittest.TestCase):
    def test_direct_final_walk_keeps_faster_and_cheaper_bus_and_rail_access(self):
        for provider in ("bus", "rail"):
            graph, virtual, expected = _access_fixture(provider)
            control = dict(virtual)
            control.pop(START)
            for mode in MODES:
                with self.subTest(provider=provider, mode=mode):
                    baseline, _ = _search(graph, control, mode=mode)
                    self.assertEqual([item["path"] for item in baseline], [expected])
                    candidates, _ = _search(graph, virtual, mode=mode)
                    transit = next(item for item in candidates if item["path"] == expected)
                    self.assertEqual(transit["cost"], baseline[0]["cost"])
                    self.assertEqual(transit["path"].edge_times, baseline[0]["path"].edge_times)
                    self.assertEqual(transit["walk_m"], 20.0)
                    self.assertLess(transit["cost"], 11.25)
                    self.assertLess(transit["path"].arrival_minute, 7.5)
                    if mode == "fewTransfers":
                        self.assertEqual(candidates[0]["path"], [START, TARGET])
                    else:
                        self.assertEqual(candidates[0]["path"], expected)

    def test_boarding_access_can_require_two_walking_edges(self):
        for provider in ("bus", "rail"):
            graph, virtual, expected = _access_fixture(provider, (10.0, 10.0))
            for mode in MODES:
                with self.subTest(provider=provider, mode=mode):
                    candidates, _ = _search(graph, virtual, mode=mode)
                    transit = next(item for item in candidates if item["path"] == expected)
                    self.assertEqual(transit["walk_m"], 30.0)
                    self.assertLess(transit["path"].arrival_minute, 7.5)

    def test_connecting_station_walk_keeps_rail_boarding_and_preparation(self):
        graph, virtual, expected = _access_fixture("rail", (80.0,))
        graph[START][expected[1]]["connecting_station"] = True
        for mode in MODES:
            with self.subTest(mode=mode):
                candidates, choices = _search(graph, virtual, mode=mode)
                transit = next(item for item in candidates if item["path"] == expected)
                self.assertEqual(transit["path"].edge_times, [1.0, 3.0, 4.0, 5.0, 5.125])
                self.assertEqual(choices.boarded[0][2], 3.0)

    def test_walk_after_previous_ride_keeps_legal_transfer(self):
        graph = nx.DiGraph()
        hub = ("phys", "hub")
        first = _leg(graph, START, hub, "first", departure=0.0, arrival=1.0)
        board = ("phys", "transfer-stop")
        _walk(graph, hub, board, 10.0)
        finish = ("phys", "finish")
        final = _leg(graph, board, finish, "final", departure=2.0, arrival=3.0)
        virtual = {hub: _final_walk(600.0), finish: _final_walk(10.0)}
        expected = [*first, *final, TARGET]
        for mode in MODES:
            with self.subTest(mode=mode):
                candidates, _ = _search(graph, virtual, mode=mode)
                transit = next(item for item in candidates if item["path"] == expected)
                self.assertEqual(transit["walk_m"], 20.0)
                self.assertEqual(transit["path"].edge_times,
                                 [0.0, 1.0, 1.0, 1.125, 2.0, 3.0, 3.0, 3.125])
                self.assertEqual({state.run_id for state in transit["path"].edge_rides.values()},
                                 {"run:first", "run:final"})

    def test_exact_segment_limit_still_applies_before_boarding(self):
        for access_walk in (20.0, 20.001):
            graph = nx.DiGraph()
            hub = ("phys", "hub")
            board = ("phys", "board")
            finish = ("phys", "finish")
            _walk(graph, START, hub, 580.0)
            _walk(graph, hub, board, access_walk)
            leg = _leg(graph, board, finish, "main", departure=20.0, arrival=21.0)
            virtual = {hub: _final_walk(20.0), finish: _final_walk(10.0)}
            expected = [START, hub, *leg, TARGET]
            for mode in ("cost", "fewTransfers"):
                with self.subTest(access_walk=access_walk, mode=mode):
                    candidates, choices = _search(graph, virtual, mode=mode)
                    self.assertEqual(any(item["path"] == expected for item in candidates),
                                     access_walk == 20.0)
                    self.assertEqual(bool(choices.boarded), access_walk == 20.0)
                    self.assertTrue(any(item["path"] == [START, hub, TARGET]
                                        for item in candidates))

    def test_exact_total_limit_survives_real_ride_and_new_boarding(self):
        for initial_walk in (570.0, 570.001):
            graph = nx.DiGraph()
            first_board = ("phys", "first-board")
            hub = ("phys", "hub")
            _walk(graph, START, first_board, initial_walk)
            first = _leg(graph, first_board, hub, "first", departure=8.0, arrival=9.0)
            board = ("phys", "final-board")
            finish = ("phys", "finish")
            _walk(graph, hub, board, 20.0)
            final = _leg(graph, board, finish, "final", departure=10.0, arrival=11.0)
            virtual = {hub: _final_walk(10.0), finish: _final_walk(10.0)}
            expected = [START, *first, *final, TARGET]
            for mode in ("cost", "fewTransfers"):
                with self.subTest(initial_walk=initial_walk, mode=mode):
                    candidates, _ = _search(graph, virtual, mode=mode, max_total_walk=600.0)
                    self.assertEqual(any(item["path"] == expected for item in candidates),
                                     initial_walk == 570.0)
                    self.assertTrue(all(item["walk_m"] <= 600.0 for item in candidates))
                    self.assertTrue(any(item["path"] == [START, *first, TARGET]
                                        for item in candidates))

    def test_bus_only_keeps_bus_walk_access_and_excludes_rail_boarding(self):
        graph, virtual, bus_path = _access_fixture("bus")
        rail_board = ("phys", "rail-board")
        rail_finish = ("phys", "rail-finish")
        _walk(graph, START, rail_board, 10.0)
        rail = _leg(graph, rail_board, rail_finish, "rail", mode="rail",
                    departure=3.0, arrival=4.0)
        virtual[rail_finish] = _final_walk(10.0)
        rail_path = [START, *rail, TARGET]
        for mode in MODES:
            with self.subTest(mode=mode):
                candidates, choices = _search(graph, virtual, mode=mode, bus_only=True)
                self.assertTrue(any(item["path"] == bus_path for item in candidates))
                self.assertFalse(any(item["path"] == rail_path for item in candidates))
                self.assertTrue(all(graph.nodes[v]["mode"] == "bus"
                                    for _, v, _ in choices.boarded))
                if mode != "time":
                    unrestricted, _ = _search(graph, virtual, mode=mode)
                    self.assertTrue(any(item["path"] == rail_path for item in unrestricted))

    def test_selected_run_and_clocks_are_retained_for_walk_access(self):
        for provider, expected_clocks in (
            ("bus", [0.125, 0.125, 1.125, 1.125, 1.25]),
            ("rail", [0.125, 2.125, 3.125, 4.125, 4.25]),
        ):
            graph, virtual, expected = _access_fixture(provider)
            for mode in MODES:
                with self.subTest(provider=provider, mode=mode):
                    candidates, _ = _search(graph, virtual, mode=mode)
                    path = next(item["path"] for item in candidates if item["path"] == expected)
                    self.assertEqual(path.edge_times, expected_clocks)
                    self.assertEqual(path.arrival_minute, expected_clocks[-1])
                    self.assertEqual(set(path.edge_rides), {1, 2})
                    boarded, continued = path.edge_rides[1], path.edge_rides[2]
                    self.assertEqual((boarded.run_id, continued.run_id), ("run:main", "run:main"))
                    self.assertEqual((boarded.board_sequence, boarded.sequence, continued.sequence),
                                     (1, 1, 2))
                    self.assertEqual(boarded.departure_minute, expected_clocks[1])
                    self.assertEqual(continued.departure_minute, expected_clocks[1])


if __name__ == "__main__":
    unittest.main()
