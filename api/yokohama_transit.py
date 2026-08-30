from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from gtfs_route_backend import GtfsRouteBackend
from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata, TransitDataset, TransitMode

YOKOHAMA_BUS_FEED_ID = "yokohama_bus"
YOKOHAMA_BUS_STATIC_URL = (
    "https://api.odpt.org/api/v4/files/odpt/YokohamaMunicipal/Bus.zip?date=current"
)
YOKOHAMA_BUS_RESOURCE_ID = "1f099583-33d3-4017-a42f-1448571142fc"
YOKOHAMA_BUS_APPROVED_REVISION = "20260727"
YOKOHAMA_BUS_APPROVED_FEED_VERSION = "v3.0_20260727"
YOKOHAMA_BUS_APPROVED_VALID_FROM = "2026-07-27"
YOKOHAMA_BUS_APPROVED_VALID_UNTIL = "2027-07-26"
YOKOHAMA_BUS_MANIFEST_FILENAME = "yokohama_bus_gtfs_manifest.json"

_REQUIRED_GTFS_FILES = (
    "stops.txt",
    "routes.txt",
    "trips.txt",
    "stop_times.txt",
    "feed_info.txt",
)


@dataclass(frozen=True, slots=True)
class YokohamaBusGtfsManifest:
    source_url: str
    resource_id: str
    revision: str
    feed_version: str
    validated_service_date: str
    fetched_at: datetime
    sha256: str
    valid_from: str
    valid_until: str
    calendar_coverage_from: str
    calendar_coverage_until: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "YokohamaBusGtfsManifest":
        required = (
            "source_url",
            "resource_id",
            "revision",
            "feed_version",
            "validated_service_date",
            "fetched_at",
            "sha256",
            "valid_from",
            "valid_until",
            "calendar_coverage_from",
            "calendar_coverage_until",
        )
        for key in required:
            if key not in value:
                raise ValueError(f"Yokohama bus GTFS manifest is missing {key}")
        try:
            fetched_at = datetime.fromisoformat(str(value["fetched_at"]))
        except ValueError as error:
            raise ValueError("Yokohama bus GTFS manifest has invalid fetched_at") from error
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("Yokohama bus GTFS manifest fetched_at must be timezone-aware")

        manifest = cls(
            source_url=str(value["source_url"]),
            resource_id=str(value["resource_id"]),
            revision=str(value["revision"]),
            feed_version=str(value["feed_version"]),
            validated_service_date=_validate_date(str(value["validated_service_date"])),
            fetched_at=fetched_at,
            sha256=str(value["sha256"]),
            valid_from=_validate_date(str(value["valid_from"])),
            valid_until=_validate_date(str(value["valid_until"])),
            calendar_coverage_from=_validate_date(str(value["calendar_coverage_from"])),
            calendar_coverage_until=_validate_date(str(value["calendar_coverage_until"])),
        )
        _validate_manifest_identity(manifest)
        if not re.fullmatch(r"[0-9a-f]{64}", manifest.sha256):
            raise ValueError("Yokohama bus GTFS manifest has invalid sha256")
        if manifest.valid_until < manifest.valid_from:
            raise ValueError("Yokohama bus GTFS manifest valid_until precedes valid_from")
        if manifest.calendar_coverage_until < manifest.calendar_coverage_from:
            raise ValueError(
                "Yokohama bus GTFS manifest calendar coverage end precedes start"
            )
        return manifest

    def to_mapping(self) -> dict[str, str]:
        return {
            "source_url": self.source_url,
            "resource_id": self.resource_id,
            "revision": self.revision,
            "feed_version": self.feed_version,
            "validated_service_date": self.validated_service_date,
            "fetched_at": self.fetched_at.isoformat(),
            "sha256": self.sha256,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "calendar_coverage_from": self.calendar_coverage_from,
            "calendar_coverage_until": self.calendar_coverage_until,
        }


def _validate_manifest_identity(manifest: YokohamaBusGtfsManifest) -> None:
    expected = {
        "source_url": YOKOHAMA_BUS_STATIC_URL,
        "resource_id": YOKOHAMA_BUS_RESOURCE_ID,
        "revision": YOKOHAMA_BUS_APPROVED_REVISION,
        "feed_version": YOKOHAMA_BUS_APPROVED_FEED_VERSION,
        "valid_from": YOKOHAMA_BUS_APPROVED_VALID_FROM,
        "valid_until": YOKOHAMA_BUS_APPROVED_VALID_UNTIL,
    }
    for field, expected_value in expected.items():
        actual = getattr(manifest, field)
        if actual != expected_value:
            raise ValueError(
                f"Unexpected Yokohama bus GTFS {field}: "
                f"expected={expected_value!r}, actual={actual!r}"
            )


def _validate_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError(f"invalid service date {value!r}; expected YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise ValueError(f"invalid service date {value!r}; expected zero-padded YYYY-MM-DD")
    return value


def required_expected_service_date() -> str:
    value = os.getenv("YOKOHAMA_BUS_GTFS_EXPECTED_SERVICE_DATE")
    if value is None or value == "":
        raise RuntimeError(
            "YOKOHAMA_BUS_GTFS_EXPECTED_SERVICE_DATE is required for Yokohama bus GTFS"
        )
    return _validate_date(value)


def _safe_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    by_basename: dict[str, list[zipfile.ZipInfo]] = {}
    for member in archive.infolist():
        if member.is_dir():
            continue
        normalized = member.filename.replace("\\", "/")
        path = Path(normalized)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(
                f"Unsafe path in Yokohama bus GTFS ZIP: {member.filename}"
            )
        by_basename.setdefault(path.name, []).append(member)

    selected: dict[str, zipfile.ZipInfo] = {}
    optional = {"calendar.txt", "calendar_dates.txt"}
    for basename in set(_REQUIRED_GTFS_FILES) | optional:
        matches = by_basename.get(basename, [])
        if len(matches) > 1:
            raise RuntimeError(
                f"Yokohama bus GTFS ZIP contains multiple {basename} files"
            )
        if matches:
            selected[basename] = matches[0]

    for required in _REQUIRED_GTFS_FILES:
        if required not in selected:
            raise RuntimeError(f"Yokohama bus GTFS ZIP is missing {required}")
    if "calendar.txt" not in selected and "calendar_dates.txt" not in selected:
        raise RuntimeError(
            "Yokohama bus GTFS ZIP requires calendar.txt or calendar_dates.txt"
        )
    return selected


def _coverage(dataset: TransitDataset) -> tuple[date, date]:
    days: list[date] = []
    for calendar in dataset.calendars.values():
        days.extend((calendar.start_date, calendar.end_date))
    days.extend(exception.day for exception in dataset.service_exceptions)
    if not days:
        raise ValueError("Yokohama bus GTFS has no calendar coverage dates")
    return min(days), max(days)


def _read_feed_info(root: Path) -> tuple[str, str, str]:
    path = root / "feed_info.txt"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
    if len(rows) != 1:
        raise ValueError(
            f"Yokohama bus feed_info.txt must contain exactly one row; got {len(rows)}"
        )
    row = rows[0]
    feed_version = row.get("feed_version") or ""
    start_raw = row.get("feed_start_date") or ""
    end_raw = row.get("feed_end_date") or ""
    try:
        valid_from = datetime.strptime(start_raw, "%Y%m%d").date().isoformat()
        valid_until = datetime.strptime(end_raw, "%Y%m%d").date().isoformat()
    except ValueError as error:
        raise ValueError("Yokohama bus feed_info.txt has invalid coverage date") from error
    return feed_version, valid_from, valid_until


def _validate_approved_feed_info(root: Path) -> tuple[str, str, str]:
    feed_version, valid_from, valid_until = _read_feed_info(root)
    expected = (
        YOKOHAMA_BUS_APPROVED_FEED_VERSION,
        YOKOHAMA_BUS_APPROVED_VALID_FROM,
        YOKOHAMA_BUS_APPROVED_VALID_UNTIL,
    )
    actual = (feed_version, valid_from, valid_until)
    if actual != expected:
        raise RuntimeError(
            "Yokohama bus GTFS resource changed from the explicitly approved revision: "
            f"expected={expected!r}, actual={actual!r}. "
            "Review the new ODPT resource before updating constants."
        )
    return actual


def _metadata(*, fetched_at: datetime) -> FeedMetadata:
    return FeedMetadata(
        feed_id=YOKOHAMA_BUS_FEED_ID,
        source_type="gtfs-jp",
        source_uri=YOKOHAMA_BUS_STATIC_URL,
        version=YOKOHAMA_BUS_APPROVED_FEED_VERSION,
        fetched_at=fetched_at,
    )


def _validate_stop_coordinates(dataset: TransitDataset) -> None:
    for stop in dataset.stops.values():
        if not math.isfinite(stop.lat) or not math.isfinite(stop.lon):
            raise ValueError(
                f"Yokohama bus stop has non-finite coordinates: {stop.source_id}"
            )
        if stop.lat < -90.0 or stop.lat > 90.0:
            raise ValueError(
                f"Yokohama bus stop latitude is out of range: "
                f"{stop.source_id}={stop.lat}"
            )
        if stop.lon < -180.0 or stop.lon > 180.0:
            raise ValueError(
                f"Yokohama bus stop longitude is out of range: "
                f"{stop.source_id}={stop.lon}"
            )
        if stop.lat == 0.0 and stop.lon == 0.0:
            raise ValueError(
                f"Yokohama bus stop coordinates must not be 0,0: {stop.source_id}"
            )


def _validate_bus_dataset(dataset: TransitDataset, service_date: str) -> None:
    non_bus = [
        route.id for route in dataset.routes.values() if route.mode is not TransitMode.BUS
    ]
    if non_bus:
        raise ValueError(
            "Yokohama municipal bus feed unexpectedly contains non-bus route: "
            f"{non_bus[0]}"
        )
    _validate_stop_coordinates(dataset)
    requested = datetime.strptime(service_date, "%Y-%m-%d").date()
    if not dataset.active_service_ids(requested):
        raise RuntimeError(
            "Yokohama bus GTFS has no active service on expected date: "
            f"{service_date}"
        )


def _validate_service_date_is_approved(service_date: str) -> None:
    if not (
        YOKOHAMA_BUS_APPROVED_VALID_FROM
        <= service_date
        <= YOKOHAMA_BUS_APPROVED_VALID_UNTIL
    ):
        raise RuntimeError(
            "Yokohama bus expected service date is outside the approved GTFS resource: "
            f"date={service_date}, "
            f"coverage={YOKOHAMA_BUS_APPROVED_VALID_FROM}.."
            f"{YOKOHAMA_BUS_APPROVED_VALID_UNTIL}"
        )


def fetch_yokohama_bus_gtfs(
    output_dir: str | Path,
    *,
    expected_service_date: str,
    consumer_key: str,
    client: httpx.Client | None = None,
) -> YokohamaBusGtfsManifest:
    expected_service_date = _validate_date(expected_service_date)
    _validate_service_date_is_approved(expected_service_date)
    if not consumer_key:
        raise ValueError("consumer_key is required for Yokohama bus GTFS download")

    target = Path(output_dir)
    if target.exists():
        raise FileExistsError(
            "Yokohama bus GTFS output already exists; choose a new version directory: "
            f"{target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)

    owns_client = client is None
    http_client = client or httpx.Client(timeout=60.0, follow_redirects=True)
    try:
        response = http_client.get(
            YOKOHAMA_BUS_STATIC_URL,
            params={
                "date": "current",
                "acl:consumerKey": consumer_key,
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise RuntimeError(
                "Yokohama bus GTFS download failed: "
                f"HTTP {error.response.status_code} for {YOKOHAMA_BUS_STATIC_URL}"
            ) from None
        archive_bytes = response.content
        if not archive_bytes:
            raise RuntimeError("Downloaded Yokohama bus GTFS ZIP is empty")
    finally:
        if owns_client:
            http_client.close()

    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=str(target.parent)))
    try:
        archive_path = staging / "source.zip"
        archive_path.write_bytes(archive_bytes)
        feed_dir = staging / "feed"
        feed_dir.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            for basename, member in _safe_members(archive).items():
                with archive.open(member) as source, (feed_dir / basename).open("wb") as dest:
                    shutil.copyfileobj(source, dest)
        archive_path.unlink()

        feed_version, valid_from, valid_until = _validate_approved_feed_info(feed_dir)
        fetched_at = datetime.now(timezone.utc)
        dataset = GtfsTransitAdapter.load(
            feed_dir,
            metadata=_metadata(fetched_at=fetched_at),
        )
        _validate_bus_dataset(dataset, expected_service_date)
        coverage_from, coverage_until = _coverage(dataset)

        manifest = YokohamaBusGtfsManifest(
            source_url=YOKOHAMA_BUS_STATIC_URL,
            resource_id=YOKOHAMA_BUS_RESOURCE_ID,
            revision=YOKOHAMA_BUS_APPROVED_REVISION,
            feed_version=feed_version,
            validated_service_date=expected_service_date,
            fetched_at=fetched_at,
            sha256=hashlib.sha256(archive_bytes).hexdigest(),
            valid_from=valid_from,
            valid_until=valid_until,
            calendar_coverage_from=coverage_from.isoformat(),
            calendar_coverage_until=coverage_until.isoformat(),
        )
        (feed_dir / YOKOHAMA_BUS_MANIFEST_FILENAME).write_text(
            json.dumps(manifest.to_mapping(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(feed_dir, target)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def load_yokohama_bus_dataset(
    gtfs_dir: str | Path, *, expected_service_date: str
) -> TransitDataset:
    expected_service_date = _validate_date(expected_service_date)
    _validate_service_date_is_approved(expected_service_date)
    root = Path(gtfs_dir)
    manifest_path = root / YOKOHAMA_BUS_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Yokohama bus GTFS manifest must be a JSON object")
    manifest = YokohamaBusGtfsManifest.from_mapping(raw)
    if manifest.validated_service_date != expected_service_date:
        raise RuntimeError(
            "Yokohama bus GTFS expected service date mismatch: "
            f"expected={expected_service_date}, installed={manifest.validated_service_date}"
        )

    _validate_approved_feed_info(root)
    dataset = GtfsTransitAdapter.load(
        root,
        metadata=FeedMetadata(
            feed_id=YOKOHAMA_BUS_FEED_ID,
            source_type="gtfs-jp",
            source_uri=manifest.source_url,
            version=manifest.feed_version,
            fetched_at=manifest.fetched_at,
        ),
    )
    _validate_bus_dataset(dataset, expected_service_date)
    coverage_from, coverage_until = _coverage(dataset)
    if (
        coverage_from.isoformat() != manifest.calendar_coverage_from
        or coverage_until.isoformat() != manifest.calendar_coverage_until
    ):
        raise RuntimeError(
            "Yokohama bus GTFS calendar coverage does not match manifest: "
            f"manifest={manifest.calendar_coverage_from}.."
            f"{manifest.calendar_coverage_until}, "
            f"actual={coverage_from.isoformat()}..{coverage_until.isoformat()}"
        )
    return dataset


class YokohamaBusRouteBackend(GtfsRouteBackend):
    def __init__(self, dataset: TransitDataset, **kwargs: Any) -> None:
        if dataset.metadata.feed_id != YOKOHAMA_BUS_FEED_ID:
            raise ValueError(
                f"YokohamaBusRouteBackend requires {YOKOHAMA_BUS_FEED_ID} dataset"
            )
        super().__init__(dataset, **kwargs)
