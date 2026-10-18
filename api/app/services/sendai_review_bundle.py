"""Exact-version Sendai reviewed artifacts co-located with one validated GTFS bundle.

No network or alternate-source discovery. The city S3 GTFS ZIP is the one
content-addressed deployment object for the feed and its reviewed subway and
municipal sources. Its root review manifest binds every JSON byte to the
original GTFS source ZIP SHA-256.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

GTFS_MANIFEST = "sendai_gtfs_manifest.json"
REVIEW_MANIFEST = "sendai_review_manifest.json"
REVIEW_FILES = {
    "municipal": "sendai_municipal_review.json",
    "subway_published": "sendai_subway_published.json",
    "subway_review": "sendai_subway_review.json",
}
_SHA = re.compile(r"[0-9a-f]{64}")


def _json_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gtfs_source_sha(root: Path) -> str:
    manifest = _json_object(root / GTFS_MANIFEST)
    value = manifest.get("sha256")
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError("Sendai GTFS manifest needs an exact source ZIP SHA-256")
    return value


def create_review_manifest(root: str | Path) -> dict:
    """Return an exact binding for three *already independently approved* files.

    This byte-integrity manifest is not an approval. The offline preparer must
    first independently validate the official GTFS, model, and query date.
    """
    root = Path(root)
    source_sha = _gtfs_source_sha(root)
    paths = {key: root / name for key, name in REVIEW_FILES.items()}
    for path in paths.values():
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Sendai reviewed input is missing or a symlink: {path.name}")
    municipal = _json_object(paths["municipal"])
    if municipal.get("bus_feed_version") != f"sha256:{source_sha}":
        raise ValueError("Sendai municipal review does not match official GTFS source SHA")
    period = municipal.get("operating_period")
    if not isinstance(period, dict):
        raise ValueError("Sendai reviewed operating period is required")
    from sendai_operating_period import OperatingPeriodReview

    reviewed = OperatingPeriodReview.from_mapping(period)
    return {
        "schema_version": 1,
        "city": "sendai",
        "bus_source_sha256": source_sha,
        "query_start": reviewed.query_start.isoformat(),
        "query_end": reviewed.query_end.isoformat(),
        "files": {key: _sha256(path) for key, path in paths.items()},
    }


def validated_reviewed_paths(root: str | Path) -> dict[str, Path]:
    """Fail closed on missing, modified, or cross-version review material."""
    root = Path(root)
    observed = _json_object(root / REVIEW_MANIFEST)
    required = {
        "schema_version", "city", "bus_source_sha256",
        "query_start", "query_end", "files",
    }
    if set(observed) != required or observed["schema_version"] != 1 or observed["city"] != "sendai":
        raise ValueError("invalid Sendai reviewed bundle manifest")
    files = observed["files"]
    if not isinstance(files, dict) or set(files) != set(REVIEW_FILES):
        raise ValueError("incomplete Sendai reviewed bundle file inventory")
    if any(not isinstance(value, str) or not _SHA.fullmatch(value) for value in files.values()):
        raise ValueError("invalid Sendai reviewed file SHA-256")
    expected = create_review_manifest(root)
    if observed != expected:
        raise ValueError("Sendai reviewed bundle SHA/date/version binding mismatch")
    return {key: root / name for key, name in REVIEW_FILES.items()}
