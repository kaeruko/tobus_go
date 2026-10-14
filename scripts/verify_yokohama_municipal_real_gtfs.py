"""Read-only cross-feed real GTFS acceptance probe for Yokohama Issue #241.

Both bus and subway directories must contain their existing pinned manifests.
A reviewed, version-locked walking-link JSON must be supplied explicitly.
Missing inputs or an unverified transfer stop this probe; NEVER estimate it.

This does not write files, download GTFS or access secrets. The selected OD
must actually produce a two-feed scheduled journey for BOTH passes.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from yokohama_fare_coverage import YokohamaFareCoverage
from yokohama_municipal_backend import load_reviewed_transfer_links
from yokohama_real_gtfs_acceptance import check_real_municipal_od
from yokohama_subway import load_reviewed_yokohama_subway_coverage
from yokohama_transit import load_yokohama_bus_dataset


def _date(value: str) -> date:
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError("service-date must be zero-padded YYYY-MM-DD")
    return result


def _time(value: str) -> tuple[int, int]:
    if (not isinstance(value, str) or len(value) != 5
            or value[2] != ":" or not value[:2].isascii()
            or not value[3:].isascii() or not value[:2].isdigit()
            or not value[3:].isdigit()):
        raise ValueError("start-time must be HH:MM with ASCII digits")
    hour, minute = int(value[:2]), int(value[3:])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("start-time must be 00:00..23:59")
    return hour, minute


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus-gtfs-dir", required=True, type=Path)
    parser.add_argument("--bus-coverage", required=True, type=Path)
    parser.add_argument("--subway-gtfs-dir", required=True, type=Path)
    parser.add_argument("--reviewed-links", required=True, type=Path)
    parser.add_argument("--service-date", required=True)
    parser.add_argument("--start-time", required=True)
    parser.add_argument("--origin-stop-id", required=True)
    parser.add_argument("--destination-stop-id", required=True)
    parser.add_argument("--bus-transfer-stop-id", required=True)
    parser.add_argument("--subway-transfer-stop-id", required=True)
    args = parser.parse_args()

    date_value = _date(args.service_date)
    hour, minute = _time(args.start_time)
    for path in (args.bus_gtfs_dir, args.subway_gtfs_dir):
        if not path.is_dir():
            raise FileNotFoundError(path)
    for path in (args.bus_coverage, args.reviewed_links):
        if not path.is_file():
            raise FileNotFoundError(path)

    # Both loaders verify pinned provenance, GTFS revision, active service and
    # SHA-256 manifests before *any* path is approved.
    bus_dataset = load_yokohama_bus_dataset(
        args.bus_gtfs_dir, expected_service_date=args.service_date,
    )
    bus_coverage = YokohamaFareCoverage.load(args.bus_coverage, dataset=bus_dataset)
    subway_coverage = load_reviewed_yokohama_subway_coverage(
        args.subway_gtfs_dir, expected_service_date=args.service_date,
    )
    reviewed_links = load_reviewed_transfer_links(
        args.reviewed_links, bus_coverage, subway_coverage,
    )
    summary = check_real_municipal_od(
        bus_coverage=bus_coverage, subway_coverage=subway_coverage,
        transfer_links=reviewed_links,
        bus_transfer_stop_id=args.bus_transfer_stop_id,
        subway_transfer_stop_id=args.subway_transfer_stop_id,
        origin_stop_id=args.origin_stop_id,
        destination_stop_id=args.destination_stop_id,
        departure=datetime(date_value.year, date_value.month, date_value.day,
                           hour, minute, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
