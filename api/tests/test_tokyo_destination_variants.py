"""Final alighting variants must not consume Tokyo's transit candidate budget."""

import contextlib
from dataclasses import replace
import io
import unittest
from unittest.mock import patch

import networkx as nx

import toei_engine as engine
import tokyo_search_labels as labels
from route_engine import RouteContractError
from tokyo_route_signatures import transit_path_signature
from tokyo_timetable_choices import RideState


START = ("phys", "origin")
TARGET = ("phys", "dest:35.0,139.0")


class _Choices:
    can_wait_offboard = True
    use_realtime = False
    manager = object()

    def board_options(self, u, v, ready):
        return ((ready, RideState(
            "bus", "fixture-day", f"run:{v[2]}:{u[1]}", v[2], 0, 0, ready,
        )),)

    def ride_options(self, u, v, current, state):
        return ((current + 1.0, replace(state, sequence=state.sequence + 1)),)


def _leg(graph, board, line, stops, *, board_cost=1.0, mode="bus"):
    """Add one ride with legal alighting at every successive stop."""
    graph.add_node(board, lat=35.0, lon=139.0)
    origin = ("line", board[1], line)
    graph.add_node(origin, mode=mode, line=line, lat=35.0, lon=139.0)
    graph.add_edge(board, origin, etype="board", w=board_cost)
    prefix = [board, origin]
    paths = {}
    previous = origin
    for stop in stops:
        physical = ("phys", stop)
        following = ("line", stop, line)
        graph.add_node(physical, lat=35.0, lon=139.0)
        graph.add_node(following, mode=mode, line=line, lat=35.0, lon=139.0)
        graph.add_edge(previous, following, etype="ride", mode=mode, w=1.0)
        graph.add_edge(following, physical, etype="alight", w=0.0)
        prefix.append(following)
        paths[stop] = [*prefix, physical]
        previous = following
    return paths


def _search(graph, virtual, *, mode, max_search=5, heuristic=lambda node: 0.0):
    with contextlib.redirect_stdout(io.StringIO()):
        return list(labels.search_labels(
            graph, _Choices(), START, TARGET, mode=mode, start_minute=0.0,
            max_search=max_search, max_visited=10000, max_travel_min=240,
            time_limit_sec=15.0, max_total_walk=3000.0, max_segment_walk=600.0,
            walk_speed=80.0, rail_boarding_minutes=2.0,
            advance_time=lambda u, v, clock, edge: clock + edge.get("meters", 0.0) / 80.0,
            virtual_connections=virtual, edge_uses_rail=lambda u, v: False,
            heuristic=heuristic,
        ))


def _candidate_lines(graph, candidate):
    return [graph.nodes[v]["line"]
            for u, v in zip(candidate["path"], candidate["path"][1:])
            if graph.get_edge_data(u, v, {}).get("etype") == "board"]


class TokyoDestinationVariantsTest(unittest.TestCase):
    def test_final_alights_do_not_spend_candidate_budget_and_other_line_same_bucket_survives(self):
        graph = nx.DiGraph()
        _leg(graph, START, "main", ("near", "middle", "far"))
        _leg(graph, START, "alternative", ("alternative-end",), board_cost=10.0)
        virtual = {
            ("phys", "near"): (1.0, 100.0),
            ("phys", "middle"): (2.0, 200.0),
            ("phys", "far"): (3.0, 300.0),
            # The distinct line must survive even with the same final walk bucket.
            ("phys", "alternative-end"): (1.0, 100.0),
        }
        for mode in ("cost", "fewTransfers"):
            with self.subTest(mode=mode):
                candidates = _search(graph, virtual, mode=mode, max_search=2)
                self.assertEqual([_candidate_lines(graph, item) for item in candidates],
                                 [["main"], ["alternative"]])
                self.assertEqual([item["cost"] for item in candidates], [3.0, 12.0])
                self.assertEqual([item["walk_m"] for item in candidates], [100.0, 100.0])

    def test_best_cost_feasible_alighting_is_selected_even_when_it_is_later_and_walks_farther(self):
        graph = nx.DiGraph()
        paths = _leg(graph, START, "main", ("near", "best", "too-far"))
        virtual = {
            ("phys", "near"): (9.0, 100.0),
            ("phys", "best"): (1.0, 200.0),
            ("phys", "too-far"): (0.0, 650.0),
        }
        for mode in ("cost", "fewTransfers"):
            with self.subTest(mode=mode):
                candidates = _search(graph, virtual, mode=mode)
                self.assertEqual(len(candidates), 1)
                candidate = candidates[0]
                self.assertEqual(candidate["path"], [*paths["best"], TARGET])
                self.assertEqual(candidate["cost"], 4.0)
                self.assertEqual(candidate["walk_m"], 200.0)
                self.assertEqual(candidate["path"].arrival_minute, 4.5)
                self.assertEqual({ride.run_id for ride in candidate["path"].edge_rides.values()},
                                 {"run:main:origin"})

    def test_fastest_search_keeps_existing_arrival_and_final_walk_groups(self):
        graph = nx.DiGraph()
        paths = _leg(graph, START, "main", ("near", "middle", "far"))
        virtual = {
            ("phys", "near"): (9.0, 100.0),
            ("phys", "middle"): (2.0, 200.0),
            ("phys", "far"): (1.0, 300.0),
        }
        candidates = _search(graph, virtual, mode="time", max_search=2)
        self.assertEqual([item["path"] for item in candidates],
                         [[*paths["near"], TARGET], [*paths["middle"], TARGET]])
        self.assertEqual([item["path"].arrival_minute for item in candidates], [2.25, 4.5])

    def test_intermediate_alighting_still_offers_a_useful_transfer(self):
        graph = nx.DiGraph()
        first = _leg(graph, START, "main", ("transfer", "far"))
        connection = _leg(graph, ("phys", "transfer"), "connection", ("connection-end",))
        virtual = {
            ("phys", "transfer"): (1.0, 100.0),
            ("phys", "far"): (3.0, 300.0),
            ("phys", "connection-end"): (1.0, 100.0),
        }
        transfer_path = [*first["transfer"], *connection["connection-end"][1:], TARGET]
        for mode in ("cost", "fewTransfers"):
            with self.subTest(mode=mode):
                candidates = _search(graph, virtual, mode=mode, max_search=2)
                self.assertEqual([_candidate_lines(graph, item) for item in candidates],
                                 [["main"], ["main", "connection"]])
                candidate = candidates[1]
                self.assertEqual(candidate["path"], transfer_path)
                self.assertEqual(candidate["cost"], 5.0)
                self.assertEqual(candidate["path"].arrival_minute, 3.25)
                rides = candidate["path"].edge_rides
                self.assertEqual(rides[1].run_id, "run:main:origin")
                self.assertEqual(rides[4].run_id, "run:connection:transfer")
                self.assertEqual((rides[1].board_sequence, rides[1].sequence), (0, 1))
                self.assertEqual((rides[4].board_sequence, rides[4].sequence), (0, 1))
                self.assertEqual((rides[1].departure_minute, rides[4].departure_minute),
                                 (0.0, 1.0))

    def test_later_cheaper_variant_of_yielded_goal_does_not_spend_another_slot(self):
        graph = nx.DiGraph()
        main = _leg(graph, START, "main", ("near", "later"))
        alternative = _leg(graph, START, "alternative", ("alternative-end",), board_cost=150.0)
        virtual = {
            ("phys", "near"): (9.0, 100.0),
            ("phys", "later"): (1.0, 200.0),
            ("phys", "alternative-end"): (1.0, 100.0),
        }
        # Force a same-itinerary cheaper completion to be discovered after the
        # first emission. Even an inconsistent caller heuristic cannot refill
        # the quota with another final alighting variant.
        candidates = _search(
            graph, virtual, mode="cost", max_search=2,
            heuristic=lambda node: 100.0 if node == ("line", "later", "main") else 0.0,
        )
        self.assertEqual([item["path"] for item in candidates],
                         [[*main["near"], TARGET], [*alternative["alternative-end"], TARGET]])
        self.assertEqual([item["cost"] for item in candidates], [11.0, 152.0])
        self.assertEqual([item["path"].edge_rides[1].run_id for item in candidates],
                         ["run:main:origin", "run:alternative:origin"])

    def test_response_collector_keeps_cheapest_final_alighting_even_if_it_walks_farther(self):
        graph = nx.DiGraph()
        paths = _leg(graph, START, "main", ("near", "far"))

        def selected_path(stop, arrival):
            nodes = [*paths[stop], TARGET]
            return labels.SelectedPath(
                nodes, [600.0] * (len(nodes) - 2) + [arrival], {}, _Choices(), 600.0,
            )

        near = selected_path("near", 610.0)
        far = selected_path("far", 620.0)
        for mode, generator_name in (("cost", "find_paths_generator"),
                                     ("fewTransfers", "find_few_transfers_paths_generator")):
            with self.subTest(mode=mode):
                consumed = []

                def raw_paths():
                    consumed.append(near)
                    yield {"cost": 11.0, "path": near, "walk_m": 100.0}
                    consumed.append(far)
                    yield {"cost": 4.0, "path": far, "walk_m": 200.0}
                    raise AssertionError("Duplicate grouping must respect the raw candidate limit")

                def details_for_path(graph, path, *args, **kwargs):
                    return [
                        {"kind": "bus", "title": "main", "meters": 0.0},
                        {"kind": "walk", "title": "walk", "meters": (
                            100.0 if path[-2] == ("phys", "near") else 200.0)},
                    ]

                with patch.object(engine, generator_name, return_value=raw_paths()), \
                        patch.object(engine, "calculate_real_arrival_time",
                                     side_effect=lambda graph, tm, path, *args, **kwargs:
                                     path.arrival_minute) as real_arrival, \
                        patch.object(engine, "segments_detailed", side_effect=details_for_path) as details, \
                        patch.object(engine, "path_to_coords", return_value=[]), \
                        patch.object(engine, "path_to_route_geometry", return_value=[
                            {"kind": "bus", "points": [[35.0, 139.0], [35.0, 139.0]]},
                        ]), \
                        contextlib.redirect_stdout(io.StringIO()):
                    candidates = engine.search_best_routes(
                        graph, object(), START, mode=mode, start_time="10:00", limit=2,
                        target_node=TARGET, day_type="weekday", use_realtime=False,
                    )
                self.assertEqual(consumed, [near, far])
                self.assertEqual(len(candidates), 1)
                self.assertIs(candidates[0]["path"], far)
                self.assertEqual(candidates[0]["cost_score"], 4.0)
                self.assertEqual(candidates[0]["walking_distance_meters"], 200)
                self.assertEqual(candidates[0]["arrival_time"], "10:20")
                self.assertEqual(real_arrival.call_count, 1)
                self.assertEqual(details.call_count, 1)

    def _neighboring_initial_bus_boarding_fixture(self):
        graph = nx.DiGraph()
        board_three = ("phys", "yahiro-three")
        board_four = ("phys", "yahiro-four")
        via_three = _leg(graph, board_three, "kin37", ("yahiro-four", "transfer"))["transfer"]
        via_four = _leg(graph, board_four, "kin37", ("transfer",))["transfer"]
        last_ride = _leg(graph, ("phys", "transfer"), "kusa39", ("arrival",))["arrival"]
        graph.add_node(START)
        graph.add_node(TARGET)
        graph.add_edge(START, board_three, etype="walk", meters=40.0, w=1.0)
        graph.add_edge(START, board_four, etype="walk", meters=70.0, w=2.0)
        graph.add_edge(("phys", "arrival"), TARGET, etype="walk", meters=500.0, w=1.0)

        def selected(first_leg, *, first_trip="kin37-trip", service="saturday"):
            nodes = [START, *first_leg, *last_ride[1:], TARGET]
            board_indexes = [
                index for index, (u, v) in enumerate(zip(nodes, nodes[1:]))
                if graph.get_edge_data(u, v)["etype"] == "board"
            ]
            self.assertEqual(len(board_indexes), 2)
            rides = {
                board_indexes[0]: RideState(
                    "bus", service, f"feed|{service}|{first_trip}",
                    "kin37", 1, 1, 497, trip_id=first_trip,
                ),
                board_indexes[1]: RideState(
                    "bus", service, f"feed|{service}|kusa39-trip",
                    "kusa39", 1, 1, 507, trip_id="kusa39-trip",
                ),
            }
            return labels.SelectedPath(
                nodes, [497.0] * (len(nodes) - 2) + [509.0],
                rides, _Choices(), 480.0,
            )

        return graph, selected(via_four), selected(via_three)

    def test_neighboring_boarding_poles_on_same_bus_run_keep_shorter_walk(self):
        graph, long_walk, short_walk = self._neighboring_initial_bus_boarding_fixture()
        self.assertNotEqual(
            engine._transit_path_signature(graph, long_walk),
            engine._transit_path_signature(graph, short_walk),
        )

        for mode, generator_name in (
            ("cost", "find_paths_generator"),
            ("fewTransfers", "find_few_transfers_paths_generator"),
        ):
            with self.subTest(mode=mode):
                def raw_paths():
                    yield {"cost": 4.0, "path": long_walk, "walk_m": 573.0}
                    yield {"cost": 5.0, "path": short_walk, "walk_m": 546.0}
                    raise AssertionError("Do not search past the raw candidate limit")

                with patch.object(engine, generator_name, return_value=raw_paths()), \
                        patch.object(engine, "calculate_real_arrival_time",
                                     side_effect=lambda g, tm, p, *args, **kw:
                                     p.arrival_minute) as arrival, \
                        patch.object(engine, "segments_detailed",
                                     side_effect=lambda g, p, *args, **kw: [
                                         {"kind": "bus", "title": "錦37", "meters": 0},
                                         {"kind": "bus", "title": "草39", "meters": 0},
                                         {"kind": "walk", "title": "徒歩", "meters":
                                          573 if p is long_walk else 546},
                                     ]) as detail, \
                        patch.object(engine, "path_to_coords", return_value=[]), \
                        contextlib.redirect_stdout(io.StringIO()):
                    candidates = engine.search_best_routes(
                        graph, object(), START, mode=mode,
                        start_time="08:00", limit=2,
                        target_node=TARGET, day_type="saturday",
                        use_realtime=False,
                    )

                self.assertEqual(len(candidates), 1)
                self.assertIs(candidates[0]["path"], short_walk)
                self.assertEqual(candidates[0]["walking_distance_meters"], 546)
                self.assertEqual(candidates[0]["arrival_time"], "08:29")
                self.assertEqual(arrival.call_count, 1)
                self.assertEqual(detail.call_count, 1)

    def test_different_first_bus_runs_or_service_days_stay_distinct(self):
        graph, first, second = self._neighboring_initial_bus_boarding_fixture()
        first_board_index = next(
            i for i, (u, v) in enumerate(zip(second, second[1:]))
            if graph.get_edge_data(u, v)["etype"] == "board"
        )
        initial_state = second.edge_rides[first_board_index]

        for difference, modified in (
            ("trip", replace(
                initial_state, run_id="feed|saturday|other-trip",
                trip_id="other-trip",
            )),
            ("service", replace(
                initial_state, run_id="feed|sunday|kin37-trip",
                service_key="sunday",
            )),
        ):
            with self.subTest(difference=difference):
                from_first = labels.SelectedPath(
                    second, second.edge_times,
                    {**second.edge_rides, first_board_index: modified},
                    second.choices, second.start_minute,
                )

                def raw_paths():
                    yield {"cost": 4.0, "path": first, "walk_m": 573.0}
                    yield {"cost": 5.0, "path": from_first, "walk_m": 546.0}

                with patch.object(engine, "find_few_transfers_paths_generator",
                                  return_value=raw_paths()), \
                        patch.object(engine, "calculate_real_arrival_time",
                                     return_value=509.0), \
                        patch.object(engine, "segments_detailed",
                                     return_value=[
                                         {"kind": "bus", "title": "錦37", "meters": 0},
                                         {"kind": "bus", "title": "草39", "meters": 0},
                                         {"kind": "walk", "title": "徒歩", "meters": 500},
                                     ]), \
                        patch.object(engine, "path_to_coords", return_value=[]), \
                        contextlib.redirect_stdout(io.StringIO()):
                    candidates = engine.search_best_routes(
                        graph, object(), START, mode="fewTransfers",
                        start_time="08:00", limit=2,
                        target_node=TARGET, day_type="saturday",
                        use_realtime=False,
                    )
                self.assertEqual(len(candidates), 2)


    def test_goal_signature_rejects_changed_explicit_line_even_in_transit_only_mode(self):
        graph = nx.DiGraph()
        path = _leg(graph, START, "main", ("end",))["end"]
        graph.nodes[("line", "end", "main")]["line"] = "different-line"
        with self.assertRaisesRegex(RouteContractError, "ride line changed without a transfer"):
            transit_path_signature(graph, [*path, TARGET], transit_only=True)

    def test_signature_ignores_only_last_alighting_and_trailing_walk(self):
        graph = nx.DiGraph()
        paths = _leg(graph, START, "main", ("near", "far"))
        detour = ("phys", "detour")
        graph.add_edge(("phys", "near"), TARGET, etype="walk", meters=100.0)
        graph.add_edge(("phys", "far"), detour, etype="walk", meters=50.0)
        graph.add_edge(detour, TARGET, etype="walk", meters=200.0)
        self.assertEqual(
            engine._transit_path_signature(graph, [*paths["near"], TARGET]),
            engine._transit_path_signature(graph, [*paths["far"], detour, TARGET]),
        )

    def test_signature_preserves_final_direction_boarding_line_and_mode(self):
        graph = nx.DiGraph()
        north = _leg(graph, START, "main", ("north", "end"))["end"]
        south = _leg(graph, START, "main", ("south", "end"))["end"]
        other_board = _leg(graph, ("phys", "other-origin"), "main", ("north", "end"))["end"]
        other_line = _leg(graph, START, "another-pattern", ("north", "end"))["end"]
        signature = engine._transit_path_signature(graph, [*north, TARGET])
        for name, path in (("direction", south), ("boarding", other_board),
                           ("line-pattern", other_line)):
            with self.subTest(difference=name):
                self.assertNotEqual(signature, engine._transit_path_signature(graph, [*path, TARGET]))
        rail_graph = nx.DiGraph()
        rail = _leg(rail_graph, START, "main", ("north", "end"), mode="rail")["end"]
        self.assertNotEqual(signature, engine._transit_path_signature(rail_graph, [*rail, TARGET]))

    def test_signature_preserves_previous_alighting_and_transfer_boarding(self):
        graph = nx.DiGraph()
        first = _leg(graph, START, "first", ("transfer-a", "transfer-b"))
        final_a = _leg(graph, ("phys", "transfer-a"), "last", ("near", "far"))
        final_b = _leg(graph, ("phys", "transfer-b"), "last", ("near", "far"))
        path_a = [*first["transfer-a"], *final_a["near"][1:], TARGET]
        path_b = [*first["transfer-b"], *final_b["near"][1:], TARGET]
        path_a_far = [*first["transfer-a"], *final_a["far"][1:], TARGET]
        self.assertEqual(engine._transit_path_signature(graph, path_a),
                         engine._transit_path_signature(graph, path_a_far))
        self.assertNotEqual(engine._transit_path_signature(graph, path_a),
                            engine._transit_path_signature(graph, path_b))

    def test_signature_keeps_previous_alighting_when_final_boarding_is_the_same(self):
        graph = nx.DiGraph()
        first = _leg(graph, START, "first", ("transfer-a", "transfer-b"))
        hub = ("phys", "common-boarding")
        final = _leg(graph, hub, "last", ("near",))["near"]
        for stop in ("transfer-a", "transfer-b"):
            graph.add_edge(("phys", stop), hub, etype="walk", meters=50.0)
        path_a = [*first["transfer-a"], *final, TARGET]
        path_b = [*first["transfer-b"], *final, TARGET]
        self.assertNotEqual(engine._transit_path_signature(graph, path_a),
                            engine._transit_path_signature(graph, path_b))


if __name__ == "__main__":
    unittest.main()
