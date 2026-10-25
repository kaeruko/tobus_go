from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import gc
import gzip
import hashlib
import io
import json
import os
import pickle
import platform
import subprocess
import sys
import threading
import time
import types
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hwm_bytes() -> int:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("Linux VmHWM is unavailable")


class RssSampler:
    def __init__(self, process, interval: float = 0.01):
        self.process = process
        self.interval = interval
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self.peak = max(self.peak, int(self.process.memory_info().rss))

    def __enter__(self):
        self.peak = int(self.process.memory_info().rss)
        self._thread.start()
        return self

    def __exit__(self, *_args):
        self._stop.set()
        self._thread.join()
        self.peak = max(self.peak, int(self.process.memory_info().rss))


def stage(process, name: str, started: float, before_rss: int) -> dict:
    rss = int(process.memory_info().rss)
    return {
        "name": name,
        "elapsed_seconds": time.perf_counter() - started,
        "rss_bytes": rss,
        "rss_delta_bytes": rss - before_rss,
        "process_hwm_bytes": hwm_bytes(),
    }


def worker(args) -> int:
    import psutil

    process = psutil.Process()
    stages = [
        {
            "name": "python_worker_entered",
            "elapsed_seconds": 0.0,
            "rss_bytes": int(process.memory_info().rss),
            "rss_delta_bytes": 0,
            "process_hwm_bytes": hwm_bytes(),
        }
    ]

    imports_started = time.perf_counter()
    imports_before = int(process.memory_info().rss)
    sys.path.insert(0, str(args.repo / "api"))
    from zoneinfo import ZoneInfo

    import toei_engine as te
    from tokyo_metro_gtfs import add_tokyo_metro_to_graph
    from tokyo_route_engine import TokyoRouteDependencies, TokyoRouteEngine
    from benchmarks.tokyo_metro_release_2026_10_25.run import (
        candidate_digest,
        coordinates,
        stable_candidate,
        stats_from_log,
    )

    stages.append(stage(process, "application_imports", imports_started, imports_before))

    pickle_started = time.perf_counter()
    pickle_before = int(process.memory_info().rss)
    with args.app_data.open("rb") as source:
        data = pickle.load(source)
    stages.append(stage(process, "base_pickle", pickle_started, pickle_before))

    bus_started = time.perf_counter()
    bus_before = int(process.memory_info().rss)
    with contextlib.redirect_stdout(io.StringIO()):
        te.gtfs_repo.load_data(str(args.bus_gtfs))
    stages.append(stage(process, "toei_bus_gtfs", bus_started, bus_before))

    metro_started = time.perf_counter()
    metro_before = int(process.memory_info().rss)
    with contextlib.redirect_stdout(io.StringIO()):
        feed = add_tokyo_metro_to_graph(
            data["G"],
            data["TM"],
            gtfs_dir=str(args.metro_gtfs),
            stations_path=str(args.metro_stations),
            railways_path=str(args.metro_railways),
            counterpart_stations_path=str(args.toei_stations),
            reviewed_transfers_path=str(args.transfer_manifest),
            walk_radius=data["WALK_RAD"],
        )
    stages.append(stage(process, "tokyo_metro_gtfs_and_graph", metro_started, metro_before))

    engine_started = time.perf_counter()
    engine_before = int(process.memory_info().rss)
    jst = ZoneInfo("Asia/Tokyo")
    app = types.SimpleNamespace(state=types.SimpleNamespace(**data))
    engine = TokyoRouteEngine(
        app,
        dependencies=TokyoRouteDependencies(
            now=lambda: dt.datetime(2026, 10, 23, 8, 0, tzinfo=jst)
        ),
    )
    engine._graph_for_scope(
        frozenset(("toei_bus", "toei_subway", "tokyo_metro")),
        include_estimated_transfers=args.transfer_mode == "estimated",
    )
    stages.append(stage(process, "engine_ready", engine_started, engine_before))
    ready = {
        "transfer_mode": args.transfer_mode,
        "stages": stages,
        "rss_bytes": int(process.memory_info().rss),
        "process_hwm_bytes": hwm_bytes(),
    }
    print("READY\t" + json.dumps(ready, separators=(",", ":")), flush=True)

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    with gzip.open(args.baseline, "rt", encoding="utf-8") as source:
        baseline = json.load(source)["rows"]
    estimated = args.transfer_mode == "estimated"
    expected = {
        (row["case"], row["mode"], row["candidate_limit"]): row
        for row in baseline
        if bool(row["estimated_transfers"]) == estimated
    }
    cases = [
        *(dict(case, _matrix=True) for case in corpus["matrix_cases"]),
        *(dict(case, _matrix=False) for case in corpus["supplemental_cases"]),
    ]
    rows = []
    mismatches = []
    for case in cases:
        limits = (
            corpus["fixed_contract"]["candidate_limits"]
            if case.pop("_matrix")
            else case["candidate_limits"]
        )
        for objective in corpus["fixed_contract"]["modes"]:
            for limit in limits:
                gc.collect()
                before_rss = int(process.memory_info().rss)
                before_hwm = hwm_bytes()
                log = io.StringIO()
                error = None
                payload = None
                started = time.perf_counter()
                with RssSampler(process) as sampler:
                    try:
                        origin = coordinates(data["G"], case, "origin")
                        destination = coordinates(data["G"], case, "destination")
                        with contextlib.redirect_stdout(log):
                            payload = engine.search_legacy(
                                alat=origin[0],
                                alon=origin[1],
                                blat=destination[0],
                                blon=destination[1],
                                pref=objective,
                                transport_scope=frozenset(case["scope"]),
                                include_estimated_transfers=estimated,
                                start_time=case["time"],
                                date_str=case["date"],
                                limit=limit,
                            )
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                elapsed = time.perf_counter() - started
                raw_candidates = [] if payload is None else payload.get("candidates", [])
                candidates = [stable_candidate(candidate) for candidate in raw_candidates]
                stats = stats_from_log(log.getvalue())
                row = {
                    "case": case["name"],
                    "scope": case["scope"],
                    "mode": objective,
                    "candidate_limit": limit,
                    "estimated_transfers": estimated,
                    "elapsed_seconds": elapsed,
                    "error": error,
                    "candidate_count": len(candidates),
                    "candidate_sha256": candidate_digest(candidates),
                    "max_pop": max((item.get("visited", 0) for item in stats), default=0),
                    "max_queue": max((item.get("queue", 0) for item in stats), default=0),
                    "max_retained_labels": max(
                        (item.get("frontier_labels", 0) for item in stats), default=0
                    ),
                    "rss_before_bytes": before_rss,
                    "sampled_peak_rss_bytes": sampler.peak,
                    "rss_after_bytes": int(process.memory_info().rss),
                    "hwm_before_bytes": before_hwm,
                    "hwm_after_bytes": hwm_bytes(),
                }
                rows.append(row)
                key = (case["name"], objective, limit)
                old = expected.pop(key, None)
                if old is None:
                    mismatches.append({"key": key, "reason": "unexpected"})
                else:
                    current_fields = {
                        "error": error,
                        "candidate_count": len(candidates),
                        "candidate_sha256": row["candidate_sha256"],
                        "candidates": candidates,
                    }
                    changed = [
                        field for field, value in current_fields.items() if old[field] != value
                    ]
                    if changed:
                        mismatches.append({"key": key, "fields": changed})
    mismatches.extend({"key": key, "reason": "missing"} for key in expected)
    result = {
        "transfer_mode": args.transfer_mode,
        "feed": {
            "version": feed.version,
            "valid_from": feed.start_date.isoformat(),
            "valid_until": feed.end_date.isoformat(),
        },
        "stages": stages,
        "rows": rows,
        "summary": {
            "rows": len(rows),
            "errors": sum(row["error"] is not None for row in rows),
            "elapsed_over_15_seconds": sum(row["elapsed_seconds"] > 15 for row in rows),
            "pop_limit_hits": sum(row["max_pop"] > 100_000 for row in rows),
            "correctness_mismatches": len(mismatches),
            "max_elapsed_seconds": max(row["elapsed_seconds"] for row in rows),
            "max_pop": max(row["max_pop"] for row in rows),
            "max_sampled_peak_rss_bytes": max(
                row["sampled_peak_rss_bytes"] for row in rows
            ),
            "max_process_hwm_bytes": hwm_bytes(),
        },
        "mismatches": mismatches,
    }
    print("RESULT\t" + json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0 if not mismatches and not result["summary"]["errors"] else 1


def run_worker(args, transfer_mode: str) -> dict:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--transfer-mode",
        transfer_mode,
    ]
    for flag, value in (
        ("--repo", args.repo),
        ("--app-data", args.app_data),
        ("--bus-gtfs", args.bus_gtfs),
        ("--metro-gtfs", args.metro_gtfs),
        ("--metro-stations", args.metro_stations),
        ("--metro-railways", args.metro_railways),
        ("--toei-stations", args.toei_stations),
        ("--transfer-manifest", args.transfer_manifest),
        ("--corpus", args.corpus),
        ("--baseline", args.baseline),
    ):
        command.extend((flag, str(value)))
    started = time.perf_counter()
    child = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    ready = None
    result = None
    assert child.stdout is not None
    for line in child.stdout:
        if line.startswith("READY\t"):
            ready = json.loads(line.split("\t", 1)[1])
            ready["external_process_start_to_ready_seconds"] = time.perf_counter() - started
        elif line.startswith("RESULT\t"):
            result = json.loads(line.split("\t", 1)[1])
    stderr = child.stderr.read() if child.stderr is not None else ""
    return_code = child.wait()
    if return_code != 0 or ready is None or result is None:
        raise RuntimeError(
            f"Linux worker failed mode={transfer_mode} rc={return_code}: {stderr[-2000:]}"
        )
    result["ready"] = ready
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure Phase 4 on local Linux")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--transfer-mode", choices=("ordinary", "estimated"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--app-data", type=Path, required=True)
    parser.add_argument("--bus-gtfs", type=Path, required=True)
    parser.add_argument("--metro-gtfs", type=Path, required=True)
    parser.add_argument("--metro-stations", type=Path, required=True)
    parser.add_argument("--metro-railways", type=Path, required=True)
    parser.add_argument("--toei-stations", type=Path, required=True)
    parser.add_argument("--transfer-manifest", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--metro-archive", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.worker:
        if args.transfer_mode is None:
            raise SystemExit("--transfer-mode is required for --worker")
        return worker(args)
    if args.output is None or args.metro_archive is None:
        raise SystemExit("--output and --metro-archive are required")
    for path in (
        args.repo,
        args.app_data,
        args.bus_gtfs,
        args.metro_gtfs,
        args.metro_stations,
        args.metro_railways,
        args.toei_stations,
        args.transfer_manifest,
        args.corpus,
        args.baseline,
        args.metro_archive,
    ):
        if not path.exists():
            raise SystemExit(f"required input does not exist: {path}")
    ordinary = run_worker(args, "ordinary")
    estimated = run_worker(args, "estimated")
    total_memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    payload = {
        "schema": "tokyo_metro_phase4_linux_measurement/v1",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpu_count": os.cpu_count(),
            "total_memory_bytes": total_memory,
            "measurement": (
                "two fresh sequential worker processes; external monotonic startup-to-ready; "
                "10ms RSS sampling plus Linux VmHWM; local WSL2, not Lambda"
            ),
        },
        "inputs": {
            "app_data_sha256": sha256(args.app_data),
            "metro_archive_sha256": sha256(args.metro_archive),
            "transfer_manifest_sha256": sha256(args.transfer_manifest),
            "phase2_baseline_sha256": sha256(args.baseline),
        },
        "workers": {"ordinary": ordinary, "estimated": estimated},
        "comparison": {
            "startup_to_ready_seconds": {
                mode: result["ready"]["external_process_start_to_ready_seconds"]
                for mode, result in (("ordinary", ordinary), ("estimated", estimated))
            },
            "search_peak_rss_bytes": {
                mode: result["summary"]["max_sampled_peak_rss_bytes"]
                for mode, result in (("ordinary", ordinary), ("estimated", estimated))
            },
            "search_peak_rss_difference_bytes": (
                estimated["summary"]["max_sampled_peak_rss_bytes"]
                - ordinary["summary"]["max_sampled_peak_rss_bytes"]
            ),
            "memory_headroom_bytes": {
                mode: total_memory - result["summary"]["max_process_hwm_bytes"]
                for mode, result in (("ordinary", ordinary), ("estimated", estimated))
            },
            "all_188_rows_match_phase2": (
                ordinary["summary"]["correctness_mismatches"] == 0
                and estimated["summary"]["correctness_mismatches"] == 0
                and ordinary["summary"]["rows"] + estimated["summary"]["rows"] == 188
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
