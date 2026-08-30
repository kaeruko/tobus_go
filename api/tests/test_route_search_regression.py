import datetime
import unittest
from unittest.mock import patch

import networkx as nx

from toei_engine import search_best_routes, search_best_routes_once


class _FakeTimetableManager:
    def get_delays_snapshot(self):
        return {}


class TokyoRouteSearchRegressionTest(unittest.TestCase):
    def setUp(self):
        self.origin = ("phys", "origin")
        self.line = ("line", "toei-bus-001")
        self.destination = ("phys", "destination")
        self.path = [self.origin, self.line, self.destination]

        self.graph = nx.DiGraph()
        self.graph.add_node(
            self.origin,
            name="東京駅丸の内北口",
            lat=35.6837,
            lon=139.7660,
        )
        self.graph.add_node(
            self.line,
            name="都01",
            lat=35.6800,
            lon=139.7600,
            mode="bus",
        )
        self.graph.add_node(
            self.destination,
            name="新橋駅前",
            lat=35.6663,
            lon=139.7586,
        )
        self.tm = _FakeTimetableManager()

        self.steps = [
            {
                "kind": "walk",
                "title": "徒歩",
                "from_": "現在地",
                "to": "東京駅丸の内北口",
                "meters": 80,
                "minutes": 1,
            },
            {
                "kind": "bus",
                "title": "都01",
                "from_": "東京駅丸の内北口",
                "to": "新橋駅前",
                "departure_time": "10:05",
                "arrival_time": "10:15",
                "minutes": 10,
                "route_id": "001",
                "trip_id": "trip-001",
            },
        ]

    def test_time_priority_contract_is_stable(self):
        with (
            patch(
                "toei_engine.find_fastest_path",
                return_value=(615, self.path),
            ),
            patch(
                "toei_engine.calculate_real_arrival_time",
                return_value=615,
            ),
            patch(
                "toei_engine.segments_detailed",
                return_value=self.steps,
            ),
        ):
            candidates = search_best_routes(
                self.graph,
                self.tm,
                self.origin,
                mode="time",
                start_time="10:00",
                limit=5,
                target_date=datetime.datetime(2026, 8, 21, 10, 0),
                target_node=self.destination,
                day_type="weekday",
            )

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["id"], "Fastest")
        self.assertEqual(candidate["lines"], ["都01"])
        self.assertEqual(candidate["total_time"], 15)
        self.assertEqual(candidate["arrival_time"], "10:15")
        self.assertEqual(candidate["transfers"], 0)
        self.assertEqual(candidate["rides"], 1)
        self.assertEqual(candidate["walking_distance_meters"], 80)
        self.assertEqual(candidate["walking_segment_count"], 1)
        self.assertEqual(candidate["boards"], 1)
        self.assertEqual(candidate["cost_score"], 0.0)
        self.assertEqual(candidate["steps"], self.steps)
        self.assertEqual(
            set(candidate),
            {
                "id",
                "lines",
                "total_time",
                "arrival_time",
                "steps",
                "score_label",
                "cost_score",
                "path",
                "points",
                "total",
                "transfers",
                "rides",
                "walking_distance_meters",
                "walking_segment_count",
                "boards",
            },
        )

    def test_few_transfers_uses_comfort_contract(self):
        with (
            patch(
                "toei_engine.find_paths_generator",
                return_value=iter(
                    [{"cost": 7.5, "path": self.path, "walk_m": 80}]
                ),
            ),
            patch(
                "toei_engine.calculate_real_arrival_time",
                return_value=615,
            ),
            patch(
                "toei_engine.segments_detailed",
                return_value=self.steps,
            ),
        ):
            candidates = search_best_routes(
                self.graph,
                self.tm,
                self.origin,
                mode="fewTransfers",
                start_time="10:00",
                limit=5,
                target_date=datetime.datetime(2026, 8, 21, 10, 0),
                target_node=self.destination,
                day_type="weekday",
            )

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["id"], "Comfort-1")
        self.assertEqual(candidate["lines"], ["都01"])
        self.assertEqual(candidate["total_time"], 15)
        self.assertEqual(candidate["arrival_time"], "10:15")
        self.assertEqual(candidate["cost_score"], 7.5)
        self.assertEqual(candidate["score_label"], "楽さ 7.5 (所要15分)")
        self.assertEqual(candidate["transfers"], 0)
        self.assertEqual(candidate["walking_distance_meters"], 80)
        self.assertEqual(candidate["walking_segment_count"], 1)

    def test_requested_departure_date_and_time_are_preserved(self):
        base_candidate = {
            "id": "Fastest",
            "steps": [],
        }
        with patch(
            "toei_engine.search_best_routes",
            return_value=[base_candidate],
        ) as search:
            result = search_best_routes_once(
                self.graph,
                self.tm,
                self.origin,
                mode="time",
                start_time="08:35",
                limit=5,
                target_date_str="2026-08-21",
                target_node=self.destination,
                day_type="weekday",
            )

        self.assertEqual(result[0]["departure_date"], "2026-08-21T08:35:00")
        self.assertFalse(result[0]["is_future_suggestion"])

        args = search.call_args.args
        self.assertEqual(args[3], "time")
        self.assertEqual(args[4], "08:35")
        self.assertEqual(args[5], 5)
        self.assertEqual(args[6], datetime.datetime(2026, 8, 21, 8, 35))


if __name__ == "__main__":
    unittest.main()
