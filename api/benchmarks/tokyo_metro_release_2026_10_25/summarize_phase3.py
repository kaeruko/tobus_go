from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import platform
import sys
from pathlib import Path


METRICS = (
    "max_pop",
    "elapsed_seconds",
    "max_queue",
    "max_retained_labels",
    "candidate_count",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[float], quantile: float) -> float:
    """Return the linearly interpolated Type-7 sample percentile."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot summarize an empty sample")
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize_rows(rows: list[dict]) -> dict:
    result = {"rows": len(rows), "metrics": {}}
    for metric in METRICS:
        values = [float(row[metric]) for row in rows]
        result["metrics"][metric] = {
            "median": percentile(values, 0.50),
            "p95": percentile(values, 0.95),
            "p99": percentile(values, 0.99),
            "max": max(values),
        }
    return result


def group(rows: list[dict], fields: tuple[str, ...]) -> dict:
    grouped: dict[tuple, list[dict]] = {}
    for row in rows:
        key = tuple(row[field] for field in fields)
        grouped.setdefault(key, []).append(row)
    return {
        " / ".join(str(value) for value in key): summarize_rows(group_rows)
        for key, group_rows in sorted(grouped.items(), key=lambda item: str(item[0]))
    }


def row_key(row: dict) -> dict:
    return {
        key: row[key]
        for key in (
            "case",
            "scope",
            "mode",
            "candidate_limit",
            "estimated_transfers",
        )
    }


def select_one(rows: list[dict], **expected) -> dict:
    matches = [
        row for row in rows if all(row.get(key) == value for key, value in expected.items())
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one highlight row for {expected}: {len(matches)}")
    row = matches[0]
    return {
        **row_key(row),
        **{metric: row[metric] for metric in METRICS},
        "candidate_sha256": row["candidate_sha256"],
        "error": row["error"],
    }


def deterministic_gzip(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_file, target.open("wb") as output_file:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output_file, mtime=0) as archive:
            for block in iter(lambda: input_file.read(1024 * 1024), b""):
                archive.write(block)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize the fixed Phase 3 corpus run")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--compressed-run", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if payload.get("schema") != "tokyo_metro_release_corpus_result/v1":
        parser.error("unexpected corpus result schema")
    rows = payload["rows"]
    if len(rows) != 188:
        parser.error(f"fixed corpus row count changed: {len(rows)}")

    comparison = payload["summary"]["correctness_comparison"]
    errors = [row for row in rows if row["error"] is not None]
    elapsed_over_limit = [row for row in rows if row["elapsed_seconds"] > 15.0]
    pop_limit_hits = [
        row
        for row in rows
        if row["max_pop"] > 100_000
        or (row["error"] and "max_visited" in row["error"])
    ]
    if not comparison["performed"] or comparison["mismatches"] != 0:
        parser.error("Phase 2 correctness comparison did not pass")
    if errors or elapsed_over_limit or pop_limit_hits:
        parser.error("fixed Phase 3 performance gate failed")

    max_rows = {}
    for metric in METRICS:
        maximum = max(float(row[metric]) for row in rows)
        max_rows[metric] = {
            "value": maximum,
            "rows": [row_key(row) for row in rows if float(row[metric]) == maximum],
        }

    scope_rows = []
    for row in rows:
        normalized = dict(row)
        normalized["scope_key"] = "+".join(row["scope"])
        scope_rows.append(normalized)

    summary = {
        "schema": "tokyo_metro_phase3_performance/v1",
        "source": {
            "uncompressed_sha256": sha256(args.input),
            "phase2_baseline_sha256": comparison["baseline_sha256"],
            "correctness_mismatches": comparison["mismatches"],
            "feed": payload["feed"],
            "transfer_manifest_sha256": payload["transfer_manifest_sha256"],
        },
        "measurement": {
            "method": (
                "188 searches executed sequentially in one warm Python process; "
                "time.perf_counter covered TokyoRouteEngine.search_legacy only; "
                "gc.collect ran immediately before each search; initial pickle/GTFS load "
                "and graph construction were excluded"
            ),
            "percentile_method": "Type-7 linear interpolation over the 188 fixed searches",
            "runtime_warning": (
                "elapsed time is local-host evidence; pop, queue and retained-label counters "
                "are engine measurements for the fixed inputs"
            ),
            "environment": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "logical_cpu_count": os.cpu_count(),
                "processor": platform.processor(),
            },
        },
        "gate": {
            "rows": len(rows),
            "errors": len(errors),
            "elapsed_over_15_seconds": len(elapsed_over_limit),
            "pop_limit_hits": len(pop_limit_hits),
            "correctness_mismatches": comparison["mismatches"],
            "passed": not errors
            and not elapsed_over_limit
            and not pop_limit_hits
            and comparison["mismatches"] == 0,
        },
        "distributions": {
            "overall": summarize_rows(rows),
            "by_objective": group(rows, ("mode",)),
            "by_estimated_transfer_mode": group(rows, ("estimated_transfers",)),
            "by_objective_and_estimated_transfer_mode": group(
                rows, ("mode", "estimated_transfers")
            ),
            "by_scope": group(scope_rows, ("scope_key",)),
        },
        "maxima": max_rows,
        "reference_cases": {
            "shibuya_asakusa_ordinary": select_one(
                rows,
                case="tokyo_metro_only",
                mode="fewTransfers",
                candidate_limit=5,
                estimated_transfers=False,
            ),
            "shibuya_asakusa_estimated": select_one(
                rows,
                case="tokyo_metro_only",
                mode="fewTransfers",
                candidate_limit=5,
                estimated_transfers=True,
            ),
            "nakano_sakaue_myoden_estimated": select_one(
                rows,
                case="estimated_transfer_stress",
                mode="fewTransfers",
                candidate_limit=5,
                estimated_transfers=True,
            ),
        },
    }

    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    deterministic_gzip(args.input, args.compressed_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
