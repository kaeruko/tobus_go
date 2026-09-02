import unittest
from types import SimpleNamespace
from unittest.mock import patch

import networkx as nx

from app.routes import compute_route_candidates


class InitialWalkCandidateMetricsTest(unittest.TestCase):
    def setUp(self):
        self.origin = ("phys", "origin")
        self.destination = ("phys", "destination")
        self.virtual_destination = ("phys", "dest:test")
        self.graph = nx.DiGraph()
        self.graph.add_node(
            self.origin,
            name="平井七丁目",
            lat=35.7100,
            lon=139.8400,
        )
        self.graph.add_node(
            self.destination,
            name="池袋駅東口",
            lat=35.7300,
            lon=139.7100,
        )
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                G=self.graph,
                TM=object(),
                WALK_RAD=500,
                SI=object(),
            )
        )

    def _compute(self, candidate):
        nearest_results = [
            (self.origin, 120.8),
            (self.destination, 10.0),
        ]
        with (
            patch("app.routes.nearest_phys", side_effect=nearest_results),
            patch(
                "app.routes.get_virtual_connections",
                return_value=(self.virtual_destination, [(self.destination, 1.0, 10.0)]),
            ),
            patch("app.routes.determine_day_type", return_value="weekday"),
            patch("app.routes.search_best_routes_once", return_value=[candidate]),
            patch("app.routes.haversine", return_value=10.0),
            patch("app.routes.assign_candidate_step_ids"),
        ):
            return compute_route_candidates(
                self.app,
                35.7110,
                139.8410,
                35.7300,
                139.7100,
                "fewTransfers",
                start_time="06:30",
                date_str="2026-09-03",
            )["candidates"][0]

    def test_existing_first_walk_updates_canonical_distance_without_new_segment(self):
        candidate = {
            "steps": [
                {
                    "kind": "walk",
                    "title": "徒歩",
                    "from_": "平井七丁目",
                    "to": "平井駅前",
                    "meters": 50,
                    "minutes": 1,
                    "edges": 1,
                }
            ],
            "points": [[35.7100, 139.8400]],
            "total_time": 10,
            "walking_distance_meters": 50,
            "walking_segment_count": 1,
            "path": [self.origin],
        }

        result = self._compute(candidate)

        self.assertEqual(result["steps"][0]["from_"], "現在地")
        self.assertEqual(result["steps"][0]["meters"], 170)
        self.assertEqual(result["steps"][0]["minutes"], 3)
        self.assertEqual(result["walking_distance_meters"], 170)
        self.assertEqual(result["walking_segment_count"], 1)
        self.assertEqual(result["total_time"], 12)
        self.assertNotIn("walk_m", result)

    def test_new_first_walk_updates_distance_and_segment_count(self):
        candidate = {
            "steps": [
                {
                    "kind": "bus",
                    "title": "上23",
                    "from_": "平井七丁目",
                    "to": "上野松坂屋前",
                    "minutes": 20,
                }
            ],
            "points": [[35.7100, 139.8400]],
            "total_time": 20,
            "walking_distance_meters": 0,
            "walking_segment_count": 0,
            "path": [self.origin],
        }

        result = self._compute(candidate)

        first = result["steps"][0]
        self.assertEqual(first["kind"], "walk")
        self.assertEqual(first["from_"], "現在地")
        self.assertEqual(first["to"], "平井七丁目")
        self.assertEqual(first["meters"], 120)
        self.assertEqual(first["minutes"], 2)
        self.assertEqual(result["walking_distance_meters"], 120)
        self.assertEqual(result["walking_segment_count"], 1)
        self.assertEqual(result["total_time"], 22)
        self.assertNotIn("walk_m", result)


if __name__ == "__main__":
    unittest.main()
