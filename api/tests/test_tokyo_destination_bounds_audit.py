"""All-node parity is exact, independent of the bounded-suffix safety oracle."""
from __future__ import annotations

import contextlib
from dataclasses import asdict, replace
import importlib.util
import io
import json
import math
from pathlib import Path
import pickle
import sys
from types import MappingProxyType
import unittest
from unittest.mock import patch

import networkx as nx

from route_engine import RouteContractError
import tokyo_destination_bounds_audit as audit
from tokyo_time_bounds import TimeBounds
from tokyo_time_rounding import TimeRoundingGuard
from tokyo_timetable_choices import TimetableChoices
from tests import test_tokyo_compiled_routes_local_check as gtfs
from tests import test_tokyo_dataset_rail_choices as shared_rail
from tests import test_tokyo_waiting_contract as rail
from tests import test_tokyo_bus_choices_contract as bus


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_tokyo_destination_bounds_local.py"
spec = importlib.util.spec_from_file_location("destination_bounds_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class TokyoDestinationBoundsAuditTest(unittest.TestCase):
    def setUp(self):
        source = gtfs.TokyoCompiledRoutesLocalCheckTest()
        source.setUp()
        self.addCleanup(source.doCleanups)
        source.full_fixture()
        self.root = source.root
        run = rail._run("private_run", (("P", 600), ("Q", 605), ("P", 607), ("Z", 610)))
        run["odpt:trainTimetableObject"][1]["odpt:departureTime"] = "10:06"
        rail_source = shared_rail.TokyoDatasetRailChoicesTest()
        rail_source.fixture(run)
        self.rail_source = rail_source
        self.graph = nx.compose(rail_source.graph, source.graph)
        rail._walk(self.graph, rail._physical("Q"), bus._phys("A"), 2.0)
        self.graph.add_node(("phys", "private_unreachable"))
        self.manager = rail_source.manager
        self.repository = probe.GtfsRepository("tokyo_bus_probe").load_data(str(self.root))
        _, _, snapshot, _, _ = probe.load_inputs(self.root, "fixture", ("2026-09-04",))
        self.bus_binding = probe.TokyoBusDatasetBinding(snapshot, self.repository)
        self.inputs = audit.collect_common_inputs(
            rail_source.binding, self.bus_binding, self.manager, self.repository)
        self.choices = TimetableChoices(
            self.graph, self.manager, day_type=rail_source.day, use_realtime=False,
            deadline=3000, bus_repository=self.repository)

    def projection(self, predicate=lambda _u, _v: False, **kw):
        return audit.project_common_graph(
            self.graph, self.choices, self.inputs.rail, self.inputs.bus,
            edge_uses_rail=predicate, **kw)

    def compare(self, **kw):
        args = dict(projection=self.projection(), target=bus._phys("C"),
                    virtual_connections={rail._physical("Z"): (0.0, 160.0)},
                    edge_uses_rail=lambda _u, _v: False)
        args.update(kw)
        return audit.verify_destination_case(**args)

    def paths(self):
        paths = tuple(self.root / name for name in
                      ("train.json", "stations.json", "railways.json", "trusted.pkl"))
        for path, data in zip(paths[:3], (self.rail_source.runs,
                                        self.rail_source.stations, self.rail_source.railways)):
            path.write_text(json.dumps(data), encoding="utf-8")
        paths[3].write_bytes(pickle.dumps({"G": self.graph, "TM": self.manager}))
        return paths

    def arguments(self, paths):
        return [str(SCRIPT), "--train-timetables", str(paths[0]), "--stations", str(paths[1]),
                "--railways", str(paths[2]), "--trusted-prebuilt", str(paths[3]),
                "--gtfs-dir", str(self.root), "--expected-feed-version", "fixture",
                "--expected-prebuilt-sha256", probe.sha256(paths[3]), "--expected-sha", "a" * 40]

    def test_all_eight_cases_all_nodes_and_guard_bits_without_any_passed_gate_or_od(self):
        with (patch.object(probe.engine, "_tokyo_label_search", side_effect=AssertionError("OD")),
              patch("tokyo_bound_projection_audit.verify_static_graph_projection",
                    side_effect=AssertionError("stage 2 rerun")),
              patch("tokyo_rail_interval_audit.verify_static_rail_interval_minima",
                    side_effect=AssertionError("rail input rerun")),
              patch.object(probe.TokyoBusDatasetBinding, "verify_static_bus_interval_minima",
                           side_effect=AssertionError("bus input rerun"))):
            for _, predicate in (("full", lambda u, v: False),
                                 ("bus", lambda u, v: bus.engine._edge_uses_rail(self.graph, u, v))):
                projection = self.projection(predicate)
                for kind, target, virtual in probe.destination_manifest(self.graph):
                    report = audit.verify_destination_case(
                        projection, target, virtual, edge_uses_rail=predicate)
                    self.assertTrue(report["common_destination_bounds_verified"], kind)
                    self.assertTrue(report["rounding_guard_equivalence_verified"])
                    self.assertEqual(report["all_nodes_compared"], len(self.graph))
                    self.assertEqual(report["priority_pairs_compared"], len(self.graph) * 10)
                    self.assertFalse(report["unconditional_priority_admissibility_verified"])
                    self.assertFalse(report["unexpanded_suffix_step_bound_verified"])
                    self.assertFalse(report["real_timetable_suffix_admissibility_verified"])

    def test_common_reverse_search_cannot_call_reference_builder_or_indexes(self):
        projection = self.projection()
        with (patch.object(audit, "make_time_bounds", side_effect=AssertionError("old bound")),
              patch("tokyo_time_bounds._build_rail_index", side_effect=AssertionError("old rail")),
              patch("tokyo_time_bounds._build_bus_index", side_effect=AssertionError("old bus"))):
            bound = audit.common_destination_bounds(projection, bus._phys("C"), {})
        self.assertGreater(bound(bus._phys("A")), 0)
        self.assertNotIn(("phys", "private_unreachable"), bound._values)
        self.assertEqual(bound(("phys", "private_unreachable")), 0.0)

    def test_fixed_time_query_keeps_candidate_order_clocks_runs_and_metadata(self):
        def run():
            with (patch.object(bus.engine, "gtfs_repo", self.repository),
                  contextlib.redirect_stdout(io.StringIO())):
                rows = list(bus.engine._tokyo_label_search(
                    self.graph, self.manager, rail._physical("P"), bus._phys("C"),
                    "09:58", self.rail_source.day, "time", 3, 100000, 240,
                    None, 15.0, None, None, False, False))
            return [{"cost": row["cost"], "nodes": list(row["path"]),
                     "clocks": row["path"].edge_times, "walk_m": row["walk_m"],
                     "runs": {index: asdict(ride) if ride else None
                              for index, ride in row["path"].edge_rides.items()},
                     "metadata": {index: row["path"].choices.metadata(ride)
                                  for index, ride in row["path"].edge_rides.items() if ride}}
                    for row in rows]

        expected = run()
        calls = []
        def explicit_common(graph, choices, target, virtual, **kw):
            calls.append(True)
            projection = audit.project_common_graph(
                graph, choices, self.inputs.rail, self.inputs.bus,
                edge_uses_rail=kw["edge_uses_rail"], check_deadline=kw["check_deadline"],
                walk_speed=kw["walk_speed"], rail_boarding_minutes=kw["rail_boarding_minutes"])
            return audit.common_destination_bounds(projection, target, virtual,
                                                    check_deadline=kw["check_deadline"])
        with patch("tokyo_search_labels.make_time_bounds", side_effect=explicit_common):
            actual = run()
        self.assertTrue(expected)
        self.assertEqual(actual, expected)
        self.assertEqual(calls, [True])
        self.assertTrue(any({ride["provider"] for ride in row["runs"].values() if ride}
                            == {"rail", "bus"} for row in actual))

    def test_equal_zeros_cannot_hide_membership_loss_and_one_ulp_or_signed_zero_fails(self):
        node = ("private", "node")
        for old, new, reason in (({node: 0.0}, {}, "reachability"),
                                 ({node: 0.0}, {node: -0.0}, "bits"),
                                 ({node: 1.0}, {node: math.nextafter(1.0, math.inf)}, "bits")):
            with self.assertRaisesRegex(RouteContractError, reason) as caught:
                audit.compare_all_nodes((node,), TimeBounds(old, {}), TimeBounds(new, {}))
            self.assertNotIn("private", str(caught.exception))
        with self.assertRaisesRegex(RouteContractError, "outside"):
            audit.compare_all_nodes((), TimeBounds({node: 0.0}, {}), TimeBounds({}, {}))

    def test_changed_common_minimum_stops_with_one_reference_call_and_no_reselection(self):
        altered = dict(self.inputs.rail)
        pair = next(iter(altered))
        altered[pair] += 1.0
        projection = audit.project_common_graph(
            self.graph, self.choices, altered, self.inputs.bus, edge_uses_rail=lambda u, v: False)
        with patch.object(audit, "make_time_bounds", wraps=audit.make_time_bounds) as old:
            with self.assertRaisesRegex(RouteContractError, "bits differ"):
                self.compare(projection=projection, target=("phys", pair[1]), virtual_connections={})
        old.assert_called_once()

    def test_unused_seed_and_disconnected_edge_still_determine_global_guard_maximum(self):
        self.graph.add_edge("disconnected", 42, etype="walk", meters=8000.0)
        projection = self.projection()
        target = bus._phys("C")
        ordinary = audit.common_destination_bounds(projection, target, {})
        seeded = audit.common_destination_bounds(projection, target, {target: (0.0, 16000.0)})
        self.assertEqual(ordinary._values, seeded._values)
        self.assertEqual(ordinary.report["max_edge_minutes"], 100.0)
        self.assertEqual(seeded.report["max_edge_minutes"], 200.0)
        report = self.compare(projection=projection, target=target,
                              virtual_connections={target: (0.0, 16000.0)})
        self.assertEqual(report["max_edge_minutes"], 200.0)

    def test_even_an_unused_missing_seed_cannot_change_after_freezing(self):
        virtual = {"missing": (0.0, 80.0)}
        original = audit.make_time_bounds
        def mutate_after_reference(*args, **kw):
            value = original(*args, **kw)
            virtual["missing"] = (0.0, 160.0)
            return value
        with patch.object(audit, "make_time_bounds", side_effect=mutate_after_reference) as old:
            with self.assertRaisesRegex(RouteContractError, "frozen virtual destination seeds changed"):
                self.compare(virtual_connections=virtual)
            old.assert_called_once()

    def test_source_and_graph_same_size_mutations_fail_even_without_minimum_change(self):
        self.repository.stop_times["later"][2] = ("C", 626, 626)
        with self.assertRaisesRegex(RouteContractError, "sources changed"):
            self.inputs.check_sources()
        with self.assertRaisesRegex(RouteContractError, "source clock"):
            audit.collect_common_inputs(self.rail_source.binding, self.bus_binding,
                                        self.manager, self.repository)
        projection = self.projection()
        self.graph[rail._physical("Q")][bus._phys("A")]["w"] += 1
        with self.assertRaisesRegex(RouteContractError, "graph changed"):
            self.compare(projection=projection)

    def test_original_deadline_and_reference_exception_propagate_without_retry(self):
        projection = self.projection()
        original = RuntimeError("original deadline")
        with patch.object(audit, "make_time_bounds") as old:
            with self.assertRaises(RuntimeError) as caught:
                self.compare(projection=projection,
                             check_deadline=lambda: (_ for _ in ()).throw(original))
            self.assertIs(caught.exception, original)
            old.assert_not_called()
        with patch.object(audit, "make_time_bounds", side_effect=original) as old:
            with self.assertRaises(RuntimeError) as caught:
                self.compare(projection=projection)
            self.assertIs(caught.exception, original)
            old.assert_called_once()

    def test_disabled_reference_realtime_noncanonical_and_guard_corruption_are_rejected(self):
        with patch.object(audit, "make_time_bounds", return_value=TimeBounds({}, {"scope": "custom: zero"})):
            with self.assertRaisesRegex(RouteContractError, "disabled"):
                self.compare()
        self.choices.use_realtime = True
        with self.assertRaisesRegex(RouteContractError, "static reference"):
            self.projection()
        self.choices.use_realtime = False
        self.graph.add_edge("bad", bus._line("A"), etype="xfer")
        with self.assertRaisesRegex(RouteContractError, "noncanonical"):
            self.projection()
        self.graph.remove_edge("bad", bus._line("A"))
        calls = []
        def broken_guard(**kw):
            guard = TimeRoundingGuard(**kw)
            calls.append(guard)
            if len(calls) == 2:
                guard._error = math.nextafter(guard._error, math.inf)
            return guard
        with patch.object(audit, "TimeRoundingGuard", side_effect=broken_guard):
            with self.assertRaisesRegex(RouteContractError, "internal value differs"):
                self.compare()
        self.assertEqual(len(calls), 2)

    def test_mixed_node_ties_zero_cycles_and_reverse_addition_order_are_preserved(self):
        self.graph.add_edge(10, "x", etype="walk", meters=24.0)
        self.graph.add_edge("x", (11,), etype="walk", meters=16.0)
        self.graph.add_edge((11,), "end", etype="walk", meters=8.0)
        self.graph.add_edge("same", (11,), etype="walk", meters=16.0)
        self.graph.add_edge("zero1", "zero2", etype="unknown")
        self.graph.add_edge("zero2", "zero1", etype="unknown")
        self.graph.add_edge("zero2", "end", etype="unknown")
        projection = self.projection()
        result = audit.common_destination_bounds(projection, "end", {})
        self.assertEqual(result(10), 0.3 + (0.2 + 0.1))
        self.assertEqual(result("zero1"), 0.0)
        self.assertIn("zero1", result._values)
        self.assertTrue(self.compare(projection=projection, target="end", virtual_connections={})[
            "bound_binary64_bits_verified"])

    def test_missing_virtual_nodes_validate_before_skipping_and_overflow_cannot_be_unreachable_zero(self):
        projection = self.projection()
        for value in ((-1.0, 80.0), (0.0, math.inf), (0.0, -1.0)):
            with self.assertRaises(RouteContractError):
                audit.common_destination_bounds(projection, "outside", {"missing": value})
        huge = replace(projection, nodes=(1, 2, 3), max_edge_minutes=1e308,
                       reverse=MappingProxyType({1: (), 2: ((1, 1e308),), 3: ((2, 1e308),)}))
        with self.assertRaisesRegex(RouteContractError, "overflowed"):
            audit.common_destination_bounds(huge, 3, {})

    def test_full_cli_hashes_clean_sha_no_writes_and_distinct_non_safety_marker(self):
        paths = self.paths()
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        argv = self.arguments(paths)
        with (patch.object(sys, "argv", argv), patch.object(probe, "check_repository") as repository,
              patch.object(probe.engine, "_tokyo_label_search", side_effect=AssertionError("OD")),
              contextlib.redirect_stdout(io.StringIO()) as output,
              contextlib.redirect_stderr(io.StringIO()) as diagnostics):
            probe.main()
        report, marker = output.getvalue().splitlines()[-2:]
        report = json.loads(report)
        self.assertEqual(marker, "READ_ONLY_TOKYO_COMMON_DESTINATION_BOUNDS_PARITY_OK")
        self.assertEqual(report["case_count"], 8)
        self.assertEqual(report["all_node_comparisons"], len(self.graph) * 8)
        self.assertEqual(repository.call_count, 2)
        self.assertFalse(report["unconditional_priority_admissibility_verified"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertNotIn("private", report.__str__() + diagnostics.getvalue())

    def test_cli_stops_first_case_with_safe_diagnostic_and_preserves_original_exception(self):
        paths = self.paths()
        original = RuntimeError("original reference interruption")
        with (patch.object(probe, "verify_destination_case", side_effect=original) as compare,
              contextlib.redirect_stdout(io.StringIO()) as output,
              contextlib.redirect_stderr(io.StringIO()) as diagnostics):
            with self.assertRaises(RuntimeError) as caught:
                probe.inspect(*paths[:3], self.root, "fixture", paths[3])
        self.assertIs(caught.exception, original)
        compare.assert_called_once()
        self.assertIn('"stage": "stopped"', diagnostics.getvalue())
        self.assertIn('"mode": "time"', diagnostics.getvalue())
        self.assertNotIn("private", diagnostics.getvalue())
        self.assertNotIn("READ_ONLY_TOKYO_COMMON_DESTINATION", output.getvalue())

    def test_one_equal_case_followed_by_error_cannot_emit_success_or_try_another_target(self):
        paths = self.paths()
        original = RuntimeError("stopped after first equal destination")
        with (patch.object(sys, "argv", self.arguments(paths)),
              patch.object(probe, "check_repository"),
              patch.object(probe, "verify_destination_case", side_effect=[{}, original]) as compare,
              contextlib.redirect_stdout(io.StringIO()) as output,
              contextlib.redirect_stderr(io.StringIO()) as diagnostics):
            with self.assertRaises(RuntimeError) as caught:
                probe.main()
        self.assertIs(caught.exception, original)
        self.assertEqual(compare.call_count, 2)
        self.assertEqual(diagnostics.getvalue().count('"stage": "equal"'), 1)
        self.assertNotIn("_OK", output.getvalue())

    def test_changed_files_wrong_prebuilt_and_unsupported_options_never_emit_marker(self):
        paths = self.paths()
        argv = self.arguments(paths)
        with (patch.object(sys, "argv", argv), patch.object(probe, "check_repository"),
              patch.object(probe, "fingerprints", side_effect=[{}, {"changed": "yes"}]),
              patch.object(probe, "inspect", return_value={}),
              contextlib.redirect_stdout(io.StringIO()) as output):
            with self.assertRaisesRegex(RouteContractError, "files changed"):
                probe.main()
            self.assertNotIn("_OK", output.getvalue())
        wrong = list(argv)
        wrong[wrong.index("--expected-prebuilt-sha256") + 1] = "f" * 64
        with (patch.object(sys, "argv", wrong), patch.object(probe, "check_repository"),
              patch.object(probe, "inspect") as inspect):
            with self.assertRaisesRegex(RouteContractError, "before unpickling"):
                probe.main()
            inspect.assert_not_called()
        for extra in (("--realtime",), ("--query-date", "2026-09-04"), ("--max-candidates", "4")):
            with (patch.object(sys, "argv", argv + list(extra)),
                  patch.object(probe, "check_repository") as repository,
                  contextlib.redirect_stderr(io.StringIO())):
                with self.assertRaises(SystemExit):
                    probe.main()
                repository.assert_not_called()


if __name__ == "__main__":
    unittest.main()
