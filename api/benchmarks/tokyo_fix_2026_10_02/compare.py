"""Compare the committed Tokyo engine with the current implementation offline.

Uses one loaded graph/GTFS dataset. Both source versions execute in independent
modules and the timetable object's class is switched before each measurement.
No source substitutions or application-source writes are performed.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import gc
import hashlib
import io
import json
import pickle
import statistics
import subprocess
import sys
import time
import types
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "api"))
import toei_engine as current

MODES = ["time", "cost", "fewTransfers"]
CASES = [
    {"id": "tokyo_toyosu", "origin": [35.681236, 139.767125], "destination": [35.6544, 139.7965]},
    {"id": "shinjuku_asakusa", "origin": [35.690921, 139.700258], "destination": [35.71165, 139.79662]},
    {"id": "tokyo_toyosu_bus_only", "origin": [35.681236, 139.767125], "destination": [35.6544, 139.7965], "bus_only": True},
]
JST = ZoneInfo("Asia/Tokyo")


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_baseline(ref):
    source = subprocess.check_output(["git", "show", f"{ref}:api/toei_engine.py"], cwd=ROOT)
    baseline = types.ModuleType("tokyo_benchmark_baseline")
    baseline.__file__ = str(ROOT / "api/toei_engine.py")
    sys.modules[baseline.__name__] = baseline
    exec(compile(source, baseline.__file__, "exec"), baseline.__dict__)
    return baseline, hashlib.sha256(source).hexdigest()


def load_data():
    started = time.perf_counter()
    with (ROOT / "api/data/app_data.pkl").open("rb") as stream:
        data = pickle.load(stream)
    load_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    current.gtfs_repo.load_data(str(ROOT / "api/data/ToeiBus-GTFS"))
    return data, load_ms, (time.perf_counter() - started) * 1000


def prepare(module, data, case):
    origin, _ = module.nearest_phys(data["G"], *case["origin"], spatial_index=data["SI"])
    target, connections = module.get_virtual_connections(
        data["G"], *case["destination"], walk_radius=module.MAX_WALK_SEG_M,
        spatial_index=data["SI"],
    )
    date = case.get("date", "2026-10-02")
    return {
        "a_phys": origin,
        "target_node": target,
        "virtual_dest_connections": connections,
        "target_coords": case["destination"],
        "start_time": case.get("time", "10:00"),
        "target_date_str": date,
        "day_type": module.determine_day_type(date),
        "use_realtime": case.get("use_realtime", False),
        "bus_only": case.get("bus_only", False),
        "limit": 5,
    }


def run_core(module, data, case, mode):
    data["TM"].__class__ = module.TimetableManager
    kwargs = prepare(module, data, case)
    captured = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(captured):
        routes = module.search_best_routes_once(data["G"], data["TM"], mode=mode, **kwargs)
    return {"ms": (time.perf_counter() - started) * 1000, "routes": routes}


def comparable_adapter(payload):
    value = json.loads(json.dumps(payload))
    for candidate in value.get("candidates", []):
        for step in candidate.get("steps", []):
            step.pop("step_id", None)
    return value


def run_adapter(module, data, case, mode):
    from route_engine import GeoPoint, RouteSearchRequest, normalize_route_preference, serialize_route_result
    from tokyo_route_engine import TokyoRouteDependencies, TokyoRouteEngine

    data["TM"].__class__ = module.TimetableManager
    app = types.SimpleNamespace(state=types.SimpleNamespace(
        G=data["G"], TM=data["TM"], SI=data["SI"], WALK_RAD=data["WALK_RAD"],
    ))
    deps = TokyoRouteDependencies(
        nearest_phys=module.nearest_phys,
        haversine=module.haversine,
        get_virtual_connections=module.get_virtual_connections,
        search_best_routes_once=module.search_best_routes_once,
        time_str_to_min=module.time_str_to_min,
        min_to_time_str=module.min_to_time_str,
        determine_day_type=module.determine_day_type,
        rss_mb=module._rss_mb,
        now=lambda: datetime.datetime(2026, 1, 1, tzinfo=JST),
    )
    engine = TokyoRouteEngine(app, dependencies=deps)
    request = RouteSearchRequest(
        GeoPoint(*case["origin"]), GeoPoint(*case["destination"]),
        datetime.datetime(2026, 10, 2, 10, 0, tzinfo=JST),
        normalize_route_preference(mode), limit=5,
    )
    original_collect = gc.collect
    gc_times = []

    def collect(*args, **kwargs):
        started = time.perf_counter()
        collected = original_collect(*args, **kwargs)
        gc_times.append({"ms": (time.perf_counter() - started) * 1000, "collected": collected})
        return collected

    captured = io.StringIO()
    gc.collect = collect
    started = time.perf_counter()
    try:
        with contextlib.redirect_stdout(captured):
            routes = serialize_route_result(engine.search(request))
    finally:
        gc.collect = original_collect
    return {"ms": (time.perf_counter() - started) * 1000, "routes": routes, "gc": gc_times}


def compare_rows(variants, data, cases, runner, output, section, repetitions=3):
    for case in cases:
        for mode in MODES:
            # Warm both versions independently before collecting timings.
            reference = runner(variants["baseline"], data, case, mode)
            new_reference = runner(variants["current"], data, case, mode)
            canonical = comparable_adapter if runner is run_adapter else lambda value: value
            assert canonical(reference["routes"]) == canonical(new_reference["routes"]), (case["id"], mode, "warmup mismatch")
            values = {name: [] for name in variants}
            checks = []
            for iteration in range(repetitions):
                ordered = list(variants)
                if iteration % 2:
                    ordered.reverse()
                for name in ordered:
                    measured = runner(variants[name], data, case, mode)
                    same = canonical(measured["routes"]) == canonical(reference["routes"])
                    checks.append({"iteration": iteration, "variant": name, "same_payload": same, "gc": measured.get("gc", [])})
                    values[name].append(measured["ms"])
                    assert same, (case["id"], mode, iteration, name, "payload mismatch")
            medians = {name: statistics.median(times) for name, times in values.items()}
            routes = reference["routes"]
            count = len(routes.get("candidates", [])) if isinstance(routes, dict) else len(routes)
            row = {
                "id": case["id"], "mode": mode, "route_count": count,
                "times_ms": values, "median_ms": medians,
                "reduction_percent": (1 - medians["current"] / medians["baseline"]) * 100,
                "checks": checks,
            }
            output[section].append(row)
            write(output["output_path"], {k: v for k, v in output.items() if k != "output_path"})
            print(section.upper(), case["id"], mode, "routes", count, {k: round(v, 3) for k, v in medians.items()}, "reduction", round(row["reduction_percent"], 1), "identical", True, flush=True)


def main():
    parser = argparse.ArgumentParser()
    manifest = json.loads((OUT / "baseline_manifest.json").read_text(encoding="utf-8"))
    parser.add_argument("--baseline-ref", default=manifest["commit"])
    parser.add_argument("--output", type=Path, default=OUT / "comparison.json")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite existing results: {args.output}")
    baseline, baseline_hash = load_baseline(args.baseline_ref)
    data, load_ms, gtfs_load_ms = load_data()
    variants = {"baseline": baseline, "current": current}
    output = {
        "output_path": args.output,
        "baseline_ref": args.baseline_ref,
        "baseline_sha256": baseline_hash,
        "current_sha256": hashlib.sha256((ROOT / "api/toei_engine.py").read_bytes()).hexdigest(),
        "python": sys.version,
        "load_ms": load_ms,
        "gtfs_load_ms": gtfs_load_ms,
        "gtfs_trips": len(current.gtfs_repo.trips),
        "pickle_bytes": (ROOT / "api/data/app_data.pkl").stat().st_size,
        "pickle_sha256": hashlib.sha256((ROOT / "api/data/app_data.pkl").read_bytes()).hexdigest(),
        "nodes": data["G"].number_of_nodes(), "edges": data["G"].number_of_edges(),
        "note": "Offline shared graph and static GTFS. No HTTP or network access. Both source versions loaded into separate modules; TimetableManager class switched before each call. Each measured condition warmed in both versions, then three alternating paired runs. Core timings exclude coordinate preparation and explicit GC. Adapter timings include coordinate preparation, validation, serialization and unchanged explicit GC. Full payload compared; only adapter step_id UUIDs removed. Additional weekend/realtime cases compare one paired iteration each.",
        "core": [], "adapter": [], "equivalence": [],
    }
    print("DATA", output["nodes"], output["edges"], "load_ms", round(load_ms, 3), flush=True)
    compare_rows(variants, data, CASES, run_core, output, "core")
    compare_rows(variants, data, [CASES[1]], run_adapter, output, "adapter")

    # Exercise static Saturday routing and live delay handling using the same
    # real graph with deterministic injected realtime values (no live feed).
    weekend = dict(CASES[1], id="shinjuku_asakusa_saturday", date="2026-10-03")
    compare_rows(variants, data, [weekend], run_core, output, "equivalence", repetitions=1)
    tm = data["TM"]
    tm.bus_realtime_delays = {
        attrs.get("route_id"): 7.0
        for _, attrs in data["G"].nodes(data=True)
        if attrs.get("mode") == "bus" and attrs.get("route_id")
    }
    tm.realtime_delays = {
        pattern["train_num"]: 360
        for patterns in tm.train_patterns_weekday.values()
        for pattern in patterns if pattern.get("train_num")
    }
    realtime = dict(CASES[1], id="shinjuku_asakusa_realtime_delayed", use_realtime=True)
    output["realtime_injection"] = {
        "bus_route_delays": len(tm.bus_realtime_delays), "bus_delay_minutes": 7.0,
        "train_delays": len(tm.realtime_delays), "train_delay_seconds": 360,
    }
    compare_rows(variants, data, [realtime], run_core, output, "equivalence", repetitions=1)
    write(args.output, {k: v for k, v in output.items() if k != "output_path"})


if __name__ == "__main__":
    main()
