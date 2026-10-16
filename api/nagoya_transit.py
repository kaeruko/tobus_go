from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata, TransitDataset, TransitMode
from gtfs_route_backend import GtfsRouteEngine

NAGOYA_FEED_ID = "nagoya_bus"
NAGOYA_DATASET_ID = "c5794008-8053-42ab-99b9-ee7f6fdf9a9e"
NAGOYA_RESOURCE_ID = "125a1d12-7df6-489c-abde-911856e05d1b"
NAGOYA_CKAN_PACKAGE_URL = (
    "https://data.bodik.jp/api/3/action/package_show"
    f"?id={NAGOYA_DATASET_ID}"
)
NAGOYA_MANIFEST_FILENAME = "nagoya_gtfs_manifest.json"
_REQUIRED_GTFS_FILES = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")
_REVISION_PATTERN = re.compile(
    r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日改正"
)


@dataclass(frozen=True, slots=True)
class NagoyaGtfsManifest:
    dataset_id: str
    resource_id: str
    revision: str
    source_url: str
    fetched_at: datetime
    sha256: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "NagoyaGtfsManifest":
        required = (
            "dataset_id",
            "resource_id",
            "revision",
            "source_url",
            "fetched_at",
            "sha256",
        )
        for key in required:
            if key not in value:
                raise ValueError(f"Nagoya GTFS manifest is missing {key}")
        try:
            fetched_at = datetime.fromisoformat(str(value["fetched_at"]))
        except ValueError as error:
            raise ValueError("Nagoya GTFS manifest has invalid fetched_at") from error
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("Nagoya GTFS manifest fetched_at must be timezone-aware")
        manifest = cls(
            dataset_id=str(value["dataset_id"]),
            resource_id=str(value["resource_id"]),
            revision=_validate_revision(str(value["revision"])),
            source_url=str(value["source_url"]),
            fetched_at=fetched_at,
            sha256=str(value["sha256"]),
        )
        manifest.validate_source_identity()
        return manifest

    def validate_source_identity(self) -> None:
        if self.dataset_id != NAGOYA_DATASET_ID:
            raise ValueError(
                f"Unexpected Nagoya GTFS dataset_id: {self.dataset_id!r}"
            )
        if self.resource_id != NAGOYA_RESOURCE_ID:
            raise ValueError(
                f"Unexpected Nagoya GTFS resource_id: {self.resource_id!r}"
            )
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Nagoya GTFS source_url must be an absolute HTTPS URL")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("Nagoya GTFS manifest has invalid sha256")

    def to_mapping(self) -> dict[str, str]:
        return {
            "dataset_id": self.dataset_id,
            "resource_id": self.resource_id,
            "revision": self.revision,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at.isoformat(),
            "sha256": self.sha256,
        }


def _validate_revision(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError(
            f"Invalid Nagoya GTFS revision {value!r}; expected YYYY-MM-DD"
        ) from error
    if parsed.isoformat() != value:
        raise ValueError(
            f"Invalid Nagoya GTFS revision {value!r}; expected zero-padded YYYY-MM-DD"
        )
    return value


def required_expected_revision() -> str:
    value = os.getenv("NAGOYA_GTFS_EXPECTED_REVISION")
    if value is None or value == "":
        raise RuntimeError(
            "NAGOYA_GTFS_EXPECTED_REVISION is required for Nagoya runtime"
        )
    return _validate_revision(value)


def _revision_from_resource_name(name: str) -> str:
    match = _REVISION_PATTERN.search(name)
    if match is None:
        raise ValueError(
            f"Could not determine Nagoya GTFS revision from resource name: {name!r}"
        )
    return (
        f"{int(match.group('year')):04d}-"
        f"{int(match.group('month')):02d}-"
        f"{int(match.group('day')):02d}"
    )


def resolve_nagoya_resource(
    package_payload: dict[str, Any], *, expected_revision: str
) -> dict[str, str]:
    expected_revision = _validate_revision(expected_revision)
    if package_payload.get("success") is not True:
        raise RuntimeError("BODIK package_show response did not report success")
    result = package_payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("BODIK package_show response is missing result object")
    if result.get("id") != NAGOYA_DATASET_ID:
        raise ValueError(f"Unexpected BODIK package id: {result.get('id')!r}")
    resources = result.get("resources")
    if not isinstance(resources, list):
        raise ValueError("BODIK package metadata is missing resources list")
    matches = [
        resource
        for resource in resources
        if isinstance(resource, dict) and resource.get("id") == NAGOYA_RESOURCE_ID
    ]
    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one configured Nagoya GTFS resource "
            f"{NAGOYA_RESOURCE_ID}, found {len(matches)}"
        )
    resource = matches[0]
    if resource.get("package_id") not in (None, NAGOYA_DATASET_ID):
        raise ValueError(
            "Nagoya GTFS resource belongs to unexpected package: "
            f"{resource.get('package_id')!r}"
        )
    if resource.get("state") not in (None, "active"):
        raise ValueError(
            f"Nagoya GTFS resource is not active: {resource.get('state')!r}"
        )
    resource_format = str(resource.get("format") or "")
    mimetype = str(resource.get("mimetype") or "")
    if resource_format.upper() != "ZIP" and mimetype != "application/zip":
        raise ValueError("Configured Nagoya GTFS resource is not identified as ZIP")
    name = str(resource.get("name") or "")
    revision = _revision_from_resource_name(name)
    if revision != expected_revision:
        raise RuntimeError(
            "Nagoya GTFS revision mismatch: "
            f"expected={expected_revision}, catalog_resource={revision}"
        )
    source_url = str(resource.get("url") or "")
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Nagoya GTFS resource URL must be absolute HTTPS")
    return {
        "dataset_id": NAGOYA_DATASET_ID,
        "resource_id": NAGOYA_RESOURCE_ID,
        "revision": revision,
        "source_url": source_url,
    }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_gtfs_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    files = [member for member in archive.infolist() if not member.is_dir()]
    normalized: list[tuple[zipfile.ZipInfo, str]] = []
    for member in files:
        name = member.filename.replace("\\", "/")
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"Unsafe path in Nagoya GTFS ZIP: {member.filename}")
        normalized.append((member, name))

    by_basename: dict[str, list[tuple[zipfile.ZipInfo, str]]] = {}
    for member, name in normalized:
        by_basename.setdefault(Path(name).name, []).append((member, name))

    selected: dict[str, zipfile.ZipInfo] = {}
    required_plus_calendar = set(_REQUIRED_GTFS_FILES) | {
        "calendar.txt",
        "calendar_dates.txt",
    }
    for basename in required_plus_calendar:
        matches = by_basename.get(basename, [])
        if len(matches) > 1:
            raise RuntimeError(f"Nagoya GTFS ZIP contains multiple {basename} files")
        if matches:
            selected[basename] = matches[0][0]

    for required in _REQUIRED_GTFS_FILES:
        if required not in selected:
            raise RuntimeError(f"Nagoya GTFS ZIP is missing {required}")
    if "calendar.txt" not in selected and "calendar_dates.txt" not in selected:
        raise RuntimeError("Nagoya GTFS ZIP requires calendar.txt or calendar_dates.txt")
    return selected


def fetch_nagoya_gtfs(
    output_dir: str | Path,
    *,
    expected_revision: str,
    client: httpx.Client | None = None,
) -> NagoyaGtfsManifest:
    expected_revision = _validate_revision(expected_revision)
    target = Path(output_dir)
    if target.exists():
        raise FileExistsError(
            "Nagoya GTFS output already exists; choose a new version directory: "
            f"{target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)

    owns_client = client is None
    http_client = client or httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        metadata_response = http_client.get(NAGOYA_CKAN_PACKAGE_URL)
        metadata_response.raise_for_status()
        package_payload = metadata_response.json()
        if not isinstance(package_payload, dict):
            raise ValueError("BODIK package_show response must be a JSON object")
        resource = resolve_nagoya_resource(
            package_payload, expected_revision=expected_revision
        )

        zip_response = http_client.get(resource["source_url"])
        zip_response.raise_for_status()
        archive_bytes = zip_response.content
        if not archive_bytes:
            raise RuntimeError("Downloaded Nagoya GTFS ZIP is empty")
    finally:
        if owns_client:
            http_client.close()

    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=str(target.parent)))
    try:
        archive_path = staging / "source.zip"
        archive_path.write_bytes(archive_bytes)
        with zipfile.ZipFile(archive_path) as archive:
            members = _safe_gtfs_members(archive)
            feed_dir = staging / "feed"
            feed_dir.mkdir()
            for basename, member in members.items():
                with archive.open(member) as source, (feed_dir / basename).open("wb") as dest:
                    shutil.copyfileobj(source, dest)
        archive_path.unlink()

        fetched_at = datetime.now(timezone.utc)
        manifest = NagoyaGtfsManifest(
            dataset_id=NAGOYA_DATASET_ID,
            resource_id=NAGOYA_RESOURCE_ID,
            revision=expected_revision,
            source_url=resource["source_url"],
            fetched_at=fetched_at,
            sha256=_sha256_bytes(archive_bytes),
        )
        metadata = FeedMetadata(
            feed_id=NAGOYA_FEED_ID,
            source_type="gtfs-jp",
            source_uri=manifest.source_url,
            version=manifest.revision,
            fetched_at=manifest.fetched_at,
        )
        GtfsTransitAdapter.load(feed_dir, metadata=metadata)
        (feed_dir / NAGOYA_MANIFEST_FILENAME).write_text(
            json.dumps(manifest.to_mapping(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(feed_dir, target)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def load_nagoya_dataset(
    gtfs_dir: str | Path, *, expected_revision: str
) -> TransitDataset:
    expected_revision = _validate_revision(expected_revision)
    root = Path(gtfs_dir)
    manifest_path = root / NAGOYA_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Nagoya GTFS manifest must be a JSON object")
    manifest = NagoyaGtfsManifest.from_mapping(raw)
    if manifest.revision != expected_revision:
        raise RuntimeError(
            "Nagoya GTFS manifest revision mismatch: "
            f"expected={expected_revision}, installed={manifest.revision}"
        )
    metadata = FeedMetadata(
        feed_id=NAGOYA_FEED_ID,
        source_type="gtfs-jp",
        source_uri=manifest.source_url,
        version=manifest.revision,
        fetched_at=manifest.fetched_at,
    )
    dataset = GtfsTransitAdapter.load(root, metadata=metadata)
    non_bus_routes = [
        route.id for route in dataset.routes.values() if route.mode is not TransitMode.BUS
    ]
    if non_bus_routes:
        raise ValueError(
            "Nagoya city-bus feed unexpectedly contains non-bus route: "
            f"{non_bus_routes[0]}"
        )
    return dataset


class NagoyaRouteBackend(GtfsRouteEngine):
    def __init__(self, dataset: TransitDataset, **kwargs: Any):
        if dataset.metadata.feed_id != NAGOYA_FEED_ID:
            raise ValueError(f"NagoyaRouteBackend requires {NAGOYA_FEED_ID} dataset")
        super().__init__(dataset, **kwargs)
