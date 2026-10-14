"""Offline smoke test: real Yokohama GTFS -> pass-scoped /route API.

Select a deterministic operating daytime bus trip on --route-id from the installed feed,
then search that origin/destination with BOTH pass policies. Check returned
rides against the same source GTFS and confirm additional payment is 0.

This is an integration smoke test, NOT an independent official timetable
oracle, proof of all pass eligibility, or permission to publish. No files are
created or changed, no ODPT token used, and no network server is started.

Example (from repository root):
  python scripts/smoke_yokohama_real_gtfs.py ^
    --gtfs-dir api/data/yokohama/2026-09-04 ^
    --coverage api/data/yokohama/2026-09-04/coverage.json ^
    --manifest-service-date 2026-09-04 --ride-date 2026-09-04 --route-id 200
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.app_factory import create_app

POLICIES = (
    "yokohama_welfare_special_pass",
    "yokohama_senior_special_pass",
)
ELIGIBLE_ROUTES = ("yokohama_bus:089", "yokohama_bus:200", "yokohama_bus:280")


def _distance_m(a, b) -> float:
    radius = 6371008.8
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat, dlon = lat2 - lat1, math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(h)))


def _clock(minute: int) -> str:
    if type(minute) is not int or minute < 0:
        raise ValueError(f"invalid service-day minute: {minute!r}")
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _stops_by_trip(dataset, trip_ids: set[str]) -> dict[str, list]:
    result: dict[str, list] = defaultdict(list)
    for row in dataset.stop_times:
        if row.trip_id in trip_ids:
            result[row.trip_id].append(row)
    for rows in result.values():
        rows.sort(key=lambda row: row.sequence)
    return result


def choose_probe(dataset, *, ride_date: str, route_id: str = "089") -> dict:
    day = date.fromisoformat(ride_date)
    if day.isoformat() != ride_date:
        raise ValueError("ride-date must be YYYY-MM-DD")
    if route_id not in {"089", "200", "280"}:
        raise ValueError(f"unsupported tested route: {route_id!r}")
    target_route = f"yokohama_bus:{route_id}"
    active = dataset.active_service_ids(day)
    trips = sorted(
        (trip for trip in dataset.trips.values()
         if trip.route_id == target_route and trip.service_id in active),
        key=lambda trip: trip.source_id,
    )
    if not trips:
        raise RuntimeError(f"no active trips for reviewed route {route_id} on {ride_date}")
    stop_rows = _stops_by_trip(dataset, {trip.id for trip in trips})
    for trip in trips:
        rows = stop_rows.get(trip.id, ())
        for start in rows[:-1]:
            depart = start.departure_minute
            if depart is None or not 8 * 60 <= depart < 18 * 60:
                continue
            origin = dataset.stops[start.stop_id]
            for finish in reversed(rows):
                arrival = finish.arrival_minute
                if (
                    finish.sequence <= start.sequence or arrival is None
                    or not 10 <= arrival - depart <= 90
                ):
                    continue
                destination = dataset.stops[finish.stop_id]
                if _distance_m(origin, destination) < 1000:
                    continue
                return {
                    "route_id": trip.route_id,
                    "trip_id": trip.id,
                    "origin": origin,
                    "destination": destination,
                    "start_time": _clock(depart - 5),
                    "source_departure": _clock(depart),
                    "source_arrival": _clock(arrival),
                }
    raise RuntimeError(
        f"no suitable daytime, >1km origin/destination on route {route_id} on {ride_date}; "
        "do not silently change dates or pass classification"
    )


def _verify_steps(candidate: dict, dataset, active: frozenset[str], trip_rows: dict) -> list:
    rides = [step for step in candidate.get("steps", ()) if step.get("kind") == "bus"]
    if not rides:
        raise AssertionError("candidate has no actual bus ride")
    for step in rides:
        route_id, trip_id = step.get("route_id"), step.get("trip_id")
        if route_id not in ELIGIBLE_ROUTES:
            raise AssertionError(f"unreviewed/excluded route returned: {route_id}")
        trip = dataset.trips.get(trip_id)
        if trip is None or trip.route_id != route_id or trip.service_id not in active:
            raise AssertionError(f"ride has missing/inactive/mismatched trip: {trip_id}")
        rows = trip_rows[trip_id]
        origin_match = [
            row for row in rows
            if row.stop_id == step.get("departureStopId")
            and row.departure_minute is not None
            and _clock(row.departure_minute) == step.get("departure_time")
        ]
        destination_match = [
            row for row in rows
            if row.stop_id == step.get("arrivalPoleId")
            and row.arrival_minute is not None
            and _clock(row.arrival_minute) == step.get("arrival_time")
        ]
        if not origin_match or not destination_match or not any(
            src.sequence < dst.sequence for src in origin_match for dst in destination_match
        ):
            raise AssertionError(
                f"API ride stops/times disagree with GTFS for {trip_id}: "
                f"{step.get('departure_time')} -> {step.get('arrival_time')}"
            )
    return rides


def run_smoke(
    *, gtfs_dir: Path, coverage: Path,
    manifest_service_date: str, ride_date: str, route_id: str = "089",
) -> dict:
    if route_id not in {"089", "200", "280"}:
        raise ValueError(f"unsupported tested route: {route_id!r}")
    if not gtfs_dir.is_dir():
        raise FileNotFoundError(gtfs_dir)
    if not coverage.is_file():
        raise FileNotFoundError(coverage)
    if os.getenv("APP_CITY", "yokohama") != "yokohama":
        raise RuntimeError("APP_CITY must be yokohama for this smoke test")
    if os.getenv("YOKOHAMA_REALTIME_MODE", "disabled") != "disabled":
        raise RuntimeError("disable YOKOHAMA_REALTIME_MODE explicitly; refusing realtime fallback")

    configured = {
        "APP_CITY": "yokohama",
        "YOKOHAMA_REALTIME_MODE": "disabled",
        "YOKOHAMA_BUS_GTFS_DIR": str(gtfs_dir.resolve()),
        "YOKOHAMA_FARE_COVERAGE_PATH": str(coverage.resolve()),
        "YOKOHAMA_BUS_GTFS_EXPECTED_SERVICE_DATE": manifest_service_date,
    }
    results = []
    with patch.dict(os.environ, configured):
        with TestClient(create_app("local")) as client:
            dataset = client.app.state.transit_dataset
            covered = client.app.state.route_backend.fare_coverage
            if covered is None:
                raise AssertionError("the reviewed coverage was not loaded")
            if {key for key, kind in covered.route_service_kinds.items() if kind == "local"} != set(ELIGIBLE_ROUTES):
                raise AssertionError("smoke test only supports the partial three-route coverage")
            if covered.route_service_kinds["yokohama_bus:271"] != "sightseeing":
                raise AssertionError("Akai Kutsu must be excluded")
            if any(kind not in {"local", "sightseeing", "unreviewed"} for kind in covered.route_service_kinds.values()):
                raise AssertionError("unexpected unreviewed classification")
            health = client.get("/healthz", headers={"X-App-City": "yokohama"})
            health.raise_for_status()
            if health.json().get("realtime", {}).get("vehicle_positions") is not False:
                raise AssertionError("realtime unexpectedly enabled")

            probe = choose_probe(dataset, ride_date=ride_date, route_id=route_id)
            active = dataset.active_service_ids(date.fromisoformat(ride_date))
            route_trip_ids = {
                trip.id for trip in dataset.trips.values()
                if trip.route_id in ELIGIBLE_ROUTES and trip.service_id in active
            }
            trip_rows = _stops_by_trip(dataset, route_trip_ids)
            for policy_id in POLICIES:
                response = client.post(
                    "/route", headers={"X-App-City": "yokohama"},
                    json={
                        "alat": probe["origin"].lat,
                        "alon": probe["origin"].lon,
                        "blat": probe["destination"].lat,
                        "blon": probe["destination"].lon,
                        "pref": "shortTime",
                        "start_time": probe["start_time"],
                        "target_date_str": ride_date,
                        "fare_policy_id": policy_id,
                    },
                )
                if response.status_code != 200:
                    raise AssertionError(
                        f"/route returned HTTP {response.status_code} for {policy_id}: "
                        f"{response.text[:1600]}"
                    )
                candidates = response.json().get("candidates")
                if not isinstance(candidates, list) or not candidates:
                    raise AssertionError(f"no pass-scoped GTFS route found: {policy_id}")
                selected = candidates[0]
                fare = selected.get("fare")
                if not isinstance(fare, dict) or (
                    fare.get("policyId") != policy_id
                    or fare.get("settlementType") != "free_pass"
                    or fare.get("status") != "available"
                    or type(fare.get("payNowYen")) is not int
                    or fare["payNowYen"] != 0
                    or type(fare.get("effectiveFareYen")) is not int
                    or fare["effectiveFareYen"] != 0
                ):
                    raise AssertionError(f"invalid pass fare quote for {policy_id}: {fare}")
                rides = _verify_steps(selected, dataset, active, trip_rows)
                if probe["route_id"] not in {step["route_id"] for step in rides}:
                    raise AssertionError(
                        f"requested route {route_id} was not actually chosen for {policy_id}; "
                        f"returned={[step['route_id'] for step in rides]!r}. "
                        "This may be a valid faster free route; choose a separate "
                        "source-backed OD instead of counting it as target-route coverage."
                    )
                # The solver may alight at an earlier stop and walk to the
                # requested GTFS destination. Report both clocks explicitly:
                # comparing the chosen bus arrival to the source's *other*
                # stop was misleading in the first real-feed smoke run.
                actual_alight_id = rides[-1]["arrivalPoleId"]
                actual_alight_stop = dataset.stops[actual_alight_id]
                destination_walk_steps = [
                    step for step in selected["steps"]
                    if step.get("step_id") == "walk-destination"
                ]
                if len(destination_walk_steps) > 1:
                    raise AssertionError("multiple destination walking steps")
                destination_walk = (
                    destination_walk_steps[0] if destination_walk_steps
                    else {"minutes": 0, "meters": 0}
                )
                final_walk_minutes = destination_walk["minutes"]
                if type(final_walk_minutes) is not int or final_walk_minutes < 0:
                    raise AssertionError("invalid walking time")
                if type(destination_walk["meters"]) is not int or destination_walk["meters"] < 0:
                    raise AssertionError("invalid walking distance")
                actual_distance_m = _distance_m(actual_alight_stop, probe["destination"])
                if actual_distance_m > client.app.state.route_backend.walk_radius_m + 1e-6:
                    raise AssertionError(
                        "alighting stop is outside destination walking radius"
                    )
                if actual_distance_m > 0.5 and not destination_walk_steps:
                    raise AssertionError("destination walking step was omitted")
                def clock_minute(value: str) -> int:
                    hour, minute = map(int, value.split(":"))
                    if hour < 0 or not 0 <= minute < 60:
                        raise AssertionError(f"invalid result clock: {value!r}")
                    return hour * 60 + minute
                end_of_bus = clock_minute(rides[-1]["arrival_time"])
                actual_destination_clock = selected.get("arrival_time")
                if not isinstance(actual_destination_clock, str):
                    raise AssertionError("candidate has no destination arrival clock")
                if clock_minute(actual_destination_clock) != end_of_bus + final_walk_minutes:
                    raise AssertionError(
                        "candidate destination arrival differs from actual bus arrival "
                        "plus final walking time"
                    )
                results.append({
                    "policy_id": policy_id,
                    "route_ids": [step["route_id"] for step in rides],
                    "trip_ids": [step["trip_id"] for step in rides],
                    "boarding_stop": dataset.stops[rides[0]["departureStopId"]].name,
                    "alighting_stop": actual_alight_stop.name,
                    "alighting_stop_id": actual_alight_id,
                    "bus_departure": rides[0]["departure_time"],
                    "bus_arrival_at_alighting_stop": rides[-1]["arrival_time"],
                    "final_walk_meters": destination_walk["meters"],
                    "final_walk_minutes": final_walk_minutes,
                    "arrival_at_requested_destination": actual_destination_clock,
                    "source_probe_destination_arrival": probe["source_arrival"],
                    "additional_payment_yen": fare["payNowYen"],
                    "result": "PASS",
                })

    return {
        "feed_version": "v3.0_20260727",
        "manifest_service_date": manifest_service_date,
        "ride_date": ride_date,
        "tested_route_id": route_id,
        "probe": {
            "route_id": probe["route_id"],
            "trip_id": probe["trip_id"],
            "from": probe["origin"].name,
            "to": probe["destination"].name,
            "search_time": probe["start_time"],
            "source_departure": probe["source_departure"],
            "source_arrival": probe["source_arrival"],
        },
        "results": results,
        "note": (
            "Only an offline integration smoke test against the SAME GTFS feed; "
            "not independent fare/official timetable validation. "
            "All other routes stay excluded."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs-dir", required=True, type=Path)
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--manifest-service-date", required=True)
    parser.add_argument("--ride-date", required=True)
    parser.add_argument(
        "--route-id", choices=("089", "200", "280"), default="089",
        help="Municipal bus route to check (default: 089). Other free routes remain available to search.",
    )
    args = parser.parse_args()
    result = run_smoke(
        gtfs_dir=args.gtfs_dir, coverage=args.coverage,
        manifest_service_date=args.manifest_service_date,
        ride_date=args.ride_date, route_id=args.route_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
