"""Read-only GTFS agency/route identity audit for Yokohama municipal subway.

DOES NOT create fare-coverage approval, walking transfers or runtime routes.
Route count is raw routes.txt records, not the number of operating lines.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from transit_dataset import TransitDataset, TransitMode, namespace_id
from yokohama_subway import FEED_ID, load_yokohama_subway_dataset
from fare_policy import YOKOHAMA_WELFARE_PASS_SOURCE, YOKOHAMA_SENIOR_PASS_SOURCE


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path.name} missing header")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name} has no rows")
    return rows


def audit_subway_routes(
    dataset: TransitDataset,
    gtfs_dir: Path,
    *,
    service_date: str,
) -> dict:
    """Summarize active trains and agency references without approving fares."""
    try:
        day = date.fromisoformat(service_date)
    except (ValueError, TypeError) as exc:
        raise ValueError("service_date must be YYYY-MM-DD") from exc
    if day.isoformat() != service_date:
        raise ValueError("service_date must be zero-padded YYYY-MM-DD")
    if (
        dataset.metadata.feed_id != FEED_ID
        or not dataset.routes
        or any(route.mode is not TransitMode.RAIL for route in dataset.routes.values())
    ):
        raise ValueError("Yokohama subway feed identity or mode mismatch")
    root = Path(gtfs_dir)
    agencies = _rows(root / "agency.txt")
    source_routes = _rows(root / "routes.txt")
    if len(source_routes) != len(dataset.routes):
        raise ValueError("source routes.txt and validated route count mismatch")
    agency_by_id: dict[str, str] = {}
    for row in agencies:
        agency_id = row.get("agency_id") or ""
        name = row.get("agency_name") or ""
        if not name:
            raise ValueError("agency_name missing")
        if agency_id in agency_by_id:
            raise ValueError("duplicated agency_id in source")
        agency_by_id[agency_id] = name

    active_services = dataset.active_service_ids(day)
    trip_count_by_route: dict[str, int] = defaultdict(int)
    active_trip_count_by_route: dict[str, int] = defaultdict(int)
    active_trip_to_route = {}
    for trip in dataset.trips.values():
        if trip.route_id not in dataset.routes:
            raise ValueError("trip references unknown subway route")
        trip_count_by_route[trip.route_id] += 1
        if trip.service_id in active_services:
            active_trip_count_by_route[trip.route_id] += 1
            active_trip_to_route[trip.id] = trip.route_id
    active_stops_by_route: dict[str, set[str]] = defaultdict(set)
    for row in dataset.stop_times:
        rid = active_trip_to_route.get(row.trip_id)
        if rid is not None:
            active_stops_by_route[rid].add(row.stop_id)

    results = []
    visited = set()
    for row in source_routes:
        raw_route_id = row.get("route_id") or ""
        route_id = namespace_id(FEED_ID, raw_route_id)
        if route_id in visited or route_id not in dataset.routes:
            raise ValueError("source routes.txt contains invalid or duplicate route ID")
        visited.add(route_id)
        ref = row.get("agency_id") or ""
        if ref and ref not in agency_by_id:
            raise ValueError("route references unlisted source agency_id")
        if ref:
            agency_name = agency_by_id[ref]
            identity_state = "GTFS_EXPLICIT_AGENCY_ID_ONLY"
        elif len(agencies) == 1:
            agency_name = agencies[0]["agency_name"]
            identity_state = "GTFS_SINGLE_AGENCY_ONLY"
        else:
            agency_name = None
            identity_state = "UNRESOLVED_MULTIPLE_AGENCIES"
        r = dataset.routes[route_id]
        results.append({
            "route_id": route_id,
            "short_name": r.short_name,
            "long_name": r.long_name,
            "source_agency_id": ref or None,
            "source_agency_name": agency_name,
            "agency_mapping": identity_state,
            "total_trips": trip_count_by_route.get(route_id, 0),
            "active_service_day_trips": active_trip_count_by_route.get(route_id, 0),
            "active_timed_station_count": len(active_stops_by_route[route_id]),
            "pass_coverage_status": "UNREVIEWED_GTFS_ROUTE_ID",
        })
    if visited != set(dataset.routes):
        raise ValueError("source routes.txt inventory mismatch")
    results.sort(key=lambda row: row["route_id"])
    return {
        "operation": "READ ONLY; ZERO FARE APPROVAL",
        "service_date": service_date,
        "feed_version": dataset.metadata.version,
        "source_route_record_count": len(source_routes),
        "distinct_source_route_names": len({
            (r["short_name"], r["long_name"]) for r in results
        }),
        "active_route_record_count": sum(bool(r["active_service_day_trips"]) for r in results),
        "subway_stations_in_feed": len(dataset.stops),
        "official_city_policy_sources": {
            "welfare": YOKOHAMA_WELFARE_PASS_SOURCE,
            "senior": YOKOHAMA_SENIOR_PASS_SOURCE,
        },
        "routes": results,
        "warning": (
            "GTFS agency names/IDs are source claims, NOT independent proof of "
            "municipal ownership or pass fare applicability. Route IDs and "
            "train pattern variants are not the count of physical railway lines. "
            "Review route identity before creating separate fare coverage."
        ),
        "file_action": "NONE",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subway-gtfs-dir", required=True, type=Path)
    parser.add_argument("--service-date", required=True)
    args = parser.parse_args()
    dataset = load_yokohama_subway_dataset(
        args.subway_gtfs_dir, expected_service_date=args.service_date
    )
    result = audit_subway_routes(
        dataset, args.subway_gtfs_dir, service_date=args.service_date
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
