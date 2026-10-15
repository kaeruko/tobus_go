"""Read-only static Tokyo time projection proof on explicitly pinned inputs.

Checks the new proof premises for full and rail-excluded graphs. Does not run
the accepted interval, graph-parity, destination-parity or route-sample gates.
No search, download, repair, runtime selection, guard adjustment or file output.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import pickle
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import networkx as nx
import toei_engine as engine
from check_tokyo_destination_bounds_local import destination_manifest
from check_tokyo_gtfs_local import fingerprints, load_inputs
from check_tokyo_odpt_local import check_repository, sha256
from check_tokyo_rail_routes_local import load_binding
from gtfs_loader import GtfsRepository
from route_engine import RouteContractError
from tokyo_dataset_bus_choices import TokyoBusDatasetBinding
from tokyo_destination_bounds_audit import (
    _digest_rows, _graph_digest, collect_common_inputs, common_destination_bounds,
    project_common_graph,
)
from tokyo_time_projection_proof import verify_static_time_projection
from tokyo_time_rounding import TimeRoundingGuard
from tokyo_timetable_choices import TimetableChoices


# The same audit inputs as stage 3, not changes to production query defaults.
CLOCK_PROFILES = (("normal", 600.0, 840.0), ("cross_midnight", 1439.0, 1679.0))
FORWARD_STEPS = 100000
SCOPES = ("full_graph", "bus_only_rail_excluded")
MARKER = "READ_ONLY_TOKYO_COMMON_TIME_PROJECTION_PROOF_OK"
_TRUE_FLAGS = (
    "static_time_priority_admissibility_verified", "forward_transition_coverage_verified",
    "nondecreasing_operational_clocks_verified", "one_edge_rounding_condition_verified",
    "simple_projection_step_bound_verified", "reverse_bound_inequalities_verified",
    "conditional_error_coefficients_verified",
)
_FALSE_FLAGS = (
    "unexpanded_suffix_step_bound_verified", "unconditional_priority_admissibility_verified",
    "real_timetable_suffix_admissibility_verified", "common_dataset_route_ranking_verified",
    "true_top_k_verified", "realtime_verified", "operational_calendar_verified",
)


def _reject(reason):
    raise RouteContractError("static time proof CLI rejected: reason=" + reason)


def _diagnostic(context, stage, error=None):
    row = {**context, "stage": stage}
    if error is not None:
        # Only the gate's bounded reason code, never arbitrary exception text,
        # source IDs, coordinates, filenames or itineraries in progress logs.
        message = error.args[0] if error.args and type(error.args[0]) is str else ""
        match = re.match(r"static time proof(?: CLI)? rejected: reason=([a-z_]{1,80})(?: |$)", message)
        row.update(reason=match.group(1) if match else "input_or_verification_exception",
                   exception_type=type(error).__name__)
    print("[TIME_PROJECTION_PROOF] " + json.dumps(row, ensure_ascii=True),
          file=sys.stderr, flush=True)


def _manifest_digest(manifest):
    return _digest_rows(((kind, target, tuple(seeds.items()))
                         for kind, target, seeds in manifest), lambda: None)


def _check_certificate(report, graph, scope, lower, upper):
    if (type(report) is not dict
            or any(report.get(flag) is not True for flag in _TRUE_FLAGS)
            or any(report.get(flag) is not False for flag in _FALSE_FLAGS)):
        _reject("incomplete_or_overstated_certificate")
    expected = {
        "mode": "time", "graph_scope": scope, "nodes": len(graph),
        "max_forward_steps": FORWARD_STEPS, "max_reverse_steps": len(graph) + 1,
        "simple_projection_step_bound": len(graph) + 1,
        "start_minute": lower, "deadline": upper,
        "runtime_selection": "not_selected_audit_only",
    }
    if any(report.get(key) != value for key, value in expected.items()):
        _reject("certificate_scope_or_profile_differs")


def inspect(train, stations, railways, gtfs, version, prebuilt):
    context = dict(scope="not_selected", destination_kind="not_selected", case_number=0,
                   clock_profile="not_selected", profile_number=0, mode="time",
                   phase="load_prebuilt")
    _diagnostic(context, "started")
    try:
        with prebuilt.open("rb") as stream:
            pinned = pickle.load(stream)
        if (type(pinned) is not dict or type(pinned.get("G")) is not nx.DiGraph
                or type(pinned.get("TM")) is not engine.TimetableManager):
            _reject("original_tokyo_graph_and_manager_required_no_repair")
        graph, manager = pinned["G"], pinned["TM"]
        graph_before = _graph_digest(graph, lambda: None)
        context["phase"] = "freeze_manifest"
        # Pure structural helper only; the old CLI's inspect/main are not run.
        manifest = destination_manifest(graph)
        manifest_before = _manifest_digest(manifest)
        starts = {"full_graph": manifest[1][1], "bus_only_rail_excluded": manifest[0][1]}
        context["phase"] = "load_odpt_binding"
        rail_binding = load_binding(train, stations, railways, manager)
        context["phase"] = "load_gtfs_common"
        _, _, snapshot, _, _ = load_inputs(gtfs, version, ("2026-09-04",))
        context["phase"] = "load_gtfs_reference"
        repository = GtfsRepository("tokyo_bus_probe").load_data(str(gtfs))
        context["phase"] = "collect_common_inputs"
        bus_binding = TokyoBusDatasetBinding(snapshot, repository)
        inputs = collect_common_inputs(rail_binding, bus_binding, manager, repository)
        index_before = _digest_rows(repository.timetable_index.items(), lambda: None)
        # This date constructs the static reference provider. All source
        # calendars are checked; it is not an operational-calendar certificate.
        day = date(2026, 9, 4)
        day_type = engine.ServiceDayType(
            "weekday", day, repository.get_active_service_ids(day), True)
        cases = {}
        for scope in SCOPES:
            context.update(scope=scope, destination_kind="not_selected", case_number=0,
                           clock_profile="not_selected", profile_number=0,
                           phase="project_common_graph")
            choices = TimetableChoices(graph, manager, day_type=day_type, use_realtime=False,
                                       deadline=3000, bus_repository=repository)
            predicate = (lambda u, v: False) if scope == "full_graph" else (
                lambda u, v: engine._edge_uses_rail(graph, u, v))
            projection = project_common_graph(
                graph, choices, inputs.rail, inputs.bus, edge_uses_rail=predicate)
            for number, (kind, target, seeds) in enumerate(manifest, 1):
                context.update(destination_kind=kind, case_number=number,
                               clock_profile="not_selected", profile_number=0,
                               phase="common_destination_bounds")
                bounds = common_destination_bounds(projection, target, seeds)
                profiles = []
                for profile_number, (label, lower, upper) in enumerate(CLOCK_PROFILES, 1):
                    context.update(clock_profile=label, profile_number=profile_number,
                                   phase="verify_static_time_projection")
                    _diagnostic(context, "started")
                    guard = TimeRoundingGuard(
                        start_minute=lower, deadline=upper, max_forward_steps=FORWARD_STEPS,
                        max_reverse_steps=len(graph) + 1,
                        max_edge_minutes=bounds.report["max_edge_minutes"])
                    report = verify_static_time_projection(
                        projection, inputs, bounds, guard, target, seeds,
                        start=starts[scope], mode="time", scope=scope)
                    _check_certificate(report, graph, scope, lower, upper)
                    profiles.append({"clock_profile": label, **report, "guard": dict(guard.report)})
                    _diagnostic(context, "verified")
                cases[scope + "/" + kind] = {**bounds.report, "profiles": profiles}
        context.update(phase="final_seals_and_coverage", clock_profile="not_selected",
                       profile_number=0)
        inputs.check_sources()
        if (_graph_digest(graph, lambda: None) != graph_before
                or _manifest_digest(manifest) != manifest_before):
            _reject("graph_or_fixed_manifest_changed")
        if _digest_rows(repository.timetable_index.items(), lambda: None) != index_before:
            _reject("departure_index_changed")
        if (len(cases) != 8 or any(len(case["profiles"]) != 2 for case in cases.values())
                or cases["full_graph/bus_physical"]["excluded_edges"] != 0
                or cases["bus_only_rail_excluded/bus_physical"]["excluded_edges"] <= 0):
            _reject("scope_destination_or_clock_coverage_differs")
        _diagnostic(context, "verified")
    except Exception as error:
        _diagnostic(context, "stopped", error)
        raise
    return {
        "audit_mode": "tokyo_common_static_time_projection_proof_premises",
        "calendar_scope": "all_source_calendars_no_date_filter",
        "destination_policy": "four_fixed_structural_destinations_v1",
        "start_policy": "rail_physical_for_full_bus_physical_for_rail_excluded",
        "clock_policy": "stage_3_normal_and_cross_midnight_v1",
        "destination_count": 4, "case_count": len(cases),
        "clock_profile_checks": sum(len(case["profiles"]) for case in cases.values()),
        "static_time_projection_premises_verified": True,
        **{flag: True for flag in _TRUE_FLAGS}, **{flag: False for flag in _FALSE_FLAGS},
        "cases": cases, **inputs.counts,
        "lambda_startup_verified": False,
        "accepted_audits_rerun": False, "route_search_executed": False,
        "runtime_selection": "not_selected_audit_only",
        "graph_provider": "unchanged_pinned_tokyo_graph", "mode": "time",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("train-timetables", "stations", "railways", "gtfs-dir", "trusted-prebuilt"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-feed-version", required=True)
    parser.add_argument("--expected-prebuilt-sha256", required=True)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    check_repository(args.expected_sha)
    paths = {name: getattr(args, name).resolve() for name in
             ("train_timetables", "stations", "railways", "trusted_prebuilt")}
    before = {name: sha256(path) for name, path in paths.items()}
    if before["trusted_prebuilt"] != args.expected_prebuilt_sha256.lower():
        raise RouteContractError("trusted prebuilt SHA-256 mismatch before unpickling")
    gtfs_before = fingerprints(args.gtfs_dir)
    result = inspect(paths["train_timetables"], paths["stations"], paths["railways"],
                     args.gtfs_dir, args.expected_feed_version, paths["trusted_prebuilt"])
    if (before != {name: sha256(path) for name, path in paths.items()}
            or gtfs_before != fingerprints(args.gtfs_dir)):
        raise RouteContractError("input files changed during static time proof audit")
    check_repository(args.expected_sha)
    print(json.dumps({"sha": args.expected_sha, "python": sys.version,
                      "input_hashes": {**before, **gtfs_before}, **result},
                     ensure_ascii=True, allow_nan=False))
    print(MARKER)


if __name__ == "__main__":
    main()
