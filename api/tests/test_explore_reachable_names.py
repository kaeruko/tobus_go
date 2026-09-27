import unittest
from types import SimpleNamespace

import networkx as nx

from toei_engine import get_reachable_stops


class ExploreReachableNamesTest(unittest.TestCase):
    def _graph(self):
        graph = nx.DiGraph()
        graph.add_node(
            ("phys", "A"),
            lat=35.0000,
            lon=139.0000,
            name="押上駅前",
            name_en="Oshiage Sta.",
            kind="phys",
        )
        graph.add_node(
            ("phys", "B"),
            lat=35.0100,
            lon=139.0000,
            name="業平橋",
            name_en="Narihira-bashi",
            kind="phys",
        )
        return graph

    def test_reachable_response_exposes_official_english_names(self):
        graph = self._graph()
        timetable = SimpleNamespace(route_patterns_map={"R1": [["A", "B"]]})

        result = get_reachable_stops(
            graph,
            timetable,
            35.0000,
            139.0000,
        )

        self.assertTrue(result["found"])
        self.assertEqual(result["nearest_stop"]["name"], "押上駅前")
        self.assertEqual(result["nearest_stop"]["name_en"], "Oshiage Sta.")
        self.assertEqual(result["reachable_stops"][0]["name"], "業平橋")
        self.assertEqual(
            result["reachable_stops"][0]["name_en"],
            "Narihira-bashi",
        )

    def test_missing_official_english_name_fails_fast(self):
        graph = self._graph()
        del graph.nodes[("phys", "B")]["name_en"]
        timetable = SimpleNamespace(route_patterns_map={"R1": [["A", "B"]]})

        with self.assertRaises(KeyError):
            get_reachable_stops(
                graph,
                timetable,
                35.0000,
                139.0000,
            )


if __name__ == "__main__":
    unittest.main()
