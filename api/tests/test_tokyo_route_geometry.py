import unittest

import networkx as nx

from route_engine import RouteContractError
from tokyo_route_geometry import path_to_route_geometry


class TokyoRouteGeometryTest(unittest.TestCase):
    def setUp(self):
        self.graph = nx.DiGraph()
        self.origin = ("phys", "start")
        self.first = ("phys", "board")
        self.first_line = ("line", "board", "bus")
        self.middle_line = ("line", "middle", "bus")
        self.middle = ("phys", "middle")
        self.next_stop = ("phys", "transfer")
        self.second_line = ("line", "transfer", "rail")
        self.last_line = ("line", "end", "rail")
        self.end = ("phys", "end")
        for node, lat, lon in (
            (self.origin, 35.0, 139.0),
            (self.first, 35.001, 139.0),
            (self.first_line, 35.001, 139.0),
            (self.middle_line, 35.002, 139.0),
            (self.middle, 35.002, 139.0),
            (self.next_stop, 35.003, 139.0),
            (self.second_line, 35.003, 139.0),
            (self.last_line, 35.004, 139.0),
            (self.end, 35.004, 139.0),
        ):
            self.graph.add_node(node, lat=lat, lon=lon)
        self.graph.add_edge(self.origin, self.first, etype="walk", meters=100)
        self.graph.add_edge(self.first, self.first_line, etype="board")
        self.graph.add_edge(self.first_line, self.middle_line, etype="ride", mode="bus")
        self.graph.add_edge(self.middle_line, self.middle, etype="alight")
        self.graph.add_edge(self.middle, self.next_stop, etype="walk", meters=100)
        self.graph.add_edge(self.next_stop, self.second_line, etype="board")
        self.graph.add_edge(self.second_line, self.last_line, etype="ride", mode="rail")
        self.graph.add_edge(self.last_line, self.end, etype="alight")
        self.path = [
            self.origin, self.first, self.first_line, self.middle_line,
            self.middle, self.next_stop, self.second_line, self.last_line, self.end,
        ]

    def test_walk_and_ride_segments_do_not_merge_across_transfers(self):
        self.assertEqual(
            path_to_route_geometry(self.graph, self.path),
            [
                {"kind": "walk", "points": [[35.0, 139.0], [35.001, 139.0]]},
                {"kind": "bus", "points": [[35.001, 139.0], [35.002, 139.0]]},
                {"kind": "walk", "points": [[35.002, 139.0], [35.003, 139.0]]},
                {"kind": "rail", "points": [[35.003, 139.0], [35.004, 139.0]]},
            ],
        )

    def test_consecutive_ride_edges_keep_the_intermediate_stop(self):
        extra = ("line", "extra", "bus")
        self.graph.add_node(extra, lat=35.0015, lon=139.0)
        self.graph.remove_edge(self.first_line, self.middle_line)
        self.graph.add_edge(self.first_line, extra, etype="ride", mode="bus")
        self.graph.add_edge(extra, self.middle_line, etype="ride", mode="bus")
        index = self.path.index(self.middle_line)
        self.path.insert(index, extra)
        segments = path_to_route_geometry(self.graph, self.path)
        self.assertEqual(
            segments[1]["points"],
            [[35.001, 139.0], [35.0015, 139.0], [35.002, 139.0]],
        )

    def test_virtual_final_walk_is_explicit_and_not_assumed(self):
        destination = ("phys", "dest:35.0045,139.0005")
        with self.assertRaisesRegex(RouteContractError, "edge is absent"):
            path_to_route_geometry(self.graph, [*self.path, destination])
        segments = path_to_route_geometry(
            self.graph, [*self.path, destination],
            virtual_dest_connections=[(self.end, 1.0, 80.0)],
        )
        self.assertEqual(
            segments[-1],
            {"kind": "walk", "points": [[35.004, 139.0], [35.0045, 139.0005]]},
        )

    def test_invalid_coordinates_raise_instead_of_drawing_fake_geometry(self):
        self.graph.nodes[self.next_stop]["lat"] = float("nan")
        with self.assertRaisesRegex(RouteContractError, "unusable coordinates"):
            path_to_route_geometry(self.graph, self.path)

    def test_unsupported_ride_mode_raises(self):
        self.graph[self.first_line][self.middle_line]["mode"] = "ferry"
        with self.assertRaisesRegex(RouteContractError, "invalid mode"):
            path_to_route_geometry(self.graph, self.path)


if __name__ == "__main__":
    unittest.main()
