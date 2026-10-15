"""Independent legal clocks and counterexamples for the projection proof.

Raw schedule/resource enumeration supplies arrival clocks, never the search
or TimetableChoices. A separate last-occurrence shortcut constructs relaxed
witnesses; it is not an executable change to operational trips. Exhaustive
small graphs also test suffixes longer than the declared rounding budget.
"""
from __future__ import annotations

import ast
import contextlib
from dataclasses import replace
from fractions import Fraction
import io
import itertools
import math
from types import MappingProxyType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import networkx as nx

from route_engine import RouteContractError
import tokyo_destination_bounds_audit as destination
import tokyo_time_projection_proof as proof
from tokyo_time_bounds import TimeBounds
from tokyo_time_rounding import TimeRoundingGuard
from tokyo_time_rounding_audit import float_bits
from tokyo_timetable_choices import TimetableChoices
from tests import test_tokyo_bus_choices_contract as bus
from tests import test_tokyo_destination_bounds_audit as fixture
from tests import test_tokyo_time_rounding_audit as raw
from tests import test_tokyo_waiting_contract as rail


F = Fraction.from_float


def _last_occurrence_edges(nodes):
    """A different, test-only proof witness: leave each node at its last visit."""
    index, kept = 0, []
    while index < len(nodes) - 1:
        last = max(i for i in range(index, len(nodes)) if nodes[i] == nodes[index])
        if last == len(nodes) - 1:
            break
        kept.append(last)
        index = last + 1
    return kept


@contextlib.contextmanager
def _forbid_calls(functions):
    """Observe actual calls without replacing reviewed transition methods."""
    codes = {function.__code__ for function in functions}
    previous = sys.getprofile()
    def profile(frame, event, arg):
        if event == "call" and frame.f_code in codes:
            raise AssertionError("forbidden search/provider/parity-gate call")
    sys.setprofile(profile)
    try:
        yield
    finally:
        sys.setprofile(previous)


def _inputs(choices, rail_minima, bus_minima):
    # Synthetic raw-schedule inputs. The proof gate independently checks their
    # complete source interval inequalities and departure-index consistency.
    return destination.CommonIntervalInputs(
        MappingProxyType(rail_minima), MappingProxyType(bus_minima),
        choices.manager, choices.repository,
        destination._sources_digest(choices.manager, choices.repository, lambda: None),
        MappingProxyType({}),
    )


class StaticTimeProjectionProofTest(unittest.TestCase):
    def setUp(self):
        self.source = fixture.TokyoDestinationBoundsAuditTest()
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)

    def case(self, *, scope="full_graph", target=None, virtual=None, nf=100000,
             start=600.0, upper=840.0, inputs=None):
        f = self.source
        inputs = f.inputs if inputs is None else inputs
        target = bus._phys("C") if target is None else target
        virtual = {rail._physical("Z"): (0.0, 160.0)} if virtual is None else virtual
        predicate = lambda u, v: scope == "bus_only_rail_excluded" and bus.engine._edge_uses_rail(f.graph, u, v)
        projection = destination.project_common_graph(f.graph, f.choices, inputs.rail, inputs.bus,
                                                     edge_uses_rail=predicate)
        bounds = destination.common_destination_bounds(projection, target, virtual)
        guard = TimeRoundingGuard(start_minute=start, deadline=upper, max_forward_steps=nf,
            max_reverse_steps=len(f.graph) + 1, max_edge_minutes=bounds.report["max_edge_minutes"])
        return dict(projection=projection, inputs=inputs, bounds=bounds, guard=guard,
                    target=target, virtual_connections=virtual,
                    start=bus._phys("A") if scope == "bus_only_rail_excluded" else rail._physical("P"),
                    mode="time", scope=scope)

    def test_all_destinations_scopes_profiles_preserve_guard_and_do_not_call_prior_gates(self):
        import tokyo_bound_projection_audit as graph_audit
        import tokyo_rail_interval_audit as rail_audit
        from tokyo_dataset_bus_choices import TokyoBusDatasetBinding
        forbidden = (bus.engine._tokyo_label_search, proof.forward.search_labels,
                     TimetableChoices.board_options, TimetableChoices.ride_options,
                     destination.verify_destination_case,
                     graph_audit.verify_static_graph_projection,
                     rail_audit.verify_static_rail_interval_minima,
                     TokyoBusDatasetBinding.verify_static_bus_interval_minima)
        for scope in ("full_graph", "bus_only_rail_excluded"):
            for _kind, target, virtual in fixture.probe.destination_manifest(self.source.graph):
                for start, upper in ((600.0, 840.0), (1439.0, 1679.0)):
                    case = self.case(scope=scope, target=target, virtual=virtual, start=start, upper=upper)
                    guard, bounds = case["guard"], case["bounds"]
                    clocks = (start, math.nextafter(start, math.inf), (start + upper) / 2, upper)
                    priorities = [float_bits(guard(clock, bounds(node)))
                                  for node in self.source.graph for clock in clocks]
                    before = dict(guard.report), dict(bounds._values)
                    with _forbid_calls(forbidden):
                        result = proof.verify_static_time_projection(**case)
                    self.assertTrue(result["static_time_priority_admissibility_verified"])
                    self.assertTrue(result["forward_transition_coverage_verified"])
                    self.assertTrue(result["nondecreasing_operational_clocks_verified"])
                    self.assertTrue(result["one_edge_rounding_condition_verified"])
                    self.assertEqual(result["simple_projection_step_bound"], len(self.source.graph) + 1)
                    self.assertEqual(result["included_edges"] + result["excluded_edges"], self.source.graph.number_of_edges())
                    self.assertFalse(result["unexpanded_suffix_step_bound_verified"])
                    self.assertFalse(result["unconditional_priority_admissibility_verified"])
                    self.assertFalse(result["real_timetable_suffix_admissibility_verified"])
                    self.assertFalse(result["common_dataset_route_ranking_verified"])
                    self.assertEqual(result["runtime_selection"], "not_selected_audit_only")
                    self.assertEqual(before, (guard.report, bounds._values))
                    self.assertEqual(priorities, [float_bits(guard(clock, bounds(node)))
                                     for node in self.source.graph for clock in clocks])

    def test_budget_equality_is_sufficient_and_one_less_stops_without_a_larger_guard(self):
        nr = len(self.source.graph) + 1
        self.assertTrue(proof.verify_static_time_projection(**self.case(nf=nr))[
            "static_time_priority_admissibility_verified"])
        case = self.case(nf=nr - 1)
        before = dict(case["guard"].report)
        with _forbid_calls((TimeRoundingGuard.__init__,)):
            with self.assertRaisesRegex(RouteContractError, "projection_step_budget_insufficient.*declared_nf=.*required_nr="):
                proof.verify_static_time_projection(**case)
        self.assertEqual(case["guard"].report, before)

    def test_missing_duplicate_extra_and_excluded_edges_fail_before_certification(self):
        for mutation in ("missing", "duplicate", "extra", "excluded"):
            with self.subTest(mutation=mutation):
                case = self.case(scope="bus_only_rail_excluded" if mutation == "excluded" else "full_graph")
                projection = case["projection"]
                reverse = {node: list(rows) for node, rows in projection.reverse.items()}
                node = next(node for node, rows in reverse.items() if rows)
                if mutation == "missing":
                    reverse[node].pop()
                    reason = "legal_edge_missing"
                elif mutation == "duplicate":
                    reverse[node].append(reverse[node][0])
                    reason = "extra_or_duplicate"
                elif mutation == "extra":
                    reverse[bus._phys("A")].append((bus._phys("C"), 0.0))
                    reason = "extra_projected_edge"
                else:
                    reverse[rail._line("P")].append((rail._physical("P"), 2.0))
                    reason = "excluded_edge_in_projection"
                case["projection"] = replace(projection, reverse=MappingProxyType(
                    {node: tuple(rows) for node, rows in reverse.items()}))
                with self.assertRaisesRegex(RouteContractError, reason):
                    proof.verify_static_time_projection(**case)

    def test_unknown_dispatch_kind_and_line_walk_are_not_silently_relaxed(self):
        graph = self.source.graph
        first, last = rail._physical("Q"), bus._phys("A")
        graph[first][last]["etype"] = "unreviewed_teleport"
        with self.assertRaisesRegex(RouteContractError, "uncovered_forward_transition"):
            proof.verify_static_time_projection(**self.case())
        graph.remove_edge(first, last)
        rail._walk(graph, rail._line("Q"), bus._phys("A"), 2.0)
        with self.assertRaisesRegex(RouteContractError, "uncovered_forward_transition"):
            proof.verify_static_time_projection(**self.case())

    def test_source_interval_inequality_is_independent_of_common_weight_equality(self):
        values = dict(self.source.inputs.rail)
        pair = next(iter(values))
        values[pair] += 1.0
        inputs = replace(self.source.inputs, rail=MappingProxyType(values))
        with self.assertRaisesRegex(RouteContractError, "ride_weight_exceeds_source_interval"):
            proof.verify_static_time_projection(**self.case(inputs=inputs))

    def test_walk_clock_override_has_to_match_the_projected_edge(self):
        case = self.case()
        p = case["projection"]
        reverse = {node: list(rows) for node, rows in p.reverse.items()}
        last = bus._phys("A")
        reverse[last] = [(node, math.nextafter(weight, math.inf)
                         if node == rail._physical("Q") else weight)
                         for node, weight in reverse[last]]
        case["projection"] = replace(p, reverse=MappingProxyType(
            {node: tuple(rows) for node, rows in reverse.items()}))
        with self.assertRaisesRegex(RouteContractError, "projected_transition_weight_differs"):
            proof.verify_static_time_projection(**case)

    def test_decreasing_inactive_source_clocks_and_nonexact_minutes_are_rejected(self):
        source = self.source
        station, rows = next(iter(source.manager.train_patterns_weekday.items()))
        bad = dict(rows[0], dep=700, arr=699)
        source.manager.train_patterns_weekend[station] = [bad]
        source.choices = TimetableChoices(source.graph, source.manager, day_type=source.rail_source.day,
            use_realtime=False, deadline=3000, bus_repository=source.repository)
        forged = replace(source.inputs, source_digest=destination._sources_digest(
            source.manager, source.repository, lambda: None))
        with self.assertRaisesRegex(RouteContractError, "invalid_rail_interval"):
            proof.verify_static_time_projection(**self.case(inputs=forged))
        bad["arr"], bad["dep"] = 701, 700.0
        # Refresh the explicit synthetic snapshot; do not recover or coerce it.
        source.choices = TimetableChoices(source.graph, source.manager, day_type=source.rail_source.day,
            use_realtime=False, deadline=3000, bus_repository=source.repository)
        forged = replace(source.inputs, source_digest=destination._sources_digest(
            source.manager, source.repository, lambda: None))
        with self.assertRaisesRegex(RouteContractError, "nonexact_source_clock"):
            proof.verify_static_time_projection(**self.case(inputs=forged))

    def test_bus_nonmonotone_dwell_and_inconsistent_departure_index_are_rejected(self):
        repository = self.source.repository
        trip = next(iter(repository.trips))
        sequence = next(iter(repository.stop_times[trip]))
        original = repository.stop_times[trip][sequence]
        stop, arrival, departure = original
        repository.stop_times[trip][sequence] = (stop, departure + 1, departure)
        forged = replace(self.source.inputs, source_digest=destination._sources_digest(
            self.source.manager, repository, lambda: None))
        with self.assertRaisesRegex(RouteContractError, "decreasing_bus_source_clock"):
            proof.verify_static_time_projection(**self.case(inputs=forged))
        repository.stop_times[trip][sequence] = original
        case = self.case()
        key = next(iter(repository.timetable_index))
        scheduled, position, trip_id = repository.timetable_index[key][0]
        repository.timetable_index[key][0] = (scheduled + 1, position, trip_id)
        with self.assertRaisesRegex(RouteContractError, "bus_departure_index_inconsistent"):
            proof.verify_static_time_projection(**case)

    def test_reverse_bellman_seed_and_reachability_violations_are_independent_failures(self):
        for mutation, reason in (("seed", "seed_bound_inequality_failed"),
                                 ("edge", "reverse_bellman_inequality_failed"),
                                 ("membership", "bound_reachability_membership_differs")):
            with self.subTest(mutation=mutation):
                case = self.case()
                values = dict(case["bounds"]._values)
                if mutation == "seed":
                    values[case["target"]] = 1.0
                elif mutation == "edge":
                    node = bus._phys("A")
                    values[node] += 1.0
                else:
                    values.pop(case["target"])
                case["bounds"] = TimeBounds(values, dict(case["bounds"].report))
                with self.assertRaisesRegex(RouteContractError, reason):
                    proof.verify_static_time_projection(**case)

    def test_nonimproving_seeds_still_have_to_be_covered_by_unchanged_guard_maximum(self):
        target = bus._phys("C")
        case = self.case(target=target, virtual={target: (0.0, 16000.0)})
        self.assertEqual(case["bounds"].report["max_edge_minutes"], 200.0)
        case["guard"] = TimeRoundingGuard(start_minute=600.0, deadline=840.0,
            max_forward_steps=100000, max_reverse_steps=len(self.source.graph) + 1,
            max_edge_minutes=case["projection"].max_edge_minutes)
        with self.assertRaisesRegex(RouteContractError, "guard_maximum_excludes_edge_or_seed"):
            proof.verify_static_time_projection(**case)

    def test_virtual_origin_can_be_a_line_node_and_missing_seed_validation_is_not_skipped(self):
        target = ("virtual", "goal")
        case = self.case(target=target, virtual={rail._line("Q"): (0.0, 80.0),
                                                ("phys", "absent"): (0.0, 2.0)})
        result = proof.verify_static_time_projection(**case)
        self.assertEqual(result["destination_seed_entries"], 1)
        self.assertEqual(result["missing_virtual_nodes"], 1)
        case["virtual_connections"][("phys", "absent")] = (0.0, math.nan)
        with self.assertRaisesRegex(RouteContractError, "nonfinite_or_negative_number"):
            proof.verify_static_time_projection(**case)
        case["virtual_connections"] = {("phys", "absent"): (0.0, 2.0)}
        with self.assertRaisesRegex(RouteContractError, "no_present_destination_seed"):
            proof.verify_static_time_projection(**case)

    def test_disabled_or_modified_guard_and_wrong_reverse_count_never_acquire_a_certificate(self):
        case = self.case()
        case["guard"]._enabled = False
        with self.assertRaisesRegex(RouteContractError, "rounding_guard_disabled"):
            proof.verify_static_time_projection(**case)
        for factor in (0.0, 2.0):
            case = self.case()
            case["guard"]._error *= factor
            case["guard"].report["fixed_error_minutes"] = case["guard"]._error
            with self.assertRaises(RouteContractError):
                proof.verify_static_time_projection(**case)
        case = self.case()
        case["guard"] = TimeRoundingGuard(start_minute=600.0, deadline=840.0,
            max_forward_steps=100000, max_reverse_steps=len(self.source.graph),
            max_edge_minutes=case["bounds"].report["max_edge_minutes"])
        with self.assertRaisesRegex(RouteContractError, "reverse_step_count_differs"):
            proof.verify_static_time_projection(**case)

    def test_realtime_other_modes_line_start_and_used_provider_are_out_of_scope(self):
        for mode in ("fewTransfers", "cost"):
            case = self.case()
            case["mode"] = mode
            with self.assertRaisesRegex(RouteContractError, "unsupported_proof_scope"):
                proof.verify_static_time_projection(**case)
        case = self.case()
        case["projection"].choices.use_realtime = True
        with self.assertRaisesRegex(RouteContractError, "noncanonical_or_realtime_provider"):
            proof.verify_static_time_projection(**case)
        self.source.choices.use_realtime = False
        case = self.case()
        case["start"] = rail._line("P")
        with self.assertRaisesRegex(RouteContractError, "start_without_physical_no_ride_invariant"):
            proof.verify_static_time_projection(**case)
        case = self.case()
        self.source.choices.board_options(rail._physical("P"), rail._line("P"), 600.0)
        with self.assertRaisesRegex(RouteContractError, "provider_already_used"):
            proof.verify_static_time_projection(**case)

    def test_nonbinary_arithmetic_or_query_clock_outside_exact_domain_is_not_certified(self):
        case = self.case()
        info = SimpleNamespace(radix=10, mant_dig=53, max_exp=1024, rounds=1)
        with patch.object(proof.sys, "float_info", info):
            with self.assertRaisesRegex(RouteContractError, "unsupported_binary64_arithmetic_environment"):
                proof.verify_static_time_projection(**case)
        with self.assertRaisesRegex(RouteContractError, "clock_domain_outside_exact_source_scope"):
            proof.verify_static_time_projection(**self.case(start=1e16, upper=1e16 + 240.0))

    def test_changed_executable_contract_stops_instead_of_assuming_old_proof(self):
        case = self.case()
        with patch.object(proof.forward, "search_labels", lambda *a, **kw: ()):
            with self.assertRaisesRegex(RouteContractError, "unreviewed_transition_implementation"):
                proof.verify_static_time_projection(**case)
        with patch.dict(proof._REVIEWED_AST_SHA256, {"timetable": "0" * 64}):
            with self.assertRaisesRegex(RouteContractError, "unreviewed_transition_implementation"):
                proof.verify_static_time_projection(**case)
        first, second = ast.parse("def f(): pass"), ast.parse("def f(): pass")
        if "type_params" not in second.body[0]._fields:
            second.body[0]._fields += ("type_params",)
        second.body[0].type_params = []
        self.assertEqual(proof._ast_form(first), proof._ast_form(second))

    def test_mid_audit_mutation_is_rejected_and_deadline_exception_is_preserved(self):
        case = self.case()
        original = proof._check_bound_inequalities
        def mutate(*args):
            result = original(*args)
            case["virtual_connections"][("phys", "unused_missing")] = (0.0, 1.0)
            return result
        with patch.object(proof, "_check_bound_inequalities", side_effect=mutate):
            with self.assertRaisesRegex(RouteContractError, "proof_inputs_changed_during_verification"):
                proof.verify_static_time_projection(**case)
        error = RuntimeError("original explicit proof deadline")
        def deadline():
            raise error
        with self.assertRaises(RuntimeError) as caught:
            proof.verify_static_time_projection(**self.case(), check_deadline=deadline)
        self.assertIs(caught.exception, error)


class ProjectionProofOracleTest(unittest.TestCase):
    def test_raw_mixed_schedules_resources_and_every_prefix_match_the_projection_lemma(self):
        checks = paths = forbidden_pickup_passes = 0
        covered = set()
        for offset, alighting_kind in itertools.product((0, 839), ("alight", "xfer")):
            graph, choices, runs, rail_minima, bus_minima = raw._mixed_fixture(offset)
            for _u, _v, edge in graph.edges(data=True):
                if edge.get("etype") == "alight":
                    edge["etype"] = alighting_kind
            inputs = _inputs(choices, rail_minima, bus_minima)
            projection = destination.project_common_graph(graph, choices, inputs.rail, inputs.bus,
                                                          edge_uses_rail=lambda u, v: False)
            target = ("virtual", "goal")
            virtual = {rail._physical("Z"): (0.0, 5.0), bus._phys("D"): (0.0, 800.0),
                       rail._physical("C"): (0.0, 16000.0),
                       # The through bus misses the final train by 0.05 min.
                       # This fixed exit makes that branch complete too; it
                       # must not be a vacuous forbidden-pickup assertion.
                       rail._physical("E"): (0.0, 5.0)}
            bounds = destination.common_destination_bounds(projection, target, virtual)
            weights = {(u, v): weight for v, rows in projection.reverse.items() for u, weight in rows}
            nr = len(graph) + 1
            for start in (offset + 598.0, math.nextafter(offset + 598.0, math.inf), offset + 599.0):
                guard = TimeRoundingGuard(start_minute=start, deadline=offset + 840.0,
                    max_forward_steps=nr, max_reverse_steps=nr, max_edge_minutes=bounds.report["max_edge_minutes"])
                report = proof.verify_static_time_projection(projection, inputs, bounds, guard, target, virtual,
                    start=rail._physical("A"), mode="time", scope="full_graph")
                self.assertTrue(report["static_time_priority_admissibility_verified"])
                with _forbid_calls((TimetableChoices.board_options, TimetableChoices.ride_options,
                                    proof.forward.search_labels, bus.engine._tokyo_label_search)):
                    traces = raw._enumerate(graph, runs, rail._physical("A"), target, start, virtual,
                                             deadline=offset + 840.0, step_bound=24)
                self.assertTrue(traces)
                eps = F(math.ulp(offset + 840.0))
                for trace in traces:
                    paths += 1
                    nodes = tuple(state[0] for state in trace)
                    edge_weights = []
                    for first, second in zip(trace, trace[1:]):
                        weight = (virtual[first[0]][1] / 80.0 if second[0] == target
                                  else weights[first[0], second[0]])
                        if second[0] == target:
                            covered.add(("virtual", None))
                        else:
                            kind = graph[first[0]][second[0]]["etype"]
                            role_node = second[0] if kind == "board" else first[0]
                            covered.add((kind, graph.nodes[role_node].get("mode")))
                            if kind in ("alight", "xfer"):
                                self.assertIsNotNone(first[2])
                                self.assertNotEqual(first[3], first[4])
                        delta = F(second[1]) - F(first[1])
                        self.assertGreaterEqual(delta, 0)
                        self.assertLessEqual(F(weight), delta + eps)
                        edge_weights.append(weight)
                        if second[2] is not None and runs[second[2]][1] == "through" and second[0][1] == "Q":
                            self.assertNotEqual(second[3], second[4])
                            forbidden_pickup_passes += 1
                    for index, state in enumerate(trace):
                        retained = _last_occurrence_edges(nodes[index:])
                        self.assertLessEqual(len(retained), nr)
                        projected = sum((F(edge_weights[index + i]) for i in retained), Fraction())
                        actual = F(trace[-1][1]) - F(state[1])
                        self.assertLessEqual(projected, actual + len(retained) * eps)
                        self.assertLessEqual(F(bounds(state[0])), projected + F(guard.report["reverse_error_minutes"]))
                        self.assertLessEqual(guard(state[1], bounds(state[0])), trace[-1][1])
                        checks += 1
        self.assertGreater(paths, 6)
        self.assertGreater(checks, 100)
        self.assertGreater(forbidden_pickup_passes, 0)
        self.assertEqual(covered, {("walk", None), ("virtual", None)} |
                         set(itertools.product(("board", "ride", "alight", "xfer"), ("rail", "bus"))))

    def test_zero_time_bus_occurrence_cycle_refutes_pop_based_suffix_length_not_admissibility(self):
        line = "buspat:zero-loop"
        graph = bus._graph(("A", "A"), line=line)
        repository = bus._repository(("loop", "active", (("A", 600, 600), ("A", 600, 600))))
        manager = rail._manager(rail._run("unused", (("P", 600), ("Q", 601))))
        manager.pattern_stops_map = {"zero-loop": ["A", "A"]}
        choices = TimetableChoices(graph, manager, day_type=bus._day("active"), use_realtime=False,
                                   deadline=840.0, bus_repository=repository)
        inputs = _inputs(choices, {(rail._station("P"), rail._station("Q")): math.nextafter(1.0, -math.inf)},
                         {(bus.ROUTE, "A", "A"): 0.0})
        projection = destination.project_common_graph(graph, choices, inputs.rail, inputs.bus,
                                                       edge_uses_rail=lambda u, v: False)
        target, virtual = ("virtual", "goal"), {bus._phys("A"): (0.0, 5.0)}
        bounds = destination.common_destination_bounds(projection, target, virtual)
        guard = TimeRoundingGuard(start_minute=600.0, deadline=840.0, max_forward_steps=100000,
            max_reverse_steps=len(graph) + 1, max_edge_minutes=bounds.report["max_edge_minutes"])
        report = proof.verify_static_time_projection(projection, inputs, bounds, guard, target, virtual,
            start=bus._phys("A"), mode="time", scope="full_graph")
        self.assertTrue(report["static_time_priority_admissibility_verified"])
        self.assertFalse(report["unexpanded_suffix_step_bound_verified"])
        clock, steps = 600.0, 0
        for _ in range(33334):
            options = choices.board_options(bus._phys("A"), bus._line("A", line), clock)
            self.assertEqual(len(options), 1)
            departure, fresh = options[0]
            self.assertEqual(departure, 600.0)  # Independent raw source expectation.
            self.assertEqual(fresh.sequence, fresh.board_sequence)
            options = choices.ride_options(bus._line("A", line), bus._line("A", line), departure, fresh)
            self.assertEqual(len(options), 1)
            arrival, moved = options[0]
            self.assertEqual(arrival, 600.0)
            self.assertNotEqual(moved.sequence, moved.board_sequence)
            clock = arrival + 0.0  # Moved bus alighting, never fresh alighting.
            steps += 3
        arrival, steps = clock + 5.0 / 80.0, steps + 1
        self.assertEqual(steps, 100003)
        self.assertGreater(steps, guard.report["max_forward_steps"])
        self.assertEqual(arrival, 600.0625)
        self.assertLessEqual(guard(600.0, bounds(bus._phys("A"))), arrival)

    def test_cycle_erasure_must_not_be_applied_to_same_run_operational_occurrences(self):
        graph = rail._graph(("A", "B"), ("B", "A"), ("A", "C"))
        manager = rail._manager(rail._run("loop", (("A", 600), ("B", 603), ("A", 606), ("C", 608))))
        choices = TimetableChoices(graph, manager, "weekday", use_realtime=False, deadline=840.0)
        clock, state = min(choices.board_options(rail._physical("A"), rail._line("A"), 600.0), key=lambda x: x[0])
        self.assertEqual(choices.ride_options(rail._line("A"), rail._line("C"), clock, state), ())
        for first, last in (("A", "B"), ("B", "A"), ("A", "C")):
            options = choices.ride_options(rail._line(first), rail._line(last), clock, state)
            self.assertEqual(len(options), 1)
            clock, state = options[0]
        self.assertEqual(clock, 608.0)
        self.assertEqual(_last_occurrence_edges(("A", "B", "A", "C")), [2])

    def test_undercovered_acyclic_suffix_is_a_real_guard_counterexample_at_normal_clock(self):
        start, weight = 600.0, 0.49 * math.ulp(600.0)
        arrival, remaining = start, 0.0
        for _ in range(10):
            arrival += weight
            remaining += weight
        guard = TimeRoundingGuard(start_minute=start, deadline=840.0, max_forward_steps=2,
                                 max_reverse_steps=12, max_edge_minutes=weight)
        self.assertTrue(guard.report["enabled"])
        self.assertEqual(arrival, 600.0)
        self.assertEqual(guard(start, remaining), math.nextafter(start, math.inf))
        self.assertGreater(guard(start, remaining), arrival)

    def test_exhaustive_small_graphs_include_longer_suffixes_than_nf_without_provider_oracle(self):
        # All 4^4 directed edge choices, five clock regimes, three seed forms.
        # The independent expected bound enumerates every simple reverse path.
        pairs = ((0, 1), (1, 0), (0, 2), (1, 2))
        cases = paths = checked = long_suffixes = cyclic = 0
        for start in (0.0, 600.0, math.nextafter(1024.0, -math.inf), 1439.0, 1e16):
            upper = start + 240.0
            tiny = math.ulp(start) if start == 0.0 else 0.49 * math.ulp(start)
            for selected in itertools.product((None, 0.0, tiny, 0.025), repeat=4):
                base, reverse = {n: [] for n in range(3)}, {n: [] for n in range(3)}
                for (first, last), weight in zip(pairs, selected):
                    if weight is not None:
                        base[first].append((last, weight))
                        reverse[last].append((first, weight))
                projection = SimpleNamespace(nodes=tuple(base), reverse=reverse, counts={}, walk_speed=80.0,
                    max_edge_minutes=max((w for rows in base.values() for _, w in rows), default=0.0))
                for kind in ("physical", "virtual", "hybrid"):
                    target = 3 if kind == "virtual" else 2
                    virtual = ({2: (0.0, 4.0), 1: (0.0, 2.0), 99: (0.0, 8.0)} if kind == "virtual" else
                               {0: (0.0, 2.0), 1: (0.0, 4.0), 2: (0.0, 40.0)} if kind == "hybrid" else {})
                    adjacency = {n: list(rows) for n, rows in base.items()}
                    adjacency.setdefault(target, [])
                    for node, (_, meters) in virtual.items():
                        if node in base:
                            adjacency[node].append((target, meters / 80.0))
                    bounds = destination.common_destination_bounds(projection, target, virtual)
                    guard = TimeRoundingGuard(start_minute=start, deadline=upper, max_forward_steps=4,
                        max_reverse_steps=4, max_edge_minutes=bounds.report["max_edge_minutes"])
                    self.assertTrue(guard.report["enabled"])
                    cases += 1

                    def simple(node, seen):
                        if node == target:
                            return 0.0
                        candidates = []
                        for following, weight in adjacency[node]:
                            if following not in seen:
                                remaining = simple(following, seen | {following})
                                if remaining is not None:
                                    candidates.append(remaining + weight)
                        return min(candidates) if candidates else None

                    for node in base:
                        expected = simple(node, {node})
                        self.assertEqual(expected is not None, node in bounds._values)
                        if expected is not None:
                            self.assertEqual(float_bits(expected), float_bits(bounds(node)))

                    def walks(nodes, clocks, weights):
                        if nodes[-1] == target:
                            yield nodes, clocks, weights
                            return
                        if len(weights) == 12:
                            return
                        for following, weight in adjacency[nodes[-1]]:
                            arrival = clocks[-1] + weight
                            if clocks[-1] <= arrival <= upper:
                                yield from walks(nodes + (following,), clocks + (arrival,), weights + (weight,))

                    for nodes, clocks, weights in walks((0,), (start,), ()):
                        paths += 1
                        for first in range(len(nodes)):
                            retained = _last_occurrence_edges(nodes[first:])
                            self.assertLessEqual(len(retained), 4)
                            witness = sum((F(weights[first + i]) for i in retained), Fraction())
                            elapsed = F(clocks[-1]) - F(clocks[first])
                            self.assertLessEqual(witness, elapsed + len(retained) * F(math.ulp(upper)))
                            self.assertLessEqual(F(bounds(nodes[first])), witness + F(guard.report["reverse_error_minutes"]))
                            self.assertLessEqual(guard(clocks[first], bounds(nodes[first])), clocks[-1])
                            checked += 1
                            long_suffixes += len(weights) - first > 4
                            cyclic += len(retained) < len(weights) - first
        self.assertEqual((cases, paths, checked, long_suffixes, cyclic),
                         (3840, 34700, 251380, 98640, 144900))


if __name__ == "__main__":
    unittest.main()
