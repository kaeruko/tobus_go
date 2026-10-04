"""Tokyo searches must wait for usable runs and retain the boarded run.

Fixtures load ordinary ODPT timetable records through TimetableManager, then
check complete legal itineraries without external data or network requests.
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
from app.services.train_realtime import StaticTrainGtfs, StaticTrainStop, StaticTrainTrip
from app.services.train_route_identity import enrich_route_result_train_trip_ids


RAILWAY = "odpt.Railway:Toei.Asakusa"


def _station(name):
    return f"odpt.Station:Toei.Asakusa.{name}"


def _physical(name):
    return ("phys", _station(name))


def _line(name):
    return ("line", _station(name), RAILWAY)


def _time(minute):
    return f"{int(minute // 60):02d}:{int(minute % 60):02d}"


def _run(identity, stops, *, number=None, calendar="Weekday"):
    return {
        "@id": f"urn:uuid:{identity}",
        "owl:sameAs": f"odpt.TrainTimetable:Toei.Asakusa.{identity}.{calendar}",
        "odpt:railway": RAILWAY,
        "odpt:trainNumber": number or identity,
        "odpt:calendar": f"odpt.Calendar:{calendar}",
        "odpt:trainTimetableObject": [
            {
                "odpt:departureStation": _station(name),
                "odpt:arrivalStation": _station(name),
                "odpt:departureTime": _time(minute),
                "odpt:arrivalTime": _time(minute),
            }
            for name, minute in stops
        ],
    }


def _manager(*runs):
    manager = engine.TimetableManager()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "trains.json"
        path.write_text(json.dumps(runs), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            manager.load_train_timetables(str(path))
    return manager


def _graph(*edges):
    graph = nx.DiGraph()
    for left, right in edges:
        for name in (left, right):
            graph.add_node(_physical(name), name=name, lat=35.0, lon=139.0)
            graph.add_node(_line(name), name=name, mode="rail", route_id=RAILWAY)
            graph.add_edge(
                _physical(name), _line(name), etype="board",
                w=engine.TRANSFER_PENALTY,
            )
            graph.add_edge(_line(name), _physical(name), etype="alight", w=0.0)
        graph.add_edge(
            _line(left), _line(right), etype="ride", mode="rail",
            w=engine.RAIL_RIDE_COST,
        )
    return graph


def _walk(graph, left, right, meters):
    graph.add_node(left, name=left[1], lat=35.0, lon=139.0)
    graph.add_node(right, name=right[1], lat=35.0, lon=139.0)
    graph.add_edge(
        left, right, etype="walk", meters=meters,
        w=engine.WALK_COST * max(1.0, meters / engine.WALK_SPEED_M_PER_MIN),
    )


def _boardings(graph, path):
    return sum(graph[left][right]["etype"] == "board"
               for left, right in zip(path, path[1:]))


def _fastest(graph, manager, start="A", target="C", **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return engine.find_fastest_path(
            graph, manager, _physical(start), _physical(target),
            start_time_str="09:58", use_realtime=False, **kwargs,
        )


class TokyoWaitingContractTest(unittest.TestCase):
    def test_fastest_coalesces_unnecessary_boarding_cycles_within_search_budget(self):
        # The loop is legal and stays available. Repeatedly boarding it or
        # immediately alighting cannot improve the later B->C connection.
        # Distinct boarding-count groups formerly used 508 pops here; the
        # same-run/resource comparison completes comfortably within 150.
        graph = _graph(("A", "B"), ("B", "D"), ("D", "B"), ("B", "C"))
        loop_stops = [("B", 603)]
        for index in range(15):
            loop_stops.extend((("D", 606 + index * 6), ("B", 609 + index * 6)))
        manager = _manager(
            _run("access", (("A", 600), ("B", 601))),
            _run("loop", loop_stops),
            _run("finish", (("B", 699), ("C", 700))),
        )
        from tokyo_search_labels import search_labels

        def bounded_search(*args, **kwargs):
            kwargs["max_visited"] = 150
            return search_labels(*args, **kwargs)

        with patch("tokyo_search_labels.search_labels", side_effect=bounded_search):
            arrival, path = _fastest(graph, manager)
        self.assertEqual(arrival, 701)
        self.assertEqual(_boardings(graph, path), 2)
        self.assertEqual(path, [_physical("A"), _line("A"), _line("B"),
                                _physical("B"), _line("B"), _line("C"),
                                _physical("C")])

    def test_earlier_readiness_can_choose_later_departure_with_earlier_arrival(self):
        graph = _graph(("A", "B"))
        manager = _manager(
            _run("slow", (("A", 600), ("B", 620))),
            _run("fast", (("A", 601), ("B", 610))),
        )
        arrival, path = _fastest(graph, manager, target="B")
        self.assertEqual(arrival, 611)
        self.assertEqual(_boardings(graph, path), 1)

    def test_cost_and_few_transfers_keep_the_selected_later_fast_run(self):
        graph = _graph(("A", "B"))
        manager = _manager(
            _run("slow", (("A", 600), ("B", 620))),
            _run("fast", (("A", 601), ("B", 610))),
        )
        for search_function in (engine.find_paths_generator,
                                engine.find_few_transfers_paths_generator):
            with self.subTest(search=search_function.__name__):
                with contextlib.redirect_stdout(io.StringIO()):
                    results = list(search_function(
                        graph, manager, _physical("A"), _physical("B"),
                        start_time_str="09:58", use_realtime=False,
                    ))
                self.assertTrue(
                    any(candidate["path"].edge_times[-1] == 611
                        for candidate in results),
                    "A later fast run must survive and retain its selected timing",
                )

    def test_same_run_continues_without_switching_to_unreachable_train(self):
        graph = _graph(("A", "B"), ("B", "C"))
        manager = _manager(
            _run("N1", (("A", 600), ("B", 605), ("C", 620))),
            _run("N2", (("B", 607), ("C", 608))),
        )
        arrival, path = _fastest(graph, manager)
        # B 10:05 + one-minute alight + two-minute preparation misses N2.
        self.assertEqual(arrival, 621)
        self.assertEqual(_boardings(graph, path), 1)
        self.assertEqual(path, [_physical("A"), _line("A"), _line("B"),
                                _line("C"), _physical("C")])

    def test_legal_switch_records_second_boarding_and_preparation_time(self):
        graph = _graph(("A", "B"), ("B", "C"))
        manager = _manager(
            _run("N1", (("A", 600), ("B", 605), ("C", 620))),
            _run("N2", (("B", 609), ("C", 610))),
        )
        arrival, path = _fastest(graph, manager)
        self.assertEqual(arrival, 611)
        self.assertEqual(_boardings(graph, path), 2)
        self.assertEqual(path, [_physical("A"), _line("A"), _line("B"),
                                _physical("B"), _line("B"), _line("C"),
                                _physical("C")])

    def test_later_arrival_on_a_different_run_keeps_better_downstream_service(self):
        graph = _graph(("A", "B"), ("B", "C"))
        manager = _manager(
            _run("N1", (("A", 600), ("B", 605), ("C", 620))),
            _run("N2", (("A", 601), ("B", 606), ("C", 610))),
        )
        arrival, path = _fastest(graph, manager)
        self.assertEqual(arrival, 611)
        # Choosing N2 at A is feasible. Switching from N1 at B is too late.
        self.assertEqual(_boardings(graph, path), 1)

    def test_equal_train_numbers_do_not_join_distinct_terminating_runs(self):
        graph = _graph(("A", "B"), ("B", "C"))
        manager = _manager(
            _run("first-service", (("A", 600), ("B", 605)), number="N1"),
            _run("second-service", (("B", 607), ("C", 608)), number="N1"),
        )
        arrival, path = _fastest(graph, manager)
        self.assertIsNone(arrival)
        self.assertIsNone(path)

    def test_terminating_train_cannot_continue_in_reverse_direction(self):
        graph = _graph(("X", "A"), ("A", "B"), ("B", "A"), ("A", "C"))
        manager = _manager(
            _run("outward", (("X", 595), ("A", 600), ("B", 605))),
            _run("reverse", (("B", 607), ("A", 609), ("C", 610))),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            arrival, path = engine.find_fastest_path(
                graph, manager, _physical("X"), _physical("C"),
                start_time_str="09:53", use_realtime=False,
            )
        # The reverse train can be boarded after alighting at A. At B the
        # connection is too short; staying on the outward train cannot turn
        # it into the reverse service.
        self.assertEqual(arrival, 611)
        self.assertEqual(path, [_physical("X"), _line("X"), _line("A"),
                                _physical("A"), _line("A"), _line("C"),
                                _physical("C")])
        self.assertEqual(_boardings(graph, path), 2)

    def test_loop_preserves_the_occurrence_and_actual_intermediate_stops(self):
        graph = _graph(("X", "A"), ("A", "B"), ("B", "A"), ("A", "C"))
        manager = _manager(_run(
            "loop", (("X", 595), ("A", 600), ("B", 605),
                     ("A", 610), ("C", 615)),
        ))
        with contextlib.redirect_stdout(io.StringIO()):
            arrival, path = engine.find_fastest_path(
                graph, manager, _physical("X"), _physical("C"),
                start_time_str="09:53", use_realtime=False,
            )
        self.assertEqual(arrival, 616)
        self.assertEqual(path, [_physical("X"), _line("X"), _line("A"),
                                _line("B"), _line("A"), _line("C"),
                                _physical("C")])
        self.assertEqual(_boardings(graph, path), 1)

    def test_equal_preparation_and_departure_time_is_boardable(self):
        graph = _graph(("A", "B"))
        manager = _manager(_run("N1", (("A", 600), ("B", 605))))
        arrival, path = _fastest(graph, manager, target="B")
        self.assertEqual(arrival, 606)
        self.assertEqual(_boardings(graph, path), 1)
        with contextlib.redirect_stdout(io.StringIO()):
            late_arrival, late_path = engine.find_fastest_path(
                graph, manager, _physical("A"), _physical("B"),
                start_time_str="09:59", use_realtime=False,
            )
        self.assertIsNone(late_arrival)
        self.assertIsNone(late_path)

    def test_operating_day_selects_the_matching_run_set(self):
        graph = _graph(("A", "B"))
        manager = _manager(
            _run("weekday", (("A", 600), ("B", 605)), calendar="Weekday"),
            _run("weekend", (("A", 602), ("B", 612)), calendar="SaturdayHoliday"),
        )
        for day_type, expected in (("weekday", 606), ("holiday", 613)):
            with self.subTest(day_type=day_type):
                arrival, path = _fastest(graph, manager, target="B", day_type=day_type)
                self.assertEqual(arrival, expected)
                self.assertEqual(_boardings(graph, path), 1)

    def test_after_midnight_run_does_not_wrap_back_to_zero(self):
        graph = _graph(("A", "B"))
        manager = _manager(_run("overnight", (("A", 1445), ("B", 1450))))
        with contextlib.redirect_stdout(io.StringIO()):
            arrival, path = engine.find_fastest_path(
                graph, manager, _physical("A"), _physical("B"),
                start_time_str="23:58", use_realtime=False,
            )
        self.assertEqual(arrival, 1451)
        self.assertEqual(_boardings(graph, path), 1)

    def test_waiting_and_final_walk_share_the_original_240_minute_deadline(self):
        manager = _manager(_run("late", (("A", 602), ("B", 838))))
        for final_walk, feasible in ((80, True), (81, False)):
            with self.subTest(final_walk=final_walk):
                graph = _graph(("A", "B"))
                _walk(graph, _physical("B"), _physical("C"), final_walk)
                with contextlib.redirect_stdout(io.StringIO()):
                    arrival, path = engine.find_fastest_path(
                        graph, manager, _physical("A"), _physical("C"),
                        start_time_str="10:00", use_realtime=False,
                    )
                if feasible:
                    self.assertEqual(arrival, 840)
                    self.assertEqual(_boardings(graph, path), 1)
                else:
                    self.assertIsNone(arrival)
                    self.assertIsNone(path)

    def test_waiting_keeps_the_same_cost_walk_amount_and_boarding_count(self):
        graph = _graph(("A", "B"))
        _walk(graph, _physical("start"), _physical("A"), 320)
        _walk(graph, _physical("B"), _physical("target"), 280)
        manager = _manager(_run("later", (("A", 660), ("B", 665))))
        candidates = []
        for departure in ("09:58", "10:48"):
            with contextlib.redirect_stdout(io.StringIO()):
                search = engine.find_few_transfers_paths_generator(
                    graph, manager, _physical("start"), _physical("target"),
                    start_time_str=departure, use_realtime=False,
                )
                candidate = next(search)
                search.close()
            self.assertEqual(candidate["walk_m"], 600)
            self.assertEqual(_boardings(graph, candidate["path"]), 1)
            self.assertAlmostEqual(candidate["cost"], 17.05)
            candidates.append(candidate)
        self.assertEqual(candidates[0]["path"], candidates[1]["path"])
        self.assertEqual(candidates[0]["cost"], candidates[1]["cost"])

    def test_paused_generator_uses_one_realtime_snapshot(self):
        graph = _graph(("A", "B"))
        _walk(graph, _physical("A"), _physical("B"), 400)
        manager = _manager(_run("N1", (("A", 600), ("B", 610))))
        with contextlib.redirect_stdout(io.StringIO()):
            search = engine.find_few_transfers_paths_generator(
                graph, manager, _physical("A"), _physical("B"),
                start_time_str="09:58", use_realtime=True,
            )
            first = next(search)
            self.assertEqual(_boardings(graph, first["path"]), 0)
            manager.train_service_suspended.add(RAILWAY)
            manager.realtime_delays["N1"] = 600
            manager.train_status_text[RAILWAY] = "運転見合わせ"
            rest = list(search)
        self.assertTrue(
            any((_line("A"), _line("B")) in
                list(zip(candidate["path"], candidate["path"][1:]))
                for candidate in rest),
            "A search started before the update must keep its original usable train",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            updated = list(engine.find_few_transfers_paths_generator(
                graph, manager, _physical("A"), _physical("B"),
                start_time_str="09:58", use_realtime=True,
            ))
        self.assertFalse(
            any((_line("A"), _line("B")) in
                list(zip(candidate["path"], candidate["path"][1:]))
                for candidate in updated),
            "A new search must use the updated suspension snapshot",
        )


def _identity_graph(*edges):
    graph = _graph(*edges)
    for node, attributes in graph.nodes(data=True):
        name = node[1].rsplit(".", 1)[-1]
        attributes["name_en"] = name
        if node[0] == "phys":
            attributes["station_code"] = name
        else:
            attributes["disp"] = "浅草線"
            attributes["disp_en"] = "Asakusa Line"
    return graph


def _static_trip(identity, stops):
    return StaticTrainTrip(
        trip_id=f"gtfs-{identity}", route_id="1", headsign=stops[-1][0],
        stops=tuple(
            StaticTrainStop(
                sequence=index, stop_id=f"gtfs-stop-{name}", stop_name=name,
                arrival_time=_time(minute) + ":00",
                departure_time=_time(minute) + ":00", stop_code=name,
            )
            for index, (name, minute) in enumerate(stops)
        ),
    )


class TokyoSelectedTrainIntegrationTest(unittest.TestCase):
    def _detail_and_enrich(self, graph, manager, path, trips, *,
                           departure="09:58", day_type="weekday", realtime=False):
        with contextlib.redirect_stdout(io.StringIO()):
            arrival = engine.calculate_real_arrival_time(
                graph, manager, path, start_time_str=departure,
                day_type=day_type, use_realtime=realtime,
            )
            steps = engine.segments_detailed(
                graph, path, manager, start_time_str=departure,
                day_type=day_type, use_realtime=realtime,
            )
        self.assertEqual(arrival, path.edge_times[-1])
        rail_steps = [step for step in steps if step["kind"] == "rail"]
        self.assertTrue(rail_steps)
        self.assertTrue(all("selected_run" in step for step in rail_steps))
        for index, step in enumerate(steps):
            step["step_id"] = f"integration-step-{index}"
        enriched = enrich_route_result_train_trip_ids(
            {"candidates": [{"id": "integration", "steps": steps}], "meta": {}},
            timetable_manager=manager, day_type=day_type,
            static_gtfs=StaticTrainGtfs(trips={trip.trip_id: trip for trip in trips}),
        )
        self.assertEqual(
            len(enriched["candidates"]), 1,
            enriched.get("meta", {}).get("train_identity_rejected_candidates"),
        )
        resolved_rail = [step for step in enriched["candidates"][0]["steps"]
                         if step["kind"] == "rail"]
        self.assertEqual(len(resolved_rail), len(rail_steps))
        self.assertTrue(all("selected_run" not in step for step in resolved_rail))
        return arrival, rail_steps, resolved_rail

    def test_through_run_remains_the_same_in_details_and_exact_gtfs_identity(self):
        graph = _identity_graph(("A", "B"), ("B", "C"))
        manager = _manager(
            _run("N1", (("A", 600), ("B", 605), ("C", 620))),
            _run("N2", (("B", 607), ("C", 608))),
        )
        search_arrival, path = _fastest(graph, manager)
        self.assertEqual(search_arrival, 621)
        arrival, provisional, resolved = self._detail_and_enrich(
            graph, manager, path,
            (_static_trip("N1", (("A", 600), ("B", 605), ("C", 620))),
             _static_trip("N2", (("B", 607), ("C", 608)))),
        )
        self.assertEqual(arrival, search_arrival)
        self.assertEqual(len(provisional), 1)
        self.assertEqual(provisional[0]["selected_run"]["train_number"], "N1")
        self.assertEqual(provisional[0]["arrival_time"], "10:20")
        self.assertEqual(resolved[0]["trip_id"], "gtfs-N1")
        self.assertEqual(resolved[0]["departure_time"], "10:00")
        self.assertEqual(resolved[0]["arrival_time"], "10:20")
        self.assertEqual([stop["id"] for stop in resolved[0]["stops"]],
                         ["gtfs-stop-A", "gtfs-stop-B", "gtfs-stop-C"])

    def test_all_modes_keep_selected_delayed_run_after_live_realtime_changes(self):
        graph = _identity_graph(("A", "B"), ("B", "C"))
        trips = (
            _static_trip("slow", (("A", 600), ("B", 605), ("C", 620))),
            _static_trip("fast", (("A", 601), ("B", 606), ("C", 610))),
        )
        for mode in ("cost", "fewTransfers", "time"):
            with self.subTest(mode=mode):
                manager = _manager(
                    _run("slow", (("A", 600), ("B", 605), ("C", 620))),
                    _run("fast", (("A", 601), ("B", 606), ("C", 610))),
                )
                manager.realtime_delays["fast"] = 120
                with contextlib.redirect_stdout(io.StringIO()):
                    if mode == "time":
                        search_arrival, path = engine.find_fastest_path(
                            graph, manager, _physical("A"), _physical("C"),
                            start_time_str="09:58", use_realtime=True,
                        )
                    else:
                        search_function = (engine.find_paths_generator if mode == "cost"
                                           else engine.find_few_transfers_paths_generator)
                        search = search_function(
                            graph, manager, _physical("A"), _physical("C"),
                            start_time_str="09:58", use_realtime=True,
                        )
                        path = next(search)["path"]
                        search.close()
                        search_arrival = path.edge_times[-1]
                self.assertEqual(search_arrival, 613)
                manager.realtime_delays["fast"] = 600
                manager.train_status_text[RAILWAY] = "遅延"
                manager.train_service_suspended.add(RAILWAY)
                # Enrichment must validate the pinned records and their frozen
                # clocks, without choosing another train from the live table.
                with patch.object(
                    engine.TimetableManager, "get_next_train_arrival",
                    side_effect=AssertionError("selected train must not be reselected"),
                ):
                    arrival, provisional, resolved = self._detail_and_enrich(
                        graph, manager, path, trips, realtime=True,
                    )
                self.assertEqual(arrival, search_arrival)
                self.assertEqual(len(provisional), 1)
                self.assertEqual(provisional[0]["selected_run"]["train_number"], "fast")
                self.assertEqual(provisional[0]["departure_time"], "10:03")
                self.assertEqual(provisional[0]["arrival_time"], "10:12")
                self.assertEqual(resolved[0]["trip_id"], "gtfs-fast")
                self.assertEqual(resolved[0]["departure_time"], "10:03")
                self.assertEqual(resolved[0]["arrival_time"], "10:12")

    def test_saturday_and_holiday_only_runs_stay_on_the_requested_calendar(self):
        graph = _identity_graph(("A", "B"))
        manager = _manager(
            _run("saturday", (("A", 600), ("B", 605)), calendar="Saturday"),
            _run("holiday", (("A", 602), ("B", 612)), calendar="Holiday"),
        )
        trips = (
            _static_trip("saturday", (("A", 600), ("B", 605))),
            _static_trip("holiday", (("A", 602), ("B", 612))),
        )
        for day_type, expected, identity in (("saturday", 606, "saturday"),
                                             ("holiday", 613, "holiday")):
            with self.subTest(day_type=day_type):
                search_arrival, path = _fastest(
                    graph, manager, target="B", day_type=day_type,
                )
                self.assertEqual(search_arrival, expected)
                arrival, provisional, resolved = self._detail_and_enrich(
                    graph, manager, path, trips, day_type=day_type,
                )
                self.assertEqual(arrival, expected)
                self.assertEqual(provisional[0]["selected_run"]["train_number"], identity)
                self.assertEqual(resolved[0]["trip_id"], f"gtfs-{identity}")

    def test_midnight_crossing_keeps_service_day_clocks_through_identity(self):
        graph = _identity_graph(("A", "B"))
        # ODPT sometimes writes the next stop as 00:03; GTFS expresses the
        # same operating-day stop as 24:03. Neither may wrap the itinerary.
        manager = _manager(_run("midnight", (("A", 1439), ("B", 3))))
        with contextlib.redirect_stdout(io.StringIO()):
            search_arrival, path = engine.find_fastest_path(
                graph, manager, _physical("A"), _physical("B"),
                start_time_str="23:57", use_realtime=False,
            )
        self.assertEqual(search_arrival, 1444)
        arrival, provisional, resolved = self._detail_and_enrich(
            graph, manager, path,
            (_static_trip("midnight", (("A", 1439), ("B", 1443))),),
            departure="23:57",
        )
        self.assertEqual(arrival, 1444)
        self.assertEqual(provisional[0]["departure_time"], "23:59")
        self.assertEqual(provisional[0]["arrival_time"], "24:03")
        self.assertEqual(resolved[0]["trip_id"], "gtfs-midnight")
        self.assertEqual(resolved[0]["departure_time"], "23:59")
        self.assertEqual(resolved[0]["arrival_time"], "24:03")


if __name__ == "__main__":
    unittest.main()
