#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "api"
AWS_COMMAND_TIMEOUT_SECONDS = 90
PROGRESS_PREFIX = "EXPLORE_PROGRESS "
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.services.explore_editorial_content import (  # noqa: E402
    ExploreContentError,
    compile_csv,
    image_media_type,
    master_data_dir,
    source_paths,
)


def run_aws(args: list[str]) -> str:
    executable = shutil.which("aws")
    if executable is None:
        raise RuntimeError("AWS CLI was not found on PATH")
    command = [
        executable, *args, "--no-cli-pager", "--no-cli-auto-prompt",
        "--cli-connect-timeout", "10", "--cli-read-timeout", "30",
    ]
    environment = os.environ.copy()
    environment.update(AWS_PAGER="", AWS_CLI_AUTO_PROMPT="off", AWS_MAX_ATTEMPTS="2")
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,
            env=environment,
            timeout=AWS_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"AWS CLI timed out after {AWS_COMMAND_TIMEOUT_SECONDS} seconds: "
            f"{' '.join(command)}"
        ) from error
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"AWS CLI failed with exit code {result.returncode}: "
            f"{' '.join(command)}\n{stderr}"
        )
    return result.stdout.strip()


def emit_progress(enabled: bool, stage: str, **details) -> None:
    if enabled:
        print(
            PROGRESS_PREFIX + json.dumps({"stage": stage, **details}, ensure_ascii=False),
            flush=True,
        )


def list_remote_images(*, bucket: str, prefix: str, region: str) -> dict:
    image_prefix = f"{prefix}/images/"
    output = run_aws([
        "s3api", "list-objects-v2", "--bucket", bucket,
        "--prefix", image_prefix, "--region", region, "--output", "json",
    ])
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError("invalid S3 image listing: response is not JSON") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("Contents", []), list):
        raise RuntimeError("invalid S3 image listing: expected Contents list")
    images = {}
    for entry in payload.get("Contents", []):
        if (not isinstance(entry, dict) or not isinstance(entry.get("Key"), str)
                or not isinstance(entry.get("Size"), int) or entry["Size"] < 0
                or ("ETag" in entry and not isinstance(entry["ETag"], str))):
            raise RuntimeError("invalid S3 image listing: malformed image entry")
        key = entry["Key"]
        if key.startswith(image_prefix) and key != image_prefix:
            filename = key[len(image_prefix):]
            if filename in images:
                raise RuntimeError("invalid S3 image listing: duplicate image key")
            images[filename] = entry
    return images


def image_is_unchanged(source: Path, remote: dict | None) -> bool:
    if not isinstance(remote, dict) or remote.get("Size") != source.stat().st_size:
        return False
    etag = remote.get("ETag")
    if not isinstance(etag, str) or not re.fullmatch(r'"[0-9a-fA-F]{32}"|[0-9a-fA-F]{32}', etag):
        return False
    digest = hashlib.md5(usedforsecurity=False)
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == etag.strip('"').lower()


def resolve_bucket(
    *,
    bucket: str | None,
    lambda_function: str,
    region: str,
) -> str:
    if bucket is not None:
        if not bucket.strip() or bucket != bucket.strip():
            raise ValueError("--bucket must be a non-empty value without whitespace")
        return bucket

    value = run_aws(
        [
            "lambda",
            "get-function-configuration",
            "--region",
            region,
            "--function-name",
            lambda_function,
            "--query",
            "Environment.Variables.S3_BUCKET_NAME",
            "--output",
            "text",
        ]
    )
    if not value or value == "None":
        raise RuntimeError(
            f"Lambda {lambda_function!r} has no S3_BUCKET_NAME environment variable"
        )
    return value


def upload_file(
    *,
    source: Path,
    bucket: str,
    key: str,
    region: str,
    content_type: str,
    cache_control: str,
) -> None:
    run_aws(
        [
            "s3",
            "cp",
            str(source),
            f"s3://{bucket}/{key}",
            "--region",
            region,
            "--content-type",
            content_type,
            "--cache-control",
            cache_control,
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve stop_name + route_id from ODPT master data, validate "
            "content/explore/<city>/spots.csv and images, then publish the "
            "expanded JSON and referenced images to the API data S3 bucket."
        )
    )
    parser.add_argument("--city", default="tokyo", choices=("tokyo",))
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--lambda-function", default="toeigo-api")
    parser.add_argument(
        "--bucket",
        help=(
            "Explicit S3 bucket. If omitted, read S3_BUCKET_NAME from "
            "--lambda-function."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and show the publish plan without changing S3.",
    )
    parser.add_argument(
        "--progress-json", action="store_true",
        help="Emit flushed progress events for the local CMS.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    emit_progress(args.progress_json, "validate")
    csv_path, images_dir = source_paths(args.city)

    # All local validation and ODPT resolution are completed before the first
    # AWS mutation. Matching is exact stop_name + route_id; odpt:note is unused.
    payload = compile_csv(
        csv_path,
        images_dir,
        data_dir=master_data_dir(args.city),
    )

    referenced_images: list[str] = []
    seen_images: set[str] = set()
    for spot in payload["spots"]:
        for image in spot["images"]:
            filename = image["file"]
            if filename not in seen_images:
                seen_images.add(filename)
                referenced_images.append(filename)

    emit_progress(args.progress_json, "bucket")
    bucket = resolve_bucket(
        bucket=args.bucket,
        lambda_function=args.lambda_function,
        region=args.region,
    )
    prefix = f"content/explore/{args.city}"
    remote_images = list_remote_images(bucket=bucket, prefix=prefix, region=args.region)
    changed_images = [
        filename for filename in referenced_images
        if not image_is_unchanged(images_dir / filename, remote_images.get(filename))
    ]
    skipped = len(referenced_images) - len(changed_images)

    print(f"CSV      : {csv_path}")
    print(f"Images   : {len(referenced_images)}")
    print(f"Poles    : {len(payload['spots'])}")
    print(f"Bucket   : {bucket}")
    print(f"Prefix   : {prefix}")
    print(f"Changed  : {len(changed_images)} (unchanged: {skipped})")

    if args.dry_run:
        print("Dry run complete. S3 was not changed.")
        return 0

    with tempfile.TemporaryDirectory(prefix="tobus-go-explore-") as temp_dir:
        json_path = Path(temp_dir) / "spots.json"
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # Images are uploaded first. spots.json is the publish boundary and is
        # intentionally updated only after every referenced image succeeds.
        for current, filename in enumerate(changed_images):
            emit_progress(args.progress_json, "images", current=current,
                          total=len(changed_images), filename=filename, skipped=skipped)
            upload_file(
                source=images_dir / filename,
                bucket=bucket,
                key=f"{prefix}/images/{filename}",
                region=args.region,
                content_type=image_media_type(filename),
                cache_control="public,max-age=86400",
            )
            print(f"Uploaded : {filename}")
            emit_progress(args.progress_json, "images", current=current + 1,
                          total=len(changed_images), filename=filename, skipped=skipped)

        emit_progress(args.progress_json, "manifest", current=len(changed_images),
                      total=len(changed_images), skipped=skipped)
        upload_file(
            source=json_path,
            bucket=bucket,
            key=f"{prefix}/spots.json",
            region=args.region,
            content_type="application/json; charset=utf-8",
            cache_control="no-cache",
        )
        print("Published: spots.json")

    emit_progress(args.progress_json, "complete", current=len(changed_images),
                  total=len(changed_images), skipped=skipped)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ExploreContentError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
