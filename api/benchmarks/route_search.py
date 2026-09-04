from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import platform
import sys
import tracemalloc
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Sequence

from tests.test_route_search_golden import load_golden_fixture
from search_core_factory import create_search_core
from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata, TransitDataset, namespace_id
from transit_engine import BatchSearchRequest, SearchEndpoint


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    index = max(
        0,
        min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1),
    )
    return ordered[index]


def _process_rss_bytes() -> int | None:
    if sys.platform.startswith("linux"):
        try:
            resident_pages = int(
                Path("/proc/self/statm").read_text(encoding="ascii").split()[1]
            )
            return resident_pages * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            return None
    if sys.platform == "win32":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("page_fault_count", ctypes.c_ulong),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        process = ctypes.windll.kernel32.GetCurrentProcess()
        get_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        get_memory_info.restype = ctypes.c_int
        if not get_memory_info(
            process,
            ctypes.byref(counters),
            counters.cb,
        ):
            return None
        return counters.working_set_size
    return None


def _endpoint(feed_id: str, row: list[Any], rank: int) -> SearchEndpoint:
    source_id, walk_minutes, walk_meters = row
    return SearchEndpoint(
        stop_id=namespace_id(feed_id, source_id),
        walk_minutes=walk_minutes,
        walk_meters=walk_meters,
        rank=rank,
    )


def _request(
    feed_id: str,
    service_date: date,
    case: dict[str, Any],
) -> BatchSearchRequest:
    return BatchSearchRequest(
        service_date=service_date,
        departure_minute=case["departure_minute"],
        origins=tuple(
            _endpoint(feed_id, row, rank)
            for rank, row in enumerate(case["origins"])
        ),
        destinations=tuple(
            _endpoint(feed_id, row, rank)
            for rank, row in enumerate(case["destinations"])
        ),
        preference=case["preference"],
        max_rides=case.get("max_rides", 6),
    )


def _load_real_dataset(
    directory: Path,
    feed_id: str,
) -> TransitDataset:
    return GtfsTransitAdapter.load(
        directory,
        metadata=FeedMetadata(
            feed_id=feed_id,
            source_type="benchmark",
            source_uri=str(directory.resolve()),
            version="local",
            fetched_at=datetime.now(timezone.utc),
        ),
    )


def run_benchmark(
    dataset: TransitDataset,
    corpus: dict[str, Any],
    *,
    engine: str,
    runs: int,
    warmup_runs: int,
) -> dict[str, Any]:
    if runs < 1 or warmup_runs < 0:
        raise ValueError("runs must be >= 1 and warmup-runs must be >= 0")

    rss_before_build = _process_rss_bytes()
    tracemalloc.start()
    build_started = perf_counter()
    core = create_search_core(dataset, mode=engine)
    build_seconds = perf_counter() - build_started
    _, build_peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after_build = _process_rss_bytes()

    service_date = date.fromisoformat(corpus["service_date"])
    case_results = []
    for case in corpus["cases"]:
        request = _request(dataset.metadata.feed_id, service_date, case)
        for _ in range(warmup_runs):
            core.search(request)

        latencies_ms: list[float] = []
        visited_states: list[int] = []
        queue_peaks: list[int] = []
        generated_labels: list[int] = []
        route_found = False
        pair_count = 0
        for _ in range(runs):
            started = perf_counter()
            result = core.search(request)
            latencies_ms.append((perf_counter() - started) * 1000)
            diagnostics = result.diagnostics
            visited_states.append(diagnostics.visited_states)
            queue_peaks.append(diagnostics.queue_peak)
            generated_labels.append(diagnostics.generated_labels)
            route_found = diagnostics.route_found
            pair_count = len(result.pairs)

        case_results.append(
            {
                "name": case["name"],
                "preference": case["preference"],
                "origins": len(case["origins"]),
                "destinations": len(case["destinations"]),
                "route_found": route_found,
                "pair_count": pair_count,
                "latency_ms": {
                    "p50": round(median(latencies_ms), 3),
                    "p95": round(_percentile(latencies_ms, 0.95), 3),
                    "min": round(min(latencies_ms), 3),
                    "max": round(max(latencies_ms), 3),
                },
                "visited_states": {
                    "p50": median(visited_states),
                    "max": max(visited_states),
                },
                "queue_peak": {
                    "p50": median(queue_peaks),
                    "max": max(queue_peaks),
                },
                "generated_labels": {
                    "p50": median(generated_labels),
                    "max": max(generated_labels),
                },
            }
        )

    return {
        "engine": engine,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "runs": runs,
        "warmup_runs": warmup_runs,
        "dataset": {
            "feed_id": dataset.metadata.feed_id,
            "version": dataset.metadata.version,
            "stops": len(dataset.stops),
            "routes": len(dataset.routes),
            "trips": len(dataset.trips),
            "stop_times": len(dataset.stop_times),
        },
        "index_build_ms": round(build_seconds * 1000, 3),
        "index_peak_alloc_bytes": build_peak_bytes,
        "process_rss_before_index_bytes": rss_before_build,
        "process_rss_after_index_bytes": rss_after_build,
        "process_rss_index_delta_bytes": (
            None
            if rss_before_build is None or rss_after_build is None
            else rss_after_build - rss_before_build
        ),
        "cases": case_results,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark the batched GTFS route SearchCore.",
    )
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--warmup-runs", type=int, default=3)
    parser.add_argument(
        "--engine",
        choices=("python", "rust", "shadow"),
        default="python",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--gtfs-dir",
        type=Path,
        help="Optional real GTFS directory; the golden fixture is used by default.",
    )
    parser.add_argument(
        "--feed-id",
        help="Feed namespace for --gtfs-dir; for example sendai_bus.",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        help="JSON corpus containing service_date and cases for --gtfs-dir.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.gtfs_dir is None:
        if args.feed_id is not None or args.cases is not None:
            raise SystemExit("--feed-id/--cases require --gtfs-dir")
        dataset, corpus = load_golden_fixture()
    else:
        if not args.feed_id or args.cases is None:
            raise SystemExit("--gtfs-dir requires --feed-id and --cases")
        dataset = _load_real_dataset(args.gtfs_dir, args.feed_id)
        corpus = json.loads(args.cases.read_text(encoding="utf-8"))

    report = run_benchmark(
        dataset,
        corpus,
        engine=args.engine,
        runs=args.runs,
        warmup_runs=args.warmup_runs,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
