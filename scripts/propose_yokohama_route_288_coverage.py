"""Propose a five-route, development-only Yokohama municipal bus coverage.

The installed GTFS must match the 2026-09-04 approved manifest and the
existing four-route development coverage. 288 is explicitly listed by
Seirei Yokohama Hospital as accepting BOTH welfare and senior passes on the
hospital loop; the actual 2026 feed identity and schedule still require checks.

THIS IS NOT PUBLICATION APPROVAL or a broad route classifier.
Without --output, everything is read-only. With --output, CREATE a new file
only, never overwrite the installed coverage or the source GTFS.

  python scripts/propose_yokohama_route_288_coverage.py \
    --gtfs-dir api/data/yokohama/2026-09-04 \
    --coverage api/data/yokohama/2026-09-04/coverage_dev_008.json \
    --service-date 2026-09-04 --reviewed-on 2026-10-14
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from yokohama_fare_coverage import YokohamaFareCoverage
from yokohama_transit import load_yokohama_bus_dataset

PROPOSED_ROUTE = "yokohama_bus:288"
_ORIGINAL_LOCAL = frozenset({
    "yokohama_bus:008", "yokohama_bus:089", "yokohama_bus:200", "yokohama_bus:280",
})
_EXCLUDED = "yokohama_bus:271"
_SOURCE_URLS = (
    # The hospital explicitly confirms both welfare and senior passes.
    "https://www.seirei.or.jp/yokohama/outline/access/bus/circulation-bus/index.html",
    "https://www.city.yokohama.lg.jp/faq/kukyoku/kenko/"
    "shogaijiritsu/20211015164324433.html",
    "https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/"
    "koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/"
    "ikigai-shakaisanka/keirou.html",
)


def propose(
    *, gtfs_dir: Path, coverage_path: Path, service_date: str,
    reviewed_on: str,
) -> tuple[dict, dict]:
    day = date.fromisoformat(reviewed_on)
    if day.isoformat() != reviewed_on:
        raise ValueError("reviewed-on must be YYYY-MM-DD")
    dataset = load_yokohama_bus_dataset(
        gtfs_dir, expected_service_date=service_date,
    )
    reviewed = YokohamaFareCoverage.load(coverage_path, dataset=dataset)
    raw = json.loads(coverage_path.read_text(encoding="utf-8"))
    if raw["schema_version"] != 1:
        raise ValueError("requires original v1 route coverage, not v2 trip-specific coverage")
    # The installed manifest/coverage loader validates the exact feed identity
    # and EVERY route, so we do not tie this proposal to incidental trip counts.
    route = dataset.routes.get(PROPOSED_ROUTE)
    if route is None or route.short_name or route.long_name != "聖隷横浜病院循環":
        raise ValueError("GTFS route 288 name/identity changed; independent re-review required")
    if reviewed.operator_id != "yokohama_municipal_bus":
        raise ValueError("requires Yokohama municipal bus coverage")
    current = reviewed.route_service_kinds
    if {key for key, kind in current.items() if kind == "local"} != _ORIGINAL_LOCAL:
        raise ValueError("installed coverage is not the expected four-route development baseline")
    if current.get(PROPOSED_ROUTE) != "unreviewed":
        raise ValueError("route 288 is not unreviewed in the four-route coverage")
    if current.get(_EXCLUDED) != "sightseeing":
        raise ValueError("Akai Kutsu exemption is missing")
    if any(
        kind != "unreviewed"
        for key, kind in current.items()
        if key not in _ORIGINAL_LOCAL | {PROPOSED_ROUTE, _EXCLUDED}
    ):
        raise ValueError("unexpected classification for other routes")

    proposal = {
        **raw,
        "reviewed_on": reviewed_on,
        "routes": {**raw["routes"], PROPOSED_ROUTE: "local"},
    }
    counts = Counter(proposal["routes"].values())
    result = {
        "operation": "PROPOSAL ONLY: development coverage, not a verified production fare guarantee",
        "from": str(coverage_path),
        "route_added": PROPOSED_ROUTE,
        "previous_status": "unreviewed",
        "proposed_status": "local",
        "route_counts": {key: counts[key] for key in ("local", "sightseeing", "unreviewed")},
        "added_route_trips_across_all_service_days": sum(
            trip.route_id == PROPOSED_ROUTE for trip in dataset.trips.values()
        ),
        "unchanged_excluded_route": _EXCLUDED,
        "fare_review_sources": list(_SOURCE_URLS),
        "remaining_questions": [
            "Hospital published both-pass fare eligibility; confirm it still applies to 2026 GTFS trips.",
            "Validate independent timetable ODs and route variations before publication.",
            "A route name and official general fare statement are not a trip-by-trip oracle.",
        ],
    }
    return proposal, result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs-dir", required=True, type=Path)
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--service-date", required=True)
    parser.add_argument("--reviewed-on", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    proposal, result = propose(
        gtfs_dir=args.gtfs_dir, coverage_path=args.coverage,
        service_date=args.service_date, reviewed_on=args.reviewed_on,
    )
    if args.output is None:
        result["file_action"] = "DRY RUN: no file written"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.output.resolve() == args.coverage.resolve():
        raise ValueError("refusing to overwrite source coverage")
    if not args.output.parent.is_dir():
        raise FileNotFoundError(f"output directory missing: {args.output.parent}")
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {args.output}")
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(proposal, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    result["file_action"] = f"CREATED: {args.output}"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
