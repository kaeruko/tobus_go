from __future__ import annotations

import hashlib
import json
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

SENDAI_FEED_ID = "sendai_bus"
SENDAI_STATIC_URL = (
    "https://api.odpt.org/api/v4/files/odpt/SendaiMunicipal/"
    "bus_realtime_information.zip?date=current"
)
SENDAI_MANIFEST_FILENAME = "sendai_gtfs_manifest.json"
_REQUIRED_GTFS_FILES = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")


@dataclass(frozen=True, slots=True)
class SendaiGtfsManifest:
    source_url: str
    validated_service_date: str
    fetched_at: datetime
    sha256: str
    valid_from: str
    valid_until: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "SendaiGtfsManifest":
        required = (
            "source_url",
            "validated_service_date",
            "fetched_at",
            "sha256",
            "valid_from",
            "valid_until",
        )
        for key in required:
            if key not in value:
                raise ValueError(f"Sendai GTFS manifest is missing {key}")
        try:
            fetched_at = datetime.fromisoformat(str(value["fetched_at"]))
        except ValueError as error:
            raise ValueError("Sendai GTFS manifest has invalid fetched_at") from error
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("Sendai GTFS manifest fetched_at must be timezone-aware")
        manifest = cls(
            source_url=str(value["source_url"]),
            validated_service_date=_validate_date(str(value["validated_service_date"])),
            fetched_at=fetched_at,
            sha256=str(value["sha256"]),
            valid_from=_validate_date(str(value["valid_from"])),
            valid_until=_validate_date(str(value["valid_until"])),
        )
        if manifest.source_url != SENDAI_STATIC_URL:
            raise ValueError(f"Unexpected Sendai GTFS source_url: {manifest.source_url!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", manifest.sha256):
            raise ValueError("Sendai GTFS manifest has invalid sha256")
        if manifest.valid_until < manifest.valid_from:
            raise ValueError("Sendai GTFS manifest valid_until precedes valid_from")
        return manifest

    def to_mapping(self) -> dict[str, str]:
        return {
            "source_url": self.source_url,
            "validated_service_date": self.validated_service_date,
            "fetched_at": self.fetched_at.isoformat(),
            "sha256": self.sha256,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
        }


def _validate_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError(f"invalid service date {value!r}; expected YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise ValueError(f"invalid service date {value!r}; expected zero-padded YYYY-MM-DD")
    return value


def required_expected_service_date() -> str:
    value = os.getenv("SENDAI_GTFS_EXPECTED_SERVICE_DATE")
    if value is None or value == "":
        raise RuntimeError(
            "SENDAI_GTFS_EXPECTED_SERVICE_DATE is required for Sendai runtime"
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
            raise RuntimeError(f"Unsafe path in Sendai GTFS ZIP: {member.filename}")
        by_basename.setdefault(path.name, []).append(member)

    selected: dict[str, zipfile.ZipInfo] = {}
    for basename in set(_REQUIRED_GTFS_FILES) | {"calendar.txt", "calendar_dates.txt"}:
        matches = by_basename.get(basename, [])
        if len(matches) > 1:
            raise RuntimeError(f"Sendai GTFS ZIP contains multiple {basename} files")
        if matches:
            selected[basename] = matches[0]
    for required in _REQUIRED_GTFS_FILES:
        if required not in selected:
            raise RuntimeError(f"Sendai GTFS ZIP is missing {required}")
    if "calendar.txt" not in selected and "calendar_dates.txt" not in selected:
        raise RuntimeError("Sendai GTFS ZIP requires calendar.txt or calendar_dates.txt")
    return selected


def _coverage(dataset: TransitDataset) -> tuple[date, date]:
    days: list[date] = []
    for calendar in dataset.calendars.values():
        days.extend((calendar.start_date, calendar.end_date))
    days.extend(exception.day for exception in dataset.service_exceptions)
    if not days:
        raise ValueError("Sendai GTFS has no calendar coverage dates")
    return min(days), max(days)


def _metadata(*, service_date: str, fetched_at: datetime) -> FeedMetadata:
    return FeedMetadata(
        feed_id=SENDAI_FEED_ID,
        source_type="gtfs-jp",
        source_uri=SENDAI_STATIC_URL,
        version=f"service-date:{service_date}",
        fetched_at=fetched_at,
    )


def _validate_bus_dataset(dataset: TransitDataset, service_date: str) -> None:
    non_bus = [
        route.id for route in dataset.routes.values() if route.mode is not TransitMode.BUS
    ]
    if non_bus:
        raise ValueError(
            "Sendai municipal bus feed unexpectedly contains non-bus route: "
            f"{non_bus[0]}"
        )
    requested = datetime.strptime(service_date, "%Y-%m-%d").date()
    if not dataset.active_service_ids(requested):
        raise RuntimeError(
            "Sendai GTFS has no active service on expected date: "
            f"{service_date}"
        )


def fetch_sendai_gtfs(
    output_dir: str | Path,
    *,
    expected_service_date: str,
    consumer_key: str,
    client: httpx.Client | None = None,
) -> SendaiGtfsManifest:
    expected_service_date = _validate_date(expected_service_date)
    if not consumer_key:
        raise ValueError("consumer_key is required for Sendai static GTFS download")
    target = Path(output_dir)
    if target.exists():
        raise FileExistsError(
            "Sendai GTFS output already exists; choose a new version directory: "
            f"{target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)

    owns_client = client is None
    http_client = client or httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        response = http_client.get(
            SENDAI_STATIC_URL,
            params={"acl:consumerKey": consumer_key},
        )
        response.raise_for_status()
        archive_bytes = response.content
        if not archive_bytes:
            raise RuntimeError("Downloaded Sendai GTFS ZIP is empty")
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

        fetched_at = datetime.now(timezone.utc)
        dataset = GtfsTransitAdapter.load(
            feed_dir,
            metadata=_metadata(
                service_date=expected_service_date,
                fetched_at=fetched_at,
            ),
        )
        _validate_bus_dataset(dataset, expected_service_date)
        valid_from, valid_until = _coverage(dataset)
        manifest = SendaiGtfsManifest(
            source_url=SENDAI_STATIC_URL,
            validated_service_date=expected_service_date,
            fetched_at=fetched_at,
            sha256=hashlib.sha256(archive_bytes).hexdigest(),
            valid_from=valid_from.isoformat(),
            valid_until=valid_until.isoformat(),
        )
        (feed_dir / SENDAI_MANIFEST_FILENAME).write_text(
            json.dumps(manifest.to_mapping(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(feed_dir, target)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def load_sendai_dataset(
    gtfs_dir: str | Path,
    *,
    expected_service_date: str,
) -> TransitDataset:
    expected_service_date = _validate_date(expected_service_date)
    root = Path(gtfs_dir)
    manifest_path = root / SENDAI_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Sendai GTFS manifest must be a JSON object")
    manifest = SendaiGtfsManifest.from_mapping(raw)
    if manifest.validated_service_date != expected_service_date:
        raise RuntimeError(
            "Sendai GTFS expected service date mismatch: "
            f"expected={expected_service_date}, installed={manifest.validated_service_date}"
        )
    requested = datetime.strptime(expected_service_date, "%Y-%m-%d").date()
    if not (
        datetime.strptime(manifest.valid_from, "%Y-%m-%d").date()
        <= requested
        <= datetime.strptime(manifest.valid_until, "%Y-%m-%d").date()
    ):
        raise RuntimeError(
            "Sendai GTFS expected service date is outside manifest coverage: "
            f"date={expected_service_date}, coverage={manifest.valid_from}..{manifest.valid_until}"
        )
    dataset = GtfsTransitAdapter.load(
        root,
        metadata=_metadata(
            service_date=expected_service_date,
            fetched_at=manifest.fetched_at,
        ),
    )
    _validate_bus_dataset(dataset, expected_service_date)
    return dataset


class SendaiRouteBackend(GtfsRouteBackend):
    def __init__(self, dataset: TransitDataset, **kwargs: Any) -> None:
        if dataset.metadata.feed_id != SENDAI_FEED_ID:
            raise ValueError(f"SendaiRouteBackend requires {SENDAI_FEED_ID} dataset")
        super().__init__(dataset, **kwargs)
