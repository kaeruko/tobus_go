import unittest
from unittest.mock import patch

import networkx as nx

import toei_engine as engine


GENERATORS = (
    engine.find_paths_generator,
    engine.find_few_transfers_paths_generator,
)
SEARCHES = GENERATORS + (engine.find_fastest_path,)


def _search(search, graph, manager, start, target, **kwargs):
    if search is engine.find_fastest_path:
        arrival, path = search(graph, manager, start, target, **kwargs)
        return [] if path is None else [{"path": path, "arrival": arrival}]
    return list(search(graph, manager, start, target, **kwargs))


def _manager(departures):
    manager = engine.TimetableManager()
    manager.bus_departures_weekday = {
        pole: {
            "bus": [{"dep": minute, "trip": "trip", "dest": None}]
            if minute is not None else []
        }
        for pole, minute in departures.items()
    }
    return manager


class TokyoSearchPerformanceTest(unittest.TestCase):
    def setUp(self):
        self.start = ("phys", "start")
        self.target = ("phys", "target")
        self.first = ("phys", "first")
        self.second = ("phys", "second")
        self.line = ("line", "shared-bus")

    def _fork_graph(self, second_cost=2.0):
        graph = nx.DiGraph()
        for node in (self.start, self.target, self.first, self.second):
            graph.add_node(node, name=node[1])
        graph.add_node(self.line, mode="bus", route_id="bus")
        graph.add_edge(self.start, self.first, etype="walk", meters=10, w=1.0)
        graph.add_edge(
            self.start, self.second, etype="walk", meters=10, w=second_cost
        )
        graph.add_edge(self.first, self.line, etype="board", w=0.0)
        graph.add_edge(self.second, self.line, etype="board", w=0.0)
        graph.add_edge(self.line, self.target, etype="alight", w=0.25)
        return graph

    def test_boarding_comparison_checks_both_clocks_before_pruning(self):
        for search in GENERATORS:
            for second_cost in (1.0, 2.0):
                with self.subTest(search=search.__name__, second_cost=second_cost):
                    graph = self._fork_graph(second_cost)
                    manager = _manager({"first": 610, "second": 611})
                    with patch.object(
                        manager,
                        "get_next_bus_departure",
                        wraps=manager.get_next_bus_departure,
                    ) as departure:
                        results = _search(search, graph, manager, self.start, self.target)

                    # Different boarding stops are distinct itineraries even
                    # when their final walking distances are equal.
                    self.assertEqual(len(results), 2)
                    self.assertEqual(
                        results[0],
                        {
                            "cost": 1.25,
                            "path": [self.start, self.first, self.line, self.target],
                            "walk_m": 10.0,
                        },
                    )
                    self.assertEqual(results[1], {
                        "cost": second_cost + 0.25,
                        "path": [self.start, self.second, self.line, self.target],
                        "walk_m": 10.0,
                    })
                    # Equal/greater cost alone cannot establish dominance:
                    # the other boarding may catch a different departure.
                    self.assertEqual([call.args[0] for call in departure.call_args_list], ["first", "second"])

    def test_failed_time_evaluation_does_not_block_later_boarding(self):
        for search in GENERATORS:
            for first_departure in (None, 850):
                with self.subTest(search=search.__name__, first_departure=first_departure):
                    graph = self._fork_graph()
                    manager = _manager({"first": first_departure, "second": 610})
                    with patch.object(
                        manager,
                        "get_next_bus_departure",
                        wraps=manager.get_next_bus_departure,
                    ) as departure:
                        results = _search(search, graph, manager, self.start, self.target)

                    self.assertEqual(
                        results,
                        [{
                            "cost": 2.25,
                            "path": [self.start, self.second, self.line, self.target],
                            "walk_m": 10.0,
                        }],
                    )
                    self.assertEqual(
                        [call.args[0] for call in departure.call_args_list],
                        ["first", "second"],
                    )

    def test_segment_walk_limit_rejects_edge_before_time_evaluation(self):
        for search in SEARCHES:
            for final_meters in (1.0, 0.0, -10.0):
                with self.subTest(search=search.__name__, final_meters=final_meters):
                    graph = nx.DiGraph()
                    graph.add_edge(self.start, self.first, etype="walk", meters=600, w=1.0)
                    graph.add_edge(self.first, self.target, etype="walk", meters=final_meters, w=1.0)
                    with patch("toei_engine.advance_time", wraps=engine.advance_time) as advance:
                        results = _search(search, graph, object(), self.start, self.target)

                    self.assertEqual(results, [])
                    self.assertEqual(
                        [(call.args[2], call.args[3]) for call in advance.call_args_list],
                        [(self.start, self.first)],
                    )

    def test_total_walk_limit_survives_segment_reset_and_skips_time_evaluation(self):
        graph = nx.DiGraph()
        graph.add_edge(self.start, self.first, etype="walk", meters=100, w=1.0)
        graph.add_edge(self.first, self.second, etype="xfer", w=0.0)
        graph.add_edge(self.second, self.target, etype="walk", meters=1, w=1.0)
        for search in SEARCHES:
            with self.subTest(search=search.__name__):
                with (
                    patch("toei_engine.MAX_TOTAL_WALK_M", 100.0),
                    patch("toei_engine.advance_time", wraps=engine.advance_time) as advance,
                ):
                    results = _search(search, graph, object(), self.start, self.target)

                self.assertEqual(results, [])
                self.assertEqual(
                    [(call.args[2], call.args[3]) for call in advance.call_args_list],
                    [(self.start, self.first), (self.first, self.second)],
                )

    def test_heuristic_is_cached_only_for_one_search(self):
        graph = nx.DiGraph()
        for node, lat in ((self.start, 35.0), (self.first, 36.0), (self.second, 37.0), (self.target, 38.0)):
            graph.add_node(node, lat=lat, lon=139.0)
        graph.add_edge(self.start, self.first, etype="xfer", w=10.0)
        graph.add_edge(self.start, self.second, etype="xfer", w=1.0)
        graph.add_edge(self.second, self.first, etype="xfer", w=1.0)
        graph.add_edge(self.first, self.target, etype="xfer", w=1.0)
        for lat in (36.0, 39.0):
            with self.subTest(lat=lat):
                graph.nodes[self.first]["lat"] = lat
                with patch("toei_engine.haversine", return_value=0.0) as distance:
                    results = _search(engine.find_paths_generator, graph, object(), self.start, self.target)

                self.assertEqual(
                    results,
                    [{"cost": 3.0, "path": [self.start, self.second, self.first, self.target], "walk_m": 0.0}],
                )
                self.assertEqual(
                    sum(call.args[0] == lat for call in distance.call_args_list),
                    1,
                )

    def test_bus_only_with_virtual_destination_keeps_path_and_arrival(self):
        end = ("phys", "end")
        destination = ("phys", "dest:35.68,139.76")
        bus_to = ("line", "bus-to")
        rail_from, rail_to = ("line", "rail-from"), ("line", "rail-to")
        graph = nx.DiGraph()
        graph.add_node(self.start, name="start")
        graph.add_node(end, name="end")
        for node, mode in ((self.line, "bus"), (bus_to, "bus"), (rail_from, "rail"), (rail_to, "rail")):
            graph.add_node(node, mode=mode, route_id="bus")
        graph.add_edge(self.start, rail_from, etype="board", w=0.0)
        graph.add_edge(rail_from, rail_to, etype="ride", mode="rail", w=0.5)
        graph.add_edge(rail_to, end, etype="alight", w=0.0)
        graph.add_edge(self.start, self.line, etype="board", w=1.0)
        graph.add_edge(self.line, bus_to, etype="ride", mode="bus", meters=1000, w=0.5)
        graph.add_edge(bus_to, end, etype="alight", w=0.0)
        for search in SEARCHES:
            with self.subTest(search=search.__name__):
                manager = _manager({"start": 600})
                with patch.object(manager, "get_next_train_arrival", side_effect=AssertionError("bus-only search evaluated rail")):
                    results = _search(
                        search, graph, manager, self.start, destination,
                        bus_only=True, virtual_dest_connections=[(end, 1.875, 100.0)],
                    )

                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["path"], [self.start, self.line, bus_to, end, destination])
                if search is engine.find_fastest_path:
                    self.assertAlmostEqual(results[0]["arrival"], 607.05)
                else:
                    self.assertEqual(results[0]["cost"], 3.375)
                    self.assertEqual(results[0]["walk_m"], 100.0)

    def test_advance_time_accepts_prefetched_edge_and_preserves_direct_lookup(self):
        graph = nx.DiGraph()
        graph.add_edge(self.start, self.target, etype="walk", meters=160)
        self.assertEqual(engine.advance_time(graph, object(), self.start, self.target, 600), 602)
        self.assertEqual(engine.advance_time(graph, object(), self.target, self.start, 600), 600)
        edge = graph[self.start][self.target]
        with patch.object(graph, "has_edge", side_effect=AssertionError("prefetched edge looked up twice")):
            self.assertEqual(
                engine.advance_time(graph, object(), self.start, self.target, 600, edge=edge),
                602,
            )

    def test_direct_bus_departure_preserves_debug_argument_without_environment_reads(self):
        manager = _manager({"first": 610})
        for setting in ("0", "1", "first", "invalid"):
            for debug in (False, True):
                with self.subTest(setting=setting, debug=debug):
                    with (
                        patch.dict("os.environ", {"DEBUG_BUS": setting}),
                        patch("toei_engine.os.getenv", side_effect=AssertionError("unused DEBUG_BUS read")),
                    ):
                        self.assertEqual(
                            manager.get_next_bus_departure("first", "bus", 600, pole_name="first", debug=debug),
                            (610.0, "trip"),
                        )


if __name__ == "__main__":
    unittest.main()
