"""Build an opt-in, MINIMAL Yokohama municipal-bus pass-coverage file.

This is a DEVELOPMENT-ONLY bootstrap for the three expressly named eligible
municipal services (089, 200, 280). The expressly excluded 271 is sightseeing;
every other municipal route is 'unreviewed' and excluded from pass-only search.
It is NOT full Yokohama coverage, and cannot certify premium late-night trips.

Without --output this program is READ-ONLY. --output refuses overwriting.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from audit_yokohama_bus_gtfs import KNOWN_NAMES, audit, _rows, _unique
from fare_policy import YOKOHAMA_WELFARE_PASS_SOURCE
from yokohama_transit import (
    YOKOHAMA_BUS_APPROVED_FEED_VERSION,
    YOKOHAMA_BUS_FEED_ID,
    YOKOHAMA_BUS_STATIC_URL,
    load_yokohama_bus_dataset,
)

_APPROVED = {"089", "200", "280"}
_EXCLUDED = {"271"}


def proposed_coverage(directory: Path, *, service_date: str, reviewed_on: str) -> tuple[dict, dict]:
    review_date = date.fromisoformat(reviewed_on)
    if review_date.isoformat() != reviewed_on:
        raise ValueError("reviewed_on must be YYYY-MM-DD")
    report = audit(directory)
    dataset = load_yokohama_bus_dataset(
        directory, expected_service_date=service_date,
    )
    if dataset.metadata.feed_id != YOKOHAMA_BUS_FEED_ID:
        raise ValueError("unexpected Yokohama bus feed ID")
    if dataset.metadata.version != YOKOHAMA_BUS_APPROVED_FEED_VERSION:
        raise ValueError("Yokohama bus feed version is not approved")
    if dataset.metadata.source_uri != YOKOHAMA_BUS_STATIC_URL:
        raise ValueError("Yokohama bus feed URI mismatch")

    routes = _unique(
        _rows(directory / "routes.txt", required=(
            "route_id", "route_short_name", "route_long_name", "route_type",
        )), "route_id", table="routes",
    )
    if not _APPROVED | _EXCLUDED <= routes.keys():
        raise ValueError("missing required named Yokohama municipal bus routes")
    for route_id in _APPROVED | _EXCLUDED:
        title, _ = KNOWN_NAMES[route_id]
        if title not in routes[route_id]["route_long_name"]:
            raise ValueError(f"policy route {route_id} no longer matches approved title")
    for route_id, row in routes.items():
        if route_id not in (_APPROVED | _EXCLUDED):
            name = row["route_short_name"] + row["route_long_name"]
            if "あかいくつ" in name:
                raise ValueError(f"unexpected additional Akai Kutsu route: {route_id}")

    policy_routes = {
        f"{YOKOHAMA_BUS_FEED_ID}:{route_id}": (
            "local" if route_id in _APPROVED else
            "sightseeing" if route_id in _EXCLUDED else
            "unreviewed"
        )
        for route_id in sorted(routes)
    }
    if set(policy_routes) != set(dataset.routes):
        raise ValueError("proposed pass policy does not match all GTFS routes")

    proposed = {
        "schema_version": 1,
        "city": "yokohama",
        "feed_id": dataset.metadata.feed_id,
        "feed_version": dataset.metadata.version,
        "feed_source_uri": dataset.metadata.source_uri,
        "operator_id": "yokohama_municipal_bus",
        "policy_source_uri": YOKOHAMA_WELFARE_PASS_SOURCE,
        "reviewed_on": reviewed_on,
        "routes": policy_routes,
        "stop_municipalities": {},
    }
    return proposed, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs-dir", type=Path, required=True)
    parser.add_argument("--service-date", required=True)
    parser.add_argument("--reviewed-on", required=True)
    parser.add_argument("--output", type=Path, help="Explicit opt-in output; never overwrite existing files")
    args = parser.parse_args()

    coverage, report = proposed_coverage(
        args.gtfs_dir, service_date=args.service_date, reviewed_on=args.reviewed_on,
    )
    counts = {
        label: list(coverage["routes"].values()).count(label)
        for label in ("local", "sightseeing", "unreviewed")
    }
    summary = {
        "feed_version": coverage["feed_version"],
        "validated_service_date": report["validated_service_date"],
        "route_counts": counts,
        "reviewed_free_route_ids": sorted(_APPROVED),
        "excluded_akai_kutsu_route_ids": sorted(_EXCLUDED),
        "late_clock_trip_count": report["late_clock_trip_count"],
        "WARNING": (
            "Development-only partial scope. GTFS has no fare/late-night-classification "
            "evidence. Do not publish as complete pass coverage or claim all 0-yen "
            "trips are certified. Late-night service remains to be reviewed."
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.output is None:
        print("DRY RUN: no file written. Pass --output to explicitly create coverage.")
        return
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {args.output}")
    if not args.output.parent.is_dir():
        raise FileNotFoundError(f"output directory does not exist: {args.output.parent}")
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(coverage, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(f"CREATED partial coverage: {args.output}")


if __name__ == "__main__":
    main()
