"""Read-only, ALL-route Yokohama municipal GTFS pass review queue.

Use this to triage the 149 pinned municipal routes in ONE run rather than
executing the single-route inspector 149 times. Output is review work, NOT a
fare classification and NOT approved coverage. In particular, express/rapid
bus route names alone are not proof of being an excluded DIRECT bus.

All dates must be explicitly given. No file outputs or network traffic.

Example:
 python scripts/review_yokohama_bus_route_catalog.py \
    --gtfs-dir api/data/yokohama/2026-09-04 \
    --coverage api/data/yokohama/2026-09-04/coverage_dev_008.json \
    --manifest-service-date 2026-09-04 \
    --ride-date 2026-09-04 --ride-date 2026-09-05
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from audit_yokohama_bus_gtfs import audit
from yokohama_fare_coverage import YokohamaFareCoverage
from yokohama_transit import load_yokohama_bus_dataset

# Candidate-rejection terms are for MANUAL REVIEW, never automatic paid-fare
# classification. "急行" is not treated as "直行"; neither proves actual fare.
FARE_EXCEPTION_TERMS = ("あかいくつ", "空港", "羽田", "深夜", "高速", "直行", "貸切")
OTHER_UNUSUAL_TERMS = ("急行", "ふれあい", "観光", "周遊", "循環", "病院", "シャトル")
EXPECTED_EXCEPTION = "yokohama_bus:271"


def _day(text: str) -> date:
    day = date.fromisoformat(text)
    if day.isoformat() != text:
        raise ValueError(f"date must be zero-padded YYYY-MM-DD: {text!r}")
    return day


def review_catalog(
    *, gtfs_dir: Path, coverage_path: Path,
    manifest_service_date: str, ride_dates: list[str],
) -> dict:
    if not ride_dates:
        raise ValueError("provide at least one --ride-date")
    if len(set(ride_dates)) != len(ride_dates):
        raise ValueError("duplicate --ride-date is not allowed")
    days = [_day(x) for x in ride_dates]
    if _day(manifest_service_date).isoformat() != manifest_service_date:
        raise ValueError("invalid manifest-service-date")
    feed_audit = audit(gtfs_dir)
    dataset = load_yokohama_bus_dataset(
        gtfs_dir, expected_service_date=manifest_service_date,
    )
    coverage = YokohamaFareCoverage.load(coverage_path, dataset=dataset)
    if dataset.metadata.feed_id != "yokohama_bus" or coverage.operator_id != "yokohama_municipal_bus":
        raise ValueError("not a Yokohama municipal bus feed")
    if coverage.reviewed_free_trip_uris is not None:
        raise ValueError("review catalog requires route-based development coverage v1")
    if coverage.route_service_kinds.get(EXPECTED_EXCEPTION) != "sightseeing":
        raise ValueError("missing exclusion for Akai Kutsu (271)")
    if "あかいくつ" not in (
        dataset.routes[EXPECTED_EXCEPTION].short_name
        + dataset.routes[EXPECTED_EXCEPTION].long_name
    ):
        raise ValueError("Akai Kutsu (271) official name/ID changed")

    audit_routes = {f"yokohama_bus:{r['route_id']}": r
                    for r in feed_audit["special_and_late_routes"]}
    trips_per_route: Counter[str] = Counter(t.route_id for t in dataset.trips.values())
    active_services = {d.isoformat(): dataset.active_service_ids(d) for d in days}
    trips_on_day: dict[str, Counter[str]] = {
        day: Counter(
            trip.route_id for trip in dataset.trips.values()
            if trip.service_id in active
        )
        for day, active in active_services.items()
    }
    unusual_trip_headsigns: dict[str, set[str]] = defaultdict(set)
    for trip in dataset.trips.values():
        matches = {
            word for word in FARE_EXCEPTION_TERMS
            if word in trip.headsign
        }
        if matches:
            unusual_trip_headsigns[trip.route_id].update(matches)

    entries = []
    for route_id, route in sorted(dataset.routes.items()):
        short_name, long_name = route.short_name.strip(), route.long_name.strip()
        route_number = route_id.split(":")[-1]
        exact_number_label = short_name == f"{route_number}系統" and not long_name
        route_text = f"{short_name} {long_name}"
        explicit_exceptions = sorted(
            word for word in FARE_EXCEPTION_TERMS
            if word in route_text or word in unusual_trip_headsigns[route_id]
        )
        unusual = sorted(
            word for word in OTHER_UNUSUAL_TERMS if word in route_text
        )
        listed_audit = audit_routes.get(route_id, {})
        # A system may have nonstandard names that need review but are
        # NOT automatically ineligible for either pass.
        if explicit_exceptions:
            review_queue = "exception_terms_need_manual_review"
        elif not exact_number_label or unusual:
            review_queue = "nonstandard_name_need_manual_review"
        else:
            review_queue = "ordinary_name_candidate_not_approved"

        kind = coverage.route_service_kinds[route_id]
        if kind == "sightseeing":
            review_queue = "excluded_in_current_coverage"
        elif kind == "local":
            review_queue = "enabled_in_development_coverage"

        entries.append({
            "route_id": route_number,
            "short_name": short_name,
            "long_name": long_name,
            "current_coverage_kind": kind,
            "review_queue": review_queue,
            "exception_terms": explicit_exceptions,
            "other_unusual_terms": unusual,
            "unusual_trip_headsign_terms": sorted(unusual_trip_headsigns[route_id]),
            "total_feed_trips": trips_per_route[route_id],
            "trips_on_dates": {
                d: trips_on_day[d][route_id] for d in active_services
            },
            "after_23_clock_trip_flags": listed_audit.get("late_clock_trips", 0),
        })

    if len(entries) != len(dataset.routes):
        raise AssertionError("route catalog failed to enumerate every route")
    sections = {
        section: [item for item in entries if item["review_queue"] == section]
        for section in (
            "enabled_in_development_coverage",
            "excluded_in_current_coverage",
            "exception_terms_need_manual_review",
            "nonstandard_name_need_manual_review",
            "ordinary_name_candidate_not_approved",
        )
    }
    reviewable = sum(
        len(sections[x]) for x in (
            "exception_terms_need_manual_review",
            "nonstandard_name_need_manual_review",
            "ordinary_name_candidate_not_approved",
        )
    )
    if reviewable + len(sections["enabled_in_development_coverage"]) + len(sections["excluded_in_current_coverage"]) != len(entries):
        raise AssertionError("route catalog partition mismatch")
    return {
        "feed_version": dataset.metadata.version,
        "manifest_service_date": manifest_service_date,
        "ride_dates": list(active_services),
        "route_count": len(entries),
        "trip_count_all_calendar_services": len(dataset.trips),
        "coverage_schema": 1,
        "coverage_file": str(coverage_path),
        "current_coverage_counts": dict(sorted(Counter(coverage.route_service_kinds.values()).items())),
        "review_queue_counts": {k: len(v) for k, v in sections.items()},
        "reviewable_unapproved_routes": reviewable,
        "groups": sections,
        "review_policy": [
            "All groups except current development coverage and explicit exclusion are UNREVIEWED; none is automatically made free.",
            "Keyword flags only prioritize fare investigation. Rapid (急行) is not automatically Direct (直行).",
            "A GTFS stop_time at or after 23:00 is NOT proof of a nighttime surcharge.",
            "Verify official welfare and senior fare coverage, operator/route/trip identity and schedule before approving any additional route.",
            "Development route-coverage v1 is not an independently audited production free-fare guarantee.",
        ],
        "official_sources": {
            "welfare": "https://www.city.yokohama.lg.jp/faq/kukyoku/kenko/shogaijiritsu/20211015164324433.html",
            "senior": "https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/ikigai-shakaisanka/keirou.html",
            "deep_night_abolition": "https://cgi.city.yokohama.lg.jp/shimin/kouchou/search/data/36003485.html",
            "akai_kutsu_exclusion": "https://www.city.yokohama.lg.jp/kotsu/bus/norikata/akaikutsu.html",
        },
        "file_action": "READ ONLY: no files created or modified",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs-dir", required=True, type=Path)
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--manifest-service-date", required=True)
    parser.add_argument("--ride-date", required=True, action="append")
    parser.add_argument(
        "--full", action="store_true",
        help="Show details for every ordinary-name route (default: compact list of IDs)",
    )
    args = parser.parse_args()
    result = review_catalog(
        gtfs_dir=args.gtfs_dir, coverage_path=args.coverage,
        manifest_service_date=args.manifest_service_date,
        ride_dates=args.ride_date,
    )
    if not args.full:
        # Include every candidate ID, but avoid >100 verbose identical JSON
        # records; do not imply automatic fare eligibility.
        ordinary = result["groups"].pop("ordinary_name_candidate_not_approved")
        result["ordinary_name_candidate_route_ids"] = [
            item["route_id"] for item in ordinary
        ]
        result["ordinary_name_candidate_detail_hint"] = (
            "Use --full to see every regular-looking route's metadata. "
            "None of these are approved free-fare routes."
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
