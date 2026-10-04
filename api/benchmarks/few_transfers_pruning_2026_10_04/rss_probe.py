"""Isolated-process RSS and search-budget measurements for corrected Tokyo search.

No network or production writes. The local CSV snapshot is packed and compiled
with the production GTFS compiler, so measurement uses the Lambda loading path.
Windows working set and Linux RSS are reported in bytes, with a query-local
sampled peak distinct from the process-lifetime high-water mark.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import datetime as dt
import gc
import hashlib
import io
import json
import os
from pathlib import Path
import pickle
import platform
import re
import subprocess
import sys
import threading
import time
import types
import zipfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
ASSETS = ROOT / "api/data/search_rss_probe"
sys.path.insert(0, str(ROOT / "api"))
BASE = {
    "alat": 35.708166, "alon": 139.817434,
    "blat": 35.6636842, "blon": 139.6977409,
    "pref": "cost", "bus_only": False,
    "target_date_str": "2026-10-04", "start_time": "20:40", "limit": 5,
}
CASES = {
    "baseline": {},
    "departure_minus_1": {"start_time": "20:39"},
    "departure_plus_1": {"start_time": "20:41"},
    "destination_east_20m": {"blon": BASE["blon"] + 20 / (111320 * 0.8125)},
}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def memory_reader():
    if sys.platform == "win32":
        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong),
                ("peak_rss", ctypes.c_size_t), ("rss", ctypes.c_size_t),
                ("peak_paged_pool", ctypes.c_size_t), ("paged_pool", ctypes.c_size_t),
                ("peak_nonpaged_pool", ctypes.c_size_t), ("nonpaged_pool", ctypes.c_size_t),
                ("commit", ctypes.c_size_t), ("peak_commit", ctypes.c_size_t),
            ]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        handle = kernel.GetCurrentProcess()
        get_memory = psapi.GetProcessMemoryInfo
        get_memory.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
        get_memory.restype = ctypes.c_int

        def read():
            row = Counters()
            row.cb = ctypes.sizeof(row)
            if not get_memory(handle, ctypes.byref(row), row.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            return {"rss_bytes": row.rss, "process_peak_rss_bytes": row.peak_rss,
                    "private_commit_bytes": row.commit, "process_peak_private_commit_bytes": row.peak_commit}
        return read
    if sys.platform.startswith("linux"):
        def read():
            values = {}
            for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
                key, _, value = line.partition(":")
                if key in ("VmRSS", "VmHWM"):
                    values[key] = int(value.split()[0]) * 1024
            return {"rss_bytes": values["VmRSS"], "process_peak_rss_bytes": values["VmHWM"]}
        return read
    raise RuntimeError("RSS probe supports Windows and Linux")


class Sampler:
    def __init__(self, read):
        self.read = read
        self.stop = threading.Event()
        self.peak = 0
        self.samples = 0
        self.max_gap_seconds = 0.0
        self.last = None
        self.error = None

    def sample(self):
        now = time.perf_counter()
        if self.last is not None:
            self.max_gap_seconds = max(self.max_gap_seconds, now - self.last)
        self.last = now
        self.peak = max(self.peak, self.read()["rss_bytes"])
        self.samples += 1

    def loop(self):
        try:
            while not self.stop.wait(0.01):
                self.sample()
        except Exception as error:
            self.error = repr(error)

    def __enter__(self):
        self.sample()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *unused):
        self.stop.set()
        self.thread.join()
        self.sample()


def prepare():
    from gtfs_state import build_compiled_state_from_zip
    ASSETS.mkdir(parents=True, exist_ok=True)
    source = ROOT / "api/data/ToeiBus-GTFS"
    fingerprint = [{"name": path.name, "sha256": sha(path)} for path in sorted(source.glob("*.txt"))]
    manifest_path = ASSETS / "manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (previous.get("csv_files") == fingerprint and (ASSETS / "compiled.pkl.gz").exists()
                and sha(ASSETS / "compiled.pkl.gz") == previous["compiled_sha256"]):
            return previous
    archive_path = ASSETS / "local-snapshot.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.glob("*.txt")):
            archive.write(path, path.name)
    source_sha = sha(archive_path)
    with contextlib.redirect_stdout(io.StringIO()):
        artifact = build_compiled_state_from_zip(
            str(archive_path), source_sha256=source_sha,
            output_path=str(ASSETS / "compiled.pkl.gz"),
        )
    manifest = {"scope": "Local CSV snapshot packed for benchmark; not downloaded from S3 or published.",
                "csv_files": fingerprint, "source_sha256": source_sha,
                "compiled_sha256": artifact.sha256, "record_counts": artifact.record_counts}
    write_json(manifest_path, manifest)
    return manifest


def normalized(payload):
    copy = json.loads(json.dumps(payload))
    for candidate in copy.get("candidates", []):
        for step in candidate.get("steps", []):
            step.pop("step_id", None)
    return copy


def worker(args):
    read = memory_reader()
    phases = {"before_app_imports": read()}
    import toei_engine as te
    from app.route_endpoint import ApiRouteRequest, to_domain_request
    from app.services.train_realtime import StaticTrainGtfs, parse_static_gtfs
    from app.services.train_route_identity import enrich_route_result_train_trip_ids
    from app.services.train_service_calendar import parse_train_service_calendar
    from gtfs_state import load_compiled_state
    from route_engine import serialize_route_result
    from tokyo_route_engine import TokyoRouteDependencies, TokyoRouteEngine
    phases["after_app_imports"] = read()
    prebuilt = ROOT / "api/data/app_data_search_labels.pkl"
    with prebuilt.open("rb") as stream:
        data = pickle.load(stream)
    phases["after_prebuilt_load"] = read()
    manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
    load_compiled_state(te.gtfs_repo, str(ASSETS / "compiled.pkl.gz"), expected_source_sha256=manifest["source_sha256"])
    phases["after_compiled_bus_gtfs_load"] = read()
    archive = ROOT / "api/data/Toei-Train-GTFS.zip"
    content = archive.read_bytes()
    static = parse_static_gtfs(content)
    calendar = parse_train_service_calendar(content)
    del content
    active = calendar.active_trip_ids(dt.date(2026, 10, 4))
    active_static = StaticTrainGtfs({key: trip for key, trip in static.trips.items() if key in active})
    phases["after_train_gtfs_and_calendar_load"] = read()
    gc.collect()
    phases["ready_after_gc"] = read()
    calls = []

    def core(*params, **kwargs):
        started = time.perf_counter()
        try:
            return te.search_best_routes_once(*params, **kwargs)
        finally:
            calls.append((time.perf_counter() - started) * 1000)

    engine = TokyoRouteEngine(types.SimpleNamespace(state=types.SimpleNamespace(
        G=data["G"], TM=data["TM"], SI=data["SI"], WALK_RAD=data["WALK_RAD"],
    )), dependencies=TokyoRouteDependencies(
        search_best_routes_once=core,
        now=lambda: dt.datetime(2026, 10, 4, 18, 40, tzinfo=ZoneInfo("Asia/Tokyo")),
    ))
    body = {**BASE, **CASES[args.case], "pref": args.mode}
    report = {"mode": args.mode, "case": args.case, "request": body,
              "platform": platform.platform(), "python": sys.version,
              "memory_metric": "Windows working set" if sys.platform == "win32" else "Linux VmRSS",
              "scope": "Fresh process per mode/input. Refreshed prebuilt, production compiled GTFS loading, static train GTFS/calendar retained. Each query includes adapter, details, serialization and train identity. No HTTP or live RT.",
              "sampling": "10ms target interval; Python scheduling can miss shorter peaks. Also record exact OS process-lifetime high-water, which can be dominated by startup.",
              "phases": phases, "compiled_bus_gtfs": manifest,
              "sha256": {path.name: sha(path) for path in (
                  prebuilt, archive, ROOT / "api/toei_engine.py", ROOT / "api/tokyo_search_labels.py",
                  ROOT / "api/tokyo_timetable_choices.py", ROOT / "api/app/services/train_route_identity.py")},
              "runs": []}
    reference_path = OUT / f"implementation_{args.mode}_route.json"
    reference = normalized(json.loads(reference_path.read_text(encoding="utf-8")))
    for iteration in range(args.repeats):
        calls.clear()
        log = io.StringIO()
        row = {"iteration": iteration, "before": read()}
        started = time.perf_counter()
        result = payload = None
        with Sampler(read) as sampler, contextlib.redirect_stdout(log):
            try:
                payload = serialize_route_result(engine.search(to_domain_request(ApiRouteRequest(**body))))
                # Identity enrichment also annotates the shared stop objects.
                # Compare the pre-identity payload with the pre-identity
                # reference, before those annotations are added.
                comparable_payload = normalized(payload)
                row["same_as_previous_baseline_excluding_step_ids"] = comparable_payload == reference if args.case == "baseline" else None
                identity_started = time.perf_counter()
                result = enrich_route_result_train_trip_ids(
                    payload, timetable_manager=data["TM"], day_type=te.determine_day_type(body["target_date_str"]),
                    static_gtfs=active_static,
                )
                row["identity_ms"] = (time.perf_counter() - identity_started) * 1000
            except Exception as error:
                row["error"] = f"{type(error).__name__}: {error}"
        row["full_ms"] = (time.perf_counter() - started) * 1000
        row["core_ms"] = sum(calls)
        row["after"] = read()
        row["sampled_query_peak_rss_bytes"] = sampler.peak
        row["query_peak_delta_from_before_bytes"] = sampler.peak - row["before"]["rss_bytes"]
        row["samples"] = sampler.samples
        row["maximum_sample_gap_ms"] = sampler.max_gap_seconds * 1000
        row["sampler_error"] = sampler.error
        row["stats"] = re.findall(r"^\[ROUTE_DEBUG\] (?:cost|time|fewTransfers) stats:.*$", log.getvalue(), re.M)
        if payload is not None:
            row["search_candidates"] = len(payload["candidates"])
            if iteration == 0:
                write_json(OUT / f"rss_{args.mode}_{args.case}_route.json", payload)
        if result is not None:
            row["verified_candidates"] = len(result["candidates"])
            row["rejections"] = result.get("meta", {}).get("train_identity_rejected_candidates", [])
            row["arrivals"] = [candidate["arrival_time"] for candidate in result["candidates"]]
        # A controlled extra GC shows whether live query objects are retained;
        # RSS need not fall if CPython keeps free arenas or allocator pages.
        result = payload = None
        gc.collect()
        row["after_result_release_and_gc"] = read()
        report["runs"].append(row)
        if row.get("error"):
            break
    output = OUT / f"rss_{args.mode}_{args.case}.json"
    write_json(output, report)
    print(args.mode, args.case, [(round(row["sampled_query_peak_rss_bytes"] / 2**20, 1), row.get("verified_candidates"), row.get("error")) for row in report["runs"]], flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--mode", choices=("cost", "time", "fewTransfers"), default="fewTransfers")
    parser.add_argument("--case", choices=tuple(CASES), default="baseline")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--baseline-only", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    if args.worker:
        return worker(args)
    manifest = prepare()
    pairs = [(mode, "baseline") for mode in ("cost", "time", "fewTransfers")]
    if not args.baseline_only:
        pairs.extend((mode, case) for case in CASES if case != "baseline" for mode in ("cost", "fewTransfers"))
    report = {"scope": "Sequential isolated worker processes; local static data; no Lambda RSS inference from Windows values.",
              "created_at_jst": dt.datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
              "compiled_bus_record_counts": manifest["record_counts"], "measurements": []}
    for mode, case in pairs:
        command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--worker", "--mode", mode, "--case", case,
                   "--repeats", str(args.repeats if case == "baseline" else 1)]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if completed.returncode:
            print(completed.stdout, completed.stderr, flush=True)
            raise RuntimeError(f"Worker failed: {mode}/{case}")
        print(completed.stdout.strip(), flush=True)
        output = OUT / f"rss_{mode}_{case}.json"
        report["measurements"].append(json.loads(output.read_text(encoding="utf-8")))
        write_json(OUT / "rss_results.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
