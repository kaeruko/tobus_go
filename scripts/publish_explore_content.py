#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
    source_paths,
)


def run_aws(args: list[str]) -> str:
    if shutil.which("aws") is None:
        raise RuntimeError("AWS CLI was not found on PATH")
    command = ["aws", *args]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
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
            "Validate content/explore/<city>/spots.csv and images, then publish "
            "the compiled JSON and referenced images to the API data S3 bucket."
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    csv_path, images_dir = source_paths(args.city)

    # All local validation is completed before the first AWS mutation.
    payload = compile_csv(csv_path, images_dir)
    referenced_images = [
        image["file"]
        for spot in payload["spots"]
        for image in spot["images"]
    ]

    bucket = resolve_bucket(
        bucket=args.bucket,
        lambda_function=args.lambda_function,
        region=args.region,
    )
    prefix = f"content/explore/{args.city}"

    print(f"CSV      : {csv_path}")
    print(f"Images   : {len(referenced_images)}")
    print(f"Spots    : {len(payload['spots'])}")
    print(f"Bucket   : {bucket}")
    print(f"Prefix   : {prefix}")

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
        for filename in referenced_images:
            upload_file(
                source=images_dir / filename,
                bucket=bucket,
                key=f"{prefix}/images/{filename}",
                region=args.region,
                content_type=image_media_type(filename),
                cache_control="public,max-age=86400",
            )
            print(f"Uploaded : {filename}")

        upload_file(
            source=json_path,
            bucket=bucket,
            key=f"{prefix}/spots.json",
            region=args.region,
            content_type="application/json; charset=utf-8",
            cache_control="no-cache",
        )
        print("Published: spots.json")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ExploreContentError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
