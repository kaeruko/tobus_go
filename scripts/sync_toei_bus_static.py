#!/usr/bin/env python3
"""Download the reviewed public Toei bus topology snapshot without credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "api" / "config" / "toei_bus_static_release.json"
DEFAULT_OUTPUT = ROOT / "api" / "data"
MAX_SOURCE_BYTES = 32 * 1024 * 1024


def _load_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise RuntimeError(f"Could not read release manifest: {path}") from error
    if value.get("schema") != "toei_bus_static_release/v1":
        raise RuntimeError("Unsupported Toei bus static release manifest")
    sources = value.get("odpt_sources")
    if not isinstance(sources, list) or not sources:
        raise RuntimeError("Release manifest has no ODPT sources")
    return value


def _download(source: dict, destination: Path, timeout: int) -> dict:
    filename = source.get("filename")
    endpoint = source.get("endpoint")
    expected_sha256 = source.get("sha256")
    expected_records = source.get("records")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise RuntimeError("Invalid ODPT source filename")
    if not isinstance(endpoint, str) or not endpoint.startswith(
        "https://api-public.odpt.org/"
    ):
        raise RuntimeError(f"Unapproved ODPT source endpoint: {filename}")
    request = urllib.request.Request(
        endpoint,
        headers={"Accept": "application/json", "User-Agent": "toeigo-static-sync/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if getattr(response, "status", response.getcode()) != 200:
                raise RuntimeError(f"ODPT source returned non-200 status: {filename}")
            payload = response.read(MAX_SOURCE_BYTES + 1)
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(f"Could not download ODPT source: {filename}") from error
    if not payload or len(payload) > MAX_SOURCE_BYTES:
        raise RuntimeError(f"ODPT source size is invalid: {filename}")
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            "ODPT source checksum differs from reviewed snapshot: "
            f"file={filename} expected={expected_sha256} actual={actual_sha256}"
        )
    try:
        records = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"ODPT source is not valid JSON: {filename}") from error
    if not isinstance(records, list) or len(records) != expected_records:
        actual_records = len(records) if isinstance(records, list) else None
        raise RuntimeError(
            "ODPT source record count differs from reviewed snapshot: "
            f"file={filename} expected={expected_records} actual={actual_records}"
        )
    destination.write_bytes(payload)
    return {
        "filename": filename,
        "sha256": actual_sha256,
        "records": len(records),
        "bytes": len(payload),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    manifest = _load_manifest(args.manifest)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="toei-static-") as temporary:
        staging = Path(temporary)
        for source in manifest["odpt_sources"]:
            results.append(
                _download(source, staging / source["filename"], args.timeout)
            )

        # No installed file changes until every source has passed its pinned
        # checksum and structural checks.
        pending = []
        for result in results:
            filename = result["filename"]
            temporary_target = args.output_dir / f".{filename}.tmp"
            shutil.copyfile(staging / filename, temporary_target)
            pending.append((temporary_target, args.output_dir / filename))
        for temporary_target, target in pending:
            os.replace(temporary_target, target)

    print(
        json.dumps(
            {
                "snapshot_id": manifest.get("snapshot_id"),
                "output_dir": str(args.output_dir.resolve()),
                "sources": results,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
