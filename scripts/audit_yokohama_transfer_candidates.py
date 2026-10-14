"""READ-ONLY proximity triage for Yokohama bus/subway transfer candidates.

Never promote a candidate to a real walking link: a nearby coordinate does NOT
prove a walkable connection, platform access, accessibility or pass eligibility.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from transit_dataset import TransitDataset, TransitMode
from yokohama_fare_coverage import YokohamaFareCoverage
from yokohama_subway import load_yokohama_subway_dataset
from yokohama_transit import load_yokohama_bus_dataset


def _distance_m(a, b) -> float:
    lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lon)
    term = (
        math.sin((lat2 - lat1) / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2)
        * math.sin((lon2 - lon1) / 2.0) ** 2
    )
    return 12_742_000 * math.asin(min(1.0, math.sqrt(term)))


def _active_served_stop_ids(dataset: TransitDataset, day: date) -> set[str]:
    services = dataset.active_service_ids(day)
    active_trip_ids = {
        t.id for t in dataset.trips.values() if t.service_id in services
    }
    return {
        row.stop_id for row in dataset.stop_times
        if row.trip_id in active_trip_ids
    }


def _serving_routes_by_stop(dataset: TransitDataset, day: date) -> dict[str, list[dict]]:
    """Source GTFS route/headsign hints, never an official bus-stand mapping."""
    services = dataset.active_service_ids(day)
    active_trips = {
        trip.id: trip for trip in dataset.trips.values()
        if trip.service_id in services
    }
    route_heads: dict[str, dict[str, set[str]]] = {}
    for stop_time in dataset.stop_times:
        trip = active_trips.get(stop_time.trip_id)
        if trip is None:
            continue
        route_heads.setdefault(stop_time.stop_id, {}).setdefault(
            trip.route_id, set()
        )
        if trip.headsign:
            route_heads[stop_time.stop_id][trip.route_id].add(trip.headsign)
    return {
        stop_id: [
            {
                "route_id": route_id,
                "route_short_name": dataset.routes[route_id].short_name,
                "route_long_name": dataset.routes[route_id].long_name,
                "trip_headsigns": sorted(headsigns),
            }
            for route_id, headsigns in sorted(routes.items())
        ]
        for stop_id, routes in route_heads.items()
    }


def read_bus_pole_source_fields(gtfs_dir: Path, bus_stop_ids: set[str]) -> dict[str, dict]:
    """Read only selected raw GTFS pole fields; no stop-to-official-bay inference.

    stop_code and platform_code, when present, are GTFS source labels. They
    must NOT be treated as the numbered bays of an official stop map without
    a separate independent cross-check.
    """
    if not bus_stop_ids:
        return {}
    if any(
        not isinstance(value, str) or not value.startswith("yokohama_bus:")
        for value in bus_stop_ids
    ):
        raise ValueError("source pole fields require namespaced Yokohama bus stop IDs")
    path = Path(gtfs_dir) / "stops.txt"
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = csv.DictReader(source)
        if rows.fieldnames is None or "stop_id" not in rows.fieldnames:
            raise ValueError("GTFS bus stops.txt missing stop_id column")
        found: dict[str, dict] = {}
        for row in rows:
            source_id = row.get("stop_id")
            full_id = f"yokohama_bus:{source_id}"
            if full_id not in bus_stop_ids:
                continue
            if full_id in found:
                raise ValueError("duplicate source bus stop ID")
            found[full_id] = {
                "source_stop_id": source_id,
                "stop_code": row.get("stop_code") or None,
                "platform_code": row.get("platform_code") or None,
                "parent_station": row.get("parent_station") or None,
                "location_type": row.get("location_type") or None,
                "stop_desc": row.get("stop_desc") or None,
                "official_bay_number_verified": False,
            }
    if set(found) != bus_stop_ids:
        raise ValueError("source bus stop metadata missing requested GTFS pole IDs")
    return found


def audit_transfer_candidates(
    bus_coverage: YokohamaFareCoverage,
    subway_dataset: TransitDataset,
    *,
    service_date: str,
    radius_m: int = 300,
    limit: int = 40,
    focus_bus_stop_ids: tuple[str, ...] = (),
) -> dict:
    """Return ranked UNAPPROVED geometric hints from same-day scheduled stops.

    Existing municipal BUS coverage is used as a filter; subway routes are
    for exploration only, NOT automatically approved for welfare/senior passes.
    """
    try:
        parsed = date.fromisoformat(service_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("service_date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != service_date:
        raise ValueError("service_date must be zero-padded")
    if type(radius_m) is not int or not 1 <= radius_m <= 600:
        raise ValueError("radius_m must be an integer from 1 to 600")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 to 100")
    if (
        not isinstance(focus_bus_stop_ids, tuple)
        or len(focus_bus_stop_ids) > 100
        or any(
            not isinstance(pole, str)
            or not pole.startswith("yokohama_bus:")
            for pole in focus_bus_stop_ids
        )
        or len(set(focus_bus_stop_ids)) != len(focus_bus_stop_ids)
    ):
        raise ValueError("focus_bus_stop_ids requires distinct bus GTFS pole IDs")
    if (
        bus_coverage.operator_id != "yokohama_municipal_bus"
        or bus_coverage.dataset.metadata.feed_id != "yokohama_bus"
        or subway_dataset.metadata.feed_id != "yokohama_subway"
        or any(r.mode is not TransitMode.RAIL for r in subway_dataset.routes.values())
    ):
        raise ValueError("bus/subway feed or municipal coverage identity mismatch")
    bus_reviewed = bus_coverage.municipal_free_coverage()
    if bus_reviewed is None:
        raise ValueError("no reviewed municipal bus routes available")
    if set(focus_bus_stop_ids) - set(bus_reviewed.dataset.stops):
        raise ValueError("unknown focus bus GTFS pole ID")
    bus_stop_ids = _active_served_stop_ids(bus_reviewed.dataset, parsed)
    subway_stop_ids = _active_served_stop_ids(subway_dataset, parsed)
    bus_route_hints = _serving_routes_by_stop(bus_reviewed.dataset, parsed)
    subway_route_hints = _serving_routes_by_stop(subway_dataset, parsed)
    if not bus_stop_ids or not subway_stop_ids:
        raise ValueError("no active scheduled stops on service_date")

    hits = []
    for bus_id in sorted(bus_stop_ids):
        bus_stop = bus_reviewed.dataset.stops[bus_id]
        for rail_id in sorted(subway_stop_ids):
            rail_stop = subway_dataset.stops[rail_id]
            distance = _distance_m(bus_stop, rail_stop)
            if math.isfinite(distance) and distance <= radius_m:
                hits.append((distance, bus_id, rail_id))
    hits.sort()
    # Focus changes presentation only, NEVER which routes are reviewed.
    # candidate_pair_count continues to describe ALL pairs in radius.
    focus = set(focus_bus_stop_ids)
    visible_hits = [
        row for row in hits if not focus or row[1] in focus
    ]
    suggestions = [{
        "bus_stop_id": bus_id,
        "bus_stop_name": bus_reviewed.dataset.stops[bus_id].name,
        "bus_gtfs_lat": bus_reviewed.dataset.stops[bus_id].lat,
        "bus_gtfs_lon": bus_reviewed.dataset.stops[bus_id].lon,
        # Only reviewed, active municipal-bus trips; NOT a verified
        # correspondence to a numbered official bus stand.
        "active_reviewed_bus_routes": bus_route_hints.get(bus_id, []),
        "subway_stop_id": rail_id,
        "subway_stop_name": subway_dataset.stops[rail_id].name,
        "subway_gtfs_lat": subway_dataset.stops[rail_id].lat,
        "subway_gtfs_lon": subway_dataset.stops[rail_id].lon,
        # These are raw GTFS route IDs, NOT fare-reviewed subway lines.
        "active_unapproved_subway_routes": subway_route_hints.get(rail_id, []),
        "straight_line_distance_m": round(distance, 1),
        "status": "UNVERIFIED_GEOMETRIC_HINT",
        "official_transfer_evidence_url": None,
        "walkable_route_verified": False,
        "pass_fare_verified": False,
    } for distance, bus_id, rail_id in visible_hits[:limit]]
    return {
        "operation": "READ ONLY; ZERO FREE-ROUTE APPROVAL",
        "service_date": service_date,
        "bus_feed_version": bus_reviewed.dataset.metadata.version,
        "subway_feed_version": subway_dataset.metadata.version,
        "radius_m": radius_m,
        "active_reviewed_bus_stop_count": len(bus_stop_ids),
        "active_subway_stop_count_not_yet_fare_approved": len(subway_stop_ids),
        "candidate_pair_count": len(hits),
        "focus_bus_stop_ids": list(focus_bus_stop_ids),
        "focus_matching_pair_count": len(visible_hits),
        "shown_pair_count": len(suggestions),
        "candidates": suggestions,
        "warning": (
            "Straight-line proximity only. No walking path, interchange time, "
            "accessibility, official platform/bay correspondence, subway "
            "route coverage, or welfare/senior zero-yen fare is verified. "
            "Route/headsign hints are feed observations only. "
            "Do not feed candidate pairs into /route automatically."
        ),
        "file_action": "NONE",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus-gtfs-dir", required=True, type=Path)
    parser.add_argument("--bus-coverage", required=True, type=Path)
    parser.add_argument("--subway-gtfs-dir", required=True, type=Path)
    parser.add_argument("--service-date", required=True)
    parser.add_argument("--radius-m", type=int, default=300)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument(
        "--focus-bus-stop", action="append", default=[],
        help="GTFS namespaced pole ID, repeatable; e.g. yokohama_bus:3018_02",
    )
    parser.add_argument(
        "--include-bus-pole-fields", action="store_true",
        help="Include selected raw GTFS stops.txt metadata, never official bay approval",
    )
    args = parser.parse_args()
    bus_dataset = load_yokohama_bus_dataset(
        args.bus_gtfs_dir, expected_service_date=args.service_date
    )
    bus_coverage = YokohamaFareCoverage.load(
        args.bus_coverage, dataset=bus_dataset
    )
    subway_dataset = load_yokohama_subway_dataset(
        args.subway_gtfs_dir, expected_service_date=args.service_date
    )
    report = audit_transfer_candidates(
        bus_coverage, subway_dataset, service_date=args.service_date,
        radius_m=args.radius_m, limit=args.limit,
        focus_bus_stop_ids=tuple(args.focus_bus_stop),
    )
    if args.include_bus_pole_fields:
        poles = read_bus_pole_source_fields(
            args.bus_gtfs_dir,
            {row["bus_stop_id"] for row in report["candidates"]},
        )
        for row in report["candidates"]:
            row["source_bus_pole_fields"] = poles[row["bus_stop_id"]]
        report["pole_metadata_warning"] = (
            "GTFS stop_code/platform_code are optional source fields. "
            "They are NOT independently verified official boarding-bay numbers."
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
