"""Check human-reviewed Yokohama pass ODs against an installed REAL GTFS feed.

No network or realtime token required. This does not create an oracle from the
same search engine: the cases must be independently reviewed using official
route maps and timetables. No outputs are written to disk.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.app_factory import create_app

_POLICIES = {
    "yokohama_welfare_special_pass",
    "yokohama_senior_special_pass",
}


def _cases(path: Path) -> list[dict]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"cases"}:
        raise ValueError("cases JSON must contain only a 'cases' array")
    cases = value["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a nonempty array")
    if {row.get("policy_id") for row in cases if isinstance(row, dict)} != _POLICIES:
        raise ValueError("cases must cover both welfare and senior policies")
    required = {
        "name", "policy_id", "origin", "destination", "date", "start_time",
        "expected_route_id", "expected_departure_time",
        "expected_arrival_time",
    }
    seen = set()
    for row in cases:
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError(f"case lacks required fields: {row!r}")
        if not isinstance(row["name"], str) or not row["name"].strip():
            raise ValueError("case name must not be empty")
        if row["name"] in seen:
            raise ValueError(f"duplicate case name: {row['name']!r}")
        seen.add(row["name"])
        for field in ("origin", "destination"):
            coords = row[field]
            if (
                not isinstance(coords, list) or len(coords) != 2
                or any(type(x) not in (int, float) for x in coords)
                or not (-90 <= coords[0] <= 90 and -180 <= coords[1] <= 180)
            ):
                raise ValueError(f"{row['name']}: invalid {field} coordinates")
        for key in ("date", "start_time"):
            if not isinstance(row[key], str):
                raise ValueError(f"{row['name']}: {key} must be a string")
        for key in ("expected_route_id", "expected_trip_id",
                    "expected_departure_time", "expected_arrival_time"):
            if key in row and (not isinstance(row[key], str) or not row[key]):
                raise ValueError(f"{row['name']}: {key} must be nonempty")
        if row["policy_id"] not in _POLICIES:
            raise ValueError(f"unsupported policy: {row['policy_id']!r}")
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs-dir", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--service-date", required=True)
    parser.add_argument("--cases-json", type=Path, required=True)
    args = parser.parse_args()

    if not args.gtfs_dir.is_dir():
        raise FileNotFoundError(f"GTFS directory missing: {args.gtfs_dir}")
    if not args.coverage.is_file():
        raise FileNotFoundError(f"reviewed coverage JSON missing: {args.coverage}")
    cases = _cases(args.cases_json)
    if os.getenv("APP_CITY", "yokohama") != "yokohama":
        raise RuntimeError("APP_CITY must be yokohama")
    if os.getenv("YOKOHAMA_REALTIME_MODE", "disabled") != "disabled":
        raise RuntimeError("This offline check requires YOKOHAMA_REALTIME_MODE=disabled")

    os.environ.update({
        "APP_CITY": "yokohama",
        "YOKOHAMA_REALTIME_MODE": "disabled",
        "YOKOHAMA_BUS_GTFS_DIR": str(args.gtfs_dir.resolve()),
        "YOKOHAMA_FARE_COVERAGE_PATH": str(args.coverage.resolve()),
        "YOKOHAMA_BUS_GTFS_EXPECTED_SERVICE_DATE": args.service_date,
    })
    failures: list[str] = []
    with TestClient(create_app("local")) as client:
        health = client.get("/healthz", headers={"X-App-City": "yokohama"})
        health.raise_for_status()
        if health.json().get("realtime", {}).get("vehicle_positions") is not False:
            raise RuntimeError("Realtime must be disabled for this test")

        for case in cases:
            response = client.post(
                "/route",
                headers={"X-App-City": "yokohama"},
                json={
                    "alat": case["origin"][0], "alon": case["origin"][1],
                    "blat": case["destination"][0], "blon": case["destination"][1],
                    "start_time": case["start_time"],
                    "target_date_str": case["date"],
                    "pref": "shortTime",
                    "fare_policy_id": case["policy_id"],
                },
            )
            if response.status_code != 200:
                failures.append(
                    f"{case['name']}: HTTP {response.status_code}: {response.text[:500]}"
                )
                continue
            candidates = response.json().get("candidates")
            if not isinstance(candidates, list) or not candidates:
                failures.append(f"{case['name']}: no free route found")
                continue
            for candidate in candidates:
                fare = candidate.get("fare", {})
                if (
                    fare.get("policyId") != case["policy_id"]
                    or fare.get("settlementType") != "free_pass"
                    or fare.get("status") != "available"
                    or type(fare.get("payNowYen")) is not int
                    or fare["payNowYen"] != 0
                    or type(fare.get("effectiveFareYen")) is not int
                    or fare["effectiveFareYen"] != 0
                ):
                    failures.append(f"{case['name']}: candidate has nonzero/unverified fare")
            expected = {
                "route_id": case.get("expected_route_id"),
                "trip_id": case.get("expected_trip_id"),
                "departure_time": case.get("expected_departure_time"),
                "arrival_time": case.get("expected_arrival_time"),
            }
            expected = {k: v for k, v in expected.items() if v is not None}
            matching = [
                (candidate, step)
                for candidate in candidates
                for step in candidate.get("steps", [])
                if step.get("kind") == "bus"
                and all(step.get(k) == v for k, v in expected.items())
            ]
            if not matching:
                failures.append(
                    f"{case['name']}: no bus ride matches expected "
                    f"route/trip/schedule {expected}"
                )
                continue
            print(f"PASS {case['name']} ({case['policy_id']})")
    for message in failures:
        print(f"FAIL {message}", file=sys.stderr)
    print(f"Checked {len(cases)} reviewed cases; failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
