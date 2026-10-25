from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import pickle
import subprocess
import sys
import types
from pathlib import Path
from zoneinfo import ZoneInfo


EXPECTED_COMMIT = "be9c9d35f6babbf88f58c6a4f5013322a17b6c36"
JST = ZoneInfo("Asia/Tokyo")


def stable_candidate(candidate: dict) -> dict:
    result = {
        "id": candidate.get("id"),
        "departure_time": candidate.get("departure_time"),
        "arrival_time": candidate.get("arrival_time"),
        "rides": candidate.get("rides"),
        "transfers": candidate.get("transfers"),
        "total": candidate.get("total"),
        "contains_estimated_transfer": False,
        "steps": [],
    }
    for step in candidate.get("steps", []):
        selected = step.get("selected_run")
        stable_run = None
        if isinstance(selected, dict):
            stable_run = {
                key: selected.get(key)
                for key in (
                    "provider", "run_key", "run_id", "service_key", "train_number",
                    "trip_id", "route_id", "service_id", "origin_stop_id",
                    "destination_stop_id", "origin_gtfs_stop_id",
                    "destination_gtfs_stop_id", "scheduled_departure_minute",
                    "scheduled_arrival_minute", "origin_sequence", "destination_sequence",
                )
            }
        result["steps"].append({
            "kind": step.get("kind"),
            "title": step.get("title"),
            "title_en": step.get("title_en"),
            "from": step.get("from_", step.get("from")),
            "from_en": step.get("from_en"),
            "to": step.get("to"),
            "to_en": step.get("to_en"),
            "departure_time": step.get("departure_time"),
            "arrival_time": step.get("arrival_time"),
            "minutes": step.get("minutes"),
            "meters": step.get("meters"),
            "route_id": step.get("route_id"),
            "trip_id": step.get("trip_id"),
            "selected_run": stable_run,
            "stops": [
                {key: stop.get(key) for key in ("id", "odpt_id", "name", "name_en")}
                for stop in step.get("stops", []) if isinstance(stop, dict)
            ],
            "walking_connection_verified": step.get("walking_connection_verified"),
            "walking_time_estimated": step.get("walking_time_estimated"),
        })
    return result


def digest(candidates: list[dict]) -> str:
    encoded = json.dumps(candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run independent pre-Metro Toei baseline")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--app-data", type=Path, required=True)
    parser.add_argument("--bus-gtfs", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    commit = subprocess.run(
        ["git", "-C", str(args.source_root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if commit != EXPECTED_COMMIT:
        parser.error(f"pre-Metro source must be {EXPECTED_COMMIT}, got {commit}")
    sys.path.insert(0, str(args.source_root / "api"))
    import toei_engine as te
    from tokyo_route_engine import TokyoRouteDependencies, TokyoRouteEngine

    with args.app_data.open("rb") as source:
        data = pickle.load(source)
    with contextlib.redirect_stdout(io.StringIO()):
        te.gtfs_repo.load_data(str(args.bus_gtfs))

    graph = data["G"]
    rail_lines = {
        node for node, attrs in graph.nodes(data=True)
        if isinstance(node, tuple) and node and node[0] == "line" and attrs.get("mode") == "rail"
    }
    rail_phys = {
        node for node in graph.nodes
        if isinstance(node, tuple) and node and node[0] == "phys"
        and any(neighbor in rail_lines for neighbor in (*graph.predecessors(node), *graph.successors(node)))
    }
    subway_graph = graph.subgraph(rail_lines | rail_phys).copy()
    subway_state = dict(data)
    subway_state["G"] = subway_graph
    subway_state["SI"] = te.SpatialIndex(subway_graph)

    def engine(state):
        app = types.SimpleNamespace(state=types.SimpleNamespace(**state))
        return TokyoRouteEngine(
            app,
            dependencies=TokyoRouteDependencies(
                now=lambda: dt.datetime(2026, 10, 23, 8, 0, tzinfo=JST)
            ),
        )

    legacy_engine = engine(data)
    subway_engine = engine(subway_state)
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    cases = {
        case["name"]: case for case in corpus["matrix_cases"]
        if "legacy_toei" in case["tags"]
    }
    rows = []
    for case_name in ("toei_bus_only", "toei_subway_only", "toei_bus_and_subway"):
        case = cases[case_name]
        selected_engine = subway_engine if case_name == "toei_subway_only" else legacy_engine
        bus_only = case_name == "toei_bus_only"
        for mode in corpus["fixed_contract"]["modes"]:
            for limit in corpus["fixed_contract"]["candidate_limits"]:
                error = None
                payload = None
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        payload = selected_engine.search_legacy(
                            alat=case["origin"][0], alon=case["origin"][1],
                            blat=case["destination"][0], blon=case["destination"][1],
                            pref=mode, bus_only=bus_only, start_time=case["time"],
                            date_str=case["date"], limit=limit,
                        )
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                candidates = [
                    stable_candidate(candidate)
                    for candidate in ([] if payload is None else payload.get("candidates", []))
                ]
                rows.append({
                    "case": case_name,
                    "mode": mode,
                    "candidate_limit": limit,
                    "error": error,
                    "candidate_count": len(candidates),
                    "candidate_sha256": digest(candidates),
                    "candidates": candidates,
                    "baseline_method": (
                        "pre_metro_public_bus_only" if bus_only else
                        "pre_metro_rail_only_graph_control" if case_name == "toei_subway_only" else
                        "pre_metro_public_bus_and_subway"
                    ),
                })
                print(case_name, mode, limit, error or f"candidates={len(candidates)}", flush=True)

    output = {
        "schema": "pre_metro_toei_baseline/v1",
        "source_commit": commit,
        "subway_only_note": (
            "The pre-Metro public API exposed bus-only and bus+subway. Subway-only is an "
            "independent measurement control using the exact pre-Metro engine and timetable "
            "on an induced graph containing only its rail and rail-station nodes."
        ),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if any(row["error"] for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
