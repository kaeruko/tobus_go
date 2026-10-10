import datetime
import itertools
import unittest
from unittest.mock import patch

import networkx as nx

from route_engine import RouteContractError
from toei_engine import (
    RouteSearchLimitError,
    find_fastest_path,
    find_few_transfers_paths_generator,
    find_paths_generator,
    search_best_routes,
    search_best_routes_once,
    segments_detailed,
)


class _FakeTimetableManager:
    def get_delays_snapshot(self):
        return {}


class _BusOnlyTimetableManager:
    def get_next_bus_departure(
        self,
        pole_id,
        route_id,
        current_time_min,
        **kwargs,
    ):
        return current_time_min, "bus-trip"

    def get_next_train_arrival(
        self,
        current_sta,
        next_sta,
        current_time_min,
        **kwargs,
    ):
        return current_time_min + 1


class BusOnlyRouteSearchTest(unittest.TestCase):
    def setUp(self):
        self.origin = ("phys", "origin")
        self.destination = ("phys", "destination")
        self.rail_a = ("line", "rail-a")
        self.rail_b = ("line", "rail-b")
        self.bus_a = ("line", "bus-a")
        self.bus_b = ("line", "bus-b")

        self.graph = nx.DiGraph()
        self.graph.add_node(self.origin, name="origin")
        self.graph.add_node(self.destination, name="destination")
        self.graph.add_node(self.rail_a, mode="rail", name="rail")
        self.graph.add_node(self.rail_b, mode="rail", name="rail")
        self.graph.add_node(
            self.bus_a,
            mode="bus",
            name="bus",
            route_id="route-bus",
        )
        self.graph.add_node(
            self.bus_b,
            mode="bus",
            name="bus",
            route_id="route-bus",
        )

        self.graph.add_edge(self.origin, self.rail_a, etype="board", w=0)
        self.graph.add_edge(
            self.rail_a,
            self.rail_b,
            etype="ride",
            mode="rail",
            w=0,
        )
        self.graph.add_edge(self.rail_b, self.destination, etype="alight", w=0)

        self.graph.add_edge(self.origin, self.bus_a, etype="board", w=0)
        self.graph.add_edge(
            self.bus_a,
            self.bus_b,
            etype="ride",
            mode="bus",
            meters=1000,
            w=0,
        )
        self.graph.add_edge(self.bus_b, self.destination, etype="alight", w=0)

        self.tm = _BusOnlyTimetableManager()

    def test_normal_search_can_choose_rail(self):
        _, path = find_fastest_path(
            self.graph,
            self.tm,
            self.origin,
            self.destination,
            start_time_str="10:00",
        )
        self.assertIn(self.rail_a, path)
        self.assertNotIn(self.bus_a, path)

    def test_bus_only_search_excludes_rail_edges(self):
        _, path = find_fastest_path(
            self.graph,
            self.tm,
            self.origin,
            self.destination,
            start_time_str="10:00",
            bus_only=True,
        )
        self.assertIn(self.bus_a, path)
        self.assertNotIn(self.rail_a, path)


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
                "title_en": "Route To01 · Shimbashi Sta.",
                "from_": "東京駅丸の内北口",
                "from_en": "Tokyo Station Marunouchi North Exit",
                "to": "新橋駅前",
                "to_en": "Shimbashi Sta.",
                "departure_time": "10:05",
                "arrival_time": "10:15",
                "minutes": 10,
                "route_id": "001",
                "trip_id": "trip-001",
            },
        ]



    def test_same_name_walk_between_distinct_nodes_is_preserved(self):
        graph = nx.DiGraph()
        bus_stop = ("phys", "honjo-bus")
        station = ("phys", "honjo-station")
        graph.add_node(
            bus_stop,
            name="本所吾妻橋",
            lat=35.708438,
            lon=139.803502,
        )
        graph.add_node(
            station,
            name="本所吾妻橋",
            lat=35.708565,
            lon=139.804397,
        )
        graph.add_edge(
            bus_stop,
            station,
            etype="walk",
            meters=80.0,
            w=1.5,
        )

        steps = segments_detailed(
            graph,
            [bus_stop, station],
            self.tm,
            start_time_str="15:35",
        )

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["kind"], "walk")
        self.assertEqual(steps[0]["from_"], "本所吾妻橋")
        self.assertEqual(steps[0]["to"], "本所吾妻橋")
        self.assertEqual(steps[0]["meters"], 80.0)
        self.assertEqual(steps[0]["minutes"], 1)

    def test_same_name_consecutive_rail_stops_keep_distinct_ids(self):
        class _RailTimetableManager:
            def get_next_train_arrival(
                self,
                current_sta,
                next_sta,
                current_time_min,
                day_type=None,
                delays_snapshot=None,
                **kwargs,
            ):
                return current_time_min + 1

        graph = nx.DiGraph()
        origin = ("phys", "origin-station")
        same_a = ("phys", "same-a")
        same_b = ("phys", "same-b")
        line_origin = ("line", "origin-station", "test-line")
        line_same_a = ("line", "same-a", "test-line")
        line_same_b = ("line", "same-b", "test-line")

        graph.add_node(
            origin,
            name="起点",
            lat=35.70,
            lon=139.80,
            station_code="T01",
        )
        graph.add_node(
            same_a,
            name="同名駅",
            lat=35.701,
            lon=139.801,
            station_code="T02",
        )
        graph.add_node(
            same_b,
            name="同名駅",
            lat=35.702,
            lon=139.802,
            station_code="T03",
        )
        for node in (line_origin, line_same_a, line_same_b):
            graph.add_node(
                node,
                name="テスト線",
                disp="テスト線",
                mode="rail",
            )

        graph.add_edge(origin, line_origin, etype="board", w=1.0)
        graph.add_edge(
            line_origin,
            line_same_a,
            etype="ride",
            mode="rail",
            w=1.0,
        )
        graph.add_edge(
            line_same_a,
            line_same_b,
            etype="ride",
            mode="rail",
            w=1.0,
        )
        graph.add_edge(line_same_b, same_b, etype="alight", w=0.0)

        steps = segments_detailed(
            graph,
            [origin, line_origin, line_same_a, line_same_b, same_b],
            _RailTimetableManager(),
            start_time_str="15:35",
        )

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["boarding_minutes"], 2)
        self.assertEqual(
            [stop["id"] for stop in steps[0]["stops"]],
            ["T01", "T02", "T03"],
        )
        self.assertEqual(
            [stop["name"] for stop in steps[0]["stops"]],
            ["起点", "同名駅", "同名駅"],
        )
        self.assertEqual(
            [stop["odpt_id"] for stop in steps[0]["stops"]],
            ["origin-station", "same-a", "same-b"],
        )

    def test_missing_rail_station_code_raises_route_contract_error(self):
        graph = nx.DiGraph()
        origin = ("phys", "origin-station")
        line = ("line", "origin-station", "test-line")
        destination = ("phys", "destination-station")

        graph.add_node(
            origin,
            name="起点",
            lat=35.70,
            lon=139.80,
        )
        graph.add_node(
            line,
            name="テスト線",
            disp="テスト線",
            mode="rail",
        )
        graph.add_node(
            destination,
            name="終点",
            lat=35.71,
            lon=139.81,
            station_code="T02",
        )
        graph.add_edge(origin, line, etype="board", w=1.0)
        graph.add_edge(line, destination, etype="alight", w=0.0)

        with self.assertRaisesRegex(
            RouteContractError,
            "rail station has no ODPT station code: origin-station",
        ):
            segments_detailed(
                graph,
                [origin, line, destination],
                self.tm,
                start_time_str="15:35",
            )

    def test_time_priority_contract_is_stable(self):
        with (
            patch(
                "toei_engine.find_fastest_path",
                return_value=(615, self.path),
            ),
            patch(
                "toei_engine.find_few_transfers_paths_generator",
                side_effect=AssertionError(
                    "time mode must not use fewTransfers search"
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
        self.assertEqual(
            candidate["lines_en"],
            ["Route To01 · Shimbashi Sta."],
        )
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
                "lines_en",
                "total_time",
                "arrival_time",
                "steps",
                "score_label",
                "cost_score",
                "path",
                "points",
                "route_geometry",
                "total",
                "transfers",
                "rides",
                "walking_distance_meters",
                "walking_segment_count",
                "boards",
            },
        )

    def test_few_transfers_uses_lexicographic_generator(self):
        with (
            patch(
                "toei_engine.find_few_transfers_paths_generator",
                return_value=iter(
                    [
                        {
                            "cost": 7.5,
                            "path": self.path,
                            "walk_m": 80,
                        }
                    ]
                ),
            ) as few_search,
            patch(
                "toei_engine.find_paths_generator",
                side_effect=AssertionError(
                    "fewTransfers must not use legacy cost search"
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

        few_search.assert_called_once()
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["id"], "Comfort-1")
        self.assertEqual(candidate["lines"], ["都01"])
        self.assertEqual(candidate["total_time"], 15)
        self.assertEqual(candidate["arrival_time"], "10:15")
        self.assertEqual(candidate["cost_score"], 7.5)
        self.assertEqual(
            candidate["score_label"],
            "楽さ 7.5 (所要15分)",
        )
        self.assertEqual(candidate["transfers"], 0)
        self.assertEqual(candidate["walking_distance_meters"], 80)
        self.assertEqual(candidate["walking_segment_count"], 1)

    def test_duplicate_transit_itineraries_keep_shortest_walk_without_refill(self):
        origin = ("phys", "origin-dedupe")
        station = ("phys", "shimbashi")
        detour = ("phys", "nearby-bus-stop")
        target = ("phys", "target-dedupe")
        asakusa_from = ("line", "origin-dedupe", "asakusa")
        asakusa_to = ("line", "shimbashi", "asakusa")
        oedo_from = ("line", "origin-dedupe", "oedo")
        oedo_to = ("line", "shimbashi", "oedo")

        graph = nx.DiGraph()
        nodes = [
            (origin, {"name": "本所吾妻橋", "lat": 35.71, "lon": 139.80}),
            (station, {"name": "新橋", "lat": 35.666, "lon": 139.758}),
            (detour, {"name": "新橋駅前", "lat": 35.667, "lon": 139.759}),
            (target, {"name": "新橋駅", "lat": 35.668, "lon": 139.760}),
            (
                asakusa_from,
                {
                    "name": "浅草線@本所吾妻橋",
                    "lat": 35.71,
                    "lon": 139.80,
                    "mode": "rail",
                    "line": "odpt.Railway:Toei.Asakusa",
                },
            ),
            (
                asakusa_to,
                {
                    "name": "浅草線@新橋",
                    "lat": 35.666,
                    "lon": 139.758,
                    "mode": "rail",
                    "line": "odpt.Railway:Toei.Asakusa",
                },
            ),
            (
                oedo_from,
                {
                    "name": "大江戸線@本所吾妻橋",
                    "lat": 35.71,
                    "lon": 139.80,
                    "mode": "rail",
                    "line": "odpt.Railway:Toei.Oedo",
                },
            ),
            (
                oedo_to,
                {
                    "name": "大江戸線@新橋",
                    "lat": 35.666,
                    "lon": 139.758,
                    "mode": "rail",
                    "line": "odpt.Railway:Toei.Oedo",
                },
            ),
        ]
        for node, attrs in nodes:
            graph.add_node(node, **attrs)

        graph.add_edge(origin, asakusa_from, etype="board", w=1.0)
        graph.add_edge(
            asakusa_from,
            asakusa_to,
            etype="ride",
            mode="rail",
            w=1.0,
        )
        graph.add_edge(asakusa_to, station, etype="alight", w=0.0)
        graph.add_edge(station, target, etype="walk", meters=152, w=2.0)
        graph.add_edge(station, detour, etype="walk", meters=20, w=1.0)
        graph.add_edge(detour, target, etype="walk", meters=170, w=3.0)

        graph.add_edge(origin, oedo_from, etype="board", w=1.0)
        graph.add_edge(
            oedo_from,
            oedo_to,
            etype="ride",
            mode="rail",
            w=1.0,
        )
        graph.add_edge(oedo_to, station, etype="alight", w=0.0)

        direct_asakusa = [
            origin,
            asakusa_from,
            asakusa_to,
            station,
            target,
        ]
        detour_asakusa = [
            origin,
            asakusa_from,
            asakusa_to,
            station,
            detour,
            target,
        ]
        direct_oedo = [
            origin,
            oedo_from,
            oedo_to,
            station,
            target,
        ]

        def raw_paths():
            yield {"cost": 5.0, "path": detour_asakusa, "walk_m": 190}
            yield {"cost": 6.0, "path": direct_asakusa, "walk_m": 152}
            yield {"cost": 7.0, "path": direct_oedo, "walk_m": 140}
            raise AssertionError(
                "duplicate removal must not search farther just to refill"
            )

        asakusa_steps = [
            {
                "kind": "rail",
                "title": "浅草線",
                "title_en": "Asakusa Line",
                "meters": 0,
            },
            {
                "kind": "walk",
                "title": "徒歩",
                "meters": 152,
                "minutes": 2,
            },
        ]
        oedo_steps = [
            {
                "kind": "rail",
                "title": "大江戸線",
                "title_en": "Oedo Line",
                "meters": 0,
            },
            {
                "kind": "walk",
                "title": "徒歩",
                "meters": 140,
                "minutes": 2,
            },
        ]

        with (
            patch(
                "toei_engine.find_few_transfers_paths_generator",
                return_value=raw_paths(),
            ),
            patch(
                "toei_engine.calculate_real_arrival_time",
                side_effect=[623, 624],
            ) as real_arrival,
            patch(
                "toei_engine.segments_detailed",
                side_effect=[asakusa_steps, oedo_steps],
            ) as details,
        ):
            candidates = search_best_routes(
                graph,
                self.tm,
                origin,
                mode="fewTransfers",
                start_time="13:24",
                limit=3,
                target_date=datetime.datetime(2026, 10, 1, 13, 24),
                target_node=target,
                day_type="weekday",
            )

        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            [candidate["lines"] for candidate in candidates],
            [["浅草線"], ["大江戸線"]],
        )
        self.assertEqual(
            [candidate["cost_score"] for candidate in candidates],
            [6.0, 7.0],
        )
        self.assertEqual(
            [candidate["walking_distance_meters"] for candidate in candidates],
            [152, 140],
        )
        self.assertEqual(real_arrival.call_count, 2)
        self.assertEqual(details.call_count, 2)

    def test_direct_destination_walk_prunes_walk_detours_in_all_search_modes(self):
        station = ("phys", "shimbashi-direct")
        detour = ("phys", "nearby-bus-stop-direct")
        target = ("phys", "dest:35.668000,139.760000")

        graph = nx.DiGraph()
        graph.add_node(
            station,
            name="新橋",
            lat=35.666,
            lon=139.758,
        )
        graph.add_node(
            detour,
            name="新橋駅前",
            lat=35.667,
            lon=139.759,
        )
        graph.add_edge(
            station,
            detour,
            etype="walk",
            meters=20.0,
            w=0.375,
        )

        virtual_connections = [
            (station, 2.8125, 150.0),
            (detour, 2.625, 140.0),
        ]

        for generator in (
            find_paths_generator,
            find_few_transfers_paths_generator,
        ):
            with self.subTest(generator=generator.__name__):
                candidates = list(
                    generator(
                        graph,
                        self.tm,
                        station,
                        target,
                        start_time_str="13:24",
                        max_search=5,
                        virtual_dest_connections=virtual_connections,
                    )
                )
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0]["path"], [station, target])
                self.assertEqual(candidates[0]["walk_m"], 150.0)

        arrival, path = find_fastest_path(
            graph,
            self.tm,
            station,
            target,
            start_time_str="13:24",
            virtual_dest_connections=virtual_connections,
        )
        self.assertEqual(arrival, 13 * 60 + 24 + (150.0 / 80.0))
        self.assertEqual(path, [station, target])

    def test_cost_mode_keeps_legacy_comfort_generator(self):
        with (
            patch(
                "toei_engine.find_paths_generator",
                return_value=iter(
                    [
                        {
                            "cost": 6.0,
                            "path": self.path,
                            "walk_m": 80,
                        }
                    ]
                ),
            ) as legacy_search,
            patch(
                "toei_engine.find_few_transfers_paths_generator",
                side_effect=AssertionError(
                    "cost mode must keep legacy search"
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
                mode="cost",
                start_time="10:00",
                limit=5,
                target_date=datetime.datetime(2026, 8, 21, 10, 0),
                target_node=self.destination,
                day_type="weekday",
            )

        legacy_search.assert_called_once()
        self.assertEqual(candidates[0]["cost_score"], 6.0)

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

        self.assertEqual(
            result[0]["departure_date"],
            "2026-08-21T08:35:00",
        )
        self.assertFalse(result[0]["is_future_suggestion"])

        args = search.call_args.args
        self.assertEqual(args[3], "time")
        self.assertEqual(args[4], "08:35")
        self.assertEqual(args[5], 5)
        self.assertEqual(
            args[6],
            datetime.datetime(2026, 8, 21, 8, 35),
        )


class FewTransfersLexicographicSearchTest(unittest.TestCase):
    def setUp(self):
        self.graph = nx.DiGraph()
        self.tm = _FakeTimetableManager()
        self.start = ("phys", "start")
        self.target = ("phys", "target")
        self.graph.add_node(self.start, name="start")
        self.graph.add_node(self.target, name="target")

    def add_leg(
        self,
        prefix,
        origin,
        destination,
        board_cost,
        ride_cost,
    ):
        line_from = ("line", f"{prefix}:from")
        line_to = ("line", f"{prefix}:to")
        self.graph.add_node(
            line_from,
            name=line_from[1],
            mode="rail",
        )
        self.graph.add_node(
            line_to,
            name=line_to[1],
            mode="rail",
        )
        self.graph.add_edge(
            origin,
            line_from,
            etype="board",
            w=board_cost,
        )
        self.graph.add_edge(
            line_from,
            line_to,
            etype="ride",
            w=ride_cost,
        )
        self.graph.add_edge(
            line_to,
            destination,
            etype="alight",
            w=0.0,
        )

    def boarding_count(self, path):
        return sum(
            1
            for u, v in zip(path, path[1:])
            if self.graph[u][v].get("etype") == "board"
        )

    def test_two_boardings_beat_cheaper_three_boardings(self):
        expensive_mid = ("phys", "expensive-mid")
        cheap_mid_1 = ("phys", "cheap-mid-1")
        cheap_mid_2 = ("phys", "cheap-mid-2")
        for node in (expensive_mid, cheap_mid_1, cheap_mid_2):
            self.graph.add_node(node, name=node[1])

        self.add_leg(
            "expensive-1",
            self.start,
            expensive_mid,
            5.0,
            5.0,
        )
        self.add_leg(
            "expensive-2",
            expensive_mid,
            self.target,
            5.0,
            5.0,
        )

        self.add_leg(
            "cheap-1",
            self.start,
            cheap_mid_1,
            1.0,
            0.1,
        )
        self.add_leg(
            "cheap-2",
            cheap_mid_1,
            cheap_mid_2,
            1.0,
            0.1,
        )
        self.add_leg(
            "cheap-3",
            cheap_mid_2,
            self.target,
            1.0,
            0.1,
        )

        results = list(
            itertools.islice(
                find_few_transfers_paths_generator(
                    self.graph,
                    self.tm,
                    self.start,
                    self.target,
                    max_search=10,
                    max_visited=1000,
                    time_limit_sec=2.0,
                ),
                2,
            )
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(
            self.boarding_count(results[0]["path"]),
            2,
        )
        self.assertEqual(
            self.boarding_count(results[1]["path"]),
            3,
        )
        self.assertGreater(
            results[0]["cost"],
            results[1]["cost"],
        )

    def test_boarding_count_is_part_of_pruning_state(self):
        shared = ("phys", "shared")
        mid = ("phys", "mid")
        self.graph.add_node(shared, name="shared")
        self.graph.add_node(mid, name="mid")

        self.add_leg(
            "two-a",
            self.start,
            shared,
            5.0,
            5.0,
        )
        self.add_leg(
            "two-b",
            shared,
            self.target,
            5.0,
            5.0,
        )

        self.add_leg(
            "three-a",
            self.start,
            mid,
            1.0,
            0.1,
        )
        self.add_leg(
            "three-b",
            mid,
            shared,
            1.0,
            0.1,
        )
        self.add_leg(
            "three-c",
            shared,
            self.target,
            1.0,
            0.1,
        )

        results = list(find_few_transfers_paths_generator(
            self.graph,
            self.tm,
            self.start,
            self.target,
            max_search=10,
            max_visited=1000,
            time_limit_sec=2.0,
        ))

        # Distinct suffix lines now survive even with equal final walking
        # distances. Still require the cheaper three-boarding prefix to survive
        # intermediate pruning beside the earlier two-boarding prefix.
        counts = [self.boarding_count(r["path"]) for r in results]
        self.assertEqual(counts[0], 2)
        self.assertIn(3, counts)
        self.assertEqual(counts, sorted(counts))

    def test_safety_limit_raises_with_diagnostics(self):
        middle = ("phys", "middle")
        self.graph.add_node(middle, name="middle")
        self.add_leg(
            "limit-a",
            self.start,
            middle,
            1.0,
            1.0,
        )
        self.add_leg(
            "limit-b",
            middle,
            self.target,
            1.0,
            1.0,
        )

        with self.assertRaisesRegex(
            RouteSearchLimitError,
            r"reason=max_visited.*visited=1.*queue=",
        ):
            list(
                find_few_transfers_paths_generator(
                    self.graph,
                    self.tm,
                    self.start,
                    self.target,
                    max_visited=0,
                    time_limit_sec=2.0,
                )
            )


if __name__ == "__main__":
    unittest.main()
