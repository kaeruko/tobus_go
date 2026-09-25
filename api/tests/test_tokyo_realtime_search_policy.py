import datetime
import unittest
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import networkx as nx

from toei_engine import TimetableManager
from tokyo_route_engine import (
    TokyoRouteDependencies,
    TokyoRouteEngine,
    _should_use_realtime,
)


JST = ZoneInfo("Asia/Tokyo")


class TokyoRealtimeSearchPolicyTest(unittest.TestCase):
    def test_realtime_is_limited_to_imminent_departures(self):
        now = datetime.datetime(2026, 9, 25, 15, 0, tzinfo=JST)

        self.assertTrue(
            _should_use_realtime(
                date_str="2026-09-25",
                start_time="15:00",
                now=now,
            )
        )
        self.assertTrue(
            _should_use_realtime(
                date_str="2026-09-25",
                start_time="16:00",
                now=now,
            )
        )
        self.assertFalse(
            _should_use_realtime(
                date_str="2026-09-25",
                start_time="16:01",
                now=now,
            )
        )
        self.assertFalse(
            _should_use_realtime(
                date_str="2026-09-26",
                start_time="15:00",
                now=now,
            )
        )

    def test_realtime_window_can_cross_midnight(self):
        now = datetime.datetime(2026, 9, 25, 23, 40, tzinfo=JST)
        self.assertTrue(
            _should_use_realtime(
                date_str="2026-09-26",
                start_time="00:20",
                now=now,
            )
        )

    def test_tokyo_engine_passes_policy_to_route_search(self):
        def run(date_str, start_time):
            origin = ("phys", "origin")
            destination = ("phys", "destination")
            graph = nx.DiGraph()
            graph.add_node(origin, name="Origin", lat=35.0, lon=139.0)
            graph.add_node(destination, name="Destination", lat=35.1, lon=139.1)
            app = SimpleNamespace(
                state=SimpleNamespace(
                    G=graph,
                    TM=object(),
                    WALK_RAD=500,
                    SI=object(),
                )
            )
            nearest = iter(((origin, 0.0), (destination, 0.0)))
            calls = []

            def search_once(*args, **kwargs):
                calls.append(kwargs)
                return []

            engine = TokyoRouteEngine(
                app,
                dependencies=TokyoRouteDependencies(
                    nearest_phys=lambda *args, **kwargs: next(nearest),
                    haversine=lambda *args: 0.0,
                    get_virtual_connections=lambda *args, **kwargs: (
                        ("phys", "virtual-destination"),
                        [],
                    ),
                    search_best_routes_once=search_once,
                    time_str_to_min=lambda value: 0,
                    min_to_time_str=lambda value: "00:00",
                    determine_day_type=lambda value: "weekday",
                    assign_candidate_step_ids=lambda value: None,
                    rss_mb=lambda: -1.0,
                    now=lambda: datetime.datetime(
                        2026, 9, 25, 15, 0, tzinfo=JST
                    ),
                ),
            )

            engine.search_legacy(
                alat=35.0,
                alon=139.0,
                blat=35.1,
                blon=139.1,
                pref="time",
                start_time=start_time,
                date_str=date_str,
            )
            self.assertEqual(len(calls), 1)
            return calls[0]["use_realtime"]

        self.assertTrue(run("2026-09-25", "15:30"))
        self.assertFalse(run("2026-09-26", "15:30"))

    def test_static_search_ignores_bus_delay_adjustment(self):
        manager = TimetableManager()
        manager.bus_departures_weekday = {
            "pole": {
                "route": [
                    {"dep": 600, "dest": None, "trip": "trip"},
                ]
            }
        }
        manager.bus_realtime_delays["route"] = 10.0

        realtime_departure, _ = manager.get_next_bus_departure(
            "pole",
            "route",
            595,
            use_realtime=True,
        )
        static_departure, _ = manager.get_next_bus_departure(
            "pole",
            "route",
            595,
            use_realtime=False,
        )

        self.assertEqual(realtime_departure, 610.0)
        self.assertEqual(static_departure, 600.0)

    def test_static_search_ignores_train_delay_adjustment(self):
        manager = TimetableManager()
        manager.train_patterns_weekday = {
            "station-a": [
                {
                    "dep": 600,
                    "arr": 605,
                    "next_sta": "station-b",
                    "train_num": "T1",
                }
            ]
        }
        manager.realtime_delays["T1"] = 600

        realtime_arrival = manager.get_next_train_arrival(
            "station-a",
            "station-b",
            590,
            day_type="weekday",
            delays_snapshot=manager.get_delays_snapshot(),
            use_realtime=True,
        )
        static_arrival = manager.get_next_train_arrival(
            "station-a",
            "station-b",
            590,
            day_type="weekday",
            delays_snapshot={},
            use_realtime=False,
        )

        self.assertEqual(realtime_arrival, 615.0)
        self.assertEqual(static_arrival, 605)


if __name__ == "__main__":
    unittest.main()
