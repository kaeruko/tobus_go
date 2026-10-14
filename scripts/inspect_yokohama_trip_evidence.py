"""Read-only Yokohama municipal-bus trip evidence review for ONE route.

Select route ID and service date from the installed, pinned GTFS. This report
helps humans inspect whether trips on an ordinary bus route are *actually*
eligible for BOTH welfare and senior passes. It NEVER approves trips, creates
coverage, writes files, or assumes that daytime == normal fare.

Example from repository root:
 python scripts/inspect_yokohama_trip_evidence.py --gtfs-dir api/data/yokohama/2026-09-04 --coverage api/data/yokohama/2026-09-04/coverage.json --manifest-service-date 2026-09-04 --ride-date 2026-09-04 --route-id 008
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from yokohama_fare_coverage import YokohamaFareCoverage
from yokohama_transit import load_yokohama_bus_dataset

WELFARE_SOURCE = (
    "https://www.city.yokohama.lg.jp/faq/kukyoku/kenko/shogaijiritsu/"
    "20211015164324433.html"
)
SENIOR_SOURCE = (
    "https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/"
    "koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/ikigai-shakaisanka/keirou.html"
)


def _clock(value: int | None) -> str | None:
    return None if value is None else f"{value // 60:02d}:{value % 60:02d}"


def inspect_route(
    *, gtfs_dir: Path, coverage_path: Path, manifest_service_date: str,
    ride_date: str, route_id: str, limit: int = 6,
) -> dict:
    if type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError("limit must be an integer from 1 to 30")
    if not isinstance(route_id, str) or len(route_id) != 3 or not route_id.isascii() or not route_id.isdigit():
        raise ValueError("route ID must be exactly three ASCII digits, e.g. 008")
    day = date.fromisoformat(ride_date)
    if day.isoformat() != ride_date:
        raise ValueError("ride date must be YYYY-MM-DD")
    dataset = load_yokohama_bus_dataset(
        gtfs_dir, expected_service_date=manifest_service_date,
    )
    coverage = YokohamaFareCoverage.load(coverage_path, dataset=dataset)
    target = f"yokohama_bus:{route_id}"
    if target not in dataset.routes:
        raise ValueError(f"unknown route ID in installed Yokohama GTFS: {route_id}")
    route = dataset.routes[target]
    active = dataset.active_service_ids(day)
    all_trips = {key: trip for key, trip in dataset.trips.items() if trip.route_id == target}
    selected = {key: trip for key, trip in all_trips.items() if trip.service_id in active}
    rows_by_trip = defaultdict(list)
    for row in dataset.stop_times:
        if row.trip_id in all_trips:
            rows_by_trip[row.trip_id].append(row)
    detailed = []
    for trip_id, trip in selected.items():
        rows = sorted(rows_by_trip[trip_id], key=lambda row: row.sequence)
        if len(rows) < 2:
            raise ValueError(f"GTFS trip has fewer than two stop times: {trip_id}")
        first, last = rows[0], rows[-1]
        if first.departure_minute is None or last.arrival_minute is None:
            raise ValueError(f"missing first departure or last arrival: {trip_id}")
        # The flag means only at least one GTFS stop time >= 23:00,
        # *not* that the operator charges a nighttime premium.
        late_clock = any(
            minute is not None and minute >= 23 * 60
            for row in rows
            for minute in (row.arrival_minute, row.departure_minute)
        )
        detailed.append({
            "trip_id": trip_id,
            "service_id": trip.service_id,
            "headsign": trip.headsign,
            "from_stop_id": first.stop_id,
            "from_stop": dataset.stops[first.stop_id].name,
            "departure": _clock(first.departure_minute),
            "to_stop_id": last.stop_id,
            "to_stop": dataset.stops[last.stop_id].name,
            "arrival": _clock(last.arrival_minute),
            "late_clock_review_flag": late_clock,
            "v2_explicitly_reviewed": (
                coverage.reviewed_free_trip_uris is not None
                and trip_id in coverage.reviewed_free_trip_uris
            ),
        })
    detailed.sort(key=lambda x: (x["departure"], x["trip_id"]))
    by_service = Counter(trip.service_id for trip in selected.values())
    samples = [row for row in detailed if not row["late_clock_review_flag"]][:limit]
    late_samples = [row for row in detailed if row["late_clock_review_flag"]][:limit]
    return {
        "feed_version": dataset.metadata.version,
        "manifest_service_date": manifest_service_date,
        "ride_date": ride_date,
        "route_id": route_id,
        "route_short_name": route.short_name,
        "route_long_name": route.long_name,
        "coverage_schema": 1 if coverage.reviewed_free_trip_uris is None else 2,
        "route_review_classification": coverage.route_service_kinds[target],
        "total_trips_across_all_services": len(all_trips),
        "scheduled_trips_on_day": len(selected),
        "service_id_counts_on_day": dict(sorted(by_service.items())),
        "late_clock_review_flags_on_day": sum(t["late_clock_review_flag"] for t in detailed),
        "daytime_and_other_nonflagged_samples": samples,
        "late_clock_samples": late_samples,
        "sources_to_review": [WELFARE_SOURCE, SENIOR_SOURCE],
        "notes": [
            "Scheduled and after-23:00 counts are based on pinned GTFS only.",
            "GTFS clock times, service_id and route name do not prove free pass fares.",
            "This report never changes coverage or considers any sampled trip approved.",
            "Check the operator's actual trip/fare category, not time of day alone.",
            "Even when the same line is ordinarily free, premium trips may require extra fare.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs-dir", required=True, type=Path)
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--manifest-service-date", required=True)
    parser.add_argument("--ride-date", required=True)
    parser.add_argument("--route-id", required=True)
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()
    result = inspect_route(
        gtfs_dir=args.gtfs_dir, coverage_path=args.coverage,
        manifest_service_date=args.manifest_service_date,
        ride_date=args.ride_date, route_id=args.route_id, limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
