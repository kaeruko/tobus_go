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
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.services.explore_editorial_content import (  # noqa: E402
    ExploreContentError,
    compile_csv,
    image_media_type,
    master_data_dir,
    source_paths,
)


AWS_COMMAND_TIMEOUT_SECONDS = 90
PROGRESS_PREFIX = "EXPLORE_PROGRESS "
SIMPLE_ETAG_PATTERN = re.compile(r'^(?:"[0-9a-fA-F]{32}"|[0-9a-fA-F]{32})$')


def emit_progress(enabled: bool, stage: str, **fields: object) -> None:
    if enabled:
        print(
            PROGRESS_PREFIX + json.dumps(
                {"stage": stage, **fields}, ensure_ascii=False,
            ),
            flush=True,
        )


def list_remote_images(*, bucket: str, prefix: str, region: str) -> dict[str, dict]:
    image_prefix = f"{prefix.rstrip('/')}/images/"
    raw = run_aws([
        "s3api", "list-objects-v2",
        "--bucket", bucket,
        "--prefix", image_prefix,
        "--region", region,
        "--output", "json",
    ])
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"invalid S3 image listing: malformed JSON, prefix={image_prefix}: {error}"
        ) from error
    if not isinstance(response, dict):
        raise RuntimeError(
            f"invalid S3 image listing: expected object, got {type(response).__name__}"
        )
    contents = response.get("Contents", [])
    if not isinstance(contents, list):
        raise RuntimeError(
            f"invalid S3 image listing: Contents must be an array, prefix={image_prefix}"
        )
    result: dict[str, dict] = {}
    for index, item in enumerate(contents):
        if not isinstance(item, dict):
            raise RuntimeError(
                f"invalid S3 image listing: Contents[{index}] must be an object"
            )
        key = item.get("Key")
        if not isinstance(key, str):
            raise RuntimeError(
                f"invalid S3 image listing: missing Key at index={index}"
            )
        if type(item.get("Size")) is not int or item["Size"] < 0 or (
            "ETag" in item and not isinstance(item["ETag"], str)
        ):
            raise RuntimeError(
                f"invalid S3 image listing: malformed image metadata at index={index} key={key!r}"
            )
        if not key.startswith(image_prefix):
            continue
        filename = key[len(image_prefix):]
        if not filename or "/" in filename or "\\" in filename:
            raise RuntimeError(
                f"invalid S3 image listing: unexpected image object key={key!r}"
            )
        if filename in result:
            raise RuntimeError(
                f"invalid S3 image listing: duplicate image key={key!r}"
            )
        result[filename] = item
    return result


def image_is_unchanged(source: Path, remote: dict | None) -> bool:
    if remote is None:
        return False
    if not isinstance(remote, dict):
        raise RuntimeError(
            f"invalid S3 image metadata for {source}: {type(remote).__name__}"
        )
    size = remote.get("Size")
    etag = remote.get("ETag")
    # A multipart ETag cannot be compared as an MD5; re-upload it instead.
    if type(size) is not int or size < 0 or not isinstance(etag, str) or (
        SIMPLE_ETAG_PATTERN.fullmatch(etag) is None
    ):
        return False
    if size != source.stat().st_size:
        return False
    digest = hashlib.md5(usedforsecurity=False)
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return etag.strip('"').lower() == digest.hexdigest()


def run_aws(args: list[str]) -> str:
    aws_executable = shutil.which("aws")
    if aws_executable is None:
        raise RuntimeError("AWS CLI was not found on PATH")
    command = [
        aws_executable, *args,
        "--no-cli-pager", "--no-cli-auto-prompt",
        "--cli-connect-timeout", "10",
        "--cli-read-timeout", "30",
    ]
    env = {
        **os.environ,
        "AWS_PAGER": "",
        "AWS_CLI_AUTO_PROMPT": "off",
        "AWS_MAX_ATTEMPTS": "2",
    }
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=AWS_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"AWS CLI timed out after {AWS_COMMAND_TIMEOUT_SECONDS} seconds: "
            + " ".join(command)
        ) from error
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"AWS CLI failed with exit code {result.returncode}: "
            f"{' '.join(command)}\n{stderr}"
        )
    return result.stdout.strip()


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
        "--progress-json",
        action="store_true",
        help="Print flushed EXPLORE_PROGRESS JSON events for the local CMS.",
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
    print(f"CSV      : {csv_path}")
    print(f"Images   : {len(referenced_images)}")
    print(f"Poles    : {len(payload['spots'])}")
    print(f"Bucket   : {bucket}")
    print(f"Prefix   : {prefix}")

    remote_images = list_remote_images(
        bucket=bucket, prefix=prefix, region=args.region,
    )
    changed_images = [
        filename for filename in referenced_images
        if not image_is_unchanged(images_dir / filename, remote_images.get(filename))
    ]
    skipped = len(referenced_images) - len(changed_images)
    print(f"New/edited images: {len(changed_images)}; unchanged: {skipped}")

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
        for index, filename in enumerate(changed_images):
            emit_progress(
                args.progress_json, "images", current=index,
                total=len(changed_images), skipped=skipped, filename=filename,
            )
            upload_file(
                source=images_dir / filename,
                bucket=bucket,
                key=f"{prefix}/images/{filename}",
                region=args.region,
                content_type=image_media_type(filename),
                cache_control="public,max-age=86400",
            )
            print(f"Uploaded : {filename}")
            emit_progress(
                args.progress_json, "images", current=index + 1,
                total=len(changed_images), skipped=skipped, filename=filename,
            )

        emit_progress(
            args.progress_json, "manifest",
            current=len(changed_images), total=len(changed_images), skipped=skipped,
        )
        upload_file(
            source=json_path,
            bucket=bucket,
            key=f"{prefix}/spots.json",
            region=args.region,
            content_type="application/json; charset=utf-8",
            cache_control="no-cache",
        )
        print("Published: spots.json")

    emit_progress(
        args.progress_json, "complete",
        current=len(changed_images), total=len(changed_images), skipped=skipped,
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ExploreContentError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
