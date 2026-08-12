#!/usr/bin/env python3
"""Run the Toei GTFS refresh locally or against the deployment S3 bucket."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import asdict
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPOSITORY_ROOT / "api"
sys.path.insert(0, str(API_DIR))

from gtfs_refresh import (  # noqa: E402
    DEFAULT_SOURCE_URL,
    DEFAULT_STATE_KEY,
    DEFAULT_VERSION_PREFIX,
    LocalGtfsStore,
    S3GtfsStore,
    UrllibDownloader,
    build_authenticated_source_url,
    refresh_gtfs,
)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the Toei Bus GTFS ZIP")
    parser.add_argument(
        "--output-dir",
        default=str(API_DIR / "data" / "gtfs-refresh"),
        help="Local state/version directory (default: api/data/gtfs-refresh)",
    )
    parser.add_argument(
        "--s3-bucket",
        help="Use S3 instead of local files (for deployment verification)",
    )
    parser.add_argument("--state-key", default=DEFAULT_STATE_KEY)
    parser.add_argument("--version-prefix", default=DEFAULT_VERSION_PREFIX)
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    return parser.parse_args()


def main() -> int:
    _load_env_file(API_DIR / ".env")
    args = parse_args()
    token = os.getenv("ODPT_API_TOKEN", "")
    request_url = build_authenticated_source_url(args.source_url, token)

    if args.s3_bucket:
        store = S3GtfsStore(
            bucket_name=args.s3_bucket,
            state_key=args.state_key,
            version_prefix=args.version_prefix,
        )
    else:
        store = LocalGtfsStore(args.output_dir)

    result = refresh_gtfs(
        downloader=UrllibDownloader(),
        store=store,
        request_url=request_url,
        source_url=args.source_url,
    )
    if result.status == "updated":
        print(f"GTFS updated: {result.old_sha256 or 'none'} -> {result.new_sha256}")
    else:
        print(f"GTFS unchanged ({result.reason})")
    print(asdict(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
