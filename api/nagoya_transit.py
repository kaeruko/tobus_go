from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata, TransitDataset, TransitMode, TransitStop
from transit_engine import TransitItinerary, TransitRouteEngine

NAGOYA_FEED_ID = "nagoya_bus"
NAGOYA_DATASET_ID = "c5794008-8053-42ab-99b9-ee7f6fdf9a9e"
NAGOYA_RESOURCE_ID = "125a1d12-7df6-489c-abde-911856e05d1b"
NAGOYA_CKAN_PACKAGE_URL = (
    "https://data.bodik.jp/api/3/action/package_show"
    f"?id={NAGOYA_DATASET_ID}"
)
NAGOYA_MANIFEST_FILENAME = "nagoya_gtfs_manifest.json"
_REQUIRED_GTFS_FILES = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")
_REVISION_PATTERN = re.compile(
    r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日改正"
)
_JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True, slots=True)
class NagoyaGtfsManifest:
    dataset_id: str
    resource_id: str
    revision: str
    source_url: str
    fetched_at: datetime
    sha256: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "NagoyaGtfsManifest":
        required = (
            "dataset_id",
            "resource_id",
            "revision",
            "source_url",
            "fetched_at",
            "sha256",
        )
        for key in required:
            if key not in value:
                raise ValueError(f"Nagoya GTFS manifest is missing {key}")
        try:
            fetched_at = datetime.fromisoformat(str(value["fetched_at"]))
        except ValueError as error:
            raise ValueError("Nagoya GTFS manifest has invalid fetched_at") from error
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("Nagoya GTFS manifest fetched_at must be timezone-aware")
        manifest = cls(
            dataset_id=str(value["dataset_id"]),
            resource_id=str(value["resource_id"]),
            revision=_validate_revision(str(value["revision"])),
            source_url=str(value["source_url"]),
            fetched_at=fetched_at,
            sha256=str(value["sha256"]),
        )
        manifest.validate_source_identity()
        return manifest

    def validate_source_identity(self) -> None:
        if self.dataset_id != NAGOYA_DATASET_ID:
            raise ValueError(
                f"Unexpected Nagoya GTFS dataset_id: {self.dataset_id!r}"
            )
        if self.resource_id != NAGOYA_RESOURCE_ID:
            raise ValueError(
                f"Unexpected Nagoya GTFS resource_id: {self.resource_id!r}"
            )
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Nagoya GTFS source_url must be an absolute HTTPS URL")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("Nagoya GTFS manifest has invalid sha256")

    def to_mapping(self) -> dict[str, str]:
        return {
            "dataset_id": self.dataset_id,
            "resource_id": self.resource_id,
            "revision": self.revision,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at.isoformat(),
            "sha256": self.sha256,
        }


def _validate_revision(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError(
            f"Invalid Nagoya GTFS revision {value!r}; expected YYYY-MM-DD"
        ) from error
    if parsed.isoformat() != value:
        raise ValueError(
            f"Invalid Nagoya GTFS revision {value!r}; expected zero-padded YYYY-MM-DD"
        )
    return value


def required_expected_revision() -> str:
    value = os.getenv("NAGOYA_GTFS_EXPECTED_REVISION")
    if value is None or value == "":
        raise RuntimeError(
            "NAGOYA_GTFS_EXPECTED_REVISION is required for Nagoya runtime"
        )
    return _validate_revision(value)


def _revision_from_resource_name(name: str) -> str:
    match = _REVISION_PATTERN.search(name)
    if match is None:
        raise ValueError(
            f"Could not determine Nagoya GTFS revision from resource name: {name!r}"
        )
    return (
        f"{int(match.group('year')):04d}-"
        f"{int(match.group('month')):02d}-"
        f"{int(match.group('day')):02d}"
    )


def resolve_nagoya_resource(
    package_payload: dict[str, Any], *, expected_revision: str
) -> dict[str, str]:
    expected_revision = _validate_revision(expected_revision)
    if package_payload.get("success") is not True:
        raise RuntimeError("BODIK package_show response did not report success")
    result = package_payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("BODIK package_show response is missing result object")
    if result.get("id") != NAGOYA_DATASET_ID:
        raise ValueError(f"Unexpected BODIK package id: {result.get('id')!r}")
    resources = result.get("resources")
    if not isinstance(resources, list):
        raise ValueError("BODIK package metadata is missing resources list")
    matches = [
        resource
        for resource in resources
        if isinstance(resource, dict) and resource.get("id") == NAGOYA_RESOURCE_ID
    ]
    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one configured Nagoya GTFS resource "
            f"{NAGOYA_RESOURCE_ID}, found {len(matches)}"
        )
    resource = matches[0]
    if resource.get("package_id") not in (None, NAGOYA_DATASET_ID):
        raise ValueError(
            "Nagoya GTFS resource belongs to unexpected package: "
            f"{resource.get('package_id')!r}"
        )
    if resource.get("state") not in (None, "active"):
        raise ValueError(
            f"Nagoya GTFS resource is not active: {resource.get('state')!r}"
        )
    resource_format = str(resource.get("format") or "")
    mimetype = str(resource.get("mimetype") or "")
    if resource_format.upper() != "ZIP" and mimetype != "application/zip":
        raise ValueError("Configured Nagoya GTFS resource is not identified as ZIP")
    name = str(resource.get("name") or "")
    revision = _revision_from_resource_name(name)
    if revision != expected_revision:
        raise RuntimeError(
            "Nagoya GTFS revision mismatch: "
            f"expected={expected_revision}, catalog_resource={revision}"
        )
    source_url = str(resource.get("url") or "")
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Nagoya GTFS resource URL must be absolute HTTPS")
    return {
        "dataset_id": NAGOYA_DATASET_ID,
        "resource_id": NAGOYA_RESOURCE_ID,
        "revision": revision,
        "source_url": source_url,
    }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_gtfs_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    files = [member for member in archive.infolist() if not member.is_dir()]
    normalized: list[tuple[zipfile.ZipInfo, str]] = []
    for member in files:
        name = member.filename.replace("\\", "/")
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"Unsafe path in Nagoya GTFS ZIP: {member.filename}")
        normalized.append((member, name))

    by_basename: dict[str, list[tuple[zipfile.ZipInfo, str]]] = {}
    for member, name in normalized:
        by_basename.setdefault(Path(name).name, []).append((member, name))

    selected: dict[str, zipfile.ZipInfo] = {}
    required_plus_calendar = set(_REQUIRED_GTFS_FILES) | {
        "calendar.txt",
        "calendar_dates.txt",
    }
    for basename in required_plus_calendar:
        matches = by_basename.get(basename, [])
        if len(matches) > 1:
            raise RuntimeError(f"Nagoya GTFS ZIP contains multiple {basename} files")
        if matches:
            selected[basename] = matches[0][0]

    for required in _REQUIRED_GTFS_FILES:
        if required not in selected:
            raise RuntimeError(f"Nagoya GTFS ZIP is missing {required}")
    if "calendar.txt" not in selected and "calendar_dates.txt" not in selected:
        raise RuntimeError("Nagoya GTFS ZIP requires calendar.txt or calendar_dates.txt")
    return selected


def fetch_nagoya_gtfs(
    output_dir: str | Path,
    *,
    expected_revision: str,
    client: httpx.Client | None = None,
) -> NagoyaGtfsManifest:
    expected_revision = _validate_revision(expected_revision)
    target = Path(output_dir)
    if target.exists():
        raise FileExistsError(
            "Nagoya GTFS output already exists; choose a new version directory: "
            f"{target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)

    owns_client = client is None
    http_client = client or httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        metadata_response = http_client.get(NAGOYA_CKAN_PACKAGE_URL)
        metadata_response.raise_for_status()
        package_payload = metadata_response.json()
        if not isinstance(package_payload, dict):
            raise ValueError("BODIK package_show response must be a JSON object")
        resource = resolve_nagoya_resource(
            package_payload, expected_revision=expected_revision
        )

        zip_response = http_client.get(resource["source_url"])
        zip_response.raise_for_status()
        archive_bytes = zip_response.content
        if not archive_bytes:
            raise RuntimeError("Downloaded Nagoya GTFS ZIP is empty")
    finally:
        if owns_client:
            http_client.close()

    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=str(target.parent)))
    try:
        archive_path = staging / "source.zip"
        archive_path.write_bytes(archive_bytes)
        with zipfile.ZipFile(archive_path) as archive:
            members = _safe_gtfs_members(archive)
            feed_dir = staging / "feed"
            feed_dir.mkdir()
            for basename, member in members.items():
                with archive.open(member) as source, (feed_dir / basename).open("wb") as dest:
                    shutil.copyfileobj(source, dest)
        archive_path.unlink()

        fetched_at = datetime.now(timezone.utc)
        manifest = NagoyaGtfsManifest(
            dataset_id=NAGOYA_DATASET_ID,
            resource_id=NAGOYA_RESOURCE_ID,
            revision=expected_revision,
            source_url=resource["source_url"],
            fetched_at=fetched_at,
            sha256=_sha256_bytes(archive_bytes),
        )
        metadata = FeedMetadata(
            feed_id=NAGOYA_FEED_ID,
            source_type="gtfs-jp",
            source_uri=manifest.source_url,
            version=manifest.revision,
            fetched_at=manifest.fetched_at,
        )
        GtfsTransitAdapter.load(feed_dir, metadata=metadata)
        (feed_dir / NAGOYA_MANIFEST_FILENAME).write_text(
            json.dumps(manifest.to_mapping(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(feed_dir, target)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def load_nagoya_dataset(
    gtfs_dir: str | Path, *, expected_revision: str
) -> TransitDataset:
    expected_revision = _validate_revision(expected_revision)
    root = Path(gtfs_dir)
    manifest_path = root / NAGOYA_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Nagoya GTFS manifest must be a JSON object")
    manifest = NagoyaGtfsManifest.from_mapping(raw)
    if manifest.revision != expected_revision:
        raise RuntimeError(
            "Nagoya GTFS manifest revision mismatch: "
            f"expected={expected_revision}, installed={manifest.revision}"
        )
    metadata = FeedMetadata(
        feed_id=NAGOYA_FEED_ID,
        source_type="gtfs-jp",
        source_uri=manifest.source_url,
        version=manifest.revision,
        fetched_at=manifest.fetched_at,
    )
    dataset = GtfsTransitAdapter.load(root, metadata=metadata)
    non_bus_routes = [
        route.id for route in dataset.routes.values() if route.mode is not TransitMode.BUS
    ]
    if non_bus_routes:
        raise ValueError(
            "Nagoya city-bus feed unexpectedly contains non-bus route: "
            f"{non_bus_routes[0]}"
        )
    return dataset


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _clock(minute: int) -> str:
    minute %= 24 * 60
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _stop_point(
    stop: TransitStop, *, origin: bool = False, destination: bool = False
) -> dict[str, Any]:
    return {
        "name": stop.name,
        "lat": stop.lat,
        "lon": stop.lon,
        "id": stop.id,
        "is_origin": origin,
        "is_destination": destination,
    }


class NagoyaRouteBackend:
    def __init__(
        self,
        dataset: TransitDataset,
        *,
        walk_radius_m: int = 600,
        walk_speed_m_per_min: float = 80.0,
        endpoint_candidate_limit: int = 6,
    ):
        if dataset.metadata.feed_id != NAGOYA_FEED_ID:
            raise ValueError(f"NagoyaRouteBackend requires {NAGOYA_FEED_ID} dataset")
        if walk_radius_m <= 0:
            raise ValueError("walk_radius_m must be > 0")
        if walk_speed_m_per_min <= 0:
            raise ValueError("walk_speed_m_per_min must be > 0")
        if endpoint_candidate_limit < 1:
            raise ValueError("endpoint_candidate_limit must be >= 1")
        self.dataset = dataset
        self.engine = TransitRouteEngine(dataset)
        self.walk_radius_m = walk_radius_m
        self.walk_speed_m_per_min = walk_speed_m_per_min
        self.endpoint_candidate_limit = endpoint_candidate_limit

    def _nearby_stops(self, lat: float, lon: float) -> list[tuple[TransitStop, float]]:
        candidates = []
        for stop in self.dataset.stops.values():
            distance = _haversine_m(lat, lon, stop.lat, stop.lon)
            if distance <= self.walk_radius_m:
                candidates.append((stop, distance))
        candidates.sort(key=lambda item: (item[1], item[0].id))
        return candidates[: self.endpoint_candidate_limit]

    def search(
        self,
        *,
        alat: float,
        alon: float,
        blat: float,
        blon: float,
        pref: str,
        start_time: str,
        date_str: str | None,
    ) -> dict[str, Any]:
        for name, value, lower, upper in (
            ("alat", alat, -90.0, 90.0),
            ("blat", blat, -90.0, 90.0),
            ("alon", alon, -180.0, 180.0),
            ("blon", blon, -180.0, 180.0),
        ):
            if not math.isfinite(value) or value < lower or value > upper:
                raise ValueError(f"{name} out of range: {value!r}")
        if date_str is None:
            raise ValueError("target_date_str is required for Nagoya route search")
        try:
            service_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError as error:
            raise ValueError(f"invalid target_date_str: {date_str!r}") from error
        try:
            hour_text, minute_text = start_time.split(":")
            if not hour_text.isdigit() or not minute_text.isdigit():
                raise ValueError
            hour = int(hour_text)
            minute = int(minute_text)
            if hour > 23 or minute > 59:
                raise ValueError
        except ValueError as error:
            raise ValueError(f"invalid start_time: {start_time!r}") from error

        if pref == "time":
            objective = "fastest"
        elif pref in ("fewTransfers", "cost"):
            # `cost` is the legacy API value emitted while the UI visibly
            # selects "乗換少ない優先". Nagoya has no Toei comfort-cost model,
            # so this compatibility value is explicitly defined as the visible
            # few-transfer objective rather than inventing another score.
            objective = "fewest_transfers"
        else:
            raise ValueError(f"unsupported Nagoya route preference: {pref!r}")

        requested_departure = datetime(
            service_date.year,
            service_date.month,
            service_date.day,
            hour,
            minute,
            tzinfo=_JST,
        )
        origin_candidates = self._nearby_stops(alat, alon)
        destination_candidates = self._nearby_stops(blat, blon)
        meta = {
            "destination_reachable": bool(destination_candidates),
            "destination_label": "目的地",
            "fallback_node_name": (
                destination_candidates[0][0].name if destination_candidates else None
            ),
            "fallback_distance_m": (
                destination_candidates[0][1] if destination_candidates else None
            ),
            "walk_limit_m": self.walk_radius_m,
            "feed_id": self.dataset.metadata.feed_id,
            "feed_version": self.dataset.metadata.version,
        }
        if not origin_candidates or not destination_candidates:
            return {"candidates": [], "meta": meta}

        ranked: list[tuple[tuple[int, int, float], dict[str, Any]]] = []
        seen_signatures: set[tuple[str, ...]] = set()
        for origin_stop, origin_distance in origin_candidates:
            origin_walk_min = math.ceil(origin_distance / self.walk_speed_m_per_min)
            transit_departure = requested_departure + timedelta(minutes=origin_walk_min)
            if transit_departure.date() != service_date:
                raise RuntimeError(
                    "Nagoya route search does not support an initial walk crossing "
                    "the service-day boundary"
                )
            for destination_stop, destination_distance in destination_candidates:
                if objective == "fastest":
                    itinerary = self.engine.search_fastest(
                        origin_stop.id,
                        destination_stop.id,
                        departure=transit_departure,
                    )
                else:
                    itinerary = self.engine.search_fewest_transfers(
                        origin_stop.id,
                        destination_stop.id,
                        departure=transit_departure,
                    )
                if itinerary is None:
                    continue
                signature = tuple(leg.trip_id for leg in itinerary.legs)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                destination_walk_min = math.ceil(
                    destination_distance / self.walk_speed_m_per_min
                )
                candidate = self._candidate_json(
                    itinerary,
                    requested_departure=requested_departure,
                    origin_point=(alat, alon),
                    destination_point=(blat, blon),
                    origin_stop=origin_stop,
                    destination_stop=destination_stop,
                    origin_distance=origin_distance,
                    destination_distance=destination_distance,
                    origin_walk_min=origin_walk_min,
                    destination_walk_min=destination_walk_min,
                    preference=pref,
                    candidate_index=len(ranked),
                )
                final_arrival = itinerary.arrival_minute + destination_walk_min
                if objective == "fastest":
                    rank = (
                        final_arrival,
                        itinerary.transfers,
                        origin_distance + destination_distance,
                    )
                else:
                    rank = (
                        itinerary.transfers,
                        final_arrival,
                        origin_distance + destination_distance,
                    )
                ranked.append((rank, candidate))

        ranked.sort(key=lambda item: item[0])
        candidates = []
        for index, (_, candidate) in enumerate(ranked[:5]):
            candidate["id"] = f"nagoya-{index}"
            for step_index, step in enumerate(candidate["steps"]):
                step["step_id"] = f"nagoya-{index}-step-{step_index}"
            candidates.append(candidate)
        return {"candidates": candidates, "meta": meta}

    def _candidate_json(
        self,
        itinerary: TransitItinerary,
        *,
        requested_departure: datetime,
        origin_point: tuple[float, float],
        destination_point: tuple[float, float],
        origin_stop: TransitStop,
        destination_stop: TransitStop,
        origin_distance: float,
        destination_distance: float,
        origin_walk_min: int,
        destination_walk_min: int,
        preference: str,
        candidate_index: int,
    ) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        points: list[list[float]] = [[origin_point[0], origin_point[1]]]
        current_minute = requested_departure.hour * 60 + requested_departure.minute

        if origin_walk_min > 0:
            steps.append(
                {
                    "step_id": f"pending-{candidate_index}-walk-origin",
                    "kind": "walk",
                    "title": "徒歩",
                    "from_": "現在地",
                    "to": origin_stop.name,
                    "minutes": origin_walk_min,
                    "meters": round(origin_distance),
                    "departure_time": _clock(current_minute),
                    "arrival_time": _clock(current_minute + origin_walk_min),
                    "stops": [],
                    "edges": 1,
                }
            )
            current_minute += origin_walk_min
        points.append([origin_stop.lat, origin_stop.lon])

        line_names: list[str] = []
        for leg in itinerary.legs:
            if leg.departure_minute > current_minute:
                stop_name = self.dataset.stops[leg.from_stop_id].name
                steps.append(
                    {
                        "step_id": f"pending-{candidate_index}-wait-{len(steps)}",
                        "kind": "wait",
                        "title": "待ち時間",
                        "from_": stop_name,
                        "to": stop_name,
                        "place": stop_name,
                        "minutes": leg.departure_minute - current_minute,
                        "meters": 0,
                        "departure_time": _clock(current_minute),
                        "arrival_time": _clock(leg.departure_minute),
                        "stops": [],
                    }
                )
            route = self.dataset.routes[leg.route_id]
            line_name = route.short_name or route.long_name
            if line_name not in line_names:
                line_names.append(line_name)
            ride_stops = [self.dataset.stops[stop_id] for stop_id in leg.stop_ids]
            steps.append(
                {
                    "step_id": f"pending-{candidate_index}-ride-{len(steps)}",
                    "kind": "bus",
                    "title": line_name,
                    "from_": ride_stops[0].name,
                    "to": ride_stops[-1].name,
                    "minutes": leg.arrival_minute - leg.departure_minute,
                    "meters": 0,
                    "departure_time": _clock(leg.departure_minute),
                    "arrival_time": _clock(leg.arrival_minute),
                    "route_id": leg.route_id,
                    "trip_id": leg.trip_id,
                    "departureStopId": leg.from_stop_id,
                    "arrivalPoleId": leg.to_stop_id,
                    "stops": [
                        _stop_point(
                            stop,
                            origin=index == 0,
                            destination=index == len(ride_stops) - 1,
                        )
                        for index, stop in enumerate(ride_stops)
                    ],
                }
            )
            for stop in ride_stops[1:]:
                point = [stop.lat, stop.lon]
                if points[-1] != point:
                    points.append(point)
            current_minute = leg.arrival_minute

        if destination_walk_min > 0:
            steps.append(
                {
                    "step_id": f"pending-{candidate_index}-walk-destination",
                    "kind": "walk",
                    "title": "徒歩",
                    "from_": destination_stop.name,
                    "to": "目的地",
                    "minutes": destination_walk_min,
                    "meters": round(destination_distance),
                    "departure_time": _clock(current_minute),
                    "arrival_time": _clock(current_minute + destination_walk_min),
                    "stops": [],
                    "edges": 1,
                }
            )
            current_minute += destination_walk_min
        points.append([destination_point[0], destination_point[1]])

        request_minute = requested_departure.hour * 60 + requested_departure.minute
        walk_count = int(origin_walk_min > 0) + int(destination_walk_min > 0)
        return {
            "id": f"pending-{candidate_index}",
            "lines": line_names,
            "rides": itinerary.rides,
            "walks": walk_count,
            "boards": itinerary.rides,
            "transfers": itinerary.transfers,
            "total": current_minute - request_minute,
            "total_time": current_minute - request_minute,
            "walk_m": origin_distance + destination_distance,
            "steps": steps,
            "points": points,
            "preference": preference,
            "departure_date": requested_departure.isoformat(),
            "is_future_suggestion": False,
            "origin_coords": [origin_point[0], origin_point[1]],
            "destination_coords": [destination_point[0], destination_point[1]],
            "arrival_time": _clock(current_minute),
        }
