from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_REQUIRED_GTFS_FILES = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        raise RuntimeError(f"{name} is required for Lambda GTFS bundle materialization")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract_bundle(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        destination_root = destination.resolve()
        for member in archive.infolist():
            normalized = member.filename.replace("\\", "/")
            path = PurePosixPath(normalized)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"Unsafe path in city GTFS bundle: {member.filename}")
            target = (destination / Path(*path.parts)).resolve()
            if os.path.commonpath([str(destination_root), str(target)]) != str(destination_root):
                raise RuntimeError(f"Unsafe path in city GTFS bundle: {member.filename}")
        archive.extractall(destination)


def _validate_extracted_bundle(root: Path, manifest_filename: str) -> None:
    manifest_path = root / manifest_filename
    if not manifest_path.is_file():
        raise RuntimeError(f"City GTFS bundle is missing {manifest_filename}")
    for filename in _REQUIRED_GTFS_FILES:
        if not (root / filename).is_file():
            raise RuntimeError(f"City GTFS bundle is missing {filename}")
    if not (root / "calendar.txt").is_file() and not (root / "calendar_dates.txt").is_file():
        raise RuntimeError(
            "City GTFS bundle requires calendar.txt or calendar_dates.txt"
        )


def materialize_city_gtfs_bundle(
    *,
    city: str,
    target_dir: str | Path,
    manifest_filename: str,
    s3_client: Any | None = None,
) -> Path:
    if city not in {"nagoya", "sendai"}:
        raise ValueError(f"Unsupported city GTFS bundle: {city!r}")
    if not manifest_filename or Path(manifest_filename).name != manifest_filename:
        raise ValueError("manifest_filename must be one file name")

    target = Path(target_dir)
    if target.exists():
        raise FileExistsError(
            "City GTFS target already exists; refusing to reuse or overwrite it: "
            f"{target}"
        )

    prefix = city.upper()
    bucket = _required_env(f"{prefix}_GTFS_BUNDLE_S3_BUCKET")
    object_key = _required_env(f"{prefix}_GTFS_BUNDLE_S3_KEY")
    expected_sha256 = _required_env(f"{prefix}_GTFS_BUNDLE_SHA256")
    if _SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise RuntimeError(f"{prefix}_GTFS_BUNDLE_SHA256 must be 64 lowercase hex chars")

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", dir=str(target.parent))
    )
    try:
        archive_path = staging / "bundle.zip"
        feed_dir = staging / "feed"
        feed_dir.mkdir()

        if s3_client is None:
            import boto3

            s3_client = boto3.client("s3")
        s3_client.download_file(bucket, object_key, str(archive_path))

        actual_sha256 = _sha256_file(archive_path)
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                "City GTFS bundle SHA-256 mismatch: "
                f"expected={expected_sha256} actual={actual_sha256}"
            )

        _safe_extract_bundle(archive_path, feed_dir)
        _validate_extracted_bundle(feed_dir, manifest_filename)
        archive_path.unlink()
        os.replace(feed_dir, target)
        return target
    finally:
        shutil.rmtree(staging, ignore_errors=True)
