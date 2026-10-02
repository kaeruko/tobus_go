#!/usr/bin/env python3
"""Find the nearest Toei bus stop on a route from a JPEG GPS position."""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ODPT_PUBLIC_BASE = "https://api-public.odpt.org/api/v4"
TOEI_OPERATOR = "odpt.Operator:Toei"
EARTH_RADIUS_M = 6_371_008.8
_HTTP_TIMEOUT_SECONDS = 20.0
_TIE_EPSILON_METERS = 0.001


class LocatorError(RuntimeError):
    """Raised when the requested location cannot be determined safely."""


@dataclass(frozen=True, slots=True)
class CandidateStop:
    pole_id: str
    name: str
    lat: float
    lon: float
    distance_m: float
    pole_number: str | None


def _u16(data: bytes, offset: int, endian: str) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise LocatorError(f"EXIF offset out of bounds while reading uint16: {offset}")
    return struct.unpack_from(f"{endian}H", data, offset)[0]


def _u32(data: bytes, offset: int, endian: str) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise LocatorError(f"EXIF offset out of bounds while reading uint32: {offset}")
    return struct.unpack_from(f"{endian}I", data, offset)[0]


def _find_exif_tiff(jpeg: bytes) -> bytes:
    if len(jpeg) < 4 or jpeg[:2] != b"\xff\xd8":
        raise LocatorError("image is not a JPEG file")

    offset = 2
    while offset < len(jpeg):
        if jpeg[offset] != 0xFF:
            raise LocatorError(f"invalid JPEG marker at byte offset {offset}")

        while offset < len(jpeg) and jpeg[offset] == 0xFF:
            offset += 1
        if offset >= len(jpeg):
            break

        marker = jpeg[offset]
        offset += 1

        if marker in (0xD8, 0xD9):
            continue
        if marker == 0xDA:
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue

        if offset + 2 > len(jpeg):
            raise LocatorError("truncated JPEG segment length")
        segment_length = struct.unpack_from(">H", jpeg, offset)[0]
        if segment_length < 2:
            raise LocatorError(f"invalid JPEG segment length: {segment_length}")

        payload_start = offset + 2
        payload_end = offset + segment_length
        if payload_end > len(jpeg):
            raise LocatorError("truncated JPEG segment")

        if marker == 0xE1:
            payload = jpeg[payload_start:payload_end]
            if payload.startswith(b"Exif\x00\x00"):
                return payload[6:]

        offset = payload_end

    raise LocatorError("JPEG has no EXIF metadata")


_TIFF_TYPE_SIZES = {
    1: 1,  # BYTE
    2: 1,  # ASCII
    3: 2,  # SHORT
    4: 4,  # LONG
    5: 8,  # RATIONAL
    7: 1,  # UNDEFINED
    9: 4,  # SLONG
    10: 8,  # SRATIONAL
}


def _read_ifd(
    tiff: bytes,
    *,
    endian: str,
    ifd_offset: int,
) -> dict[int, tuple[int, int, bytes]]:
    entry_count = _u16(tiff, ifd_offset, endian)
    entries: dict[int, tuple[int, int, bytes]] = {}

    for index in range(entry_count):
        entry_offset = ifd_offset + 2 + index * 12
        if entry_offset + 12 > len(tiff):
            raise LocatorError(
                f"truncated EXIF IFD entry: ifd={ifd_offset}, index={index}"
            )

        tag = _u16(tiff, entry_offset, endian)
        value_type = _u16(tiff, entry_offset + 2, endian)
        count = _u32(tiff, entry_offset + 4, endian)

        type_size = _TIFF_TYPE_SIZES.get(value_type)
        if type_size is None:
            continue

        byte_count = type_size * count
        if byte_count <= 4:
            value_start = entry_offset + 8
        else:
            value_start = _u32(tiff, entry_offset + 8, endian)

        value_end = value_start + byte_count
        if value_start < 0 or value_end > len(tiff):
            raise LocatorError(
                "EXIF value points outside TIFF data: "
                f"tag=0x{tag:04x}, start={value_start}, size={byte_count}"
            )

        entries[tag] = (value_type, count, tiff[value_start:value_end])

    return entries


def _decode_ascii(
    entry: tuple[int, int, bytes] | None,
    *,
    tag_name: str,
) -> str:
    if entry is None:
        raise LocatorError(f"EXIF GPS tag is missing: {tag_name}")
    value_type, _, raw = entry
    if value_type != 2:
        raise LocatorError(
            f"EXIF GPS tag has unexpected type: {tag_name} type={value_type}"
        )
    try:
        return raw.rstrip(b"\x00").decode("ascii")
    except UnicodeDecodeError as exc:
        raise LocatorError(f"EXIF GPS tag is not ASCII: {tag_name}") from exc


def _decode_rationals(
    entry: tuple[int, int, bytes] | None,
    *,
    endian: str,
    tag_name: str,
    expected_count: int,
) -> tuple[float, ...]:
    if entry is None:
        raise LocatorError(f"EXIF GPS tag is missing: {tag_name}")

    value_type, count, raw = entry
    if value_type != 5 or count != expected_count:
        raise LocatorError(
            "EXIF GPS tag has unexpected shape: "
            f"{tag_name} type={value_type} count={count}"
        )

    expected_bytes = expected_count * 8
    if len(raw) != expected_bytes:
        raise LocatorError(
            f"EXIF GPS tag has invalid byte length: {tag_name} bytes={len(raw)}"
        )

    values: list[float] = []
    for index in range(expected_count):
        numerator = _u32(raw, index * 8, endian)
        denominator = _u32(raw, index * 8 + 4, endian)
        if denominator == 0:
            raise LocatorError(
                f"EXIF GPS rational has zero denominator: {tag_name}[{index}]"
            )
        values.append(numerator / denominator)
    return tuple(values)


def extract_gps_from_jpeg(path: Path) -> tuple[float, float]:
    try:
        jpeg = path.read_bytes()
    except OSError as exc:
        raise LocatorError(f"failed to read image: {path}: {exc}") from exc

    tiff = _find_exif_tiff(jpeg)
    if len(tiff) < 8:
        raise LocatorError("EXIF TIFF header is truncated")

    if tiff[:2] == b"II":
        endian = "<"
    elif tiff[:2] == b"MM":
        endian = ">"
    else:
        raise LocatorError("EXIF TIFF byte order is invalid")

    if _u16(tiff, 2, endian) != 42:
        raise LocatorError("EXIF TIFF magic number is invalid")

    ifd0_offset = _u32(tiff, 4, endian)
    ifd0 = _read_ifd(tiff, endian=endian, ifd_offset=ifd0_offset)

    gps_pointer = ifd0.get(0x8825)
    if gps_pointer is None:
        raise LocatorError("image EXIF has no GPS IFD")
    pointer_type, pointer_count, pointer_raw = gps_pointer
    if pointer_type != 4 or pointer_count != 1 or len(pointer_raw) != 4:
        raise LocatorError(
            "EXIF GPS IFD pointer has unexpected shape: "
            f"type={pointer_type} count={pointer_count}"
        )

    gps_ifd_offset = struct.unpack(f"{endian}I", pointer_raw)[0]
    gps = _read_ifd(tiff, endian=endian, ifd_offset=gps_ifd_offset)

    lat_ref = _decode_ascii(gps.get(0x0001), tag_name="GPSLatitudeRef")
    lat_dms = _decode_rationals(
        gps.get(0x0002),
        endian=endian,
        tag_name="GPSLatitude",
        expected_count=3,
    )
    lon_ref = _decode_ascii(gps.get(0x0003), tag_name="GPSLongitudeRef")
    lon_dms = _decode_rationals(
        gps.get(0x0004),
        endian=endian,
        tag_name="GPSLongitude",
        expected_count=3,
    )

    if lat_ref not in ("N", "S"):
        raise LocatorError(f"invalid GPSLatitudeRef: {lat_ref!r}")
    if lon_ref not in ("E", "W"):
        raise LocatorError(f"invalid GPSLongitudeRef: {lon_ref!r}")

    lat = lat_dms[0] + lat_dms[1] / 60.0 + lat_dms[2] / 3600.0
    lon = lon_dms[0] + lon_dms[1] / 60.0 + lon_dms[2] / 3600.0
    if lat_ref == "S":
        lat = -lat
    if lon_ref == "W":
        lon = -lon

    if not (-90.0 <= lat <= 90.0):
        raise LocatorError(f"EXIF latitude is out of range: {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise LocatorError(f"EXIF longitude is out of range: {lon}")

    return lat, lon


def normalize_route_label(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("route label must be a string")
    normalized = unicodedata.normalize("NFKC", value).strip()
    return re.sub(r"\s+", "", normalized)


def _pattern_route_label(pattern: Mapping[str, object]) -> str:
    title = pattern.get("dc:title")
    if not isinstance(title, str) or not title.strip():
        raise LocatorError("ODPT BusroutePattern has no dc:title")
    first_token = re.split(r"\s+", title.strip(), maxsplit=1)[0]
    return normalize_route_label(first_token)


def select_route_stop_ids(
    patterns: Iterable[Mapping[str, object]],
    route_label: str,
) -> tuple[set[str], int]:
    target = normalize_route_label(route_label)
    if not target:
        raise LocatorError("route label must not be empty")

    matched: list[Mapping[str, object]] = []
    seen_labels: set[str] = set()

    for pattern in patterns:
        label = _pattern_route_label(pattern)
        seen_labels.add(label)
        if label == target:
            matched.append(pattern)

    if not matched:
        examples = ", ".join(sorted(seen_labels)[:20])
        raise LocatorError(
            f"route not found in ODPT BusroutePattern: {route_label!r}. "
            f"example available labels: {examples}"
        )

    pole_ids: set[str] = set()
    for pattern in matched:
        pattern_id = pattern.get("owl:sameAs") or pattern.get("@id")
        orders = pattern.get("odpt:busstopPoleOrder")
        if not isinstance(orders, list) or not orders:
            raise LocatorError(
                f"matched BusroutePattern has no odpt:busstopPoleOrder: {pattern_id}"
            )

        for order in orders:
            if not isinstance(order, Mapping):
                raise LocatorError(
                    f"invalid odpt:busstopPoleOrder entry: {pattern_id}"
                )
            pole_id = order.get("odpt:busstopPole")
            if not isinstance(pole_id, str) or not pole_id:
                raise LocatorError(
                    f"BusroutePattern order has no odpt:busstopPole: {pattern_id}"
                )
            pole_ids.add(pole_id)

    if not pole_ids:
        raise LocatorError(f"route has no bus stops: {route_label!r}")

    return pole_ids, len(matched)


def haversine_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def rank_candidate_stops(
    poles: Iterable[Mapping[str, object]],
    *,
    candidate_ids: set[str],
    photo_lat: float,
    photo_lon: float,
) -> list[CandidateStop]:
    by_id: dict[str, Mapping[str, object]] = {}
    for pole in poles:
        pole_id = pole.get("owl:sameAs")
        if not isinstance(pole_id, str) or not pole_id:
            raise LocatorError("ODPT BusstopPole has no owl:sameAs")
        if pole_id in by_id:
            raise LocatorError(f"duplicate ODPT BusstopPole id: {pole_id}")
        by_id[pole_id] = pole

    missing_ids = sorted(candidate_ids.difference(by_id))
    if missing_ids:
        preview = ", ".join(missing_ids[:10])
        raise LocatorError(
            "BusroutePattern references BusstopPole records that were not returned: "
            f"{preview}"
        )

    ranked: list[CandidateStop] = []
    for pole_id in candidate_ids:
        pole = by_id[pole_id]
        lat = pole.get("geo:lat")
        lon = pole.get("geo:long")
        if (
            isinstance(lat, bool)
            or not isinstance(lat, (int, float))
            or isinstance(lon, bool)
            or not isinstance(lon, (int, float))
        ):
            raise LocatorError(f"BusstopPole has invalid coordinates: {pole_id}")

        note = pole.get("odpt:note")
        title = pole.get("dc:title")
        if isinstance(note, str) and note.strip():
            name = note.strip()
        elif isinstance(title, str) and title.strip():
            name = title.strip()
        else:
            raise LocatorError(f"BusstopPole has no display name: {pole_id}")

        pole_number_raw = pole.get("odpt:busstopPoleNumber")
        if pole_number_raw is None:
            pole_number = None
        elif isinstance(pole_number_raw, str):
            pole_number = pole_number_raw
        else:
            raise LocatorError(
                f"BusstopPole has invalid odpt:busstopPoleNumber: {pole_id}"
            )

        ranked.append(
            CandidateStop(
                pole_id=pole_id,
                name=name,
                lat=float(lat),
                lon=float(lon),
                distance_m=haversine_m(photo_lat, photo_lon, float(lat), float(lon)),
                pole_number=pole_number,
            )
        )

    ranked.sort(key=lambda item: (item.distance_m, item.pole_id))
    if not ranked:
        raise LocatorError("no candidate bus stops were available for the route")

    if (
        len(ranked) >= 2
        and abs(ranked[1].distance_m - ranked[0].distance_m)
        <= _TIE_EPSILON_METERS
        and ranked[1].pole_id != ranked[0].pole_id
    ):
        raise LocatorError(
            "nearest bus stop is tied: "
            f"{ranked[0].name} ({ranked[0].pole_id}) "
            f"and {ranked[1].name} ({ranked[1].pole_id})"
        )

    return ranked


def _fetch_odpt(endpoint: str) -> list[Mapping[str, object]]:
    query = urlencode({"odpt:operator": TOEI_OPERATOR})
    url = f"{ODPT_PUBLIC_BASE}/{endpoint}?{query}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "tobus_go/find_nearest_bus_stop.py",
        },
    )

    try:
        with urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except Exception as exc:
        raise LocatorError(f"ODPT request failed: {url}: {exc}") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocatorError(f"ODPT returned invalid UTF-8 JSON: {url}") from exc

    if not isinstance(payload, list):
        raise LocatorError(
            f"ODPT response is not a JSON array: {url}: {type(payload).__name__}"
        )
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise LocatorError(
                f"ODPT response item is not an object: {url}: index={index}"
            )
    return payload


def locate(image_path: Path, route_label: str) -> tuple[float, float, int, list[CandidateStop]]:
    photo_lat, photo_lon = extract_gps_from_jpeg(image_path)
    patterns = _fetch_odpt("odpt:BusroutePattern")
    candidate_ids, matched_pattern_count = select_route_stop_ids(patterns, route_label)
    poles = _fetch_odpt("odpt:BusstopPole")
    ranked = rank_candidate_stops(
        poles,
        candidate_ids=candidate_ids,
        photo_lat=photo_lat,
        photo_lon=photo_lon,
    )
    return photo_lat, photo_lon, matched_pattern_count, ranked


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read GPS coordinates from a JPEG and find the nearest physical "
            "Toei bus stop used by the specified route."
        )
    )
    parser.add_argument("--image", required=True, type=Path, help="JPEG path")
    parser.add_argument("--route", required=True, help="Route label, e.g. 渋88")
    parser.add_argument(
        "--show",
        type=int,
        default=3,
        help="Number of nearest candidates to print (default: 3)",
    )
    args = parser.parse_args()
    if args.show < 1:
        parser.error("--show must be at least 1")
    return args


def main() -> int:
    args = parse_args()

    try:
        photo_lat, photo_lon, pattern_count, ranked = locate(
            args.image,
            args.route,
        )
    except LocatorError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    nearest = ranked[0]
    print(f"image: {args.image}")
    print(f"gps: {photo_lat:.8f}, {photo_lon:.8f}")
    print(f"route: {normalize_route_label(args.route)}")
    print(f"matched_patterns: {pattern_count}")
    print()
    print("nearest_stop:")
    print(f"  name: {nearest.name}")
    print(f"  pole_number: {nearest.pole_number or '-'}")
    print(f"  pole_id: {nearest.pole_id}")
    print(f"  gps: {nearest.lat:.8f}, {nearest.lon:.8f}")
    print(f"  distance_m: {nearest.distance_m:.1f}")

    if args.show > 1:
        print()
        print("candidates:")
        for index, candidate in enumerate(ranked[: args.show], start=1):
            print(
                f"  {index}. {candidate.name} "
                f"[pole {candidate.pole_number or '-'}] "
                f"{candidate.distance_m:.1f} m"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
