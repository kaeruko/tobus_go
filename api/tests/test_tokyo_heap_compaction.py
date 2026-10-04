"""Queue compaction preserves every live label and its selected itinerary.

The fan-in fixture offers successively cheaper labels at the same hub, leaving
many obsolete entries queued before the first transit departure. Tests compare
the complete five-candidate result with uncompacted, sufficiently funded search.
"""

import contextlib
from dataclasses import asdict, replace
import heapq
import io
import re
import unittest
from unittest.mock import patch

import networkx as nx

from route_engine import RouteSearchLimitError
import tokyo_search_labels as labels
from tokyo_timetable_choices import RideState


START = ("phys", "start")
HUB = ("phys", "hub")
TARGET = ("phys", "target")


class _Choices:
    can_wait_offboard = True
    use_realtime = False
    manager = object()

    def __init__(self, graph):
        self.graph = graph

    def board_options(self, u, v, ready):
        if ready > 10:
            return ()
        index = self.graph.nodes[v]["index"]
        return ((10.0, RideState(
            "bus", "fixture-day", f"run-{index}", v[2], 1, 1, 10.0,
            trip_id=f"trip-{index}", route_id=f"route-{index}",
        )),)

    def ride_options(self, u, v, current, state):
        meters = self.graph.nodes[v]["meters"]
        return ((20.0 - meters / 80.0, replace(state, sequence=2)),)


def _advance_time(u, v, current, edge):
    return current + edge.get("meters", 0.0) / 80.0


def _fan_in_graph(branches=10_000):
    graph = nx.DiGraph()
    graph.add_nodes_from((START, HUB, TARGET))
    for index in range(branches):
        branch = ("phys", f"branch-{index}")
        approach_cost = index / 1000.0
        graph.add_edge(START, branch, etype="approach", w=approach_cost)
        graph.add_edge(branch, HUB, etype="approach", w=100.0 - 2 * approach_cost)
    for index in range(5):
        origin = ("line", "hub", f"line-{index}")
        destination = ("line", f"finish-{index}", f"line-{index}")
        finish = ("phys", f"finish-{index}")
        meters = 25.0 * (index + 1)
        graph.add_node(origin, mode="bus", index=index)
        graph.add_node(destination, mode="bus", meters=meters)
        graph.add_edge(HUB, origin, etype="board", w=50.0)
        graph.add_edge(origin, destination, etype="ride", mode="bus", w=1.0)
        graph.add_edge(destination, finish, etype="alight", w=0.0)
        graph.add_edge(finish, TARGET, etype="walk", meters=meters, w=1.0)
    return graph


def _search(graph, mode="cost", max_visited=30_000, advance_time=_advance_time):
    return labels.search_labels(
        graph, _Choices(graph), START, TARGET, mode=mode, start_minute=0.0,
        max_search=5, max_visited=max_visited, max_travel_min=240,
        time_limit_sec=15.0, max_total_walk=3000.0, max_segment_walk=600.0,
        walk_speed=80.0, rail_boarding_minutes=2.0, advance_time=advance_time,
        virtual_connections={}, edge_uses_rail=lambda u, v: False,
    )


def _snapshot(candidates):
    return [{
        "cost": candidate["cost"],
        "walk_m": candidate["walk_m"],
        "nodes": list(candidate["path"]),
        "edge_times": list(candidate["path"].edge_times),
        "selected_rides": [
            (index, asdict(ride))
            for index, ride in sorted(candidate["path"].edge_rides.items())
        ],
    } for candidate in candidates]


class TokyoHeapCompactionTest(unittest.TestCase):
    def test_compaction_keeps_original_entries_and_parent_frontier_references(self):
        frontier = labels._Frontier(TARGET, "cost", True)
        old_parent = labels._Label("parent", 3.0, 10.0, 0.0, 0.0, 0)
        self.assertTrue(frontier.add(old_parent))
        child = labels._Label("child", 5.0, 12.0, 0.0, 0.0, 0, parent=old_parent)
        expanded = labels._Label("expanded", 2.0, 9.0, 0.0, 0.0, 0, expanded=True)
        replacement = labels._Label("parent", 2.0, 10.0, 0.0, 0.0, 0)
        tied = labels._Label("tied", 5.0, 12.0, 0.0, 0.0, 0)
        for label in (child, expanded, replacement, tied):
            self.assertTrue(frontier.add(label))
        self.assertFalse(old_parent.active)
        child_entry = ((5.0, 5.0, 12.0), 10, child)
        tied_entry = ((5.0, 5.0, 12.0), 2, tied)
        replacement_entry = ((2.0, 2.0, 10.0), 8, replacement)
        queue = [child_entry, tied_entry, replacement_entry,
                 ((3.0, 3.0, 10.0), 1, old_parent),
                 ((2.0, 2.0, 9.0), 0, expanded)]
        heapq.heapify(queue)
        count_before = frontier.count
        groups_before = {key: tuple(group) for key, group in frontier.labels.items()}

        removed = labels._compact_queue(queue)

        self.assertEqual(removed, 2)
        self.assertEqual(len(queue), 3)
        for original_entry in (child_entry, tied_entry, replacement_entry):
            self.assertTrue(any(entry is original_entry for entry in queue))
        self.assertIs(child.parent, old_parent)
        self.assertFalse(old_parent.active)
        self.assertTrue(expanded.expanded)
        self.assertEqual(frontier.count, count_before)
        self.assertEqual(
            {key: tuple(group) for key, group in frontier.labels.items()}, groups_before,
        )
        self.assertEqual([heapq.heappop(queue)[2] for _ in range(3)],
                         [replacement, tied, child])

    def test_compaction_finishes_same_five_candidates_within_original_pop_budget(self):
        graph = _fan_in_graph()
        for mode in ("cost", "fewTransfers", "time"):
            with self.subTest(mode=mode):
                baseline_log = io.StringIO()
                with patch.object(labels, "_compact_queue", lambda queue: 0, create=True), \
                        contextlib.redirect_stdout(baseline_log):
                    baseline = list(_search(graph, mode=mode))
                self.assertEqual(len(baseline), 5)
                baseline_visits = re.findall(r"visited=(\d+)", baseline_log.getvalue())
                self.assertEqual(int(baseline_visits[-1]), 20_021)
                self.assertEqual(
                    [candidate["path"].edge_rides[2].run_id for candidate in baseline],
                    ["run-4", "run-3", "run-2", "run-1", "run-0"],
                )
                # The same 15,000-pop budget aborts the uncompacted fixture.
                with patch.object(labels, "_compact_queue", lambda queue: 0, create=True), \
                        contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(RouteSearchLimitError, "reason=max_visited"):
                        list(_search(graph, mode=mode, max_visited=15_000))

                compacted_log = io.StringIO()
                with contextlib.redirect_stdout(compacted_log):
                    compacted = list(_search(graph, mode=mode, max_visited=15_000))
                self.assertEqual(_snapshot(compacted), _snapshot(baseline))
                compacted_visits = re.findall(r"visited=(\d+)", compacted_log.getvalue())
                self.assertLessEqual(int(compacted_visits[-1]), 15_000)

    def test_compaction_time_is_charged_to_existing_fifteen_second_limit(self):
        graph = _fan_in_graph()
        compact = getattr(labels, "_compact_queue", None)
        self.assertIsNotNone(compact, "Search must expose its queue compaction helper")
        clock = {"now": 0.0}

        def expensive_compaction(queue):
            removed = compact(queue)
            clock["now"] = 16.0
            return removed

        def guarded_time(u, v, current, edge):
            self.assertLess(
                clock["now"], 15.0,
                "Search must recheck time after compaction before expanding another label",
            )
            return _advance_time(u, v, current, edge)

        with patch.object(labels.time, "monotonic", side_effect=lambda: clock["now"]), \
                patch.object(labels, "_compact_queue", side_effect=expensive_compaction) as called, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RouteSearchLimitError, "reason=time_limit_sec"):
                list(_search(graph, advance_time=guarded_time))
        self.assertGreater(called.call_count, 0)

    def test_max_visited_remains_actual_heap_pop_count(self):
        # Leave this tiny fixture uncompacted to check that a stale entry
        # which really is popped still consumes the existing safety budget.
        graph = _fan_in_graph(branches=2)
        real_pop = heapq.heappop
        popped_entries = []

        def counted_pop(queue):
            entry = real_pop(queue)
            popped_entries.append(entry)
            return entry

        with patch.object(labels.heapq, "heappop", side_effect=counted_pop), \
                patch.object(labels, "_compact_queue", lambda queue: 0, create=True), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RouteSearchLimitError, "reason=max_visited visited=5"):
                list(_search(graph, max_visited=4))
        self.assertEqual(len(popped_entries), 5)
        self.assertFalse(popped_entries[-1][2].active)


if __name__ == "__main__":
    unittest.main()
