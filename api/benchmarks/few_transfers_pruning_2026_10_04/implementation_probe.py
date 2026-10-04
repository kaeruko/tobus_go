"""Measure corrected Tokyo labels on the fixed journey, without network access.

Run from the repository root. Historical prototype results are retained.
Train identity enrichment is measured separately by identity_probe.py.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import io
import json
import pickle
import platform
import re
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
    prebuilt = ROOT / "api/data/app_data_search_labels.pkl"
    with prebuilt.open("rb") as stream:
        data = pickle.load(stream)
    pickle_ms = (time.perf_counter() - load_started) * 1000
    load_started = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        te.gtfs_repo.load_data(str(ROOT / "api/data/ToeiBus-GTFS"))
    gtfs_ms = (time.perf_counter() - load_started) * 1000
    calls = []

    def timed_search(*args, **kwargs):
        started = time.perf_counter()
        row = {"use_realtime": kwargs.get("use_realtime")}
        try:
            result = te.search_best_routes_once(*args, **kwargs)
            row["candidate_count"] = len(result)
            return result
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            row["ms"] = (time.perf_counter() - started) * 1000
            calls.append(row)

    app = types.SimpleNamespace(state=types.SimpleNamespace(
        G=data["G"], TM=data["TM"], SI=data["SI"], WALK_RAD=data["WALK_RAD"],
    ))
    engine = TokyoRouteEngine(app, dependencies=TokyoRouteDependencies(
        search_best_routes_once=timed_search,
        now=lambda: dt.datetime(2026, 10, 4, 18, 40, tzinfo=ZoneInfo("Asia/Tokyo")),
    ))
    report = {
        "python": sys.version, "platform": platform.platform(), "request": BODY,
        "scope": "Offline/static Tokyo adapter, details and serialization; no HTTP, live RT or train identity enrichment. Search uses concrete services from refreshed prebuilt rail records and bus GTFS.",
        "run_order": "cost, time, fewTransfers; each once plus one warm repeat on success in one shared process. First-for-mode includes previously populated caches; no production cold-start claim.",
        "clock_for_static_policy": "2026-10-04T18:40:00+09:00",
        "startup_ms": {"imports": import_ms, "pickle_load": pickle_ms, "bus_gtfs_load": gtfs_ms},
        "dataset": {"nodes": data["G"].number_of_nodes(), "edges": data["G"].number_of_edges(), "bus_trips": len(te.gtfs_repo.trips)},
        "sha256": {str(path.relative_to(ROOT)): sha(path) for path in (
            ROOT / "api/toei_engine.py", ROOT / "api/tokyo_search_labels.py",
            ROOT / "api/tokyo_timetable_choices.py", prebuilt,
            ROOT / "api/data/ToeiBus-GTFS/calendar.txt",
        )},
        "modes": [],
    }
    for mode in ("cost", "time", "fewTransfers"):
        mode_row = {"mode": mode, "runs": []}
        first = None
        for iteration in range(2):
            calls.clear()
            log = io.StringIO()
            row = {"iteration": iteration, "kind": "first_for_mode" if iteration == 0 else "warm"}
            started = time.perf_counter()
            payload = None
            with contextlib.redirect_stdout(log):
                try:
                    request = to_domain_request(ApiRouteRequest(**{**BODY, "pref": mode}))
                    payload = serialize_route_result(engine.search(request))
                except Exception as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
            row["full_ms"] = (time.perf_counter() - started) * 1000
            row["core_calls"] = list(calls)
            row["core_ms"] = sum(call["ms"] for call in calls)
            row["stats"] = re.findall(r"^\[ROUTE_DEBUG\] (?:cost|time|fewTransfers) stats:.*$", log.getvalue(), re.M)
            if payload is not None:
                row["candidate_count"] = len(payload["candidates"])
                row["same_as_first_excluding_step_ids"] = first is None or comparable(payload) == first
                row["candidates"] = [{
                    key: candidate.get(key) for key in (
                        "arrival_time", "total_time", "transfers", "walking_distance_meters", "lines",
                    )
                } for candidate in payload["candidates"]]
                if first is None:
                    first = comparable(payload)
                    write_json(f"implementation_{mode}_route.json", payload)
            if iteration == 0:
                (OUT / f"implementation_{mode}_first.log").write_text(log.getvalue(), encoding="utf-8")
            mode_row["runs"].append(row)
            print(mode, iteration, round(row["full_ms"], 3), row.get("candidate_count"), row.get("error"), flush=True)
            if row.get("error"):
                break
        report["modes"].append(mode_row)
        write_json("implementation_results.json", report)
    print("saved", str(OUT / "implementation_results.json"), flush=True)


if __name__ == "__main__":
    main()
