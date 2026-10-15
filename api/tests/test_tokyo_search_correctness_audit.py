"""Independent raw fixtures, exhaustive countersearch and failed obligations.

Expected arrivals come from raw timetable rows or a separate complete path
enumerator, never the product search/provider/bounds. Product methods are not
patched to insert observation hooks or to manufacture a positive certificate.
"""
from __future__ import annotations

import contextlib
from dataclasses import replace
import io
import itertools
import math
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import networkx as nx

import toei_engine as engine
import tokyo_search_labels as integration
import transit_search_labels as forward
import tokyo_time_projection_proof as old_proof
from route_engine import RouteContractError, RouteSearchLimitError
from tokyo_search_correctness_audit import (
    CompletionOracle, Query, RawRun, RawStop, SearchCorrectnessError,
    SearchLimits, State, audit_first_arrival, verify_dominance_witness,
    verify_first_goal, verify_open_witness, verify_resource_rejection,
)
from tokyo_timetable_choices import TimetableChoices
import tokyo_timetable_choices as timetable
from tests import test_tokyo_bus_choices_contract as bus
from tests import test_tokyo_waiting_contract as rail
from tests.test_tokyo_time_rounding_audit import _mixed_fixture


LIMITS = SearchLimits("synthetic_explicit", 2000, 1000, 15.0)


def _walk_graph(rows):
    graph = nx.DiGraph()
    for left, right, meters in rows:
        rail._walk(graph, bus._phys(left), bus._phys(right), meters)
    return graph


def _choices(graph, query, *, repository=None, manager=None, day=None):
    # A concrete feed outside a walk-only graph establishes canonical waiting;
    # it is not a fallback timetable and contributes no reachable transition.
    if repository is None:
        repository = bus._repository(("outside", "active", (("u", 0, 0), ("v", 0, 0))))
    return TimetableChoices(graph, manager or engine.TimetableManager(),
                            day_type=day or bus._day("active"), use_realtime=False,
                            deadline=query.deadline, bus_repository=repository)


def _run_bus(identity, stops, *, line=bus.LINE, service="active", active=True):
    return RawRun("bus", "2026-10-04", "tokyo-test|2026-10-04|" + identity, line,
                  tuple(RawStop(name, i, arrival, departure, pickup)
                        for i, (name, arrival, departure, pickup) in enumerate(stops, 1)),
                  trip_id=identity, route_id=bus.ROUTE, service_id=service, active=active)


def _audit(graph, runs, query, *, choices=None, limits=LIMITS, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return audit_first_arrival(
            graph, choices or _choices(graph, query), runs, query, limits=limits,
            max_oracle_states=kwargs.pop("max_oracle_states", 10000),
            max_oracle_transitions=kwargs.pop("max_oracle_transitions", 100000), **kwargs)


def _bus_fixture(trips, pairs, *, start="A", target="T", clock=598.0, duration=240.0):
    graph = bus._graph(*pairs)
    repository = bus._repository(*(tuple((identity, service, tuple(
        (name, arrival, departure) for name, arrival, departure, _ in stops)))
        for identity, service, stops in trips))
    runs = []
    for identity, service, stops in trips:
        for i, (_, _, _, pickup) in enumerate(stops, 1):
            repository.stop_time_boarding[identity][i] = (pickup, 0)
        runs.append(_run_bus(identity, stops, service=service, active=service == "active"))
    query = Query(bus._phys(start), bus._phys(target), clock, duration)
    return graph, tuple(runs), query, _choices(graph, query, repository=repository)


def _oracle(graph, runs, query, **kwargs):
    return CompletionOracle(graph, runs, query,
                            max_states=kwargs.get("max_states", 10000),
                            max_transitions=kwargs.get("max_transitions", 100000))


class TokyoSearchCorrectnessAuditTest(unittest.TestCase):
    def test_goal_generation_is_not_termination(self):
        graph = _walk_graph((("S", "T", 80.0), ("S", "M", 80.0), ("M", "T", 80.0)))
        graph[bus._phys("S")][bus._phys("T")]["reviewed_walk_minutes"] = 10
        query = Query(bus._phys("S"), bus._phys("T"), 600.0, 240.0)
        report = _audit(graph, (), query)
        self.assertEqual(report["arrival_minute"], 602.0)
        self.assertTrue(report["first_goal_pop_verified"])
        self.assertEqual(report["termination"], "first_goal_pop_consumer_close")
        self.assertGreater(report["counts"]["open_witness_checkpoints"], 1)

    def test_complete_walk_dag_countersearch_against_separate_path_enumerator(self):
        # All 64 DAGs on four ordered nodes; binary64 additions are made along
        # EACH full path, not by summing elapsed distances then adding start.
        pairs = tuple(itertools.combinations(range(4), 2))
        cases = 0
        for clock in (600.0, 1439.0):
            for mask in range(64):
                graph = nx.DiGraph()
                for node in range(4):
                    graph.add_node(bus._phys(str(node)))
                for bit, (left, right) in enumerate(pairs):
                    if mask & (1 << bit):
                        meters = (2.0, 4.0, 40.0, 601.0, 599.0, 1.0)[bit]
                        rail._walk(graph, bus._phys(str(left)), bus._phys(str(right)), meters)
                def arrivals(node, now, total, segment):
                    if node == bus._phys("3"):
                        yield now
                    else:
                        for following in graph.successors(node):
                            meters = graph[node][following]["meters"]
                            nxt = now + meters / 80.0
                            if total + meters <= 3000 and segment + meters <= 600 and nxt <= clock + 240:
                                yield from arrivals(following, nxt, total + meters, segment + meters)
                expected = min(arrivals(bus._phys("0"), clock, 0.0, 0.0), default=math.inf)
                query = Query(bus._phys("0"), bus._phys("3"), clock, 240.0)
                with self.subTest(clock=clock, mask=mask):
                    report = _audit(graph, (), query)
                    self.assertEqual(report["arrival_minute"], None if math.isinf(expected) else expected)
                    self.assertEqual(report["first_goal_pop_verified"], not math.isinf(expected))
                    self.assertEqual(report["queue_exhaustion_verified"], math.isinf(expected))
                cases += 1
        self.assertEqual(cases, 128)

    def test_raw_rail_bus_dwell_loop_occurrence_and_midnight(self):
        for offset in (0, 840):
            graph, choices, rows, _, _ = _mixed_fixture(offset)
            query = Query(rail._physical("A"), rail._physical("Z"), 598.0 + offset, 242.0)
            raw = []
            for mode, identity, line, stops in rows:
                source_key = f"odpt.TrainTimetable:Toei.Asakusa.{identity}.Weekday"
                raw.append(RawRun(
                    mode, "2026-09-04",
                    f"2026-09-04|{source_key}|part:0" if mode == "rail"
                    else f"tokyo-test|2026-09-04|{identity}", line,
                    tuple(RawStop(name, i, int(arr), int(dep), pickup)
                          for i, (name, arr, dep, pickup) in enumerate(stops, 0 if mode == "rail" else 1)),
                    train_number=identity if mode == "rail" else None,
                    trip_id=identity if mode == "bus" else None,
                    route_id=bus.ROUTE if mode == "bus" else None,
                    service_id="active" if mode == "bus" else None))
            with self.subTest(offset=offset):
                report = _audit(graph, tuple(raw), query, choices=choices)
                self.assertEqual(report["arrival_minute"], 620.0 + offset)
                self.assertGreater(report["counts"]["fresh_alight_rejections"], 0)

    def test_all_dominance_directions_and_expanded_dominator_keep_witness(self):
        graph, runs, query, choices = _bus_fixture(
            (("finish", "active", (("M", 610, 610, 0), ("T", 620, 620, 0))),),
            (("M", "T"),), start="M", clock=600.0)
        rail._walk(graph, bus._phys("S"), bus._phys("M"), 80.0)
        rail._walk(graph, bus._phys("S"), bus._phys("N"), 80.0)
        rail._walk(graph, bus._phys("N"), bus._phys("M"), 80.0)
        query = replace(query, start=bus._phys("S"))
        # M has expanded before N's later prefix reaches it. The child on
        # the 610 departure must remain the earlier prefix's live witness.
        report = _audit(graph, runs, query, choices=choices)
        self.assertEqual(report["arrival_minute"], 620.0)
        self.assertGreater(report["counts"]["dominance_witnesses"], 0)
        self.assertGreater(report["counts"]["expanded_dominator_witnesses"], 0)

    def test_later_prefix_with_better_walking_resources_cannot_be_discarded(self):
        graph, runs, query, choices = _bus_fixture(
            (("access", "active", (("S", 600, 600, 0), ("M", 605, 605, 0))),),
            (("S", "M"),), start="S", target="T")
        rail._walk(graph, bus._phys("S"), bus._phys("M"), 500.0)
        rail._walk(graph, bus._phys("M"), bus._phys("T"), 200.0)
        # Walk arrives earlier but cannot walk the last 200m; bus prefix can.
        report = _audit(graph, runs, query, choices=choices)
        self.assertEqual(report["arrival_minute"], 607.5)
        self.assertGreater(report["counts"].get("pruned_segment_walk", 0), 0)

    def test_new_dominator_invalidates_previous_label_with_earliest_witness(self):
        graph, runs, query, choices = _bus_fixture(
            (("finish", "active", (("M", 610, 610, 0), ("T", 620, 620, 0))),),
            (("M", "T"),), start="M", clock=600.0)
        rail._walk(graph, bus._phys("S"), bus._phys("M"), 240.0)
        rail._walk(graph, bus._phys("S"), bus._phys("N"), 80.0)
        rail._walk(graph, bus._phys("N"), bus._phys("M"), 80.0)
        query = replace(query, start=bus._phys("S"))
        report = _audit(graph, runs, query, choices=choices)
        self.assertEqual(report["arrival_minute"], 620.0)
        self.assertGreater(report["counts"]["invalidated_previous_labels"], 0)

    def test_countersearch_all_same_frontier_keys_on_complete_raw_states(self):
        graph, runs, query, choices = _bus_fixture(
            (("loop", "active", (("A", 600, 600, 0), ("B", 601, 601, 0),
                                    ("A", 602, 602, 0), ("T", 605, 605, 0))),
             ("fast", "active", (("A", 601, 601, 0), ("T", 604, 604, 0)))),
            (("A", "B"), ("B", "A"), ("A", "T")))
        rail._walk(graph, bus._phys("A"), bus._phys("T"), 500.0)
        oracle = _oracle(graph, runs, query)
        frontier = forward._Frontier(query.target, "time", choices.can_wait_offboard)
        labels = []
        for state in oracle.states:
            for cost, boards in ((0.0, 0), (5.0, 3)):
                labels.append((state, forward._Label(
                    state.node, cost, state.clock, state.total, state.segment, boards,
                    ride=None if state.ride is None else timetable.RideState(*state.ride))))
        checked = 0
        for (first, a), (second, b) in itertools.product(labels, repeat=2):
            if a is not b and frontier._key(a) == frontier._key(b) and frontier._dominates(a, b):
                verify_dominance_witness(oracle, first, second)
                checked += 1
        self.assertEqual(checked, 58)

    def test_fresh_board_cannot_reset_walk_before_any_travel(self):
        graph, runs, query, choices = _bus_fixture(
            (("dead", "active", (("A", 610, 610, 0), ("B", 611, 611, 0))),),
            (("A", "B"),), start="A", target="T", clock=600.0)
        rail._walk(graph, bus._phys("S"), bus._phys("A"), 600.0)
        rail._walk(graph, bus._phys("A"), bus._phys("T"), 80.0)
        query = replace(query, start=bus._phys("S"))
        report = _audit(graph, runs, query, choices=choices)
        self.assertIsNone(report["arrival_minute"])
        self.assertGreater(report["counts"]["fresh_alight_rejections"], 0)
        self.assertGreater(report["counts"]["pruned_segment_walk"], 0)

    def test_virtual_exact_segment_boundary_and_one_ulp_over(self):
        for meters, expected in ((520.0, 607.5), (math.nextafter(520.0, math.inf), None)):
            graph = _walk_graph((("S", "M", 80.0),))
            query = Query(bus._phys("S"), bus._phys("dest"), 600.0, 240.0,
                          ((bus._phys("M"), (0.0, meters)),))
            report = _audit(graph, (), query)
            self.assertEqual(report["arrival_minute"], expected)
            if expected is None:
                self.assertGreater(report["counts"]["pruned_segment_walk"], 0)

    def test_total_boundary_requires_transit_resets_not_total_reset(self):
        for extra, expected in ((0.0, 647.0), (1.0, None)):
            graph = nx.DiGraph()
            trips = []
            raw = []
            for i in range(5):
                left, right = f"a{i}", f"b{i}"
                graph = nx.compose(graph, bus._graph((left, right)))
                # Separate stop pairs on the same route/line, unambiguous runs.
                dep = 610 + i * 9
                stops = ((left, dep, dep, 0), (right, dep + 1, dep + 1, 0))
                trips.append((f"r{i}", "active", tuple((s, a, d) for s, a, d, _ in stops)))
                raw.append(_run_bus(f"r{i}", stops))
                rail._walk(graph, bus._phys("S" if i == 0 else f"b{i-1}"), bus._phys(left), 600.0)
            # Last virtual segment is 0m/1m after a genuine transit reset:
            # the failing case violates TOTAL only, not the segment cap.
            query = Query(bus._phys("S"), bus._phys("dest"), 600.0, 240.0,
                          ((bus._phys("b4"), (0.0, extra)),))
            choices = _choices(graph, query, repository=bus._repository(*trips))
            report = _audit(graph, tuple(raw), query, choices=choices)
            self.assertEqual(report["arrival_minute"], expected)
            if expected is None:
                self.assertGreater(report["counts"]["pruned_total_walk"], 0)

    def test_deadline_exact_binary64_and_display_rounding_are_separate(self):
        graph = _walk_graph((("S", "M", 2.0), ("M", "T", 4.0)))
        exact = (600.0 + 2.0 / 80.0) + 4.0 / 80.0
        for deadline, expected in ((exact, exact), (math.nextafter(exact, -math.inf), None)):
            query = Query(bus._phys("S"), bus._phys("T"), 600.0, deadline - 600.0)
            report = _audit(graph, (), query)
            self.assertEqual(report["arrival_minute"], expected)
            if expected is None:
                self.assertGreater(report["counts"]["pruned_deadline"], 0)

    def test_reviewed_walk_time_and_zero_meter_legacy_edge(self):
        graph = _walk_graph((("S", "M", 0.0), ("M", "T", 80.0)))
        graph[bus._phys("M")][bus._phys("T")]["reviewed_walk_minutes"] = 3
        query = Query(bus._phys("S"), bus._phys("T"), 600.0, 240.0)
        self.assertEqual(_audit(graph, (), query)["arrival_minute"], (600.0 + 1.0 / 80.0) + 3.0)

    def test_pickup_prohibited_active_service_and_zero_time_concrete_cycle(self):
        fixture = _bus_fixture(
            (("loop", "active", (("A", 600, 600, 0), ("B", 600, 600, 1),
                                    ("A", 600, 600, 0), ("T", 600, 600, 0))),
             ("inactive", "inactive", (("A", 599, 599, 0), ("T", 599, 599, 0)))),
            (("A", "B"), ("B", "A"), ("A", "T")))
        graph, runs, query, choices = fixture
        oracle = _oracle(graph, runs, query)
        # There are arbitrarily long legal reboard/ride suffixes at clock600.
        # The finite operational quotient closes with no operational depth cap.
        relation = nx.DiGraph()
        relation.add_edges_from((parent, child) for parent, children in enumerate(oracle.edges)
                                for child in children)
        self.assertTrue(any(len(component) > 1 for component in nx.strongly_connected_components(relation)))
        self.assertTrue(any(state.ride is not None and state.ride[4] > state.ride[5]
                            for state in oracle.states))
        self.assertFalse(any(state.ride is not None and state.ride[5] == 2
                             for state in oracle.states))
        report = _audit(graph, runs, query, choices=choices)
        self.assertEqual(report["arrival_minute"], 600.0)
        self.assertFalse(report["unexpanded_suffix_step_bound_verified"])

    def test_same_train_number_separate_runs_never_join(self):
        source = (rail._run("one", (("A", 600), ("B", 605)), number="N"),
                  rail._run("two", (("B", 607), ("T", 608)), number="N"))
        graph = rail._graph(("A", "B"), ("B", "T"))
        query = Query(rail._physical("A"), rail._physical("T"), 598.0, 240.0)
        choices = _choices(graph, query, manager=rail._manager(*source), day="weekday")
        runs = tuple(RawRun(
            "rail", "weekday", f"weekday|odpt.TrainTimetable:Toei.Asakusa.{identity}.Weekday|part:0",
            rail.RAILWAY, tuple(RawStop(rail._station(n), i, t, t) for i, (n, t) in enumerate(stops)),
            train_number="N") for identity, stops in
            (("one", (("A", 600), ("B", 605))), ("two", (("B", 607), ("T", 608)))))
        self.assertIsNone(_audit(graph, runs, query, choices=choices)["arrival_minute"])

    def test_bus_only_restricts_legal_set_without_changing_graph(self):
        graph = rail._graph(("A", "T"))
        query = Query(rail._physical("A"), rail._physical("T"), 598.0, 240.0, bus_only=True)
        choices = _choices(graph, query, manager=rail._manager(rail._run("r", (("A", 600), ("T", 605)))),
                           day="weekday")
        run = RawRun("rail", "weekday", "weekday|odpt.TrainTimetable:Toei.Asakusa.r.Weekday|part:0",
                     rail.RAILWAY, (RawStop(rail._station("A"), 0, 600, 600),
                                    RawStop(rail._station("T"), 1, 605, 605)), train_number="r")
        self.assertIsNone(_audit(graph, (run,), query, choices=choices)["arrival_minute"])

    def test_same_arrival_cost_counterexample_retains_uncertified_flags(self):
        graph = _walk_graph((("S", "M", 80.0),))
        graph[bus._phys("S")][bus._phys("M")]["w"] = 0.0
        query = Query(bus._phys("S"), bus._phys("dest"), 600.0, 240.0,
                      ((bus._phys("S"), (10.0, 400.0)), (bus._phys("M"), (0.0, 320.0))))
        report = _audit(graph, (), query)
        self.assertEqual(report["arrival_minute"], 605.0)
        for flag in ("same_arrival_cost_optimality_verified", "candidate_class_completeness_verified",
                     "true_top_k_verified", "unconditional_search_correctness_verified"):
            self.assertIs(report[flag], False)
        with self.assertRaisesRegex(SearchCorrectnessError, "true_top_k_is_not_certified"):
            _audit(graph, (), query, require_true_top_k=True)

    def test_missing_or_extra_raw_run_refuses_certificate_with_index_only_evidence(self):
        graph, runs, query, choices = _bus_fixture(
            (("secret-real-id", "active", (("A", 600, 600, 0), ("T", 610, 610, 0))),),
            (("A", "T"),))
        with self.assertRaises(SearchCorrectnessError) as caught:
            _audit(graph, (), query, choices=choices)
        error = caught.exception
        self.assertEqual(error.reason, "independent_transition_relation_differs")
        self.assertEqual(error.counterexample["state"], 0)
        self.assertEqual(error.counterexample["unexpected"], 1)
        self.assertNotIn("secret-real-id", str(error))
        self.assertNotIn("secret-real-id", repr(error.counterexample))
        extra = replace(runs[0], run_id="invented", trip_id="invented")
        with self.assertRaisesRegex(SearchCorrectnessError, "transition_relation_differs"):
            _audit(graph, (extra,), query, choices=choices)

    def test_lost_witness_and_premature_goal_produce_counterexamples(self):
        graph = _walk_graph((("S", "T", 400.0), ("S", "M", 80.0), ("M", "T", 80.0)))
        query = Query(bus._phys("S"), bus._phys("T"), 600.0, 240.0)
        oracle = _oracle(graph, (), query)
        slow = State(bus._phys("T"), 605.0, 400.0, 400.0)
        initial = oracle.states[0]
        for check in (lambda: verify_dominance_witness(oracle, slow, initial),
                      lambda: verify_open_witness(oracle, (slow,)),
                      lambda: verify_first_goal(oracle, slow),
                      lambda: verify_resource_rejection(oracle, initial, 600.0)):
            with self.assertRaises(SearchCorrectnessError) as caught:
                check()
            self.assertTrue(any("witness" in name for name in caught.exception.counterexample))

    def test_oracle_work_limit_or_positive_walk_cycle_is_not_complete(self):
        graph = _walk_graph((("S", "M", 1.0), ("M", "S", 1.0), ("M", "T", 1.0)))
        query = Query(bus._phys("S"), bus._phys("T"), 600.0, 240.0)
        for limits in ({"max_oracle_states": 3}, {"max_oracle_transitions": 1}):
            with self.assertRaisesRegex(SearchCorrectnessError, "oracle_.*_limit"):
                _audit(graph, (), query, **limits)

    def test_production_limits_and_actual_guard_parameters_are_not_audit_profile(self):
        graph = _walk_graph((("S", "T", 80.0),))
        query = Query(bus._phys("S"), bus._phys("T"), 600.0, 240.0)
        production = SearchLimits("production_fastest", 200000, 100000, 15.0)
        report = _audit(graph, (), query, limits=production)
        self.assertEqual(report["guard_parameters"]["max_forward_steps"], 200000)
        self.assertEqual(report["guard_parameters"]["max_reverse_steps"], len(graph) + 1)
        synthetic = _audit(graph, (), query)
        self.assertEqual(synthetic["guard_parameters"]["max_forward_steps"], 2000)
        self.assertNotEqual(synthetic["guard_parameters"]["fixed_error_minutes"],
                            report["guard_parameters"]["fixed_error_minutes"])
        with self.assertRaisesRegex(SearchCorrectnessError, "production_search_limits_differ"):
            SearchLimits("production_fastest", 100000, 100000, 15.0)

    def test_pop_and_expansion_limits_propagate_original_diagnostics_without_partial_success(self):
        graph = _walk_graph((("S", "M", 80.0), ("M", "T", 80.0)))
        query = Query(bus._phys("S"), bus._phys("T"), 600.0, 240.0)
        for limits, reason in ((SearchLimits("synthetic_explicit", 1, 100, 15.0), "max_visited"),
                               (SearchLimits("synthetic_explicit", 100, 1, 15.0), "max_expanded")):
            try:
                _audit(graph, (), query, limits=limits)
            except RouteSearchLimitError as error:
                self.assertEqual(error.reason, reason)
                self.assertEqual(error.diagnostics["max_visited"], limits.max_visited)
                self.assertEqual(error.diagnostics["max_expanded"], limits.max_expanded)
                self.assertFalse(error.tokyo_correctness_audit["certified"])
                self.assertIsNotNone(error.__traceback__)
            else:
                self.fail("a search safety limit must not return an audit report")
            self.assertIsNone(sys.gettrace())

    def test_time_limit_is_not_extended_to_pay_for_observation(self):
        graph = _walk_graph((("S", "T", 80.0),))
        query = Query(bus._phys("S"), bus._phys("T"), 600.0, 240.0)
        limits = SearchLimits("synthetic_explicit", 100, 100, 1e-300)
        with self.assertRaises(RouteSearchLimitError) as caught:
            _audit(graph, (), query, limits=limits)
        self.assertEqual(caught.exception.reason, "time_limit_sec")
        self.assertEqual(caught.exception.diagnostics["time_limit_sec"], 1e-300)
        self.assertFalse(caught.exception.tokyo_correctness_audit["certified"])
        self.assertIsNone(sys.gettrace())

    def test_conditional_pickup_provider_error_is_not_swallowed_or_wrapped(self):
        graph, runs, query, choices = _bus_fixture(
            (("conditional", "active", (("A", 600, 600, 0), ("T", 610, 610, 0))),),
            (("A", "T"),))
        choices.repository.stop_time_boarding["conditional"][1] = (2, 0)
        with self.assertRaisesRegex(ValueError, "conditional pickup is unsupported") as caught:
            _audit(graph, runs, query, choices=choices)
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(sys.gettrace())

    def test_realtime_opaque_warm_provider_and_changed_frontier_fail_fast(self):
        graph = _walk_graph((("S", "T", 80.0),))
        query = Query(bus._phys("S"), bus._phys("T"), 600.0, 240.0)
        choices = _choices(graph, query)
        choices.use_realtime = True
        with self.assertRaisesRegex(SearchCorrectnessError, "canonical_static"):
            _audit(graph, (), query, choices=choices)
        choices = _choices(graph, query)
        choices._has_rail_data = False
        with self.assertRaisesRegex(SearchCorrectnessError, "canonical_static"):
            _audit(graph, (), query, choices=choices)
        choices = _choices(graph, query)
        choices._concrete_board_options["warm"] = ()
        with self.assertRaisesRegex(SearchCorrectnessError, "fresh_search_provider"):
            _audit(graph, (), query, choices=choices)
        with patch.object(forward._Frontier, "_dominates", lambda *args: True):
            with self.assertRaisesRegex(SearchCorrectnessError, "different_search_bindings"):
                _audit(graph, (), query)

    def test_existing_trace_is_preserved_and_declined(self):
        graph = _walk_graph((("S", "T", 80.0),))
        query = Query(bus._phys("S"), bus._phys("T"), 600.0, 240.0)
        def trace(frame, event, arg):
            return trace
        original = sys.gettrace()
        try:
            sys.settrace(trace)
            with self.assertRaisesRegex(SearchCorrectnessError, "existing_trace_observer"):
                _audit(graph, (), query)
            self.assertIs(sys.gettrace(), trace)
        finally:
            sys.settrace(original)

    def test_passed_real_data_gates_are_never_called(self):
        from tests.test_tokyo_time_projection_proof import _forbid_calls
        from tokyo_bound_projection_audit import verify_static_graph_projection
        from tokyo_destination_bounds_audit import verify_destination_case
        from tokyo_rail_interval_audit import verify_static_rail_interval_minima
        graph = _walk_graph((("S", "T", 80.0),))
        query = Query(bus._phys("S"), bus._phys("T"), 600.0, 240.0)
        with _forbid_calls((old_proof.verify_static_time_projection, verify_static_graph_projection,
                            verify_destination_case, verify_static_rail_interval_minima)):
            report = _audit(graph, (), query)
        self.assertFalse(report["accepted_audits_rerun"])
        self.assertEqual(report["runtime_selection"], "not_selected_audit_only")

    def test_source_mutation_during_observed_search_refuses_success(self):
        graph = _walk_graph((("S", "T", 80.0),))
        query = Query(bus._phys("S"), bus._phys("T"), 600.0, 240.0)
        original = sys.getprofile()
        changed = False
        def profile(frame, event, arg):
            nonlocal changed
            if event == "call" and frame.f_code is forward.search_labels.__code__ and not changed:
                graph[bus._phys("S")][bus._phys("T")]["w"] += 1.0
                changed = True
        try:
            sys.setprofile(profile)
            with self.assertRaisesRegex(SearchCorrectnessError, "source_or_graph_changed"):
                _audit(graph, (), query)
        finally:
            sys.setprofile(original)
        self.assertTrue(changed)

    def test_compaction_keeps_original_live_entries_and_reopening_is_per_label(self):
        # Independent abstract queue contract; not a canonical Tokyo proof.
        a = forward._Label("M", 1.0, 5.0, 0.0, 0.0, 0, expanded=True)
        b = forward._Label("M", 1.0, 2.0, 0.0, 0.0, 0)
        c = forward._Label("X", 1.0, 3.0, 0.0, 0.0, 0, active=False)
        entry = ((2.0, 1.0, 0, 2.0), 7, b)
        queue = [((5.0, 1.0, 0, 5.0), 1, a), entry, ((3.0, 1.0, 0, 3.0), 2, c)]
        self.assertEqual(forward._compact_queue(queue), 2)
        self.assertIs(queue[0], entry)
        frontier = forward._Frontier("T", "time", True)
        self.assertTrue(frontier.add(a))
        self.assertTrue(frontier.add(b))
        self.assertFalse(a.active)
        self.assertTrue(b.active)
        self.assertFalse(b.expanded)

    def test_inconsistent_admissible_abstract_bound_reopens_after_expansion(self):
        # Independent abstract integration contract only. This is not the
        # canonical Tokyo bound/guard and never receives an audit certificate.
        graph = nx.DiGraph()
        for left, right, elapsed in (("S", "A", 3.0), ("S", "B", 1.0),
                                     ("B", "A", 1.0), ("A", "T", 10.0)):
            graph.add_edge(left, right, etype="abstract", elapsed=elapsed, w=0.0)
        lower = {"S": 0.0, "A": 0.0, "B": 10.0, "T": 0.0}
        self.assertGreater(lower["B"], 1.0 + lower["A"])
        expanded_a = []
        def advance(left, right, now, edge):
            if left == "A":
                expanded_a.append(now)
            return now + edge["elapsed"]
        class Bounds:
            report = {}
            def __call__(self, node):
                return lower[node]
        with contextlib.redirect_stdout(io.StringIO()):
            result = list(forward.search_labels(
                graph, SimpleNamespace(can_wait_offboard=True), "S", "T", mode="time",
                start_minute=0.0, max_search=1, max_visited=100, max_expanded=100,
                max_travel_min=240.0, time_limit_sec=15.0,
                max_total_walk=3000.0, max_segment_walk=600.0, walk_speed=80.0,
                rail_boarding_minutes=2, advance_time=advance, virtual_connections={},
                edge_uses_rail=lambda u, v: False,
                prepare_bounds=lambda check, deadline: (Bounds(), None, lambda g, h: g + h),
                path_signature=lambda nodes: tuple(nodes), path_factory=forward.SelectedPath,
                compact_queue=forward._compact_queue, ride_options=lambda *args: (),
                alight_minutes=lambda ride: 1.0, walk_meters=lambda edge: 0.0))
        self.assertEqual(expanded_a, [3.0, 2.0])
        self.assertEqual(result[0]["path"].arrival_minute, 12.0)


if __name__ == "__main__":
    unittest.main()
