"""Read-only audit of Yokohama municipal-bus GTFS for pass eligibility review.

This is NOT a pass-coverage generator or a legal fare decision. It highlights
route names and timetable-only overnight indicators missing from GTFS-JP fare
metadata. It never writes to the GTFS directory or creates other files.

Usage:
  python scripts/audit_yokohama_bus_gtfs.py --gtfs-dir PATH
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

WELFARE_SOURCE = (
    "https://www.city.yokohama.lg.jp/faq/kukyoku/kenko/"
    "shogaijiritsu/20211015164324433.html"
)
SENIOR_SOURCE = (
    "https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/"
    "koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/"
    "ikigai-shakaisanka/keirou.html"
)
# The IDs below must still match actual route names from the feed.
KNOWN_NAMES = {
    "089": ("ぶらり野毛山動物園BUS", "listed_eligible"),
    "200": ("ベイサイドブルー", "listed_eligible"),
    "271": ("あかいくつ", "listed_excluded"),
    "280": ("ぶらり三溪園BUS", "listed_eligible"),
}


def _rows(path: Path, *, required: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or any(k not in reader.fieldnames for k in required):
            raise ValueError(f"{path.name} is missing columns: {required}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name} has no data rows")
    return rows


def _unique(rows: list[dict[str, str]], key: str, *, table: str) -> dict[str, dict[str, str]]:
    values = {}
    for row in rows:
        item_id = row[key]
        if not item_id or item_id in values:
            raise ValueError(f"{table} missing/duplicate {key}: {item_id!r}")
        values[item_id] = row
    return values


def _minutes(clock: str) -> int:
    pieces = clock.split(":")
    if len(pieces) != 3:
        raise ValueError(f"invalid GTFS time: {clock!r}")
    hour, minute, second = (int(x) for x in pieces)
    if hour < 0 or not 0 <= minute < 60 or not 0 <= second < 60:
        raise ValueError(f"invalid GTFS time: {clock!r}")
    return hour * 60 + minute


def audit(directory: Path) -> dict:
    manifest_path = directory / "yokohama_bus_gtfs_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Yokohama manifest must be an object")
    for key in ("feed_version", "revision", "validated_service_date", "source_url"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ValueError(f"Yokohama manifest missing {key}")

    feed_rows = _rows(directory / "feed_info.txt", required=("feed_version",))
    if len(feed_rows) != 1 or feed_rows[0]["feed_version"] != manifest["feed_version"]:
        raise ValueError("feed_info version does not match Yokohama GTFS manifest")

    routes = _unique(
        _rows(directory / "routes.txt", required=("route_id", "route_short_name", "route_long_name", "route_type")),
        "route_id", table="routes",
    )
    trips = _unique(
        _rows(directory / "trips.txt", required=("trip_id", "route_id", "jp_trip_desc", "jp_trip_desc_symbol")),
        "trip_id", table="trips",
    )
    for route_id, row in routes.items():
        if row["route_type"] != "3":
            raise ValueError(f"unexpected non-bus route type: {route_id}")
        if not row["route_short_name"] and not row["route_long_name"]:
            raise ValueError(f"route lacks both names: {route_id}")
    trips_per_route: Counter[str] = Counter()
    for trip_id, row in trips.items():
        if row["route_id"] not in routes:
            raise ValueError(f"unknown route for trip: {trip_id}")
        trips_per_route[row["route_id"]] += 1

    late_trip_ids: set[str] = set()
    seen_stop_times = 0
    with (directory / "stop_times.txt").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not {"trip_id", "arrival_time", "departure_time"}.issubset(reader.fieldnames):
            raise ValueError("stop_times.txt missing required columns")
        for row in reader:
            seen_stop_times += 1
            trip_id = row["trip_id"]
            if trip_id not in trips:
                raise ValueError(f"stop_times references unknown trip: {trip_id}")
            for key in ("arrival_time", "departure_time"):
                if row[key] and _minutes(row[key]) >= 23 * 60:
                    late_trip_ids.add(trip_id)
    if not seen_stop_times:
        raise ValueError("stop_times.txt has no data rows")

    late_counts: Counter[str] = Counter(trips[trip_id]["route_id"] for trip_id in late_trip_ids)
    special = []
    for route_id in sorted(routes):
        route = routes[route_id]
        short = route["route_short_name"].strip()
        long = route["route_long_name"].strip()
        expected = KNOWN_NAMES.get(route_id)
        if expected is not None:
            if expected[0] not in long:
                raise ValueError(
                    f"known policy route {route_id} changed name: "
                    f"expected {expected[0]!r}, actual {long!r}"
                )
            review = expected[1]
        elif short != f"{route_id}系統":
            review = "manual_route_review_required"
        else:
            review = "ordinary_name_only_not_fare_verified"
        if review != "ordinary_name_only_not_fare_verified" or late_counts[route_id]:
            special.append({
                "route_id": route_id,
                "short_name": short,
                "long_name": long,
                "trips": trips_per_route[route_id],
                "late_clock_trips": late_counts[route_id],
                "review": review,
            })

    return {
        "feed_version": manifest["feed_version"],
        "revision": manifest["revision"],
        "validated_service_date": manifest["validated_service_date"],
        "route_count": len(routes),
        "trip_count": len(trips),
        "stop_time_count": seen_stop_times,
        "fare_files_present": {
            name: (directory / name).is_file()
            for name in ("fare_attributes.txt", "fare_rules.txt")
        },
        "trip_descriptions_populated": sum(
            bool(row["jp_trip_desc"].strip() or row["jp_trip_desc_symbol"].strip())
            for row in trips.values()
        ),
        "late_clock_trip_count": len(late_trip_ids),
        "special_and_late_routes": special,
        "official_references": [WELFARE_SOURCE, SENIOR_SOURCE],
        "warning": (
            "GTFS clocks at/after 23:00 are REVIEW FLAGS, NOT proof of a deep-night surcharge; "
            "earlier premium services may also exist. This audit cannot certify 0-yen fares."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs-dir", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.gtfs_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
