"""Fail-closed offline loader and explicit opt-in fetch for municipal subway GTFS.

The fetcher never logs ODPT credentials, overwrites existing files, enables
route search, or establishes public-redistribution/license permission.
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import shutil
import stat
import tempfile
import zipfile
import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit

import httpx

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


def _safe_odpt_redirect(location: str, *, consumer_key: str) -> str:
    """Validate a CDN handoff without ever logging/copying ODPT API credentials.

    SOURCE_URL (without the secret) is the only relative redirect base.
    Only HTTPS ODPT/CDN storage destinations may receive an unauthed GET.
    """
    if not isinstance(location, str) or not location.strip():
        raise ValueError("subway GTFS download redirect missing Location")
    # A relative Location must never resolve against the authenticated URL.
    resolved = urljoin(SOURCE_URL, location)
    parsed = urlsplit(resolved)
    host = (parsed.hostname or "").lower()
    allowed = (
        host in {"api.odpt.org", "api-public.odpt.org", "storage.googleapis.com",
                 "s3.amazonaws.com"}
        or bool(re.fullmatch(r"[a-z0-9-]+\.cloudfront\.net", host))
        or bool(re.fullmatch(r"s3[.-][a-z0-9-]+\.amazonaws\.com", host))
        or bool(re.fullmatch(r"[a-z0-9.-]+\.s3[.-][a-z0-9-]+\.amazonaws\.com", host))
        or bool(re.fullmatch(r"[a-z0-9.-]+\.s3\.amazonaws\.com", host))
    )
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("subway GTFS redirect must be HTTPS without userinfo or fragment")
    if not allowed or parsed.port not in (None, 443):
        # Host is intentionally returned, but NEVER the full signed URL or key.
        raise ValueError(f"subway GTFS redirect host not approved: {host or 'unknown'}")
    if consumer_key in resolved or any(
        key.lower() in {"acl:consumerkey", "consumerkey"}
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
    ):
        raise ValueError("subway GTFS redirect must not carry ODPT API credentials")
    return resolved


_MAX_ZIP_BYTES = 80 * 1024 * 1024
_MAX_UNPACK_BYTES = 400 * 1024 * 1024
_MAX_MEMBERS = 64


def _safe_zip_text_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """Flatten uniquely-named GTFS text files; refuse unsafe archive members."""
    members = archive.infolist()
    if len(members) > _MAX_MEMBERS:
        raise ValueError("subway GTFS ZIP contains too many members")
    selected: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for member in members:
        name = member.filename.replace("\\", "/")
        pieces = name.split("/")
        if (
            not name or name.startswith("/")
            or any(part in {"", ".", ".."} for part in pieces if part != pieces[-1])
            or any(part == ".." for part in pieces)
            or ":" in pieces[0]
        ):
            raise ValueError("subway GTFS ZIP contains unsafe path")
        if member.is_dir():
            continue
        mode = (member.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise ValueError("subway GTFS ZIP contains symlink")
        basename = pieces[-1]
        if not basename or not basename.endswith(".txt"):
            raise ValueError("subway GTFS ZIP contains unexpected non-GTFS file")
        if basename in selected:
            raise ValueError("subway GTFS ZIP contains duplicate text basename")
        if member.file_size < 0:
            raise ValueError("subway GTFS ZIP invalid member size")
        total += member.file_size
        if total > _MAX_UNPACK_BYTES:
            raise ValueError("subway GTFS ZIP uncompressed size limit exceeded")
        selected[basename] = member
    if not REQUIRED_FILES <= set(selected) or not (
        {"calendar.txt", "calendar_dates.txt"} & set(selected)
    ):
        raise ValueError("subway GTFS ZIP missing required files")
    return selected


def fetch_yokohama_subway_gtfs(
    output_dir: str | Path,
    *,
    expected_service_date: str,
    consumer_key: str,
    client: httpx.Client | None = None,
) -> dict:
    """Fetch+verify pinned ODPT GTFS to a NEW directory atomically, never overwrite.

    An injected HTTP client permits fully offline mock testing. Network and HTTP
    errors deliberately omit raw URLs, query parameters, keys, and response bodies.
    """
    day = _parse_day(expected_service_date)
    if not VALID_FROM <= day <= VALID_UNTIL:
        raise ValueError("subway date outside catalog edition validity")
    if not isinstance(consumer_key, str) or not consumer_key.strip():
        raise ValueError("ODPT consumer key is required")
    target = Path(output_dir)
    if target.exists():
        raise FileExistsError("subway GTFS output directory already exists")
    if not target.parent.is_dir():
        raise FileNotFoundError("subway GTFS output parent directory does not exist")

    own_client = client is None
    http_client = client or httpx.Client(timeout=60.0, follow_redirects=False)
    try:
        try:
            # Authenticate against ODPT ONLY. The next hop must never inherit
            # acl:consumerKey, cookies, Authorization, or client default params.
            response = http_client.get(
                SOURCE_URL,
                params={"date": "current", "acl:consumerKey": consumer_key},
                follow_redirects=False,
            )
        except httpx.RequestError:
            raise RuntimeError("subway GTFS ODPT request failed") from None

        # ODPT may return 302 pointing at a separate file-delivery host.
        # Follow only explicitly checked HTTPS targets with a FRESH unauthenticated
        # Request. Never use automatic redirects (which could forward secrets).
        for _ in range(3):
            if response.status_code == 200:
                break
            if response.status_code not in {301, 302, 303, 307, 308}:
                raise RuntimeError(
                    f"subway GTFS ODPT returned HTTP {response.status_code}"
                )
            if not response.headers.get("location"):
                raise RuntimeError(
                    f"subway GTFS ODPT returned HTTP {response.status_code}"
                )
            target_url = _safe_odpt_redirect(
                response.headers["location"], consumer_key=consumer_key,
            )
            try:
                response = http_client.send(
                    httpx.Request("GET", target_url),
                    auth=None,
                    follow_redirects=False,
                )
            except httpx.RequestError:
                raise RuntimeError("subway GTFS redirected download failed") from None
        else:
            raise RuntimeError("subway GTFS exceeded safe redirect limit")
        data = response.content
        if not data or len(data) > _MAX_ZIP_BYTES:
            raise ValueError("subway GTFS ZIP empty or over size limit")
    finally:
        if own_client:
            http_client.close()

    with tempfile.TemporaryDirectory(
        prefix=".yokohama_subway_", dir=str(target.parent)
    ) as staging:
        feed = Path(staging) / "feed"
        feed.mkdir()
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                selected = _safe_zip_text_members(archive)
                for name, member in selected.items():
                    # Reject unexpected inflation; copy only the validated members.
                    with archive.open(member) as source, (feed / name).open("xb") as dest:
                        shutil.copyfileobj(source, dest)
        except (zipfile.BadZipFile, RuntimeError, EOFError):
            raise ValueError("subway GTFS invalid ZIP archive") from None

        manifest = {
            "source_url": SOURCE_URL,
            "resource_id": RESOURCE_ID,
            "feed_version": VERSION,
            "fetched_at": datetime.now().astimezone().isoformat(),
            "valid_from": VALID_FROM.isoformat(),
            "valid_until": VALID_UNTIL.isoformat(),
            "validated_service_date": day.isoformat(),
            "files_sha256": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(feed.glob("*.txt"))
            },
        }
        (feed / MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        dataset = load_yokohama_subway_dataset(
            feed, expected_service_date=day.isoformat(),
        )
        if not dataset.routes or not dataset.trips:
            raise ValueError("subway GTFS dataset has no routes/trips")

        # A single rename publishes only completely validated data.
        if target.exists():
            raise FileExistsError("subway GTFS output directory already exists")
        os.rename(feed, target)
    return {
        "feed_id": dataset.metadata.feed_id,
        "feed_version": dataset.metadata.version,
        "validated_service_date": day.isoformat(),
        "route_count": len(dataset.routes),
        "trip_count": len(dataset.trips),
        "stop_count": len(dataset.stops),
        "file_count": len(manifest["files_sha256"]),
        "output_path": str(target),
        "status": "validated local GTFS; not licensed/publication approved",
    }
