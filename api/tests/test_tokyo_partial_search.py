"""Tokyo keeps validated candidates when a typed search budget is exhausted."""

from __future__ import annotations

import contextlib
from dataclasses import replace
import datetime as dt
import gc
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref
from zoneinfo import ZoneInfo

import networkx as nx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.route_endpoint import register_route_endpoint
from route_engine import RouteContractError, RouteSearchLimitError
import toei_engine as engine
from tokyo_route_engine import TokyoRouteDependencies, TokyoRouteEngine
import tokyo_search_labels as labels
from tokyo_timetable_choices import RideState


ORIGIN = ("phys", "origin")
DESTINATION = ("phys", "destination")
REASONS = (
    "max_visited", "time_limit_sec", "queue_size", "g_score_size",
    "max_expanded", "max_search",
)


def _fixture():
    graph = nx.DiGraph()
    graph.add_node(ORIGIN, name="Origin", name_en="Origin", lat=35.0, lon=139.0)
    graph.add_node(DESTINATION, name="Destination", name_en="Destination",
                   lat=35.1, lon=139.1)
    rows = []
    for index in range(3):
        line = f"line-{index}"
        left, right = ("line", "origin", line), ("line", "destination", line)
        graph.add_node(left, mode="bus", line=line, lat=35.0, lon=139.0)
        graph.add_node(right, mode="bus", line=line, lat=35.1, lon=139.1)
        graph.add_edge(ORIGIN, left, etype="board", w=5.0)
        graph.add_edge(left, right, etype="ride", w=0.8)
        graph.add_edge(right, DESTINATION, etype="alight", w=0.0)
        rows.append({"path": [ORIGIN, left, right, DESTINATION],
                     "cost": 7.0 + index, "walk_m": 0.0})
    manager = SimpleNamespace(get_delays_snapshot=lambda: {})
    return graph, manager, rows


def _steps(_graph, path, *_args, **_kwargs):
    title = path[1][2]
    return [{"kind": "bus", "title": title,
             "title_en": f"Route {title} · Destination",
             "from_": "Origin", "from_en": "Origin",
             "to": "Destination", "to_en": "Destination",
             "minutes": 15, "meters": 0,
             "stops": [{"name": "Origin", "name_en": "Origin"},
                       {"name": "Destination", "name_en": "Destination"}]}]


def _error(reason="max_visited"):
    return RouteSearchLimitError(
        f"synthetic budget exhausted: {reason}", reason=reason,
        diagnostics={"mode": "fewTransfers", "visited": 100001,
                     "yielded": 3, "queue": 12, "g_score": 17,
                     "best_cost": 25, "frontier_labels": 29,
                     "elapsed_sec": 2.0, "max_visited": 100000,
                     "max_search": 30000, "time_limit_sec": 15.0},
    )


class _RawStream:
    """Record explicit cleanup and forbid iteration after a normal limit."""

    def __init__(self, rows, error=None, *, chained=False):
        self.rows = rows
        self.error = error
        self.chained = chained
        self.next_calls = 0
        self.close_calls = 0

    def __iter__(self):
        return self

    def __next__(self):
        index = self.next_calls
        self.next_calls += 1
        if index < len(self.rows):
            return self.rows[index]
        if self.error is not None:
            if self.chained:
                raise self.error from ValueError("retained search context")
            raise self.error
        raise StopIteration

    def close(self):
        self.close_calls += 1


@contextlib.contextmanager
def _mock_search(stream, mode="fewTransfers", *, arrival=615, steps=_steps):
    selected = ("find_few_transfers_paths_generator" if mode == "fewTransfers"
                else "find_paths_generator")
    other = ("find_paths_generator" if mode == "fewTransfers"
             else "find_few_transfers_paths_generator")
    with (patch.object(engine, selected, return_value=stream) as generator,
          patch.object(engine, other, side_effect=AssertionError("wrong objective")),
          patch.object(engine, "calculate_real_arrival_time", side_effect=arrival)
          if callable(arrival) else patch.object(engine, "calculate_real_arrival_time", return_value=arrival),
          patch.object(engine, "segments_detailed", side_effect=steps)
          if callable(steps) else patch.object(engine, "segments_detailed", return_value=steps),
          contextlib.redirect_stdout(io.StringIO())):
        yield generator


def _collect(graph, manager, *, mode="fewTransfers", limit=5):
    return engine.search_best_routes(
        graph, manager, ORIGIN, mode=mode, start_time="10:00", limit=limit,
        target_date=dt.datetime(2026, 10, 4, 10), target_node=DESTINATION,
        day_type="weekend", use_realtime=False,
    )


def _http_client(graph, manager):
    app = FastAPI()
    app.state.loading_status = "ready"
    app.state.G = graph
    app.state.TM = manager
    app.state.WALK_RAD = 500
    app.state.SI = object()
    nearest = iter(((ORIGIN, 0.0), (DESTINATION, 0.0)))
    dependencies = TokyoRouteDependencies(
        nearest_phys=lambda *_args, **_kwargs: next(nearest),
        haversine=lambda *_args: 0.0,
        get_virtual_connections=lambda *_args, **_kwargs: (
            ("phys", "dest:test"), [(DESTINATION, 0.0, 0.0)]),
        search_best_routes_once=engine.search_best_routes_once,
        assign_candidate_step_ids=lambda _candidate: None,
        rss_mb=lambda: -1.0,
        now=lambda: dt.datetime(2026, 10, 5, 10, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
    app.state.route_engine = TokyoRouteEngine(app, dependencies=dependencies)
    register_route_endpoint(app, warmup_message="warming up")
    return TestClient(app)


def _payload(mode="fewTransfers"):
    return {"alat": 35.0, "alon": 139.0, "blat": 35.1, "blon": 139.1,
            "pref": mode, "start_time": "10:00",
            "target_date_str": "2026-10-04", "limit": 5}


class TokyoPartialCollectorTest(unittest.TestCase):
    def test_recognized_limits_keep_three_valid_candidates_for_both_objectives(self):
        for mode in ("fewTransfers", "cost"):
            for reason in REASONS:
                with self.subTest(mode=mode, reason=reason):
                    graph, manager, rows = _fixture()
                    error = _error(reason)
                    stream = _RawStream(rows, error, chained=True)
                    with _mock_search(stream, mode):
                        result = _collect(graph, manager, mode=mode)
                    self.assertIsInstance(result, list)
                    self.assertEqual([row["lines"] for row in result],
                                     [[f"line-{index}"] for index in range(3)])
                    self.assertIs(result.search_limit_error, error)
                    self.assertEqual(stream.close_calls, 1)
                    self.assertIsNone(error.__traceback__)
                    self.assertIsNone(error.__context__)
                    self.assertIsNone(error.__cause__)

    def test_zero_raw_candidates_reraise_same_error_and_close(self):
        for mode in ("fewTransfers", "cost"):
            with self.subTest(mode=mode):
                graph, manager, _ = _fixture()
                error = _error()
                stream = _RawStream([], error)
                with _mock_search(stream, mode), self.assertRaises(RouteSearchLimitError) as raised:
                    _collect(graph, manager, mode=mode)
                self.assertIs(raised.exception, error)
                self.assertEqual(stream.close_calls, 1)

    def test_failed_arrival_validation_does_not_turn_limit_into_success(self):
        graph, manager, rows = _fixture()
        error = _error()
        stream = _RawStream(rows, error)
        with _mock_search(stream, arrival=None), self.assertRaises(RouteSearchLimitError) as raised:
            _collect(graph, manager)
        self.assertIs(raised.exception, error)
        self.assertEqual(stream.close_calls, 1)

    def test_failed_segment_validation_does_not_turn_limit_into_success(self):
        graph, manager, rows = _fixture()
        error = _error()
        stream = _RawStream(rows, error)
        with _mock_search(stream, steps=[]), self.assertRaises(RouteSearchLimitError) as raised:
            _collect(graph, manager)
        self.assertIs(raised.exception, error)
        self.assertEqual(stream.close_calls, 1)

    def test_duplicate_transit_paths_still_collapse_to_one_valid_candidate(self):
        graph, manager, rows = _fixture()
        duplicate = dict(rows[0], cost=12.0, walk_m=100.0)
        error = _error()
        stream = _RawStream([duplicate, rows[0], dict(rows[0])], error)
        with _mock_search(stream):
            result = _collect(graph, manager)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["cost_score"], rows[0]["cost"])
        self.assertIs(result.search_limit_error, error)

    def test_unrecognized_or_untyped_failures_are_not_swallowed_after_a_candidate(self):
        failures = (
            _error("unknown_budget"), RouteSearchLimitError("legacy message only"),
            RouteContractError("invalid transit data"), RuntimeError("internal failure"),
        )
        for failure in failures:
            with self.subTest(failure=repr(failure)):
                graph, manager, rows = _fixture()
                stream = _RawStream(rows[:1], failure)
                with _mock_search(stream), self.assertRaises(type(failure)) as raised:
                    _collect(graph, manager)
                self.assertIs(raised.exception, failure)
                self.assertEqual(stream.close_calls, 1)

    def test_requested_limit_stops_without_an_extra_pop_and_closes(self):
        for mode in ("fewTransfers", "cost"):
            with self.subTest(mode=mode):
                graph, manager, rows = _fixture()
                stream = _RawStream(rows[:2], AssertionError("must not resume beyond limit"))
                with _mock_search(stream, mode):
                    result = _collect(graph, manager, mode=mode, limit=2)
                self.assertEqual(len(result), 2)
                self.assertEqual(stream.next_calls, 2)
                self.assertEqual(stream.close_calls, 1)
                self.assertIsNone(getattr(result, "search_limit_error", None))

    def test_search_once_preserves_partial_list_and_departure_annotations(self):
        graph, manager, rows = _fixture()
        error = _error()
        stream = _RawStream(rows, error)
        with _mock_search(stream):
            result = engine.search_best_routes_once(
                graph, manager, ORIGIN, mode="fewTransfers", start_time="10:00",
                target_date_str="2026-10-04", target_node=DESTINATION,
                day_type="weekend", use_realtime=False,
            )
        self.assertIs(result.search_limit_error, error)
        self.assertTrue(all(row["departure_date"] == "2026-10-04T10:00:00"
                            for row in result))

    def test_low_level_generator_still_raises_with_structured_diagnostics(self):
        graph = nx.DiGraph()
        graph.add_edge(ORIGIN, DESTINATION, etype="walk", w=1.0, meters=1.0)
        choices = SimpleNamespace(can_wait_offboard=True, manager=None, use_realtime=False)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RouteSearchLimitError) as raised:
            list(labels.search_labels(
                graph, choices, ORIGIN, DESTINATION, mode="fewTransfers", start_minute=600,
                max_search=5, max_visited=1, max_travel_min=240, time_limit_sec=15,
                max_total_walk=3000, max_segment_walk=600, walk_speed=80,
                rail_boarding_minutes=2, advance_time=lambda _u, _v, time, _edge: time + 1,
                virtual_connections={}, edge_uses_rail=lambda _u, _v: False,
            ))
        error = raised.exception
        self.assertEqual(error.reason, "max_visited")
        self.assertLessEqual(
            {"mode", "visited", "yielded", "queue", "g_score", "best_cost",
             "frontier_labels", "elapsed_sec", "max_visited", "max_search", "time_limit_sec"},
            set(error.diagnostics),
        )
        self.assertEqual(error.diagnostics["mode"], "fewTransfers")
        self.assertEqual(error.diagnostics["visited"], 2)
        self.assertEqual(error.diagnostics["yielded"], 0)

    def test_collector_preserves_candidate_from_real_core_before_actual_pop_limit(self):
        graph, manager, _ = _fixture()
        for index in range(3):
            graph.edges[("line", "origin", f"line-{index}"),
                        ("line", "destination", f"line-{index}")]["w"] = 0.8 + index

        class Choices:
            can_wait_offboard = True
            use_realtime = False

            def __init__(self):
                self.manager = manager

            def board_options(self, _origin, following, ready):
                return ((ready, RideState("bus", "day", following[2], following[2],
                                          0, 0, ready)),)

            def ride_options(self, _origin, _following, current, ride):
                return ((current + 1, replace(ride, sequence=ride.sequence + 1)),)

        def actual_core(_graph, _manager, start, target, *_args, **_kwargs):
            return labels.search_labels(
                graph, Choices(), start, target, mode="fewTransfers", start_minute=600,
                max_search=30000, max_visited=4, max_travel_min=240, time_limit_sec=15,
                max_total_walk=3000, max_segment_walk=600, walk_speed=80,
                rail_boarding_minutes=2, advance_time=lambda _u, _v, time, _edge: time,
                virtual_connections={}, edge_uses_rail=lambda _u, _v: False,
            )

        with (patch.object(engine, "find_few_transfers_paths_generator", side_effect=actual_core),
              patch.object(engine, "calculate_real_arrival_time", return_value=615),
              patch.object(engine, "segments_detailed", side_effect=_steps),
              contextlib.redirect_stdout(io.StringIO())):
            result = _collect(graph, manager)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["lines"], ["line-0"])
        error = result.search_limit_error
        self.assertEqual(error.reason, "max_visited")
        self.assertEqual(error.diagnostics["visited"], 5)
        self.assertEqual(error.diagnostics["yielded"], 1)
        self.assertEqual(error.diagnostics["max_visited"], 4)
        self.assertIsNone(error.__traceback__)

    def test_generator_frame_resources_are_released_before_detail_generation(self):
        graph, manager, rows = _fixture()
        error = _error()
        markers = []
        closed = []
        detail_calls = []

        class Marker:
            pass

        def source():
            marker = Marker()
            markers.append(weakref.ref(marker))
            try:
                yield from rows
                marker.finished = True
                raise error
            finally:
                closed.append(True)

        stream = source()

        def details(graph_value, path, *args, **kwargs):
            gc.collect()
            self.assertEqual(closed, [True])
            self.assertIsNone(stream.gi_frame)
            self.assertIsNone(markers[0](), "exception traceback retained the search frame")
            detail_calls.append(path)
            return _steps(graph_value, path, *args, **kwargs)

        with _mock_search(stream, steps=details):
            result = _collect(graph, manager)
        self.assertEqual(len(result), 3)
        self.assertEqual(len(detail_calls), 3)
        self.assertIs(result.search_limit_error, error)
        self.assertIsNone(markers[0]())


class TokyoPartialEndpointTest(unittest.TestCase):
    def test_partial_validation_keeps_two_candidates_and_http_200_for_both_modes(self):
        def arrival(_graph, _manager, path, *_args, **_kwargs):
            return None if path[1][2] == "line-1" else 615

        for mode in ("fewTransfers", "cost"):
            with self.subTest(mode=mode):
                graph, manager, rows = _fixture()
                error = _error()
                stream = _RawStream(rows, error)
                with _mock_search(stream, mode, arrival=arrival) as generator:
                    response = _http_client(graph, manager).post("/route", json=_payload(mode))
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertEqual([row["lines"] for row in payload["candidates"]],
                                 [["line-0"], ["line-2"]])
                self.assertTrue(payload["meta"]["truncated"])
                self.assertEqual(payload["meta"]["termination_reason"], "max_visited")
                self.assertEqual(payload["meta"]["search_diagnostics"], error.diagnostics)
                generator.assert_called_once()
                self.assertEqual(stream.close_calls, 1)

    def test_all_raw_candidates_invalid_keep_http_503_without_fallback_search(self):
        for mode in ("fewTransfers", "cost"):
            for invalid in ("arrival", "segments"):
                with self.subTest(mode=mode, invalid=invalid):
                    graph, manager, rows = _fixture()
                    error = _error()
                    stream = _RawStream(rows, error)
                    with _mock_search(
                            stream, mode, arrival=None if invalid == "arrival" else 615,
                            steps=[] if invalid == "segments" else _steps) as generator:
                        response = _http_client(graph, manager).post("/route", json=_payload(mode))
                    self.assertEqual(response.status_code, 503, response.text)
                    self.assertEqual(response.json()["detail"]["code"], "route_search_limit")
                    self.assertEqual(response.json()["detail"]["diagnostic"], str(error))
                    generator.assert_called_once()
                    self.assertEqual(stream.close_calls, 1)

    def test_adapter_copies_partial_diagnostics_without_retaining_a_traceback(self):
        graph, manager, rows = _fixture()
        error = _error()
        stream = _RawStream(rows, error, chained=True)
        adapter = _http_client(graph, manager).app.state.route_engine
        with _mock_search(stream):
            payload = adapter.search_legacy(
                alat=35.0, alon=139.0, blat=35.1, blon=139.1,
                pref="fewTransfers", start_time="10:00", date_str="2026-10-04", limit=5,
            )
        diagnostics = payload["meta"]["search_diagnostics"]
        self.assertEqual(diagnostics, error.diagnostics)
        self.assertIsNot(diagnostics, error.diagnostics)
        diagnostics["visited"] = -1
        self.assertEqual(error.diagnostics["visited"], 100001)
        self.assertIsNone(error.__traceback__)
        self.assertIsNone(error.__context__)
        self.assertIsNone(error.__cause__)

    def test_partial_collector_reaches_http_200_with_diagnostics(self):
        for mode in ("fewTransfers", "cost"):
            with self.subTest(mode=mode):
                graph, manager, rows = _fixture()
                error = _error("time_limit_sec")
                stream = _RawStream(rows, error)
                with _mock_search(stream, mode):
                    response = _http_client(graph, manager).post("/route", json=_payload(mode))
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertEqual(len(payload["candidates"]), 3)
                self.assertTrue(payload["meta"]["truncated"])
                self.assertEqual(payload["meta"]["termination_reason"], "time_limit_sec")
                self.assertEqual(payload["meta"]["search_diagnostics"], error.diagnostics)
                self.assertEqual(stream.close_calls, 1)
                self.assertIsNone(error.__traceback__)

    def test_no_candidate_keeps_http_503_search_limit(self):
        graph, manager, _ = _fixture()
        error = _error()
        stream = _RawStream([], error)
        with _mock_search(stream):
            response = _http_client(graph, manager).post("/route", json=_payload())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "route_search_limit")
        self.assertEqual(response.json()["detail"]["diagnostic"], str(error))
        self.assertEqual(stream.close_calls, 1)

    def test_normal_completion_does_not_add_partial_metadata(self):
        graph, manager, rows = _fixture()
        stream = _RawStream(rows)
        with _mock_search(stream):
            response = _http_client(graph, manager).post("/route", json=_payload())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["candidates"]), 3)
        for key in ("truncated", "termination_reason", "search_diagnostics"):
            self.assertNotIn(key, response.json()["meta"])
        self.assertEqual(stream.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
