from __future__ import annotations

import csv
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any


EXPECTED_COLUMNS = ("stop_id", "comment", "image", "caption")
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_IMAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ExploreContentError(RuntimeError):
    pass


class ExploreContentNotFoundError(ExploreContentError):
    pass


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def source_paths(city: str) -> tuple[Path, Path]:
    base = repository_root() / "content" / "explore" / city
    return base / "spots.csv", base / "images"


def validate_image_name(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExploreContentError("image filename must be a non-empty string")
    if not _IMAGE_NAME_RE.fullmatch(value):
        raise ExploreContentError(
            f"invalid image filename {value!r}; use only letters, digits, '.', '_' and '-'"
        )
    suffix = Path(value).suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_SUFFIXES))
        raise ExploreContentError(
            f"unsupported image extension for {value!r}; expected one of: {allowed}"
        )
    return value


def image_media_type(filename: str) -> str:
    validate_image_name(filename)
    media_type, _ = mimetypes.guess_type(filename)
    if media_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ExploreContentError(
            f"could not determine supported image media type for {filename!r}"
        )
    return media_type


def _validate_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    *,
    where: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ExploreContentError(
            f"{where} keys mismatch; missing={missing}, extra={extra}"
        )


def validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ExploreContentError("explore content root must be an object")
    _validate_exact_keys(payload, {"spots"}, where="root")

    spots = payload["spots"]
    if not isinstance(spots, list):
        raise ExploreContentError("root.spots must be a list")

    seen_stop_ids: set[str] = set()
    validated_spots: list[dict[str, Any]] = []

    for spot_index, spot in enumerate(spots):
        where = f"spots[{spot_index}]"
        if not isinstance(spot, dict):
            raise ExploreContentError(f"{where} must be an object")
        _validate_exact_keys(
            spot,
            {"stop_id", "comment", "images"},
            where=where,
        )

        stop_id = spot["stop_id"]
        comment = spot["comment"]
        images = spot["images"]

        if not isinstance(stop_id, str) or not stop_id.strip():
            raise ExploreContentError(f"{where}.stop_id must be a non-empty string")
        if stop_id != stop_id.strip():
            raise ExploreContentError(
                f"{where}.stop_id must not have surrounding whitespace"
            )
        if stop_id in seen_stop_ids:
            raise ExploreContentError(f"duplicate stop_id: {stop_id!r}")
        seen_stop_ids.add(stop_id)

        if not isinstance(comment, str):
            raise ExploreContentError(f"{where}.comment must be a string")
        if not isinstance(images, list):
            raise ExploreContentError(f"{where}.images must be a list")
        if not comment and not images:
            raise ExploreContentError(
                f"{where} must contain a comment, at least one image, or both"
            )

        validated_images: list[dict[str, str]] = []
        seen_images: set[str] = set()
        for image_index, image in enumerate(images):
            image_where = f"{where}.images[{image_index}]"
            if not isinstance(image, dict):
                raise ExploreContentError(f"{image_where} must be an object")
            _validate_exact_keys(
                image,
                {"file", "caption"},
                where=image_where,
            )
            filename = validate_image_name(image["file"])
            caption = image["caption"]
            if not isinstance(caption, str):
                raise ExploreContentError(f"{image_where}.caption must be a string")
            if filename in seen_images:
                raise ExploreContentError(
                    f"{where} references image {filename!r} more than once"
                )
            seen_images.add(filename)
            validated_images.append({"file": filename, "caption": caption})

        validated_spots.append(
            {
                "stop_id": stop_id,
                "comment": comment,
                "images": validated_images,
            }
        )

    return {"spots": validated_spots}


def compile_csv(csv_path: Path, images_dir: Path) -> dict[str, Any]:
    if not csv_path.is_file():
        raise ExploreContentNotFoundError(f"CSV was not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ExploreContentError(f"CSV has no header: {csv_path}")
        if tuple(reader.fieldnames) != EXPECTED_COLUMNS:
            raise ExploreContentError(
                "CSV columns must be exactly "
                f"{','.join(EXPECTED_COLUMNS)}; got {reader.fieldnames}"
            )

        order: list[str] = []
        comments: dict[str, str] = {}
        images_by_stop: dict[str, list[dict[str, str]]] = {}
        referenced_images: set[str] = set()

        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ExploreContentError(
                    f"CSV row {row_number} has more fields than the header"
                )

            values = {key: row[key] for key in EXPECTED_COLUMNS}
            if any(value is None for value in values.values()):
                raise ExploreContentError(f"CSV row {row_number} is malformed")

            stop_id = values["stop_id"]
            comment = values["comment"]
            image = values["image"]
            caption = values["caption"]

            if stop_id != stop_id.strip():
                raise ExploreContentError(
                    f"CSV row {row_number}: stop_id has surrounding whitespace"
                )
            if not stop_id:
                raise ExploreContentError(
                    f"CSV row {row_number}: stop_id is required"
                )
            if not comment and not image:
                raise ExploreContentError(
                    f"CSV row {row_number}: comment or image is required"
                )
            if caption and not image:
                raise ExploreContentError(
                    f"CSV row {row_number}: caption requires image"
                )

            if stop_id not in comments:
                order.append(stop_id)
                comments[stop_id] = comment
                images_by_stop[stop_id] = []
            elif comment:
                existing = comments[stop_id]
                if existing and existing != comment:
                    raise ExploreContentError(
                        f"CSV row {row_number}: conflicting comments for {stop_id!r}"
                    )
                if not existing:
                    comments[stop_id] = comment

            if image:
                filename = validate_image_name(image)
                image_path = images_dir / filename
                if not image_path.is_file():
                    raise ExploreContentError(
                        f"CSV row {row_number}: image was not found: {image_path}"
                    )
                referenced_images.add(filename)
                images_by_stop[stop_id].append(
                    {"file": filename, "caption": caption}
                )

    if images_dir.exists():
        unexpected = sorted(
            path.name
            for path in images_dir.iterdir()
            if path.is_file()
            and path.name != ".gitkeep"
            and path.name not in referenced_images
        )
        if unexpected:
            raise ExploreContentError(
                "unreferenced files exist in images directory: "
                + ", ".join(unexpected)
            )
    elif referenced_images:
        raise ExploreContentError(f"images directory was not found: {images_dir}")

    payload = {
        "spots": [
            {
                "stop_id": stop_id,
                "comment": comments[stop_id],
                "images": images_by_stop[stop_id],
            }
            for stop_id in order
        ]
    }
    return validate_payload(payload)


def load_local_content(city: str) -> dict[str, Any]:
    csv_path, images_dir = source_paths(city)
    return compile_csv(csv_path, images_dir)


def _s3_bucket() -> str:
    bucket = os.getenv("S3_BUCKET_NAME", "")
    if not bucket:
        raise ExploreContentError("S3_BUCKET_NAME is required for explore content")
    return bucket


def _content_key(city: str) -> str:
    return f"content/explore/{city}/spots.json"


def _image_key(city: str, filename: str) -> str:
    return f"content/explore/{city}/images/{validate_image_name(filename)}"


def load_s3_content(city: str) -> dict[str, Any]:
    import boto3

    bucket = _s3_bucket()
    key = _content_key(city)
    try:
        response = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        raw = response["Body"].read()
    except Exception as error:
        raise ExploreContentNotFoundError(
            f"could not read explore content from s3://{bucket}/{key}"
        ) from error

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExploreContentError(
            f"invalid UTF-8 JSON in s3://{bucket}/{key}"
        ) from error
    return validate_payload(payload)


def load_content(*, mode: str, city: str) -> dict[str, Any]:
    if mode == "local":
        return load_local_content(city)
    if mode == "lambda":
        return load_s3_content(city)
    raise ExploreContentError(f"unsupported runtime mode: {mode!r}")


def load_image(*, mode: str, city: str, filename: str) -> tuple[bytes, str]:
    filename = validate_image_name(filename)
    media_type = image_media_type(filename)

    if mode == "local":
        _, images_dir = source_paths(city)
        path = images_dir / filename
        if not path.is_file():
            raise ExploreContentNotFoundError(f"image was not found: {path}")
        return path.read_bytes(), media_type

    if mode == "lambda":
        import boto3

        bucket = _s3_bucket()
        key = _image_key(city, filename)
        try:
            response = boto3.client("s3").get_object(Bucket=bucket, Key=key)
            return response["Body"].read(), media_type
        except Exception as error:
            raise ExploreContentNotFoundError(
                f"could not read explore image from s3://{bucket}/{key}"
            ) from error

    raise ExploreContentError(f"unsupported runtime mode: {mode!r}")
