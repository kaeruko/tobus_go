"""Synthetic files through the new proof CLI, never accepted audits or search."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import pickle
import sys
import unittest
from unittest.mock import patch

import networkx as nx

from route_engine import RouteContractError
import tokyo_bound_projection_audit as graph_audit
import tokyo_destination_bounds_audit as destination
import tokyo_rail_interval_audit as rail_audit
import tokyo_time_bounds as old_bounds
import transit_search_labels as forward
from tokyo_dataset_bus_choices import TokyoBusDatasetBinding
from tokyo_timetable_choices import TimetableChoices
from tests import test_tokyo_bus_choices_contract as bus
from tests import test_tokyo_destination_bounds_audit as fixture
from tests import test_tokyo_time_projection_proof as proof_fixture


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_tokyo_time_projection_proof_local.py"
spec = importlib.util.spec_from_file_location("time_projection_proof_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class TokyoTimeProjectionProofLocalTest(unittest.TestCase):
    def setUp(self):
        self.source = fixture.TokyoDestinationBoundsAuditTest()
        with contextlib.redirect_stdout(io.StringIO()):
            self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.root = self.source.root
        self.paths = self.source.paths()

    def arguments(self):
        args = self.source.arguments(self.paths)
        args[0] = str(SCRIPT)
        return args

    def inspect(self):
        return probe.inspect(*self.paths[:3], self.root, "fixture", self.paths[3])

    def test_full_cli_checks_both_scopes_all_profiles_readonly_without_any_accepted_gate(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        forbidden = (
            probe.engine._tokyo_label_search, forward.search_labels,
            TimetableChoices.board_options, TimetableChoices.ride_options,
            old_bounds.make_time_bounds, destination.verify_destination_case,
            graph_audit.verify_static_graph_projection,
            rail_audit.verify_static_rail_interval_minima,
            TokyoBusDatasetBinding.verify_static_bus_interval_minima,
            fixture.probe.inspect, fixture.probe.main,
        )
        with (patch.object(sys, "argv", self.arguments()),
              patch.object(probe, "check_repository") as repository,
              proof_fixture._forbid_calls(forbidden),
              contextlib.redirect_stdout(io.StringIO()) as output,
              contextlib.redirect_stderr(io.StringIO()) as diagnostic):
            probe.main()
        result, marker = output.getvalue().splitlines()[-2:]
        result = json.loads(result)
        self.assertEqual(marker, "READ_ONLY_TOKYO_COMMON_TIME_PROJECTION_PROOF_OK")
        self.assertEqual(result["sha"], "a" * 40)
        self.assertEqual(result["input_hashes"], {
            **{name: probe.sha256(path) for name, path in zip(
                ("train_timetables", "stations", "railways", "trusted_prebuilt"), self.paths)},
            **probe.fingerprints(self.root)})
        self.assertEqual(repository.call_args_list, [(("a" * 40,),), (("a" * 40,),)])
        self.assertEqual((result["destination_count"], result["case_count"],
                          result["clock_profile_checks"]), (4, 8, 16))
        self.assertTrue(result["static_time_projection_premises_verified"])
        self.assertFalse(result["accepted_audits_rerun"])
        self.assertFalse(result["route_search_executed"])
        self.assertEqual(result["runtime_selection"], "not_selected_audit_only")
        for key, case in result["cases"].items():
            scope = key.split("/")[0]
            self.assertEqual(case["nodes"], len(self.source.graph))
            if scope == "full_graph":
                self.assertEqual(case["excluded_edges"], 0)
            else:
                self.assertGreater(case["excluded_edges"], 0)
            for report, (label, lower, upper) in zip(case["profiles"], probe.CLOCK_PROFILES):
                self.assertEqual(report["clock_profile"], label)
                self.assertEqual(report["graph_scope"], scope)
                self.assertEqual(report["max_forward_steps"], 100000)
                self.assertEqual(report["simple_projection_step_bound"], len(self.source.graph) + 1)
                self.assertEqual((report["start_minute"], report["deadline"]), (lower, upper))
                self.assertGreater(report["rail_source_intervals_checked"], 0)
                self.assertGreater(report["bus_source_intervals_checked"], 0)
                self.assertEqual(report["guard"]["max_forward_steps"], 100000)
                self.assertTrue(report["guard"]["enabled"])
                for flag in probe._TRUE_FLAGS:
                    self.assertIs(report[flag], True)
                for flag in probe._FALSE_FLAGS:
                    self.assertIs(report[flag], False)
        rows = [json.loads(line.partition("] ")[2]) for line in diagnostic.getvalue().splitlines()]
        self.assertEqual(sum(r["phase"] == "verify_static_time_projection" and r["stage"] == "verified"
                             for r in rows), 16)
        self.assertNotIn("private", str(result) + diagnostic.getvalue())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})

    def test_first_premise_failure_preserves_exception_budget_and_stops_without_retry(self):
        original = RouteContractError("static time proof rejected: reason=projection_step_budget_insufficient "
                                      "declared_nf=100000 required_nr=100001")
        with (patch.object(probe, "verify_static_time_projection", side_effect=original) as gate,
              contextlib.redirect_stdout(io.StringIO()) as output,
              contextlib.redirect_stderr(io.StringIO()) as diagnostic):
            with self.assertRaises(RouteContractError) as caught:
                self.inspect()
        self.assertIs(caught.exception, original)
        gate.assert_called_once()
        self.assertEqual(gate.call_args.args[3].report["max_forward_steps"], 100000)
        self.assertEqual(gate.call_args.kwargs["scope"], "full_graph")
        self.assertIn('"reason": "projection_step_budget_insufficient"', diagnostic.getvalue())
        for field in ('"case_number": 1', '"profile_number": 1', '"clock_profile": "normal"',
                      '"mode": "time"', '"stage": "stopped"'):
            self.assertIn(field, diagnostic.getvalue())
        self.assertNotIn(probe.MARKER, output.getvalue())

    def test_one_verified_profile_then_failure_never_emits_marker_or_reselects(self):
        original = RuntimeError("private source ID and itinerary must not enter progress logs")
        real_gate = probe.verify_static_time_projection
        count = 0
        def stop_second(*args, **kw):
            nonlocal count
            count += 1
            if count == 2:
                raise original
            return real_gate(*args, **kw)
        with (patch.object(sys, "argv", self.arguments()), patch.object(probe, "check_repository"),
              patch.object(probe, "verify_static_time_projection", side_effect=stop_second) as gate,
              contextlib.redirect_stdout(io.StringIO()) as output,
              contextlib.redirect_stderr(io.StringIO()) as diagnostic):
            with self.assertRaises(RuntimeError) as caught:
                probe.main()
        self.assertIs(caught.exception, original)
        self.assertEqual(gate.call_count, 2)
        self.assertEqual(diagnostic.getvalue().count('"stage": "verified"'), 1)
        self.assertIn('"clock_profile": "cross_midnight"', diagnostic.getvalue())
        self.assertNotIn("private", diagnostic.getvalue())
        self.assertNotIn(probe.MARKER, output.getvalue())

    def test_bus_only_failure_cannot_be_hidden_by_full_graph_success(self):
        original = RouteContractError("static time proof rejected: reason=legal_edge_missing_from_projection")
        real_gate = probe.verify_static_time_projection
        def stop_bus(*args, **kw):
            if kw["scope"] == "bus_only_rail_excluded":
                raise original
            return real_gate(*args, **kw)
        with (patch.object(probe, "verify_static_time_projection", side_effect=stop_bus) as gate,
              contextlib.redirect_stdout(io.StringIO()),
              contextlib.redirect_stderr(io.StringIO()) as diagnostic):
            with self.assertRaises(RouteContractError) as caught:
                self.inspect()
        self.assertIs(caught.exception, original)
        self.assertEqual(gate.call_count, 9)
        self.assertEqual(diagnostic.getvalue().count('"stage": "verified"'), 8)
        self.assertIn('"scope": "bus_only_rail_excluded"', diagnostic.getvalue())

    def test_bound_construction_error_is_not_converted_to_zero_or_a_reference_bound(self):
        original = RuntimeError("private reverse construction interruption")
        with (patch.object(probe, "common_destination_bounds", side_effect=original) as bounds,
              patch.object(probe, "verify_static_time_projection") as gate,
              contextlib.redirect_stdout(io.StringIO()),
              contextlib.redirect_stderr(io.StringIO()) as diagnostic):
            with self.assertRaises(RuntimeError) as caught:
                self.inspect()
        self.assertIs(caught.exception, original)
        bounds.assert_called_once()
        gate.assert_not_called()
        self.assertIn('"phase": "common_destination_bounds"', diagnostic.getvalue())
        self.assertNotIn("private", diagnostic.getvalue())

    def test_incomplete_certificate_cannot_pass_as_a_partial_success(self):
        with (patch.object(probe, "verify_static_time_projection", return_value={}) as gate,
              contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
            with self.assertRaisesRegex(RouteContractError, "incomplete_or_overstated_certificate"):
                self.inspect()
        gate.assert_called_once()

    def test_unknown_transition_in_trusted_graph_is_rejected_by_the_real_gate(self):
        self.source.graph.add_edge(bus._phys("A"), bus._phys("C"), etype="private_unknown")
        self.paths[3].write_bytes(pickle.dumps({"G": self.source.graph, "TM": self.source.manager}))
        with (contextlib.redirect_stdout(io.StringIO()),
              contextlib.redirect_stderr(io.StringIO()) as diagnostic):
            with self.assertRaisesRegex(RouteContractError, "uncovered_forward_transition"):
                self.inspect()
        self.assertIn('"reason": "uncovered_forward_transition"', diagnostic.getvalue())
        self.assertNotIn("private", diagnostic.getvalue())

    def test_unreviewed_transition_implementation_is_not_silently_accepted(self):
        with (patch.object(probe.engine, "_tokyo_label_search", side_effect=AssertionError("search forbidden")) as search,
              contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
            with self.assertRaisesRegex(RouteContractError, "unreviewed_transition_implementation"):
                self.inspect()
        search.assert_not_called()

    def test_no_prebuilt_repair_and_no_unpickle_before_pinned_hash_matches(self):
        args = self.arguments()
        args[args.index("--expected-prebuilt-sha256") + 1] = "f" * 64
        with (patch.object(sys, "argv", args), patch.object(probe, "check_repository"),
              patch.object(probe.pickle, "load") as unpickle):
            with self.assertRaisesRegex(RouteContractError, "before unpickling"):
                probe.main()
        unpickle.assert_not_called()
        self.paths[3].write_bytes(pickle.dumps({"G": nx.MultiDiGraph(), "TM": self.source.manager}))
        with (patch.object(probe, "load_binding") as binding,
              contextlib.redirect_stderr(io.StringIO())):
            with self.assertRaisesRegex(RouteContractError, "original_tokyo_graph_and_manager_required_no_repair"):
                self.inspect()
        binding.assert_not_called()

    def test_minute_incompatible_gtfs_stops_before_reference_repository_load(self):
        path = self.root / "stop_times.txt"
        path.write_text(path.read_text().replace("10:00:00", "10:00:01"), encoding="utf-8")
        with (patch.object(probe.GtfsRepository, "load_data") as load,
              contextlib.redirect_stderr(io.StringIO()) as diagnostic):
            with self.assertRaisesRegex(ValueError, "exact minute-aligned"):
                self.inspect()
        load.assert_not_called()
        self.assertIn('"phase": "load_gtfs_common"', diagnostic.getvalue())
        self.assertNotIn("private", diagnostic.getvalue())

    def test_file_addition_or_edit_after_inspection_prevents_marker(self):
        for name in ("train.json", "extra.txt"):
            with self.subTest(name=name):
                original = (self.root / name).read_bytes() if (self.root / name).exists() else None
                def mutate(*args):
                    path = self.root / name
                    path.write_bytes((original or b"") + b" ")
                    return {}
                try:
                    with (patch.object(sys, "argv", self.arguments()),
                          patch.object(probe, "check_repository") as repository,
                          patch.object(probe, "inspect", side_effect=mutate),
                          contextlib.redirect_stdout(io.StringIO()) as output):
                        with self.assertRaisesRegex(RouteContractError, "input files changed"):
                            probe.main()
                    self.assertEqual(repository.call_count, 1)
                    self.assertNotIn(probe.MARKER, output.getvalue())
                finally:
                    if original is None:
                        (self.root / name).unlink()
                    else:
                        (self.root / name).write_bytes(original)

    def test_clean_sha_is_required_before_and_after_inspection(self):
        for after in (False, True):
            original = ValueError("require clean main at expected SHA")
            with self.subTest(after=after):
                with (patch.object(sys, "argv", self.arguments()),
                      patch.object(probe, "check_repository", side_effect=[None, original] if after else original),
                      patch.object(probe, "inspect", return_value={}) as inspect,
                      contextlib.redirect_stdout(io.StringIO()) as output):
                    with self.assertRaises(ValueError) as caught:
                        probe.main()
                self.assertIs(caught.exception, original)
                self.assertEqual(inspect.call_count, int(after))
                self.assertNotIn(probe.MARKER, output.getvalue())

    def test_mutation_after_last_profile_is_caught_by_whole_run_seals(self):
        for kind in ("graph", "index", "source", "manifest"):
            with self.subTest(kind=kind):
                count = 0
                real_gate = probe.verify_static_time_projection
                def mutate_last(*args, **kw):
                    nonlocal count
                    result = real_gate(*args, **kw)
                    count += 1
                    if count == 16:
                        projection, inputs, _, _, _, seeds = args
                        if kind == "graph":
                            projection.graph.nodes[kw["start"]]["private_changed"] = True
                        elif kind == "index":
                            next(iter(inputs.repository.timetable_index.values())).append((0, "private_trip", 1))
                        elif kind == "source":
                            next(iter(inputs.repository.trips.values()))["private_changed"] = True
                        else:
                            seeds.clear()
                    return result
                with (patch.object(probe, "verify_static_time_projection", side_effect=mutate_last),
                      contextlib.redirect_stdout(io.StringIO()),
                      contextlib.redirect_stderr(io.StringIO()) as diagnostic):
                    with self.assertRaises(RouteContractError):
                        self.inspect()
                self.assertEqual(count, 16)
                self.assertIn('"phase": "final_seals_and_coverage"', diagnostic.getvalue())
                self.assertNotIn("private", diagnostic.getvalue())

    def test_realtime_modes_limits_dates_and_skip_options_are_not_accepted(self):
        for extra in (("--realtime",), ("--mode", "cost"), ("--max-forward-steps", "200000"),
                      ("--max-candidates", "4"), ("--query-date", "2026-09-04"),
                      ("--skip-bus-only",), ("--gtfs", str(self.root))):
            with self.subTest(extra=extra):
                with (patch.object(sys, "argv", self.arguments() + list(extra)),
                      patch.object(probe, "check_repository") as repository,
                      contextlib.redirect_stderr(io.StringIO())):
                    with self.assertRaises(SystemExit):
                        probe.main()
                repository.assert_not_called()


if __name__ == "__main__":
    unittest.main()
