"""Read-only Tokyo performance investigation; leaves application code unchanged.

Run from the repository root with api/.venv-route/Scripts/python.exe -X utf8.
The installed ODPT pickle is used as supplied. No external requests are made.
"""
from __future__ import annotations

import argparse
import bisect
import contextlib
import cProfile
import datetime
import functools
import gc
import inspect
import io
import json
import pickle
import pstats
import statistics
import sys
import time
import textwrap
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "api"))
import toei_engine as te

CASES = [
    {"id": "tokyo_toyosu", "origin": [35.681236, 139.767125], "destination": [35.6544, 139.7965]},
    {"id": "shinjuku_asakusa", "origin": [35.690921, 139.700258], "destination": [35.71165, 139.79662]},
]
MODES = ["time", "cost", "fewTransfers"]


def write_json(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def load_data():
    started = time.perf_counter()
    with (ROOT / "api/data/app_data.pkl").open("rb") as stream:
        data = pickle.load(stream)
    pickle_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    te.gtfs_repo.load_data(str(ROOT / "api/data/ToeiBus-GTFS"))
    data["_gtfs_load_ms"] = (time.perf_counter() - started) * 1000
    return data, pickle_ms


def prepare(data, case):
    g, si = data["G"], data["SI"]
    origin, distance = te.nearest_phys(g, *case["origin"], spatial_index=si)
    target, connections = te.get_virtual_connections(g, *case["destination"], walk_radius=te.MAX_WALK_SEG_M, spatial_index=si)
    return {
        "a_phys": origin,
        "target_node": target,
        "virtual_dest_connections": connections,
        "target_coords": case["destination"],
        "start_time": "10:00",
        "target_date_str": "2026-10-02",
        "day_type": te.determine_day_type("2026-10-02"),
        "use_realtime": False,
        "bus_only": case.get("bus_only", False),
        "limit": 5,
    }


def run(data, case, mode, profiler=None):
    args = prepare(data, case)
    captured = io.StringIO()
    started = time.perf_counter()
    error = None
    routes = None
    with contextlib.redirect_stdout(captured):
        if profiler:
            profiler.enable()
        try:
            routes = te.search_best_routes_once(data["G"], data["TM"], mode=mode, **args)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if profiler:
                profiler.disable()
    elapsed = (time.perf_counter() - started) * 1000
    return {"id": case["id"], "mode": mode, "ms": elapsed, "route_count": len(routes or []), "error": error, "log": captured.getvalue(), "routes": routes}


def baseline(data, load_ms):
    result = {
        "python": sys.version,
        "pickle_bytes": (ROOT / "api/data/app_data.pkl").stat().st_size,
        "load_ms": load_ms,
        "gtfs_load_ms": data["_gtfs_load_ms"],
        "gtfs_trips": len(te.gtfs_repo.trips),
        "nodes": data["G"].number_of_nodes(),
        "edges": data["G"].number_of_edges(),
        "note": "Offline local ODPT pickle and GTFS loaded, static 2026-10-02 weekday 10:00, engine layer (not HTTP). Logs captured in memory; stdout I/O excluded. No train/bus realtime data. Coordinate preparation and TokyoRouteEngine adapter/GC excluded.",
        "cases": CASES,
        "runs": [],
    }
    for case in CASES:
        for mode in MODES:
            row = run(data, case, mode)
            result["runs"].append(row)
            write_json("baseline.json", result)
            print("BASELINE", row["id"], mode, round(row["ms"], 3), row["route_count"], row["error"], flush=True)
    succeeded = [row for row in result["runs"] if row["routes"] and not row["error"]]
    for row in sorted(succeeded, key=lambda row: row["ms"], reverse=True)[:2]:
        case = next(case for case in CASES if case["id"] == row["id"])
        profiler = cProfile.Profile()
        measured = run(data, case, row["mode"], profiler)
        stats = pstats.Stats(profiler)
        stat_rows = []
        for (filename, line, function), (primitive, calls, own, cumulative, callers) in stats.stats.items():
            stat_rows.append({"file": filename, "line": line, "function": function, "calls": calls, "own_ms": own * 1000, "cumulative_ms": cumulative * 1000})
        stat_rows.sort(key=lambda item: item["cumulative_ms"], reverse=True)
        name = f"profile_{row['id']}_{row['mode']}"
        write_json(name + ".json", {"run": measured, "same_routes": measured["routes"] == row["routes"], "stats": stat_rows})
        buffer = io.StringIO()
        pstats.Stats(profiler, stream=buffer).sort_stats("cumulative").print_stats(35)
        (OUT / (name + ".txt")).write_text(buffer.getvalue(), encoding="utf-8")
        print("PROFILE", row["id"], row["mode"], round(measured["ms"], 3), measured["error"], flush=True)
    return result


def install_static_train_index(tm):
    original = tm.get_next_train_arrival
    index = {}
    for day, mapping in (("weekday", tm.train_patterns_weekday), ("weekend", tm.train_patterns_weekend)):
        for station, rows in mapping.items():
            by_next = {}
            for row in rows:
                by_next.setdefault(row["next_sta"], []).append(row)
            for next_station, next_rows in by_next.items():
                departures = [row["dep"] for row in next_rows]
                index[(day, station, next_station)] = (next_rows, departures, departures == sorted(departures))

    def indexed(self, current_sta, next_sta, current_time_min, day_type="weekday", delays_snapshot=None, use_realtime=True):
        if use_realtime:
            return original(current_sta, next_sta, current_time_min, day_type=day_type, delays_snapshot=delays_snapshot, use_realtime=True)
        day = "weekday" if day_type == "weekday" else "weekend"
        rows, departures, ordered = index.get((day, current_sta, next_sta), ([], [], True))
        if ordered:
            position = bisect.bisect_left(departures, current_time_min)
            return rows[position]["arr"] if position < len(rows) else None
        return next((row["arr"] for row in rows if row["dep"] >= current_time_min), None)

    tm.get_next_train_arrival = types.MethodType(indexed, tm)
    return original, index


def experiment(data):
    base = json.loads((OUT / "baseline.json").read_text(encoding="utf-8"))
    results = []
    started = time.perf_counter()
    original, index = install_static_train_index(data["TM"])
    index_ms = (time.perf_counter() - started) * 1000
    indexed = data["TM"].get_next_train_arrival
    print("INDEX", round(index_ms, 3), "pairs", len(index), "unsorted", sum(not value[2] for value in index.values()), flush=True)
    for case in CASES:
        for mode in MODES:
            reference = next(row for row in base["runs"] if row["id"] == case["id"] and row["mode"] == mode)
            if reference["error"]:
                continue
            values = {"baseline": [], "static_train_index": []}
            checks = []
            for iteration in range(3):
                for variant, function in (("baseline", original), ("static_train_index", indexed)):
                    data["TM"].get_next_train_arrival = function
                    measured = run(data, case, mode)
                    values[variant].append(measured["ms"])
                    checks.append({"iteration": iteration, "variant": variant, "same_routes": json.loads(json.dumps(measured["routes"])) == reference["routes"], "error": measured["error"]})
            row = {"id": case["id"], "mode": mode, "times_ms": values, "median_ms": {key: statistics.median(value) for key, value in values.items()}, "checks": checks}
            row["speedup"] = row["median_ms"]["baseline"] / row["median_ms"]["static_train_index"]
            results.append(row)
            write_json("static_train_index.json", {"index_build_ms": index_ms, "index_pairs": len(index), "results": results})
            print("EXPERIMENT", case["id"], mode, row["median_ms"], "speedup", round(row["speedup"], 3), "identical", all(check["same_routes"] for check in checks), flush=True)
    data["TM"].get_next_train_arrival = original
    return results


def compile_function(source, name):
    namespace = {}
    exec(compile(textwrap.dedent(source), f"<benchmark variant {name}>", "exec"), te.__dict__, namespace)
    return namespace[name]


def install_variant(originals, options):
    """Install copied functions in memory; application source files stay intact."""
    for name, function in originals.items():
        setattr(te, name, function)
    te._bench_lru_cache = functools.lru_cache
    if "edge" in options:
        source = inspect.getsource(originals["advance_time"])
        old = '''    if G.has_edge(u, v):
        edge = G.edges[u, v]
        etype = edge.get("etype")
        meters = edge.get("meters", 0)
    else:
        return curr_time '''
        new = '''    edge = kwargs.get("_edge")
    if edge is None:
        if not G.has_edge(u, v):
            return curr_time
        edge = G.edges[u, v]
    etype = edge.get("etype")
    meters = edge.get("meters", 0)'''
        assert old in source
        te.advance_time = compile_function(source.replace(old, new), "advance_time")
    if "env" in options:
        source = inspect.getsource(originals["get_next_bus_departure"])
        source = source.replace('os.getenv("DEBUG_BUS", "0")', repr(te.os.getenv("DEBUG_BUS", "0")))
        te.TimetableManager.get_next_bus_departure = compile_function(source, "get_next_bus_departure")
    else:
        te.TimetableManager.get_next_bus_departure = originals["get_next_bus_departure"]
    for name in ("find_fastest_path", "find_paths_generator", "find_few_transfers_paths_generator"):
        source = inspect.getsource(originals[name])
        if "edge" in options:
            old = "        for v in G[u]:\n            edge = G[u][v]"
            assert old in source
            source = source.replace(old, "        for v, edge in G[u].items():")
            source = source.replace("                use_realtime=use_realtime,\n", "                use_realtime=use_realtime,\n                _edge=edge,\n")
        if "heuristic" in options and name == "find_paths_generator":
            source = source.replace("    def heuristic(n):", "    @_bench_lru_cache(maxsize=None)\n    def heuristic(n):")
        if "precheck" in options:
            insertion = '            next_time = advance_time(\n'
            if name == "find_fastest_path":
                guard = '''            if etype == "walk":
                step_m = meters if meters > 0 else 1.0
                if seg_walk + step_m > MAX_WALK_SEG_M or total_walk + step_m > MAX_TOTAL_WALK_M:
                    continue
'''
            else:
                key = "(v, tentative_bucket, boardings + (1 if edge.get('etype') == 'board' else 0))" if name == "find_few_transfers_paths_generator" else "(v, tentative_bucket)"
                guard = '''            tentative_seg = 0.0
            if edge.get("etype") == "walk":
                step_m = meters if meters > 0 else 1.0
                tentative_seg = seg_walk_m + step_m
                if tentative_seg > MAX_WALK_SEG_M or total_walk_m + step_m > MAX_TOTAL_WALK_M:
                    continue
            tentative_bucket = int(tentative_seg // 25)
            tentative_key = KEY_PLACEHOLDER
            if cost + w >= g_score.get(tentative_key, float('inf')):
                continue
'''.replace("KEY_PLACEHOLDER", key)
            assert insertion in source
            source = source.replace(insertion, guard + insertion)
        setattr(te, name, compile_function(source, name))


def fast_experiment(data):
    names = ["advance_time", "find_fastest_path", "find_paths_generator", "find_few_transfers_paths_generator"]
    originals = {name: getattr(te, name) for name in names}
    originals["get_next_bus_departure"] = te.TimetableManager.get_next_bus_departure
    variants = {
        "baseline": set(),
        "edge": {"edge"},
        "precheck": {"precheck"},
        "heuristic_env": {"heuristic", "env"},
        "combined": {"edge", "precheck", "heuristic", "env"},
    }
    cases = CASES + [dict(CASES[0], id="tokyo_toyosu_bus_only", bus_only=True)]
    rows = []
    for case in cases:
        for mode in MODES:
            install_variant(originals, set())
            reference = run(data, case, mode)
            values = {variant: [] for variant in variants}
            checks = []
            for iteration in range(3):
                # Rotate the order to distribute warm-state and allocator effects.
                ordered = list(variants)
                ordered = ordered[iteration:] + ordered[:iteration]
                for variant in ordered:
                    install_variant(originals, variants[variant])
                    measured = run(data, case, mode)
                    values[variant].append(measured["ms"])
                    checks.append({"iteration": iteration, "variant": variant, "same_routes": measured["routes"] == reference["routes"], "error": measured["error"]})
            row = {"id": case["id"], "mode": mode, "route_count": reference["route_count"], "times_ms": values, "median_ms": {key: statistics.median(value) for key, value in values.items()}, "checks": checks}
            row["speedup"] = {key: row["median_ms"]["baseline"] / value for key, value in row["median_ms"].items()}
            rows.append(row)
            write_json("fast_variants.json", {"variants": {key: sorted(value) for key, value in variants.items()}, "note": "Each mode/case warmed once and all variant orders rotated across three measured iterations. Full Python route dictionaries including path compared in memory. Baseline/variants share the loaded static timetable and graph. DEBUG_BUS snapshot fixed for each variant install.", "results": rows})
            print("FAST_VARIANTS", case["id"], mode, "routes", row["route_count"], {key: round(value, 3) for key, value in row["median_ms"].items()}, "identical", all(check["same_routes"] for check in checks), flush=True)
    install_variant(originals, variants["combined"])
    profiler = cProfile.Profile()
    measured = run(data, CASES[1], "fewTransfers", profiler)
    buffer = io.StringIO()
    pstats.Stats(profiler, stream=buffer).sort_stats("cumulative").print_stats(40)
    (OUT / "profile_combined_shinjuku_asakusa_fewTransfers.txt").write_text(buffer.getvalue(), encoding="utf-8")
    write_json("profile_combined_shinjuku_asakusa_fewTransfers.json", {"run": measured})
    install_variant(originals, set())
    return rows


def adapter_experiment(data):
    from route_engine import GeoPoint, RouteSearchRequest, normalize_route_preference, serialize_route_result
    from tokyo_route_engine import TokyoRouteDependencies, TokyoRouteEngine
    from zoneinfo import ZoneInfo

    names = ["advance_time", "find_fastest_path", "find_paths_generator", "find_few_transfers_paths_generator"]
    originals = {name: getattr(te, name) for name in names}
    originals["get_next_bus_departure"] = te.TimetableManager.get_next_bus_departure
    app = types.SimpleNamespace(state=types.SimpleNamespace(G=data["G"], TM=data["TM"], SI=data["SI"], WALK_RAD=data["WALK_RAD"]))
    zone = ZoneInfo("Asia/Tokyo")
    # Freeze now so every request is clearly outside the realtime horizon.
    engine = TokyoRouteEngine(app, dependencies=TokyoRouteDependencies(now=lambda: datetime.datetime(2026, 1, 1, tzinfo=zone)))
    case = CASES[1]
    rows = []
    original_collect = gc.collect

    def comparable(payload):
        if payload is None:
            return None
        canonical = json.loads(json.dumps(payload))
        for candidate in canonical.get("candidates", []):
            for step in candidate.get("steps", []):
                # Step UUIDs are deliberately new for every API request.
                step.pop("step_id", None)
        return canonical

    def measure(mode, skip_gc):
        request = RouteSearchRequest(GeoPoint(*case["origin"]), GeoPoint(*case["destination"]), datetime.datetime(2026, 10, 2, 10, 0, tzinfo=zone), normalize_route_preference(mode), limit=5)
        gc_times = []

        def collect(*args, **kwargs):
            started = time.perf_counter()
            collected = 0 if skip_gc else original_collect(*args, **kwargs)
            gc_times.append({"ms": (time.perf_counter() - started) * 1000, "collected": collected, "skipped": skip_gc})
            return collected

        captured = io.StringIO()
        gc.collect = collect
        started = time.perf_counter()
        error = None
        routes = None
        try:
            with contextlib.redirect_stdout(captured):
                routes = serialize_route_result(engine.search(request))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            gc.collect = original_collect
        return {"ms": (time.perf_counter() - started) * 1000, "routes": routes, "error": error, "gc": gc_times, "log": captured.getvalue()}

    variants = {"baseline": set(), "combined": {"edge", "precheck", "heuristic", "env"}, "combined_no_forced_gc": {"edge", "precheck", "heuristic", "env"}}
    for mode in MODES:
        install_variant(originals, set())
        reference = measure(mode, False)
        values = {key: [] for key in variants}
        checks = []
        for iteration in range(3):
            ordered = list(variants)
            ordered = ordered[iteration:] + ordered[:iteration]
            for variant in ordered:
                install_variant(originals, variants[variant])
                measured = measure(mode, variant == "combined_no_forced_gc")
                values[variant].append(measured["ms"])
                checks.append({"iteration": iteration, "variant": variant, "same_routes": comparable(measured["routes"]) == comparable(reference["routes"]), "error": measured["error"], "gc": measured["gc"]})
        row = {"id": case["id"], "mode": mode, "route_count": len((reference["routes"] or {}).get("candidates", [])), "reference_error": reference["error"], "times_ms": values, "median_ms": {key: statistics.median(value) for key, value in values.items()}, "checks": checks}
        rows.append(row)
        write_json("adapter_variants.json", {"note": "Full TokyoRouteEngine.search plus serialize_route_result; coordinate preparation, validation and explicit GC included. Every payload field except intentionally randomized UUID step_id compared. Logs captured, local static data, three rotating paired iterations after reference warmup. GC skip is diagnostic only: repeated-request memory/peak Lambda memory not tested.", "results": rows})
        print("ADAPTER", case["id"], mode, "routes", row["route_count"], "error", row["reference_error"], {key: round(value, 3) for key, value in row["median_ms"].items()}, "identical", all(check["same_routes"] for check in checks), flush=True)
    install_variant(originals, set())
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["baseline", "experiment", "fast", "adapter", "all"], default="all")
    args = parser.parse_args()
    data, load_ms = load_data()
    print("DATA", data["G"].number_of_nodes(), data["G"].number_of_edges(), "load_ms", round(load_ms, 3), flush=True)
    if args.stage in ("baseline", "all"):
        baseline(data, load_ms)
    if args.stage in ("experiment", "all"):
        experiment(data)
    if args.stage in ("fast", "all"):
        fast_experiment(data)
    if args.stage in ("adapter", "all"):
        adapter_experiment(data)


if __name__ == "__main__":
    main()
