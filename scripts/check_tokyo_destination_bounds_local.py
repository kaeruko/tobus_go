"""Read-only stage-3 all-node bounds/guard parity on the pinned Tokyo graph.

No standalone interval/projection gate, OD route matrix, provider switch,
download or artifact write. Unconditional priority admissibility stays false:
the unexpanded legal-suffix N_f proof is a separate, unfinished obligation.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import pickle
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import networkx as nx
import toei_engine as engine
from check_tokyo_gtfs_local import fingerprints, load_inputs
from check_tokyo_odpt_local import check_repository, sha256
from check_tokyo_rail_routes_local import load_binding
from gtfs_loader import GtfsRepository
from route_engine import RouteContractError
from tokyo_dataset_bus_choices import TokyoBusDatasetBinding
from tokyo_destination_bounds_audit import (
    collect_common_inputs, project_common_graph, verify_destination_case,
)
from tokyo_timetable_choices import TimetableChoices


def destination_manifest(graph):
    """Freeze structural destinations before any bound/reference computation."""
    physical = sorted((node for node in graph if isinstance(node, tuple)
                       and len(node) == 2 and node[0] == "phys"), key=repr)
    by_mode = {}
    for mode in ("bus", "rail"):
        candidates = [node for node in physical if any(
            edge.get("etype") == "board" and graph.nodes[following].get("mode") == mode
            for following, edge in graph[node].items())]
        if not candidates:
            raise RouteContractError("destination manifest lacks structural " + mode + " target")
        by_mode[mode] = candidates[0]
    bus, rail = by_mode["bus"], by_mode["rail"]
    if bus == rail:
        raise RouteContractError("destination manifest requires distinct bus and rail physical targets")
    virtual, missing = ("audit_virtual_destination",), ("audit_missing_virtual_seed",)
    if virtual in graph or missing in graph:
        raise RouteContractError("destination manifest synthetic nodes collide with the Tokyo graph")
    # These distances are audit seeds, not changes to G or a public query.
    return (
        ("bus_physical", bus, {}),
        ("rail_physical", rail, {}),
        ("virtual_multiple", virtual,
         {bus: (0.0, 160.0), rail: (0.0, 80.0), missing: (0.0, 80.0)}),
        ("physical_and_virtual", bus,
         {bus: (0.0, 320.0), rail: (0.0, 80.0), missing: (0.0, 80.0)}),
    )


def inspect(train, stations, railways, gtfs, version, prebuilt):
    with prebuilt.open("rb") as stream:
        pinned = pickle.load(stream)
    if (type(pinned) is not dict or type(pinned.get("G")) is not nx.DiGraph
            or not isinstance(pinned.get("TM"), engine.TimetableManager)):
        raise RouteContractError("trusted prebuilt requires original Tokyo DiGraph and TM; no repair")
    graph, manager = pinned["G"], pinned["TM"]
    manifest = destination_manifest(graph)
    rail_binding = load_binding(train, stations, railways, manager)
    _, _, snapshot, _, _ = load_inputs(gtfs, version, ("2026-09-04",))
    repository = GtfsRepository("tokyo_bus_probe").load_data(str(gtfs))
    bus_binding = TokyoBusDatasetBinding(snapshot, repository)
    inputs = collect_common_inputs(rail_binding, bus_binding, manager, repository)
    # An artificial profile constructs the unchanged static reference only;
    # common and old minima still include ALL source calendars, not this date.
    day = date(2026, 9, 4)
    profile = engine.ServiceDayType("weekday", day, repository.get_active_service_ids(day), True)
    choices = TimetableChoices(graph, manager, day_type=profile, use_realtime=False,
                               deadline=3000, bus_repository=repository)
    cases = {}
    for scope, predicate in (
        ("full_graph", lambda u, v: False),
        ("bus_only_rail_excluded", lambda u, v: engine._edge_uses_rail(graph, u, v)),
    ):
        projection = project_common_graph(graph, choices, inputs.rail, inputs.bus,
                                          edge_uses_rail=predicate)
        for number, (kind, target, seeds) in enumerate(manifest, 1):
            diagnostic = {"scope": scope, "destination_kind": kind,
                          "case_number": number, "mode": "time"}
            print("[DESTINATION_BOUND] " + json.dumps({**diagnostic, "stage": "started"}),
                  file=sys.stderr)
            try:
                cases[scope + "/" + kind] = verify_destination_case(
                    projection, target, seeds, edge_uses_rail=predicate)
            except Exception as error:
                print("[DESTINATION_BOUND] " + json.dumps({
                    **diagnostic, "stage": "stopped", "reason": type(error).__name__,
                }), file=sys.stderr)
                raise
            print("[DESTINATION_BOUND] " + json.dumps({**diagnostic, "stage": "equal"}),
                  file=sys.stderr)
    inputs.check_sources()
    if len(cases) != 8:
        raise RouteContractError("destination bound audit case coverage differs")
    if (cases["full_graph/bus_physical"]["excluded_edges"] != 0
            or cases["bus_only_rail_excluded/bus_physical"]["excluded_edges"] == 0):
        raise RouteContractError("destination bound rail-exclusion coverage differs")
    return {
        "audit_mode": "tokyo_common_static_destination_bounds_and_guard_parity",
        "calendar_scope": "all_source_calendars_no_date_filter",
        "destination_policy": "four_fixed_structural_destinations_v1",
        "destination_count": 4, "case_count": len(cases), "cases": cases,
        "all_node_comparisons": sum(case["all_nodes_compared"] for case in cases.values()),
        "priority_pairs_compared": sum(case["priority_pairs_compared"] for case in cases.values()),
        "common_destination_bounds_verified": True,
        "rounding_guard_equivalence_verified": True,
        "guarded_priority_equivalence_verified": True,
        "conditional_error_coefficients_verified": True,
        "unexpanded_suffix_step_bound_verified": False,
        "unconditional_priority_admissibility_verified": False,
        "real_timetable_suffix_admissibility_verified": False,
        "common_dataset_route_ranking_verified": False,
        "true_top_k_verified": False, "realtime_verified": False,
        "operational_calendar_verified": False,
        "lambda_startup_verified": False,
        "common_bounds_provider": "not_selected_audit_only",
        "graph_provider": "unchanged_pinned_tokyo_graph",
        "mode": "time", **inputs.counts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
        raise RouteContractError("input files changed during destination bound audit")
    check_repository(args.expected_sha)
    print(json.dumps({"sha": args.expected_sha, "python": sys.version,
                      "input_hashes": {**before, **gtfs_before}, **result},
                     ensure_ascii=True, allow_nan=False))
    print("READ_ONLY_TOKYO_COMMON_DESTINATION_BOUNDS_PARITY_OK")


if __name__ == "__main__":
    main()
