from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
import csv
from urllib.parse import urlsplit, parse_qs
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from gtfs_route_backend import GtfsRouteEngine
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
    file_sha256: dict[str, str]
    published_version: str | None = None
    schema_version: int = 2

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "SendaiGtfsManifest":
        if value.get("schema_version") != 2:
            raise ValueError("Sendai GTFS manifest schema 2 with source ZIP/file integrity is required")
        required = (
            "source_url",
            "validated_service_date",
            "fetched_at",
            "sha256",
            "valid_from",
            "valid_until",
            "file_sha256",
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
            file_sha256=value["file_sha256"],
            published_version=value.get("published_version"),
        )
        _validate_source_url(manifest.source_url)
        if (not isinstance(manifest.file_sha256, dict) or not manifest.file_sha256
                or any(not isinstance(k, str) or k not in _GTFS_FILES or
                    not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None
                    for k,v in manifest.file_sha256.items())):
            raise ValueError("invalid exact GTFS file hash inventory")
        if manifest.published_version is not None and (not isinstance(manifest.published_version, str)
                or not manifest.published_version.strip()):
            raise ValueError("invalid published feed version")
        if not re.fullmatch(r"[0-9a-f]{64}", manifest.sha256):
            raise ValueError("Sendai GTFS manifest has invalid sha256")
        if manifest.valid_until < manifest.valid_from:
            raise ValueError("Sendai GTFS manifest valid_until precedes valid_from")
        return manifest

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "file_sha256": self.file_sha256,
            "published_version": self.published_version,
            "source_url": self.source_url,
            "validated_service_date": self.validated_service_date,
            "fetched_at": self.fetched_at.isoformat(),
            "sha256": self.sha256,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
        }


_GTFS_FILES = set(_REQUIRED_GTFS_FILES) | {"calendar.txt", "calendar_dates.txt", "feed_info.txt", "agency.txt", "pattern_jp.txt", "shapes.txt"}
SOURCE_ARCHIVE = "sendai_gtfs_source.zip"


def _validate_source_url(url):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    if (parsed.scheme != "https" or parsed.netloc not in ("api.odpt.org", "api-public.odpt.org")
            or parsed.path != "/api/v4/files/odpt/SendaiMunicipal/bus_realtime_information.zip"
            or set(query) != {"date"} or len(query["date"]) != 1
            or (query["date"][0] != "current" and re.fullmatch(r"[0-9]{8}", query["date"][0]) is None)
            or parsed.fragment):
        raise ValueError("explicit official Sendai municipal GTFS source URL required")
    return parsed


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
    for basename in _GTFS_FILES:
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


def _metadata(*, service_date: str, fetched_at: datetime, source_url=SENDAI_STATIC_URL, sha256=None) -> FeedMetadata:
    return FeedMetadata(
        feed_id=SENDAI_FEED_ID,
        source_type="gtfs-jp",
        source_uri=source_url,
        version=f"sha256:{sha256}" if sha256 is not None else f"service-date:{service_date}",
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
    consumer_key: str | None = None,
    source_url: str = SENDAI_STATIC_URL,
    expected_sha256: str | None = None,
    client: httpx.Client | None = None,
) -> SendaiGtfsManifest:
    expected_service_date = _validate_date(expected_service_date)
    parsed = _validate_source_url(source_url)
    if parsed.hostname == "api.odpt.org" and not consumer_key:
        raise ValueError("consumer_key is required for authenticated Sendai static GTFS download")
    if expected_sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("expected_sha256 must be a lower-case SHA-256")
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
        params = None if parsed.hostname == "api-public.odpt.org" else {"acl:consumerKey": consumer_key}
        response = http_client.get(source_url, params=params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise RuntimeError(
                "Sendai GTFS download failed: "
                f"HTTP {error.response.status_code} for {source_url}"
            ) from None
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
        actual_sha = hashlib.sha256(archive_bytes).hexdigest()
        if expected_sha256 is not None and actual_sha != expected_sha256:
            raise ValueError("official Sendai GTFS ZIP SHA-256 mismatch")
        shutil.copyfile(archive_path, feed_dir / SOURCE_ARCHIVE)

        fetched_at = datetime.now(timezone.utc)
        dataset = GtfsTransitAdapter.load(
            feed_dir,
            metadata=_metadata(
                service_date=expected_service_date,
                fetched_at=fetched_at, source_url=source_url, sha256=actual_sha,
            ),
        )
        _validate_bus_dataset(dataset, expected_service_date)
        valid_from, valid_until = _coverage(dataset)
        manifest = SendaiGtfsManifest(
            source_url=source_url,
            validated_service_date=expected_service_date,
            fetched_at=fetched_at,
            sha256=hashlib.sha256(archive_bytes).hexdigest(),
            valid_from=valid_from.isoformat(),
            valid_until=valid_until.isoformat(),
            file_sha256={f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                         for f in feed_dir.iterdir() if f.name in _GTFS_FILES},
            published_version=_published_version(feed_dir),
        )
        verify_sendai_bundle(feed_dir, manifest)
        (feed_dir / SENDAI_MANIFEST_FILENAME).write_text(
            json.dumps(manifest.to_mapping(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(feed_dir, target)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _published_version(root):
    path = root / "feed_info.txt"
    if not path.is_file():
        return None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1 or rows[0].get("feed_publisher_name") != "仙台市交通局":
        raise ValueError("official municipal feed_info publisher required")
    for field in ("feed_start_date", "feed_end_date"):
        value = rows[0].get(field, "")
        if not re.fullmatch(r"[0-9]{8}", value):
            raise ValueError("explicit published Sendai feed date range required")
        datetime.strptime(value, "%Y%m%d")
    return rows[0].get("feed_version") or None


def verify_sendai_bundle(root, manifest):
    """Read-only exact source ZIP, extracted bytes and complete input inventory."""
    archive = root / SOURCE_ARCHIVE
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest.sha256:
        raise ValueError("Sendai GTFS source ZIP SHA-256 mismatch")
    with zipfile.ZipFile(archive) as z:
        members = _safe_members(z)
        if set(members) != set(manifest.file_sha256):
            raise ValueError("Sendai GTFS input inventory differs from manifest/source ZIP")
        for name, member in members.items():
            raw = (root / name).read_bytes()
            if raw != z.read(member) or hashlib.sha256(raw).hexdigest() != manifest.file_sha256[name]:
                raise ValueError(f"Sendai GTFS extracted file integrity mismatch: {name}")
    if {p.name for p in root.iterdir() if p.name in _GTFS_FILES} != set(manifest.file_sha256):
        raise ValueError("unmanifested Sendai GTFS input file")
    if _published_version(root) != manifest.published_version:
        raise ValueError("published Sendai feed version mismatch")
    if (root / "feed_info.txt").is_file():
        with (root / "feed_info.txt").open(encoding="utf-8-sig", newline="") as handle:
            info = next(csv.DictReader(handle))
        declared = tuple(datetime.strptime(info[key], "%Y%m%d").date().isoformat()
                         for key in ("feed_start_date", "feed_end_date"))
        if declared != (manifest.valid_from, manifest.valid_until):
            raise ValueError("Sendai feed_info and calendar coverage mismatch")


def load_sendai_dataset(
    gtfs_dir: str | Path, *, expected_service_date: str
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
    verify_sendai_bundle(root, manifest)
    dataset = GtfsTransitAdapter.load(
        root,
        metadata=FeedMetadata(
            feed_id=SENDAI_FEED_ID,
            source_type="gtfs-jp",
            source_uri=manifest.source_url,
            version=f"sha256:{manifest.sha256}",
            fetched_at=manifest.fetched_at,
        ),
    )
    _validate_bus_dataset(dataset, expected_service_date)
    actual_from, actual_until = _coverage(dataset)
    if (actual_from.isoformat(), actual_until.isoformat()) != (manifest.valid_from, manifest.valid_until):
        raise ValueError("Sendai GTFS manifest calendar coverage mismatch")
    if not manifest.valid_from <= expected_service_date <= manifest.valid_until:
        raise ValueError("Sendai GTFS approval date outside published coverage")
    return dataset


class SendaiRouteBackend(GtfsRouteEngine):
    def __init__(self, dataset: TransitDataset, **kwargs: Any) -> None:
        if dataset.metadata.feed_id != SENDAI_FEED_ID:
            raise ValueError(f"SendaiRouteBackend requires {SENDAI_FEED_ID} dataset")
        super().__init__(dataset, **kwargs)

