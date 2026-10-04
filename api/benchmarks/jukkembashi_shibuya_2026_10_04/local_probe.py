"""Read-only, static Tokyo search for the user's fixed journey.

Run from the repository root with api/.venv-route/Scripts/python.exe -X utf8.
No network, production writes, or train identity resolution are performed.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import io
import json
import pickle
import platform
import statistics
import sys
import time
import types
from pathlib import Path
from zoneinfo import ZoneInfo

STARTED = time.perf_counter()
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "api"))
import toei_engine as te
from app.route_endpoint import ApiRouteRequest, to_domain_request
from route_engine import serialize_route_result
from tokyo_route_engine import TokyoRouteDependencies, TokyoRouteEngine

JST = ZoneInfo("Asia/Tokyo")
BODY = {
    "alat": 35.708166, "alon": 139.817434,
    "blat": 35.6636842, "blon": 139.6977409,
    "pref": "cost", "bus_only": False,
    "target_date_str": "2026-10-04", "start_time": "20:40", "limit": 5,
}


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def comparable(payload):
    result = json.loads(json.dumps(payload))
    for candidate in result.get("candidates", []):
        for step in candidate.get("steps", []):
            step.pop("step_id", None)
    return result


def main():
    import_ms = (time.perf_counter() - STARTED) * 1000
    load_started = time.perf_counter()
    with (ROOT / "api/data/app_data.pkl").open("rb") as stream:
        data = pickle.load(stream)
    pickle_ms = (time.perf_counter() - load_started) * 1000
    load_started = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        te.gtfs_repo.load_data(str(ROOT / "api/data/ToeiBus-GTFS"))
    gtfs_ms = (time.perf_counter() - load_started) * 1000

    timing_calls = []

    def timed_search(*args, **kwargs):
        started = time.perf_counter()
        info = {
            "use_realtime": kwargs.get("use_realtime"),
            "target_node": list(kwargs["target_node"]),
            "virtual_connections": len(kwargs.get("virtual_dest_connections") or []),
        }
        try:
            result = te.search_best_routes_once(*args, **kwargs)
            info["candidate_count"] = len(result)
            return result
        except Exception as exc:
            info["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            info["ms"] = (time.perf_counter() - started) * 1000
            timing_calls.append(info)

    app = types.SimpleNamespace(state=types.SimpleNamespace(
        G=data["G"], TM=data["TM"], SI=data["SI"], WALK_RAD=data["WALK_RAD"],
    ))
    # Freeze the application clock outside the realtime horizon. This is an
    # explicit offline/static measurement, not an emulation of live RT.
    dependencies = TokyoRouteDependencies(
        search_best_routes_once=timed_search,
        now=lambda: dt.datetime(2026, 10, 4, 18, 40, tzinfo=JST),
    )
    engine = TokyoRouteEngine(app, dependencies=dependencies)
    report = {
        "python": sys.version, "platform": platform.platform(),
        "request": BODY,
        "origin_reference": "GTFS stops.txt 0751-01 十間橋",
        "destination_reference": "渋谷区役所公式map place coordinates !3d35.6636842!4d139.6977409",
        "scope": "Offline/static, no HTTP, no realtime feeds, no train identity resolution. Full_ms includes coordinate setup, detail generation, adapter contract checks, explicit GC, and serialization; core_ms is the nested search_best_routes_once time.",
        "run_order": "cost first+5 warm, time first+5 warm, fewTransfers once, all in one shared process. First means first for that mode; time/fewTransfers already share caches from preceding modes. No claim of OS cold cache or production cold start.",
        "startup_scope": "Imports begin after standard-library setup. Python process launch, report hashing, train GTFS/identity setup, network, and app rendering are excluded.",
        "clock_for_static_policy": "2026-10-04T18:40:00+09:00",
        "startup": {"imports_ms": import_ms, "pickle_load_ms": pickle_ms, "bus_gtfs_load_ms": gtfs_ms},
        "dataset": {"nodes": data["G"].number_of_nodes(), "edges": data["G"].number_of_edges(), "bus_trips": len(te.gtfs_repo.trips)},
        "sha256": {str(path.relative_to(ROOT)): sha(path) for path in (
            ROOT / "api/toei_engine.py", ROOT / "api/tokyo_route_engine.py", ROOT / "api/data/app_data.pkl", ROOT / "api/data/ToeiBus-GTFS/calendar.txt",
        )},
        "modes": [],
    }
    for mode in ("cost", "time", "fewTransfers"):
        mode_row = {"mode": mode, "runs": []}
        reference = None
        for iteration in range(6 if mode != "fewTransfers" else 1):
            body = {**BODY, "pref": mode}
            request = to_domain_request(ApiRouteRequest(**body))
            timing_calls.clear()
            log = io.StringIO()
            row = {"iteration": iteration, "kind": "first_for_mode_in_shared_process" if iteration == 0 else "warm"}
            started = time.perf_counter()
            payload = None
            with contextlib.redirect_stdout(log):
                try:
                    payload = serialize_route_result(engine.search(request))
                except Exception as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
            row["full_ms"] = (time.perf_counter() - started) * 1000
            row["core_calls"] = list(timing_calls)
            row["core_ms"] = sum(call["ms"] for call in timing_calls)
            if payload is not None:
                row["candidate_count"] = len(payload["candidates"])
                row["same_as_first_excluding_step_ids"] = reference is None or comparable(payload) == reference
                if reference is None:
                    reference = comparable(payload)
                    write_json(f"local_{mode}_route.json", payload)
            if iteration == 0:
                (OUT / f"local_{mode}_first.log").write_text(log.getvalue(), encoding="utf-8")
            mode_row["runs"].append(row)
            print(mode, iteration, round(row["full_ms"], 3), row.get("candidate_count"), row.get("error"), flush=True)
            if row.get("error"):
                break
        warm = [row for row in mode_row["runs"] if row["kind"] == "warm"]
        if warm:
            mode_row["warm_summary_ms"] = {
                key: {"median": statistics.median(row[key] for row in warm), "min": min(row[key] for row in warm), "max": max(row[key] for row in warm)}
                for key in ("full_ms", "core_ms")
            }
        report["modes"].append(mode_row)
        write_json("local_results.json", report)
    print("saved", str(OUT / "local_results.json"), flush=True)


if __name__ == "__main__":
    main()
