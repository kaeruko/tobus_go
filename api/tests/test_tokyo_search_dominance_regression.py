"""Feasible routes must survive cheaper labels with worse future resources.

These regressions cover the former candidate-loss bug in all three objectives.
Fixtures use local synthetic data and the unchanged production costs
and walking limits; no benchmark module or external data is required.
"""

import contextlib
import io
import unittest

import networkx as nx

import toei_engine as engine


class _Timetable:
    def __init__(self, departures=None, last_bus_departure=None):
        self.departures = departures or {}
        self.last_bus_departure = last_bus_departure

    def get_next_bus_departure(self, pole_id, route_id, current_time_min, **kwargs):
        departure = self.departures.get(route_id, current_time_min)
        if self.last_bus_departure is not None and route_id.endswith("-4"):
            departure = self.last_bus_departure
        return (departure, route_id) if current_time_min <= departure else (None, None)

    def get_next_train_arrival(self, current_sta, next_sta, current_time_min, **kwargs):
        # FIFO: either prefix can wait for this train if it arrives in time.
        return 20 * 60 + 55 if current_time_min <= 20 * 60 + 50 else None


def _physical(graph, name):
    node = ("phys", name)
    graph.add_node(node, name=name)
    return node


def _walk(graph, left, right, meters):
    graph.add_edge(
        left, right, etype="walk", meters=meters,
        w=engine.WALK_COST * max(1.0, meters / engine.WALK_SPEED_M_PER_MIN),
    )


def _bus_leg(graph, start, end, route, ride_edges=1):
    line_nodes = [("line", f"{route}-stop-{index}", route)
                  for index in range(ride_edges + 1)]
    for node in line_nodes:
        graph.add_node(node, name=node[1], mode="bus", route_id=route)
    graph.add_edge(start, line_nodes[0], etype="board", w=engine.TRANSFER_PENALTY)
    for left, right in zip(line_nodes, line_nodes[1:]):
        graph.add_edge(left, right, etype="ride", mode="bus", w=engine.BUS_RIDE_COST)
    graph.add_edge(line_nodes[-1], end, etype="alight", w=0.0)
    return [start, *line_nodes, end]


def _total_walk_branch(graph, start, merge, name, walk_m, extra_rides):
    path = [start]
    for segment in range(5):
        midpoint = _physical(graph, f"{name}-walk-{segment}-mid")
        board_at = _physical(graph, f"{name}-walk-{segment}-end")
        _walk(graph, path[-1], midpoint, walk_m / 10)
        _walk(graph, midpoint, board_at, walk_m / 10)
        path.extend((midpoint, board_at))
        end = merge if segment == 4 else _physical(graph, f"{name}-alight-{segment}")
        # Extra ride edges offset the shorter branch's smaller walking cost.
        leg = _bus_leg(graph, board_at, end, f"{name}-{segment}",
                       1 + (extra_rides if segment == 0 else 0))
        path.extend(leg[1:])
    return path


def _walking_branch(graph, start, merge, name, lengths):
    path = [start]
    for index, meters in enumerate(lengths):
        following = merge if index == len(lengths) - 1 else _physical(graph, f"{name}-{index}")
        _walk(graph, path[-1], following, meters)
        path.append(following)
    return path


def _prefix_state(graph, manager, path):
    state = {"cost": 0.0, "time": engine.time_str_to_min("20:40"),
             "total_walk": 0.0, "seg_walk": 0.0, "boardings": 0}
    for left, right in zip(path, path[1:]):
        edge = graph[left][right]
        state["cost"] += edge["w"]
        if edge["etype"] == "walk":
            state["total_walk"] += edge["meters"]
            state["seg_walk"] += edge["meters"]
        else:
            state["seg_walk"] = 0.0
        state["boardings"] += edge["etype"] == "board"
        state["time"] = engine.advance_time(
            graph, manager, left, right, state["time"], use_realtime=False, edge=edge,
        )
    return state


def _search(graph, manager, start, target, search=engine.find_few_transfers_paths_generator):
    with contextlib.redirect_stdout(io.StringIO()):
        return list(search(
            graph, manager, start, target, start_time_str="20:40", use_realtime=False,
        ))


class TokyoSearchDominanceRegressionTest(unittest.TestCase):
    def _graph(self):
        graph = nx.DiGraph()
        return graph, *(_physical(graph, name) for name in ("start", "merge", "target"))

    def _assert_feasible_branch_survives(self, graph, manager, cheap_path, feasible_path,
                                       walk_m, reason):
        # The control removes only the cheaper prefix's private nodes, keeping
        # the feasible itinerary and its downstream edges identical.
        control = graph.copy()
        control.remove_nodes_from(cheap_path[1:-1])
        start, target = feasible_path[0], feasible_path[-1]
        self.assertLessEqual(walk_m, engine.MAX_TOTAL_WALK_M)
        for search in (engine.find_few_transfers_paths_generator,
                       engine.find_paths_generator):
            with self.subTest(mode=search.__name__):
                control_results = _search(control, manager, start, target, search)
                self.assertEqual(len(control_results), 1, "control itinerary must be feasible")
                self.assertEqual(control_results[0]["path"], feasible_path)
                self.assertAlmostEqual(control_results[0]["walk_m"], walk_m)
                results = _search(graph, manager, start, target, search)
                self.assertTrue(
                    any(candidate["path"] == feasible_path for candidate in results),
                    f"Cheaper {reason} prefix must not remove the only feasible itinerary",
                )
        with self.subTest(mode="time"), contextlib.redirect_stdout(io.StringIO()):
            for fixture in (control, graph):
                arrival, path = engine.find_fastest_path(
                    fixture, manager, start, target, start_time_str="20:40", use_realtime=False,
                )
                self.assertIsNotNone(arrival)
                self.assertEqual(path, feasible_path)

    def test_higher_cost_early_arrival_can_catch_last_train(self):
        graph, start, merge, target = self._graph()
        cheap = _bus_leg(graph, start, merge, "late-cheap")
        early = _bus_leg(graph, start, merge, "early-extra-stop", ride_edges=2)
        rail_start, rail_end = ("line", "merge", "rail"), ("line", "target", "rail")
        for node in (rail_start, rail_end):
            graph.add_node(node, name=node[1], mode="rail")
        graph.add_edge(merge, rail_start, etype="board", w=engine.TRANSFER_PENALTY)
        graph.add_edge(rail_start, rail_end, etype="ride", mode="rail", w=engine.RAIL_RIDE_COST)
        graph.add_edge(rail_end, target, etype="alight", w=0.0)
        manager = _Timetable({"late-cheap": 20 * 60 + 55, "early-extra-stop": 20 * 60 + 41})

        cheap_state = _prefix_state(graph, manager, cheap)
        early_state = _prefix_state(graph, manager, early)
        self.assertLess(cheap_state["cost"], early_state["cost"])
        self.assertAlmostEqual(cheap_state["time"], 20 * 60 + 58.5)
        self.assertAlmostEqual(early_state["time"], 20 * 60 + 47)
        for resource in ("boardings", "total_walk", "seg_walk"):
            self.assertEqual(cheap_state[resource], early_state[resource])
        for prefix_time, catches_train in ((cheap_state["time"], False), (early_state["time"], True)):
            ready = engine.advance_time(graph, manager, merge, rail_start, prefix_time, use_realtime=False)
            arrival = engine.advance_time(graph, manager, rail_start, rail_end, ready, use_realtime=False)
            self.assertEqual(arrival is not None, catches_train)

        self._assert_feasible_branch_survives(
            graph, manager, cheap, [*early, rail_start, rail_end, target],
            walk_m=0.0, reason="late-arriving",
        )

    def test_higher_cost_shorter_total_walk_can_finish_within_3000_m(self):
        graph, start, merge, target = self._graph()
        cheap = _total_walk_branch(graph, start, merge, "cheap-long", 2600, extra_rides=0)
        short = _total_walk_branch(graph, start, merge, "dearer-short", 2300, extra_rides=8)
        _walk(graph, merge, target, 500)
        # Waiting for the same final departure isolates total walk from time.
        manager = _Timetable(last_bus_departure=21 * 60 + 50)
        cheap_state = _prefix_state(graph, manager, cheap)
        short_state = _prefix_state(graph, manager, short)
        self.assertLess(cheap_state["cost"], short_state["cost"])
        self.assertEqual(cheap_state["time"], short_state["time"])
        self.assertEqual(cheap_state["boardings"], short_state["boardings"])
        self.assertEqual(cheap_state["boardings"], 5)
        self.assertEqual(cheap_state["seg_walk"], short_state["seg_walk"])
        self.assertEqual(short_state["seg_walk"], 0)
        self.assertEqual(cheap_state["total_walk"], 2600)
        self.assertEqual(short_state["total_walk"], 2300)
        self.assertGreater(cheap_state["total_walk"] + 500, engine.MAX_TOTAL_WALK_M)
        self.assertLessEqual(short_state["total_walk"] + 500, engine.MAX_TOTAL_WALK_M)
        self.assertLessEqual(500, engine.MAX_WALK_SEG_M)

        self._assert_feasible_branch_survives(
            graph, manager, cheap, [*short, target], walk_m=2800, reason="longer-total-walk",
        )

    def test_same_walk_bucket_keeps_shorter_exact_segment(self):
        graph, start, merge, target = self._graph()
        cheap = _walking_branch(graph, start, merge, "cheap-long", (199, 200, 200))
        # The production one-minute walking cost floor makes this shorter
        # prefix slightly dearer, without changing the actual walked meters.
        short = _walking_branch(graph, start, merge, "dearer-short", (40, 268, 268))
        _walk(graph, merge, target, 10)
        manager = _Timetable()
        cheap_state = _prefix_state(graph, manager, cheap)
        short_state = _prefix_state(graph, manager, short)
        self.assertLess(cheap_state["cost"], short_state["cost"])
        self.assertEqual(cheap_state["boardings"], short_state["boardings"])
        self.assertEqual(cheap_state["seg_walk"], 599)
        self.assertEqual(short_state["seg_walk"], 576)
        self.assertEqual(int(cheap_state["seg_walk"] // 25), 23)
        self.assertEqual(int(short_state["seg_walk"] // 25), 23)
        self.assertGreater(cheap_state["seg_walk"] + 10, engine.MAX_WALK_SEG_M)
        self.assertLessEqual(short_state["seg_walk"] + 10, engine.MAX_WALK_SEG_M)
        self.assertLessEqual(cheap_state["total_walk"] + 10, engine.MAX_TOTAL_WALK_M)

        self._assert_feasible_branch_survives(
            graph, manager, cheap, [*short, target], walk_m=586, reason="longer-walk-segment",
        )


if __name__ == "__main__":
    unittest.main()
