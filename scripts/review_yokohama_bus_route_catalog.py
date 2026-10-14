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

from audit_yokohama_bus_gtfs import audit, _rows, _unique
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
    include_registry: bool = False,
    ordinary_triage: bool = False,
) -> dict:
    if ordinary_triage and not include_registry:
        raise ValueError("--ordinary-triage requires --with-reviewed-registry")
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
    result = {
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
    if include_registry:
        from propose_yokohama_reviewed_coverage import _load_reviews
        records = _load_reviews(dataset, reviewed_on=coverage.reviewed_on.isoformat())
        annotate_catalog_with_registry(result, records)
    if ordinary_triage:
        result["ordinary_review_triage"] = ordinary_review_triage(
            gtfs_dir=gtfs_dir, report=result,
        )
    return result



def annotate_catalog_with_registry(report: dict, records: dict) -> None:
    """Overlay reviewed decisions for triage without changing fare eligibility."""
    entries = [item for section in report["groups"].values() for item in section]
    by_id = {item["route_id"]: item for item in entries}
    if len(by_id) != report["route_count"]:
        raise ValueError("route catalog duplicate/missing route IDs")
    unknown = sorted(set(records) - set(by_id))
    if unknown:
        raise ValueError(f"registry routes missing from GTFS catalog: {unknown}")
    # Validate all decisions before mutating the in-memory report.
    for number, record in records.items():
        status = record["status"]
        if status not in {"pending", "development_eligible"}:
            raise ValueError(f"invalid registry status: {number}: {status!r}")
        kind = by_id[number]["current_coverage_kind"]
        if status == "pending" and kind != "unreviewed":
            raise ValueError(f"pending route is enabled or excluded: {number}")
        if status == "development_eligible" and kind not in {"local", "unreviewed"}:
            raise ValueError(f"development route has invalid coverage: {number}")
    for item in entries:
        if (item["current_coverage_kind"] == "local"
            and item["route_id"] not in {"089", "200", "280"}
            and item["route_id"] not in records):
            raise ValueError(
                f"enabled route missing from explicit review registry: {item['route_id']}"
            )
    unregistered = {
        "exception_terms_need_manual_review": [],
        "nonstandard_name_need_manual_review": [],
        "ordinary_name_candidate_not_approved": [],
    }
    for item in entries:
        record = records.get(item["route_id"])
        item["registry_status"] = record["status"] if record else "not_registered"
        if record:
            item["registry_remaining_checks"] = list(record["remaining_checks"])
        elif item["review_queue"] in unregistered:
            unregistered[item["review_queue"]].append(item["route_id"])
    report["review_registry"] = {
        "purpose": "READ-ONLY triage; not production fare certification",
        "registered_route_count": len(records),
        "pending_route_ids": sorted(
            number for number, record in records.items() if record["status"] == "pending"
        ),
        "development_eligible_route_ids": sorted(
            number for number, record in records.items()
            if record["status"] == "development_eligible"
        ),
        "unregistered_route_ids_by_queue": {
            name: sorted(ids) for name, ids in unregistered.items()
        },
        "unregistered_review_queue_count": sum(len(x) for x in unregistered.values()),
        "warning": "Name/time/registry status cannot prove a trip is free; pending and unregistered stay excluded.",
    }



# Text is only a lead for human fare review; no keyword decides eligibility.
_ORDINARY_TRIP_ATTENTION_TERMS = (
    "深夜", "深夜急行", "高速", "直行", "直通", "特急", "貸切", "空港", "羽田", "観光",
)
_109_REFERENCE = "https://www.city.yokohama.lg.jp/kotsu/bus/unchin/bus_teiki.html"
_109_2026_TIMETABLE_REFERENCE = (
    "https://navi.hamabus.city.yokohama.lg.jp/koutuu/smart/diagram/"
    "Search/bus?course=0001601091&startId=00090593&stopNo=14"
)
_MUNICIPAL_NIGHT_BUS_ABOLITION_REFERENCE = (
    "https://cgi.city.yokohama.lg.jp/shimin/kouchou/search/data/36003485.html"
)


def ordinary_review_triage(*, gtfs_dir: Path, report: dict) -> dict:
    """Prioritize manual review of ordinary-named unapproved routes.

    Route names, service descriptions, late clocks and references to special
    fare programs are leads only.  This function cannot approve free trips,
    change the source coverage or substitute metadata for fare evidence.
    """
    ordinary = report["groups"]["ordinary_name_candidate_not_approved"]
    all_entries = [
        item for group in report["groups"].values() for item in group
    ]
    route_index = {item["route_id"]: item for item in all_entries}
    if len(route_index) != report["route_count"]:
        raise ValueError("route catalog must contain unique route IDs")
    candidates = {item["route_id"] for item in ordinary}
    if any(item["current_coverage_kind"] != "unreviewed" for item in ordinary):
        raise ValueError("ordinary review queue contains enabled or excluded route")

    trips = _unique(_rows(
        gtfs_dir / "trips.txt",
        required=("trip_id", "route_id", "jp_trip_desc", "jp_trip_desc_symbol"),
    ), "trip_id", table="trips")
    counts: Counter[str] = Counter()
    annotations: Counter[str] = Counter()
    keywords: dict[str, set[str]] = defaultdict(set)
    samples: dict[str, list[str]] = defaultdict(list)
    for trip_id, trip in trips.items():
        number = trip["route_id"]
        if number not in route_index:
            raise ValueError(f"trip route missing from reviewed catalog: {number}")
        counts[number] += 1
        fields = [trip.get(k) for k in (
            "jp_trip_desc", "jp_trip_desc_symbol", "trip_headsign",
        )]
        if any(value is not None and not isinstance(value, str) for value in fields):
            raise ValueError(f"invalid trip description for {trip_id}")
        desc, symbol, headsign = (value or "" for value in fields)
        if number not in candidates:
            continue
        if desc.strip() or symbol.strip():
            annotations[number] += 1
        hits = {
            term for term in _ORDINARY_TRIP_ATTENTION_TERMS
            if term in f"{desc} {symbol} {headsign}"
        }
        keywords[number].update(hits)
        if (desc.strip() or symbol.strip() or hits) and len(samples[number]) < 5:
            samples[number].append(trip_id)
    if len(trips) != report["trip_count_all_calendar_services"]:
        raise ValueError("trip inventory count differs from reviewed GTFS")
    if any(counts[item["route_id"]] != item["total_feed_trips"] for item in all_entries):
        raise ValueError("trip inventory per-route count differs from reviewed GTFS")

    reasons: dict[str, list[str]] = {}
    priority_samples: dict[str, dict] = {}
    for item in ordinary:
        number = item["route_id"]
        flags = []
        if keywords[number]:
            flags.append("trip_text_fare_exception_keyword")
        if annotations[number]:
            flags.append("gtfs_jp_trip_annotation")
        if item["after_23_clock_trip_flags"]:
            flags.append("after_23_clock_not_proof_of_surcharge")
        if number == "109":
            # Historical environmental commuter pass discount excluded 109
            # express trips, but that scheme ended 2026-09-27.  It is NOT
            # evidence of the welfare/senior pass fare on 2026-10-14.
            flags.append("109_express_historical_other_scheme_needs_independent_review")
        if flags:
            reasons[number] = flags
            priority_samples[number] = {
                "matched_trip_keywords": sorted(keywords[number]),
                "gtfs_jp_annotated_trip_count": annotations[number],
                "after_23_clock_trip_flags": item["after_23_clock_trip_flags"],
                "sample_raw_trip_ids": samples[number],
            }

    priority = sorted(reasons)
    # Divide all attention flags into actually actionable service/text leads
    # and clock-only context.  The 2024 municipal night-bus abolition makes
    # "after 23:00" particularly weak fare evidence, not an exclusion.
    service_leads = sorted(
        number for number in priority
        if number == "109" or keywords[number] or annotations[number]
    )
    clock_only = sorted(set(priority) - set(service_leads))
    routine = sorted(candidates - set(priority))
    if len(service_leads) + len(clock_only) + len(routine) != len(candidates):
        raise AssertionError("ordinary review triage did not partition the catalog")
    return {
        "purpose": "READ ONLY manual investigation order, NOT fare approval",
        "ordinary_unapproved_route_count": len(candidates),
        "priority_route_count": len(priority),
        "priority_route_ids": priority,
        "review_attention_tiers": {
            "service_or_text_lead_route_ids": service_leads,
            "clock_only_informational_route_ids": clock_only,
            "other_unreviewed_route_ids": routine,
            "service_or_text_lead_count": len(service_leads),
            "clock_only_informational_count": len(clock_only),
            "other_unreviewed_count": len(routine),
        },
        "priority_reasons_by_route": reasons,
        "priority_trip_examples_by_route": priority_samples,
        "other_ordinary_route_ids": routine,
        "official_109_context_url": _109_REFERENCE if "109" in candidates else None,
        "official_109_2026_service_change_url": (
            _109_2026_TIMETABLE_REFERENCE if "109" in candidates else None
        ),
        "official_municipal_night_bus_abolition_url": (
            _MUNICIPAL_NIGHT_BUS_ABOLITION_REFERENCE
        ),
        "warning": (
            "109 was excluded from a DIFFERENT commuter-pass discount scheme "
            "ending on 2026-09-27; this does NOT prove welfare/senior exclusion. "
            "Yokohama municipal night bus services were abolished on 2024-04-01; "
            "GTFS clocks >=23h are informational only, not paid deep-night "
            "service evidence. 109 had some express trips converted to through "
            "service in 2026; this is not evidence of welfare/senior pass terms. "
            "No GTFS annotation proves a surcharge or exemption, and no flag "
            "means UNREVIEWED, not eligible for free-pass search."
        ),
        "file_action": "READ ONLY: no fare/GTFS/coverage/registry files written",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs-dir", required=True, type=Path)
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--manifest-service-date", required=True)
    parser.add_argument("--ride-date", required=True, action="append")
    parser.add_argument(
        "--with-reviewed-registry", action="store_true",
        help="Strict read-only reconciliation with the common fare review registry",
    )
    parser.add_argument(
        "--ordinary-triage", action="store_true",
        help="Read-only trip-metadata priority queue for ordinary unapproved routes; "
             "requires --with-reviewed-registry, never approves fare",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Show details for every ordinary-name route (default: compact list of IDs)",
    )
    args = parser.parse_args()
    result = review_catalog(
        gtfs_dir=args.gtfs_dir, coverage_path=args.coverage,
        manifest_service_date=args.manifest_service_date,
        ride_dates=args.ride_date,
        include_registry=args.with_reviewed_registry,
        ordinary_triage=args.ordinary_triage,
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
