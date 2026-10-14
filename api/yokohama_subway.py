"""Read-only, fail-closed OFFLINE loader for pinned Yokohama municipal subway GTFS.

A separately recorded file-integrity manifest is required. This does not
download ODPT data, enable route search, or certify pass fares/license rights.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from datetime import date, datetime
from pathlib import Path

from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata, TransitMode

FEED_ID = "yokohama_subway"
SOURCE_URL = "https://api.odpt.org/api/v4/files/odpt/YokohamaMunicipal/Train.zip?date=current"
RESOURCE_ID = "27ed8a34-c89f-4c5c-98af-5950f04183e2"
VERSION = "20251226"
VALID_FROM = date(2025, 12, 26)
VALID_UNTIL = date(2026, 12, 31)
MANIFEST = "yokohama_subway_gtfs_manifest.json"
REQUIRED_FILES = frozenset({
    "agency.txt", "feed_info.txt", "routes.txt", "stops.txt",
    "trips.txt", "stop_times.txt",
})


def _parse_day(text: str) -> date:
    if not isinstance(text, str):
        raise ValueError("subway service date must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("subway service date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != text:
        raise ValueError("subway service date must be zero-padded")
    return parsed


def _csv(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not set(columns).issubset(reader.fieldnames):
            raise ValueError(f"{path.name} missing expected columns")
        values = list(reader)
    if not values:
        raise ValueError(f"{path.name} has no rows")
    return values


def load_yokohama_subway_dataset(
    directory: str | Path, *, expected_service_date: str,
):
    """Validate edition, local bytes, GTFS identity, service day and rail mode.

    The manifest is local provenance, not independent proof of ODPT origin.
    """
    day = _parse_day(expected_service_date)
    if not VALID_FROM <= day <= VALID_UNTIL:
        raise ValueError("subway date outside catalog edition validity")
    root = Path(directory)
    manifest_path = root / MANIFEST
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    fields = {
        "source_url", "resource_id", "feed_version", "fetched_at",
        "valid_from", "valid_until", "validated_service_date", "files_sha256",
    }
    if not isinstance(raw, dict) or set(raw) != fields:
        raise ValueError("subway manifest schema mismatch")
    expected = {
        "source_url": SOURCE_URL,
        "resource_id": RESOURCE_ID,
        "feed_version": VERSION,
        "valid_from": VALID_FROM.isoformat(),
        "valid_until": VALID_UNTIL.isoformat(),
        "validated_service_date": day.isoformat(),
    }
    for key, expected_value in expected.items():
        if raw[key] != expected_value:
            raise ValueError(f"subway manifest {key} mismatch")
    try:
        fetched_at = datetime.fromisoformat(raw["fetched_at"])
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid subway fetched_at") from exc
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("subway fetched_at must be timezone-aware")

    hashes = raw["files_sha256"]
    files = {p.name for p in root.glob("*.txt") if p.is_file()}
    if (not isinstance(hashes, dict) or files != set(hashes)
            or not REQUIRED_FILES <= files
            or not {"calendar.txt", "calendar_dates.txt"} & files):
        raise ValueError("subway GTFS inventory/checksum list mismatch")
    for name, digest in hashes.items():
        if (not isinstance(name, str) or name != Path(name).name
                or not name.endswith(".txt") or not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
            raise ValueError("subway file checksum entry invalid")
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"subway checksum mismatch: {name}")

    feed = _csv(root / "feed_info.txt", ("feed_version",))
    if len(feed) != 1 or feed[0]["feed_version"] != VERSION:
        raise ValueError("subway feed_info version mismatch")
    if feed[0].get("feed_start_date") and date.fromisoformat(
        feed[0]["feed_start_date"]
    ) > day:
        raise ValueError("subway feed begins after requested date")
    if feed[0].get("feed_end_date") and date.fromisoformat(
        feed[0]["feed_end_date"]
    ) < day:
        raise ValueError("subway feed ends before requested date")
    agency = _csv(root / "agency.txt", ("agency_name", "agency_timezone"))
    if not any(row["agency_timezone"] == "Asia/Tokyo" for row in agency):
        raise ValueError("subway agency timezone mismatch")

    dataset = GtfsTransitAdapter.load(root, metadata=FeedMetadata(
        feed_id=FEED_ID, source_type="gtfs", source_uri=SOURCE_URL,
        version=VERSION, fetched_at=fetched_at,
    ))
    if any(route.mode is not TransitMode.RAIL for route in dataset.routes.values()):
        raise ValueError("subway contains non-rail route")
    if any(
        not math.isfinite(stop.lat) or not math.isfinite(stop.lon)
        or not (-90 <= stop.lat <= 90 and -180 <= stop.lon <= 180)
        for stop in dataset.stops.values()
    ):
        raise ValueError("subway contains invalid stop coordinates")
    active = dataset.active_service_ids(day)
    if not active or not any(t.service_id in active for t in dataset.trips.values()):
        raise ValueError("subway has no active trips for requested day")
    return dataset
