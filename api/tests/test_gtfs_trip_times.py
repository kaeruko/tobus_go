import os
import tempfile
import unittest
from collections import defaultdict
import datetime
from types import SimpleNamespace
from unittest.mock import patch

import networkx as nx

from gtfs_loader import GtfsRepository
from toei_engine import (
    ServiceDayType,
    calculate_real_arrival_time,
    search_best_routes,
    segments_detailed,
)


def _new_repository() -> GtfsRepository:
    repository = object.__new__(GtfsRepository)
    repository.stops = {}
    repository.trips = {}
    repository.stop_times = defaultdict(dict)
    repository.routes = {}
    repository.route_name_to_id = {}
    repository.timetable_index = defaultdict(list)
    repository.service_calendar = {}
    repository.service_exceptions = defaultdict(dict)
    repository._active_service_cache = {}
    repository.is_loaded = False
    return repository


class GtfsTripTimesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        directory = self.temp_dir.name
        files = {
            "calendar.txt": (
                "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                "61-160,0,0,0,0,0,1,0,20260101,20261231\n"
                "61-170,1,1,1,1,1,0,0,20260101,20261231\n"
            ),
            "calendar_dates.txt": "service_id,date,exception_type\n",
            "stops.txt": (
                "stop_id,stop_name,stop_lat,stop_lon\n"
                "1350-02,平井七丁目,35.0,139.0\n"
                "1349-01,平井七丁目北公園前,35.1,139.1\n"
                "0665-01,社会福祉会館前,35.2,139.2\n"
                "9999-01,別の終点,35.3,139.3\n"
            ),
            "routes.txt": (
                "route_id,route_short_name,route_type\n070,上２３,3\n"
            ),
            "trips.txt": (
                "route_id,service_id,trip_id,trip_headsign,direction_id\n"
                "070,61-160,56208-1-61-160-1326,上野松坂屋前,1\n"
                "070,61-170,weekday-trip,上野松坂屋前,1\n"
                "070,61-160,short-trip,別の終点,1\n"
                "070,61-160,express-trip,上野松坂屋前,1\n"
                "070,61-160,late-trip,上野松坂屋前,1\n"
            ),
            "stop_times.txt": (
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                "short-trip,13:20:00,13:20:00,1350-02,4\n"
                "short-trip,13:25:00,13:25:00,9999-01,5\n"
                "weekday-trip,13:21:00,13:21:00,1350-02,4\n"
                "weekday-trip,13:31:00,13:31:00,0665-01,11\n"
                "express-trip,13:25:00,13:25:00,1350-02,4\n"
                "express-trip,13:35:00,13:35:00,0665-01,11\n"
                "56208-1-61-160-1326,13:30:00,13:30:00,1350-02,4\n"
                "56208-1-61-160-1326,13:31:00,13:31:00,1349-01,5\n"
                "56208-1-61-160-1326,13:40:00,13:40:00,0665-01,11\n"
                "late-trip,25:10:00,25:10:00,1350-02,4\n"
                "late-trip,25:20:00,25:20:00,0665-01,11\n"
            ),
        }
        for filename, content in files.items():
            with open(
                os.path.join(directory, filename),
                "w",
                encoding="utf-8",
                newline="",
            ) as file:
                file.write(content)

        self.repository = _new_repository()
        self.repository.load_data(directory)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_finds_ue23_arrival_from_the_same_active_trip(self):
        leg = self.repository.find_next_trip_leg(
            "070",
            "1350-02",
            "0665-01",
            earliest_departure_minute=13 * 60 + 19,
            active_service_ids=frozenset({"61-160"}),
            required_stop_ids=("1350-02", "1349-01", "0665-01"),
        )

        self.assertIsNotNone(leg)
        self.assertEqual(leg.trip_id, "56208-1-61-160-1326")
        self.assertEqual(leg.departure_minute, 13 * 60 + 30)
        self.assertEqual(leg.arrival_minute, 13 * 60 + 40)
        self.assertEqual(leg.origin_sequence, 4)
        self.assertEqual(leg.destination_sequence, 11)

    def test_does_not_switch_to_an_inactive_service(self):
        leg = self.repository.find_next_trip_leg(
            "070",
            "1350-02",
            "0665-01",
            earliest_departure_minute=13 * 60 + 19,
            active_service_ids=frozenset({"61-170"}),
        )

        self.assertEqual(leg.trip_id, "weekday-trip")
        self.assertEqual(leg.arrival_minute, 13 * 60 + 31)

    def test_rejects_a_trip_that_does_not_reach_the_destination(self):
        leg = self.repository.find_next_trip_leg(
            "070",
            "1350-02",
            "0665-01",
            earliest_departure_minute=13 * 60 + 19,
            active_service_ids=frozenset({"61-160"}),
        )

        self.assertNotEqual(leg.trip_id, "short-trip")

    def test_rejects_a_trip_that_skips_a_required_path_stop(self):
        leg = self.repository.find_next_trip_leg(
            "070",
            "1350-02",
            "0665-01",
            earliest_departure_minute=13 * 60 + 19,
            active_service_ids=frozenset({"61-160"}),
            required_stop_ids=("1350-02", "1349-01", "0665-01"),
        )

        self.assertEqual(leg.trip_id, "56208-1-61-160-1326")

    def test_supports_gtfs_times_after_midnight(self):
        leg = self.repository.find_next_trip_leg(
            "070",
            "1350-02",
            "0665-01",
            earliest_departure_minute=25 * 60,
            active_service_ids=frozenset({"61-160"}),
        )

        self.assertEqual(leg.trip_id, "late-trip")
        self.assertEqual(leg.departure_minute, 25 * 60 + 10)
        self.assertEqual(leg.arrival_minute, 25 * 60 + 20)

    def test_exposes_ordered_stops_without_losing_existing_behavior(self):
        self.assertEqual(
            self.repository.get_trip_stop_ids("56208-1-61-160-1326"),
            ["1350-02", "1349-01", "0665-01"],
        )
        details = self.repository.get_bus_details(
            "56208-1-61-160-1326", 5
        )
        self.assertEqual(details["next_stop_id"], "1349-01")
    def _graph_and_path(self):
        graph = nx.DiGraph()
        pole_ids = [
            "odpt.BusstopPole:Toei.HiraiNanachome.1350.2",
            "odpt.BusstopPole:Toei.HiraiNanachomeKitakoen.1349.1",
            "odpt.BusstopPole:Toei.ShakaiFukushiKaikan.665.1",
        ]
        names = ["平井七丁目", "平井七丁目北公園前", "社会福祉会館前"]
        line_id = "buspat:ue23"
        physical_nodes = []
        line_nodes = []
        for index, (pole_id, name) in enumerate(zip(pole_ids, names)):
            physical = ("phys", pole_id)
            line = ("line", pole_id, line_id)
            graph.add_node(
                physical,
                name=name,
                lat=35.0 + index * 0.01,
                lon=139.0 + index * 0.01,
            )
            graph.add_node(
                line,
                name=f"{name}@上２３",
                disp="上２３ 上野松坂屋前行",
                mode="bus",
                route_id="odpt.Busroute:Toei.Ue23",
                lat=35.0 + index * 0.01,
                lon=139.0 + index * 0.01,
            )
            physical_nodes.append(physical)
            line_nodes.append(line)

        graph.add_edge(physical_nodes[0], line_nodes[0], etype="board")
        graph.add_edge(
            line_nodes[0], line_nodes[1], etype="ride", mode="bus"
        )
        graph.add_edge(
            line_nodes[1], line_nodes[2], etype="ride", mode="bus"
        )
        graph.add_edge(line_nodes[2], physical_nodes[2], etype="alight")
        path = [
            physical_nodes[0],
            line_nodes[0],
            line_nodes[1],
            line_nodes[2],
            physical_nodes[2],
        ]
        return graph, path

    def test_bus_segment_uses_exact_gtfs_arrival(self):
        graph, path = self._graph_and_path()
        day_type = ServiceDayType(
            "weekday",
            datetime.date(2026, 8, 12),
            frozenset({"61-160"}),
            True,
        )

        with patch("toei_engine.gtfs_repo", self.repository):
            segments = segments_detailed(
                graph,
                path,
                SimpleNamespace(),
                start_time_str="13:19",
                day_type=day_type,
            )
            arrival = calculate_real_arrival_time(
                graph,
                SimpleNamespace(),
                path,
                start_time_str="13:19",
                day_type=day_type,
            )

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["kind"], "wait")
        bus = segments[1]
        self.assertEqual(bus["trip_id"], "56208-1-61-160-1326")
        self.assertEqual(bus["departure_time"], "13:30")
        self.assertEqual(bus["arrival_time"], "13:40")
        self.assertEqual(bus["minutes"], 10)
        self.assertEqual(arrival, 13 * 60 + 40)

    def test_fastest_candidate_replaces_the_search_heuristic_with_gtfs_time(self):
        graph, path = self._graph_and_path()
        day_type = ServiceDayType(
            "weekday",
            datetime.date(2026, 8, 12),
            frozenset({"61-160"}),
            True,
        )

        class FakeTimetableManager:
            def get_delays_snapshot(self):
                return {}

            def get_next_bus_departure(self, *args, **kwargs):
                return 13 * 60 + 30, "pattern"

        with patch("toei_engine.gtfs_repo", self.repository):
            candidates = search_best_routes(
                graph,
                FakeTimetableManager(),
                path[0],
                mode="time",
                start_time="13:19",
                limit=1,
                target_date=datetime.datetime(2026, 8, 12, 13, 19),
                target_node=path[-1],
                day_type=day_type,
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["arrival_time"], "13:40")
        self.assertEqual(candidates[0]["total_time"], 21)
        self.assertEqual(candidates[0]["steps"][-1]["arrival_time"], "13:40")


if __name__ == "__main__":
    unittest.main()
