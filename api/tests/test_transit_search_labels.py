"""The shared label core works without Tokyo loaders or manager metadata."""

import contextlib
from dataclasses import dataclass, replace
import io
from pathlib import Path
import pickle
import subprocess
import sys
from types import SimpleNamespace
import unittest

import networkx as nx

from route_engine import RouteContractError, RouteSearchLimitError
import transit_search_labels as shared
import tokyo_search_labels as tokyo


@dataclass(frozen=True)
class _Run:
    run_id: str
    sequence: int
    board_sequence: int

    @property
    def future_key(self):
        return self.run_id, self.sequence, self.sequence != self.board_sequence


class _Choices:
    can_wait_offboard = True
    stops = ("a", "b", "a", "c")
    times = (10.0, 12.0, 14.0, 16.0)

    def board_options(self, u, v, ready):
        if ready > self.times[0]:
            return ()
        return ((10.0, _Run("loop", 0, 0)),)

    def ride_options(self, u, v, clock, ride):
        following = ride.sequence + 1
        if (following >= len(self.stops)
                or (u, v) != (self.stops[ride.sequence], self.stops[following])):
            return ()
        return ((self.times[following], replace(ride, sequence=following)),)


class _ZeroBound:
    def __init__(self, mode):
        self.mode = mode
        self.report = {}

    def __call__(self, node, segment_walk=None):
        return (0, 0.0) if self.mode == "fewTransfers" else 0.0


def _fixture():
    graph = nx.DiGraph()
    for node in ("a", "b", "c"):
        graph.add_node(node, mode="bus")
    graph.add_edge("start", "board", etype="walk", meters=80.0, w=1.5)
    graph.add_edge("board", "a", etype="board", w=5.0)
    graph.add_edge("a", "b", etype="ride", w=0.8)
    graph.add_edge("b", "a", etype="ride", w=0.8)
    graph.add_edge("a", "c", etype="ride", w=0.8)
    graph.add_edge("c", "finish", etype="alight", w=0.0)
    graph.add_edge("finish", "target", etype="walk", meters=80.0, w=1.5)
    return graph


def _search(mode, **overrides):
    graph = _fixture()
    choices = _Choices()

    def prepare_bounds(check_deadline, deadline):
        check_deadline()
        return _ZeroBound(mode), lambda cost, remaining: cost, lambda clock, remaining: clock

    arguments = dict(
        mode=mode, start_minute=9.0, max_search=5, max_visited=1000,
        max_travel_min=240.0, time_limit_sec=15.0,
        max_total_walk=3000.0, max_segment_walk=600.0,
        walk_speed=80.0, rail_boarding_minutes=2.0,
        advance_time=lambda u, v, clock, edge: clock + edge.get("meters", 0.0) / 80.0,
        virtual_connections={}, edge_uses_rail=lambda u, v: False,
        prepare_bounds=prepare_bounds, path_signature=tuple,
        path_factory=shared.SelectedPath, compact_queue=shared._compact_queue,
        ride_options=lambda u, v, clock, ride, edge: choices.ride_options(u, v, clock, ride),
        alight_minutes=lambda ride: 0.0,
    )
    arguments.update(overrides)
    with contextlib.redirect_stdout(io.StringIO()):
        return list(shared.search_labels(graph, choices, "start", "target", **arguments))


class TransitSearchLabelsTest(unittest.TestCase):
    def test_circular_run_and_exact_clocks_in_all_objectives_without_tokyo_manager(self):
        for mode in ("cost", "time", "fewTransfers"):
            with self.subTest(mode=mode):
                candidates = _search(mode)
                self.assertEqual(len(candidates), 1)
                path = candidates[0]["path"]
                self.assertEqual(path, ["start", "board", "a", "b", "a", "c", "finish", "target"])
                self.assertEqual(path.edge_times, [10.0, 10.0, 12.0, 14.0, 16.0, 16.0, 17.0])
                self.assertEqual([ride.sequence for ride in path.edge_rides.values()], [0, 1, 2, 3])
                self.assertEqual({ride.run_id for ride in path.edge_rides.values()}, {"loop"})
                self.assertEqual(path.arrival_minute, 17.0)
                self.assertEqual(candidates[0]["walk_m"], 160.0)
                self.assertFalse(hasattr(path, "timetable_manager"))
                self.assertFalse(hasattr(path.choices, "manager"))

    def test_exact_total_and_segment_walking_limits(self):
        for mode in ("cost", "time", "fewTransfers"):
            with self.subTest(mode=mode):
                self.assertEqual(len(_search(mode, max_total_walk=160.0, max_segment_walk=80.0)), 1)
                self.assertEqual(_search(mode, max_total_walk=159.0), [])
                self.assertEqual(_search(mode, max_segment_walk=79.0), [])

    def test_explicit_alighting_policy_changes_the_same_selected_run_clock(self):
        path = _search("time", alight_minutes=lambda ride: 1.25)[0]["path"]
        self.assertEqual(path.edge_times[-2:], [17.25, 18.25])
        self.assertEqual({ride.run_id for ride in path.edge_rides.values()}, {"loop"})

    def test_builder_failure_propagates_the_original_exception_without_retry(self):
        error = ValueError("invalid snapshot version")
        calls = []

        def broken(check_deadline, deadline):
            calls.append(deadline)
            raise error

        with self.assertRaises(ValueError) as raised:
            _search("time", prepare_bounds=broken)
        self.assertIs(raised.exception, error)
        self.assertEqual(calls, [249.0])

    def test_provider_failure_propagates_without_another_provider(self):
        error = RouteContractError("invalid run order")
        calls = []

        def broken(u, v, clock, ride, edge):
            calls.append((u, v))
            raise error

        with self.assertRaises(RouteContractError) as raised:
            _search("cost", ride_options=broken)
        self.assertIs(raised.exception, error)
        self.assertEqual(calls, [("a", "b")])

    def test_limit_keeps_structured_diagnostics(self):
        with self.assertRaises(RouteSearchLimitError) as raised:
            _search("cost", max_visited=1)
        self.assertEqual(raised.exception.reason, "max_visited")
        self.assertEqual(raised.exception.diagnostics["visited"], 2)
        self.assertEqual(raised.exception.diagnostics["mode"], "cost")

    def test_unknown_objective_is_rejected(self):
        with self.assertRaisesRegex(RouteContractError, "Unsupported label search mode"):
            _search("unknown")

    def test_shared_import_has_no_tokyo_dependency(self):
        script = """
import builtins
original_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.startswith('tokyo_') or name == 'toei_engine':
        raise AssertionError('City-specific import: ' + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded
import transit_search_labels
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tokyo_selected_path_pickle_identity_and_detail_metadata_stay_compatible(self):
        manager = {"snapshot": "fixture"}
        choices = SimpleNamespace(manager=manager, use_realtime=True)
        path = tokyo.SelectedPath(["a", "b"], [11.0], {}, choices, 10.0)
        restored = pickle.loads(pickle.dumps(path))
        self.assertEqual(type(restored).__module__, "tokyo_search_labels")
        self.assertIs(type(restored), tokyo.SelectedPath)
        self.assertEqual(restored.timetable_manager, manager)
        self.assertTrue(restored.use_realtime)
        self.assertEqual(restored.arrival_minute, 11.0)
