"""A freshly boarded bus and a continuing bus have different alight clocks.

The feed is loaded by the ordinary GTFS repository; rail uses ordinary ODPT
records. The cheaper fresh boarding must not remove the only last-train path.
"""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import networkx as nx

import toei_engine as engine
from gtfs_loader import GtfsRepository
from tokyo_timetable_choices import TimetableChoices


BUS_ROUTE = "bus-route"
BUS_LINE = "bus-pattern"
RAILWAY = "odpt.Railway:Toei.Asakusa"
START = ("phys", "start")
A = ("phys", "A")
B = ("phys", "B")
C = ("phys", "odpt.Station:Toei.Asakusa.C")
TARGET = ("phys", "odpt.Station:Toei.Asakusa.Target")


def _bus(stop):
    return ("line", stop, BUS_LINE)


def _rail(physical):
    return ("line", physical[1], RAILWAY)


def _walk(graph, left, right, meters):
    graph.add_edge(
        left, right, etype="walk", meters=meters,
        w=engine.WALK_COST * max(1.0, meters / engine.WALK_SPEED_M_PER_MIN),
    )


def _graph():
    graph = nx.DiGraph()
    for node in (START, A, B, C, TARGET, ("phys", "D")):
        graph.add_node(node, name=node[1], lat=35.0, lon=139.0)
    for stop in ("A", "B", "D"):
        graph.add_node(_bus(stop), name=stop, mode="bus", route_id=BUS_ROUTE)
        graph.add_edge(("phys", stop), _bus(stop), etype="board",
                       w=engine.TRANSFER_PENALTY)
        graph.add_edge(_bus(stop), ("phys", stop), etype="alight", w=0.0)
    for left, right in (("A", "B"), ("B", "D")):
        graph.add_edge(_bus(left), _bus(right), etype="ride", mode="bus",
                       w=engine.BUS_RIDE_COST)
    for node in (C, TARGET):
        graph.add_node(_rail(node), name=node[1], mode="rail", route_id=RAILWAY)
        graph.add_edge(node, _rail(node), etype="board", w=engine.TRANSFER_PENALTY)
        graph.add_edge(_rail(node), node, etype="alight", w=0.0)
    graph.add_edge(_rail(C), _rail(TARGET), etype="ride", mode="rail",
                   w=engine.RAIL_RIDE_COST)
    _walk(graph, START, A, 600.0)
    _walk(graph, START, B, 576.0)
    _walk(graph, B, C, 50.0)
    return graph


class TokyoBusBoardPhaseRegressionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        directory = Path(self.directory.name)
        files = {
            "stops.txt": (
                "stop_id,stop_name,stop_lat,stop_lon\n"
                "A,A,35.0,139.0\nB,B,35.0,139.0\nD,D,35.0,139.0\n"
            ),
            "routes.txt": "route_id,route_short_name,route_type\nbus-route,Bus,3\n",
            "trips.txt": (
                "route_id,service_id,trip_id,trip_headsign,direction_id\n"
                "bus-route,weekday,same-bus,D,0\n"
            ),
            "stop_times.txt": (
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                "same-bus,10:08:00,10:08:00,A,1\n"
                "same-bus,10:10:00,10:10:00,B,2\n"
                "same-bus,10:12:00,10:12:00,D,3\n"
            ),
        }
        for name, content in files.items():
            (directory / name).write_text(content, encoding="utf-8")
        self.repository = GtfsRepository("bus-phase-fixture").load_data(str(directory))
        timetable = [{
            "@id": "urn:uuid:last-train",
            "owl:sameAs": "odpt.TrainTimetable:Toei.Asakusa.last-train.Weekday",
            "odpt:railway": RAILWAY,
            "odpt:trainNumber": "last-train",
            "odpt:calendar": "odpt.Calendar:Weekday",
            "odpt:trainTimetableObject": [{
                "odpt:departureStation": node[1],
                "odpt:arrivalStation": node[1],
                "odpt:departureTime": minute,
                "odpt:arrivalTime": minute,
            } for node, minute in ((C, "10:13"), (TARGET, "10:14"))],
        }]
        path = directory / "trains.json"
        path.write_text(json.dumps(timetable), encoding="utf-8")
        self.manager = engine.TimetableManager()
        with contextlib.redirect_stdout(io.StringIO()):
            self.manager.load_train_timetables(str(path))
        self.graph = _graph()
        self.expected_path = [START, A, _bus("A"), _bus("B"), B,
                              C, _rail(C), _rail(TARGET), TARGET]

    def _search(self, mode, graph):
        with patch.object(engine, "gtfs_repo", self.repository), \
                contextlib.redirect_stdout(io.StringIO()):
            if mode == "time":
                return engine.find_fastest_path(
                    graph, self.manager, START, TARGET,
                    start_time_str="10:00", use_realtime=False,
                )
            search = (engine.find_paths_generator if mode == "cost"
                      else engine.find_few_transfers_paths_generator)
            generator = search(
                graph, self.manager, START, TARGET,
                start_time_str="10:00", use_realtime=False,
            )
            try:
                candidate = next(generator, None)
                if candidate is None:
                    return None, None
                return candidate["path"].arrival_minute, candidate["path"]
            finally:
                generator.close()

    def test_fixture_has_equal_bus_position_but_different_board_phases(self):
        choices = TimetableChoices(
            self.graph, self.manager, use_realtime=False,
            bus_repository=self.repository, deadline=840,
        )
        departure, boarded_a = choices.board_options(A, _bus("A"), 607.5)[0]
        continued_time, continued = choices.ride_options(
            _bus("A"), _bus("B"), departure, boarded_a,
        )[0]
        fresh_time, fresh = choices.board_options(B, _bus("B"), 607.2)[0]
        self.assertEqual(continued_time, fresh_time)
        self.assertEqual(continued_time, 610)
        for attribute in ("provider", "service_key", "run_id", "line_id", "sequence"):
            self.assertEqual(getattr(continued, attribute), getattr(fresh, attribute))
        self.assertNotEqual(continued.board_sequence, continued.sequence)
        self.assertEqual(fresh.board_sequence, fresh.sequence)
        self.assertEqual(continued.trip_id, "same-bus")
        # Both prefixes have one boarding and reset the walk segment to zero.
        # Fresh boarding is cheaper and uses less total walking, but its
        # one-minute alight time cannot reproduce the continuing bus's future.
        fresh_cost = self.graph[START][B]["w"] + engine.TRANSFER_PENALTY
        continued_cost = (self.graph[START][A]["w"] + engine.TRANSFER_PENALTY
                          + engine.BUS_RIDE_COST)
        self.assertLess(fresh_cost, continued_cost)
        self.assertLess(576, 600)
        self.assertGreater(576 + 50, engine.MAX_WALK_SEG_M)
        ready = 610 + 50 / engine.WALK_SPEED_M_PER_MIN + engine.RAIL_BOARDING_MINUTES
        self.assertLessEqual(ready, 613)
        self.assertGreater(ready + 1, 613)

    def test_only_continuing_prefix_can_catch_last_train(self):
        continued_only = self.graph.copy()
        continued_only.remove_edge(START, B)
        fresh_only = self.graph.copy()
        fresh_only.remove_edge(START, A)
        for mode in ("cost", "fewTransfers", "time"):
            with self.subTest(mode=mode, prefix="continuing"):
                arrival, path = self._search(mode, continued_only)
                self.assertEqual(arrival, 615)
                self.assertEqual(path, self.expected_path)
                self.assertAlmostEqual(path.edge_times[3], 610)
            with self.subTest(mode=mode, prefix="fresh"):
                self.assertEqual(self._search(mode, fresh_only), (None, None))

    def test_fresh_boarding_must_not_remove_continuing_last_train_path(self):
        for mode in ("cost", "fewTransfers", "time"):
            with self.subTest(mode=mode):
                arrival, path = self._search(mode, self.graph)
                self.assertEqual(
                    arrival, 615,
                    "Fresh boarding cannot reproduce the continuing bus's zero-minute alight",
                )
                self.assertEqual(path, self.expected_path)


if __name__ == "__main__":
    unittest.main()
