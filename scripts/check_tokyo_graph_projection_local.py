"""Read-only common bus+rail A* graph-edge projection parity on pinned Tokyo G.

New stage-2 gate only: it does NOT rerun the existing interval equality gates,
OD route samples, destination/node bounds or priority rounding. Never deploys
or selects the common bounds. Requires local source data and trusted prebuilt.
"""
from __future__ import annotations

import argparse
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
from tokyo_bound_projection_audit import verify_static_graph_projection
from tokyo_dataset_bus_choices import TokyoBusDatasetBinding


def inspect(train, stations, railways, gtfs, version, prebuilt):
    with prebuilt.open("rb") as stream:
        pinned = pickle.load(stream)
    if (type(pinned) is not dict or not isinstance(pinned.get("G"), nx.DiGraph)
            or not isinstance(pinned.get("TM"), engine.TimetableManager)):
        raise ValueError("trusted prebuilt requires the original Tokyo G and TM; no repair")
    graph, manager = pinned["G"], pinned["TM"]
    rail_binding = load_binding(train, stations, railways, manager)
    _, dataset, snapshot, _, _ = load_inputs(gtfs, version, ("2026-09-04",))
    repository = GtfsRepository("tokyo_bus_probe").load_data(str(gtfs))
    bus_binding = TokyoBusDatasetBinding(snapshot, repository)

    # Non-OD structural seed selection: the seed sets are fixed before the
    # reference call, and no actual route-search or sample ranking is invoked.
    physical = sorted((node for node in graph if isinstance(node, tuple)
                       and len(node) == 2 and node[0] == "phys"), key=repr)
    if len(physical) < 2:
        raise ValueError("Tokyo graph needs two physical nodes for seed coverage")
    target, virtual = physical[0], physical[1]
    missing = ("audit_missing_virtual_destination",)
    if missing in graph:
        raise ValueError("synthetic missing virtual destination is not missing")
    seeds = {virtual: (0.0, 160.0), missing: (0.0, 80.0)}

    cases = {}
    for name, predicate in (
        ("full_graph", lambda u, v: False),
        ("bus_only_rail_excluded", lambda u, v: engine._edge_uses_rail(graph, u, v)),
    ):
        cases[name] = verify_static_graph_projection(
            graph, manager, repository, rail_binding, bus_binding,
            target=target, virtual_connections=seeds, edge_uses_rail=predicate,
        )
    if cases["full_graph"]["excluded_edges"] != 0:
        raise AssertionError("full graph unexpectedly excluded edges")
    if cases["full_graph"]["rail_rides"] == 0 or cases["full_graph"]["bus_rides"] == 0:
        raise AssertionError("projection never exercised both rail and bus ride edges")
    if cases["bus_only_rail_excluded"]["excluded_edges"] == 0:
        raise AssertionError("bus-only projection never exercised rail exclusion")
    for report in cases.values():
        if (not report["target_in_graph"] or not report["virtual_seed_entries"] == 1
                or report["missing_virtual_nodes"] != 1):
            raise AssertionError("destination graph/virtual seed coverage differs")
    return {
        "audit_mode": "tokyo_common_static_graph_projection",
        "graph_input": "pinned_original_tokyo_graph",
        "calendar_scope": "all_source_calendars_no_date_filter",
        "cases": cases,
        "common_graph_edge_projection_verified": True,
        "common_graph_seed_projection_verified": True,
        "common_bounds_provider": "not_selected_audit_only",
        "graph_and_priority_unmodified": True,
        "destination_bounds_verified": False,
        "priority_rounding_verified": False,
        "common_dataset_route_ranking_verified": False,
        "realtime_verified": False,
        "lambda_startup_verified": False,
        "true_top_k_verified": False,
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
    paths = {k: getattr(args, k).resolve() for k in
             ("train_timetables", "stations", "railways", "trusted_prebuilt")}
    before = {k: sha256(path) for k, path in paths.items()}
    if before["trusted_prebuilt"] != args.expected_prebuilt_sha256.lower():
        raise ValueError("trusted prebuilt SHA-256 mismatch before unpickling")
    gtfs_before = fingerprints(args.gtfs_dir)
    result = inspect(paths["train_timetables"], paths["stations"], paths["railways"],
                     args.gtfs_dir, args.expected_feed_version, paths["trusted_prebuilt"])
    if (before != {k: sha256(path) for k, path in paths.items()}
            or gtfs_before != fingerprints(args.gtfs_dir)):
        raise AssertionError("input files changed during graph projection audit")
    check_repository(args.expected_sha)
    print(json.dumps({
        "sha": args.expected_sha, "python": sys.version,
        "input_hashes": {**before, **gtfs_before}, **result,
    }, ensure_ascii=True))
    print("READ_ONLY_TOKYO_COMMON_GRAPH_PROJECTION_OK")


if __name__ == "__main__":
    main()
