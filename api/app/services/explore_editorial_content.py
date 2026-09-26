from __future__ import annotations

import csv
import json
import mimetypes
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


EXPECTED_COLUMNS = ("stop_name", "route_id", "comment", "image", "caption")
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


def master_data_dir(city: str) -> Path:
    if city != "tokyo":
        raise ExploreContentError(
            f"explore editorial master lookup is not configured for city={city!r}"
        )
    return repository_root() / "api" / "data"


def master_data_paths(data_dir: Path) -> tuple[Path, Path]:
    return (
        data_dir / "odpt_BusstopPole.json",
        data_dir / "odpt_BusroutePattern.json",
    )


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


def _required_string(value: Any, *, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExploreContentError(f"{where} must be a non-empty string")
    if value != value.strip():
        raise ExploreContentError(
            f"{where} must not have surrounding whitespace"
        )
    return value


def _load_json_array(path: Path, *, label: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ExploreContentNotFoundError(f"{label} was not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExploreContentError(f"{label} is not valid UTF-8 JSON: {path}") from error
    if not isinstance(payload, list):
        raise ExploreContentError(f"{label} root must be a JSON array: {path}")

    result: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ExploreContentError(f"{label}[{index}] must be an object")
        result.append(item)
    return result


def _route_label(pattern_title: str) -> str:
    first = pattern_title.split(maxsplit=1)[0]
    if not first:
        raise ExploreContentError(
            f"could not derive route label from dc:title={pattern_title!r}"
        )
    # Presentation only. Matching always uses the exact ODPT route_id.
    return unicodedata.normalize("NFKC", first)


def build_stop_route_catalog(data_dir: Path) -> list[dict[str, Any]]:
    busstop_path, pattern_path = master_data_paths(data_dir)
    poles = _load_json_array(busstop_path, label="ODPT BusstopPole master")
    patterns = _load_json_array(pattern_path, label="ODPT BusroutePattern master")

    pole_name_by_id: dict[str, str] = {}
    for index, pole in enumerate(poles):
        pole_id = _required_string(
            pole.get("owl:sameAs"),
            where=f"BusstopPole[{index}].owl:sameAs",
        )
        stop_name = _required_string(
            pole.get("dc:title"),
            where=f"BusstopPole[{index}].dc:title",
        )
        previous = pole_name_by_id.get(pole_id)
        if previous is not None and previous != stop_name:
            raise ExploreContentError(
                f"pole id {pole_id!r} has conflicting names: "
                f"{previous!r} vs {stop_name!r}"
            )
        pole_name_by_id[pole_id] = stop_name

    route_label_by_id: dict[str, str] = {}
    pole_ids_by_key: dict[tuple[str, str], set[str]] = defaultdict(set)

    for pattern_index, pattern in enumerate(patterns):
        route_id = _required_string(
            pattern.get("odpt:busroute"),
            where=f"BusroutePattern[{pattern_index}].odpt:busroute",
        )
        title = _required_string(
            pattern.get("dc:title"),
            where=f"BusroutePattern[{pattern_index}].dc:title",
        )
        label = _route_label(title)
        previous_label = route_label_by_id.get(route_id)
        if previous_label is not None and previous_label != label:
            raise ExploreContentError(
                f"route id {route_id!r} has conflicting labels: "
                f"{previous_label!r} vs {label!r}"
            )
        route_label_by_id[route_id] = label

        orders = pattern.get("odpt:busstopPoleOrder")
        if not isinstance(orders, list):
            raise ExploreContentError(
                f"BusroutePattern[{pattern_index}].odpt:busstopPoleOrder "
                "must be a list"
            )

        for order_index, order in enumerate(orders):
            if not isinstance(order, dict):
                raise ExploreContentError(
                    f"BusroutePattern[{pattern_index}]."
                    f"odpt:busstopPoleOrder[{order_index}] must be an object"
                )
            pole_id = _required_string(
                order.get("odpt:busstopPole"),
                where=(
                    f"BusroutePattern[{pattern_index}]."
                    f"odpt:busstopPoleOrder[{order_index}].odpt:busstopPole"
                ),
            )
            stop_name = pole_name_by_id.get(pole_id)
            if stop_name is None:
                raise ExploreContentError(
                    f"BusroutePattern[{pattern_index}] references unknown "
                    f"BusstopPole {pole_id!r}"
                )
            pole_ids_by_key[(stop_name, route_id)].add(pole_id)

    routes_by_stop: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (stop_name, route_id), pole_ids in pole_ids_by_key.items():
        routes_by_stop[stop_name].append(
            {
                "route_id": route_id,
                "route_label": route_label_by_id[route_id],
                "pole_ids": sorted(pole_ids),
            }
        )

    catalog: list[dict[str, Any]] = []
    for stop_name in sorted(routes_by_stop):
        routes = sorted(
            routes_by_stop[stop_name],
            key=lambda item: (item["route_label"], item["route_id"]),
        )
        catalog.append({"stop_name": stop_name, "routes": routes})
    return catalog


def _pole_ids_by_stop_route(
    data_dir: Path,
) -> dict[tuple[str, str], tuple[str, ...]]:
    catalog = build_stop_route_catalog(data_dir)
    result: dict[tuple[str, str], tuple[str, ...]] = {}
    for stop in catalog:
        stop_name = stop["stop_name"]
        for route in stop["routes"]:
            result[(stop_name, route["route_id"])] = tuple(route["pole_ids"])
    return result


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


def read_authoring_groups(
    csv_path: Path,
    images_dir: Path,
) -> list[dict[str, Any]]:
    if not csv_path.is_file():
        raise ExploreContentNotFoundError(f"CSV was not found: {csv_path}")

    order: list[tuple[str, str]] = []
    comments: dict[tuple[str, str], str] = {}
    images_by_key: dict[tuple[str, str], list[dict[str, str]]] = {}
    seen_images_by_key: dict[tuple[str, str], set[str]] = {}
    referenced_images: set[str] = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ExploreContentError(f"CSV has no header: {csv_path}")
        if tuple(reader.fieldnames) != EXPECTED_COLUMNS:
            raise ExploreContentError(
                "CSV columns must be exactly "
                f"{','.join(EXPECTED_COLUMNS)}; got {reader.fieldnames}"
            )

        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ExploreContentError(
                    f"CSV row {row_number} has more fields than the header"
                )
            values = {key: row[key] for key in EXPECTED_COLUMNS}
            if any(value is None for value in values.values()):
                raise ExploreContentError(f"CSV row {row_number} is malformed")

            stop_name = values["stop_name"]
            route_id = values["route_id"]
            comment = values["comment"]
            image = values["image"]
            caption = values["caption"]

            if stop_name != stop_name.strip() or not stop_name:
                raise ExploreContentError(
                    f"CSV row {row_number}: stop_name must be non-empty "
                    "without surrounding whitespace"
                )
            if route_id != route_id.strip() or not route_id:
                raise ExploreContentError(
                    f"CSV row {row_number}: route_id must be non-empty "
                    "without surrounding whitespace"
                )
            if not comment and not image:
                raise ExploreContentError(
                    f"CSV row {row_number}: comment or image is required"
                )
            if caption and not image:
                raise ExploreContentError(
                    f"CSV row {row_number}: caption requires image"
                )

            key = (stop_name, route_id)
            if key not in comments:
                order.append(key)
                comments[key] = comment
                images_by_key[key] = []
                seen_images_by_key[key] = set()
            elif comment:
                existing = comments[key]
                if existing and existing != comment:
                    raise ExploreContentError(
                        f"CSV row {row_number}: conflicting comments for "
                        f"stop_name={stop_name!r}, route_id={route_id!r}"
                    )
                if not existing:
                    comments[key] = comment

            if image:
                filename = validate_image_name(image)
                image_path = images_dir / filename
                if not image_path.is_file():
                    raise ExploreContentError(
                        f"CSV row {row_number}: image was not found: {image_path}"
                    )
                if filename in seen_images_by_key[key]:
                    raise ExploreContentError(
                        f"CSV row {row_number}: duplicate image {filename!r} "
                        f"for stop_name={stop_name!r}, route_id={route_id!r}"
                    )
                seen_images_by_key[key].add(filename)
                referenced_images.add(filename)
                images_by_key[key].append(
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

    return [
        {
            "stop_name": stop_name,
            "route_id": route_id,
            "comment": comments[(stop_name, route_id)],
            "images": images_by_key[(stop_name, route_id)],
        }
        for stop_name, route_id in order
    ]


def write_authoring_groups(
    csv_path: Path,
    groups: list[dict[str, Any]],
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPECTED_COLUMNS)
        writer.writeheader()
        for group_index, group in enumerate(groups):
            _validate_exact_keys(
                group,
                {"stop_name", "route_id", "comment", "images"},
                where=f"authoring_groups[{group_index}]",
            )
            stop_name = _required_string(
                group["stop_name"],
                where=f"authoring_groups[{group_index}].stop_name",
            )
            route_id = _required_string(
                group["route_id"],
                where=f"authoring_groups[{group_index}].route_id",
            )
            comment = group["comment"]
            images = group["images"]
            if not isinstance(comment, str):
                raise ExploreContentError(
                    f"authoring_groups[{group_index}].comment must be a string"
                )
            if not isinstance(images, list):
                raise ExploreContentError(
                    f"authoring_groups[{group_index}].images must be a list"
                )
            if not comment and not images:
                raise ExploreContentError(
                    f"authoring_groups[{group_index}] must contain comment or image"
                )

            if images:
                for image_index, image in enumerate(images):
                    if not isinstance(image, dict):
                        raise ExploreContentError(
                            f"authoring_groups[{group_index}].images[{image_index}] "
                            "must be an object"
                        )
                    _validate_exact_keys(
                        image,
                        {"file", "caption"},
                        where=(
                            f"authoring_groups[{group_index}].images[{image_index}]"
                        ),
                    )
                    filename = validate_image_name(image["file"])
                    caption = image["caption"]
                    if not isinstance(caption, str):
                        raise ExploreContentError(
                            f"authoring_groups[{group_index}].images[{image_index}]."
                            "caption must be a string"
                        )
                    writer.writerow(
                        {
                            "stop_name": stop_name,
                            "route_id": route_id,
                            "comment": comment if image_index == 0 else "",
                            "image": filename,
                            "caption": caption,
                        }
                    )
            else:
                writer.writerow(
                    {
                        "stop_name": stop_name,
                        "route_id": route_id,
                        "comment": comment,
                        "image": "",
                        "caption": "",
                    }
                )


def compile_csv(
    csv_path: Path,
    images_dir: Path,
    *,
    data_dir: Path,
) -> dict[str, Any]:
    groups = read_authoring_groups(csv_path, images_dir)
    if not groups:
        return {"spots": []}

    pole_ids_by_key = _pole_ids_by_stop_route(data_dir)
    claimed_poles: dict[str, tuple[str, str]] = {}
    spots: list[dict[str, Any]] = []

    for group in groups:
        stop_name = group["stop_name"]
        route_id = group["route_id"]
        key = (stop_name, route_id)
        pole_ids = pole_ids_by_key.get(key)
        if not pole_ids:
            raise ExploreContentError(
                "no BusstopPole matched exact stop_name + route_id: "
                f"stop_name={stop_name!r}, route_id={route_id!r}"
            )

        for pole_id in pole_ids:
            previous = claimed_poles.get(pole_id)
            if previous is not None and previous != key:
                raise ExploreContentError(
                    f"BusstopPole {pole_id!r} is selected by multiple CSV entries: "
                    f"{previous!r} and {key!r}"
                )
            claimed_poles[pole_id] = key
            spots.append(
                {
                    "stop_id": pole_id,
                    "comment": group["comment"],
                    "images": [dict(image) for image in group["images"]],
                }
            )

    return validate_payload({"spots": spots})


def load_local_content(city: str) -> dict[str, Any]:
    csv_path, images_dir = source_paths(city)
    return compile_csv(
        csv_path,
        images_dir,
        data_dir=master_data_dir(city),
    )


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
