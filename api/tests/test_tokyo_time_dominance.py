"""Fastest dominance may ignore prefix cost only for strictly earlier clocks.

Arrival time is the objective. The timetable offers the same concrete run to
every ready prefix, so waiting can reproduce a later prefix's continuation.
"""

import contextlib
from dataclasses import replace
import io
import unittest

import networkx as nx

import tokyo_search_labels as labels
from tokyo_timetable_choices import RideState


START = ("phys", "start")
HUB = ("phys", "hub")
TARGET = ("phys", "target")
ORIGIN = ("line", "hub", "fixture-bus")
DESTINATION = ("line", "target", "fixture-bus")


class _WaitingChoices:
    can_wait_offboard = True
    use_realtime = False
    manager = object()

    def board_options(self, u, v, ready):
        if ready > 30:
            return ()
        return ((30.0, RideState(
            "bus", "fixture-day", "same-run", "fixture-bus", 1, 1, 30.0,
            trip_id="same-trip", route_id="fixture-bus",
        )),)

    def ride_options(self, u, v, current, state):
        return ((35.0, replace(state, sequence=2)),)


def _advance_time(u, v, current, edge):
    if "arrival" in edge:
        return edge["arrival"]
    return current + edge.get("meters", 0.0) / 80.0


def _transit_finish(graph):
    graph.add_node(ORIGIN, mode="bus")
    graph.add_node(DESTINATION, mode="bus")
    graph.add_edge(HUB, ORIGIN, etype="board", w=5.0)
    graph.add_edge(ORIGIN, DESTINATION, etype="ride", mode="bus", w=0.8)
    graph.add_edge(DESTINATION, TARGET, etype="alight", w=0.0)


def _first_path(graph, *, max_expanded=None):
    search = labels.search_labels(
        graph, _WaitingChoices(), START, TARGET, mode="time", start_minute=0,
        max_search=1, max_visited=1000, max_travel_min=240,
        time_limit_sec=15, max_total_walk=3000, max_segment_walk=600,
        walk_speed=80, rail_boarding_minutes=2, advance_time=_advance_time,
        virtual_connections={}, edge_uses_rail=lambda u, v: False,
        max_expanded=max_expanded,
    )
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return next(search)
    finally:
        search.close()


class TokyoTimeDominanceTest(unittest.TestCase):
    def test_expensive_early_readiness_waits_for_same_run_within_expansion_budget(self):
        graph = nx.DiGraph()
        later_prefixes = 20
        # Later labels become successively cheaper and otherwise have equal
        # resources. Cost-based Pareto retention would expand all 20 hubs.
        for index in range(later_prefixes):
            branch = ("phys", f"late-{index}")
            graph.add_edge(START, branch, etype="approach", w=0, arrival=0)
            graph.add_edge(branch, HUB, etype="approach", w=1 / (index + 1),
                           arrival=6 + index)
        early = ("phys", "early")
        graph.add_edge(START, early, etype="approach", w=0, arrival=0)
        graph.add_edge(early, HUB, etype="approach", w=100, arrival=5)
        _transit_finish(graph)

        # 20 late branch nodes plus the six-node selected path. This is an
        # expansion budget, so actual stale heap pops still count separately.
        candidate = _first_path(graph, max_expanded=later_prefixes + 6)

        path = candidate["path"]
        self.assertEqual(path, [START, early, HUB, ORIGIN, DESTINATION, TARGET])
        self.assertEqual(path.edge_times, [0, 5, 30.0, 35.0, 35.0])
        self.assertEqual(path.arrival_minute, 35.0)
        self.assertEqual(path.edge_rides[2].run_id, "same-run")
        self.assertEqual(path.edge_rides[2].trip_id, "same-trip")
        self.assertEqual(candidate["walk_m"], 0.0)
        self.assertAlmostEqual(candidate["cost"], 105.8)

    def test_equal_readiness_keeps_cheaper_later_generated_prefix(self):
        graph = nx.DiGraph()
        expensive = ("phys", "expensive-first")
        cheap = ("phys", "cheap-second")
        for branch, cost in ((expensive, 100.0), (cheap, 0.0)):
            graph.add_edge(START, branch, etype="approach", w=0, arrival=0)
            graph.add_edge(branch, HUB, etype="approach", w=cost, arrival=5)
        _transit_finish(graph)

        candidate = _first_path(graph)

        self.assertEqual(candidate["path"],
                         [START, cheap, HUB, ORIGIN, DESTINATION, TARGET])
        self.assertEqual(candidate["path"].arrival_minute, 35.0)
        self.assertAlmostEqual(candidate["cost"], 5.8)
        self.assertEqual(candidate["path"].edge_rides[2].trip_id, "same-trip")

    def test_earlier_readiness_with_more_consecutive_walk_cannot_remove_feasible_prefix(self):
        graph = nx.DiGraph()
        later = ("phys", "later-fresh-walk")
        graph.add_edge(START, HUB, etype="walk", meters=100.0, w=1.875)
        graph.add_edge(START, later, etype="approach", w=100.0, arrival=0)
        graph.add_edge(later, HUB, etype="approach", w=0.0, arrival=2)
        graph.add_edge(HUB, TARGET, etype="walk", meters=550.0, w=10.3125)

        candidate = _first_path(graph)

        # The 1.25-minute cheap arrival would require a 650m walk segment.
        # The later prefix has an untouched segment and can walk the 550m.
        self.assertEqual(candidate["path"], [START, later, HUB, TARGET])
        self.assertEqual(candidate["path"].arrival_minute, 8.875)
        self.assertEqual(candidate["walk_m"], 550.0)


if __name__ == "__main__":
    unittest.main()
