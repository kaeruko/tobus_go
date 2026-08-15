import asyncio
import csv
import io
import os
import time
import zipfile
from dataclasses import dataclass

import httpx
from google.transit import gtfs_realtime_pb2


REALTIME_URL = (
    "https://api-public.odpt.org/api/v4/gtfs/realtime/"
    "toei_odpt_train_vehicle"
)
STATIC_GTFS_URL = (
    "https://api-public.odpt.org/api/v4/files/Toei/data/"
    "Toei-Train-GTFS.zip"
)

_REALTIME_LOCK = asyncio.Lock()
_STATIC_LOCK = asyncio.Lock()
_REALTIME_CACHE_SECONDS = 45


class TrainRealtimeError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class TrainVehicleRecord:
    trip_id: str
    vehicle_id: str
    current_stop_sequence: int
    current_status: str
    timestamp: int
    latitude: float
    longitude: float


@dataclass(frozen=True)
class StaticTrainStop:
    sequence: int
    stop_id: str
    stop_name: str
    arrival_time: str | None
    departure_time: str | None


@dataclass(frozen=True)
class StaticTrainTrip:
    trip_id: str
    route_id: str
    headsign: str | None
    stops: tuple[StaticTrainStop, ...]


@dataclass(frozen=True)
class StaticTrainGtfs:
    trips: dict[str, StaticTrainTrip]


@dataclass(frozen=True)
class ResolvedTrainVehicle:
    vehicle: TrainVehicleRecord
    trip: StaticTrainTrip
    boarding_sequence: int
    destination_sequence: int


_latest_vehicles: tuple[TrainVehicleRecord, ...] = ()
_latest_vehicles_refreshed_at = 0.0
_latest_vehicles_fetched_at = 0.0
_static_gtfs: StaticTrainGtfs | None = None


def _token() -> str:
    token = os.getenv("ODPT_API_TOKEN")
    if not token:
        raise TrainRealtimeError(
            "odpt_token_missing",
            "ODPT_API_TOKEN is required for train realtime data",
            503,
        )
    return token


def parse_vehicle_records(content: bytes) -> tuple[TrainVehicleRecord, ...]:
    if not content:
        raise TrainRealtimeError(
            "train_realtime_empty",
            "GTFS-RT train VehiclePosition response is empty",
            503,
        )

    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        feed.ParseFromString(content)
    except Exception as error:
        raise TrainRealtimeError(
            "train_realtime_invalid",
            "GTFS-RT train VehiclePosition response could not be parsed",
            503,
        ) from error

    records: list[TrainVehicleRecord] = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        vehicle = entity.vehicle
        trip_id = vehicle.trip.trip_id
        vehicle_id = vehicle.vehicle.id
        if not trip_id:
            raise TrainRealtimeError(
                "train_realtime_trip_id_missing",
                f"VehiclePosition entity {entity.id!r} has no trip_id",
                502,
            )
        if not vehicle_id:
            raise TrainRealtimeError(
                "train_realtime_vehicle_id_missing",
                f"VehiclePosition trip {trip_id!r} has no vehicle_id",
                502,
            )
        if not vehicle.HasField("current_stop_sequence"):
            raise TrainRealtimeError(
                "train_realtime_sequence_missing",
                f"VehiclePosition trip {trip_id!r} has no current_stop_sequence",
                502,
            )
        if not vehicle.HasField("current_status"):
            raise TrainRealtimeError(
                "train_realtime_status_missing",
                f"VehiclePosition trip {trip_id!r} has no current_status",
                502,
            )
        if not vehicle.HasField("timestamp"):
            raise TrainRealtimeError(
                "train_realtime_timestamp_missing",
                f"VehiclePosition trip {trip_id!r} has no timestamp",
                502,
            )
        if not vehicle.HasField("position"):
            raise TrainRealtimeError(
                "train_realtime_position_missing",
                f"VehiclePosition trip {trip_id!r} has no position",
                502,
            )

        records.append(
            TrainVehicleRecord(
                trip_id=trip_id,
                vehicle_id=vehicle_id,
                current_stop_sequence=int(vehicle.current_stop_sequence),
                current_status=(
                    gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus.Name(
                        vehicle.current_status
                    )
                ),
                timestamp=int(vehicle.timestamp),
                latitude=float(vehicle.position.latitude),
                longitude=float(vehicle.position.longitude),
            )
        )

    if not records:
        raise TrainRealtimeError(
            "train_realtime_no_vehicles",
            "GTFS-RT train feed contains no VehiclePosition entities",
            503,
        )
    return tuple(records)


def _read_csv(archive: zipfile.ZipFile, filename: str) -> list[dict[str, str]]:
    matches = [
        name
        for name in archive.namelist()
        if name == filename or name.endswith(f"/{filename}")
    ]
    if len(matches) != 1:
        raise TrainRealtimeError(
            "train_static_gtfs_invalid",
            f"Static train GTFS must contain exactly one {filename}: {matches}",
            503,
        )
    with archive.open(matches[0]) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(text))


def parse_static_gtfs(content: bytes) -> StaticTrainGtfs:
    if not content:
        raise TrainRealtimeError(
            "train_static_gtfs_empty",
            "Static train GTFS response is empty",
            503,
        )
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            trip_rows = _read_csv(archive, "trips.txt")
            stop_rows = _read_csv(archive, "stops.txt")
            stop_time_rows = _read_csv(archive, "stop_times.txt")
    except zipfile.BadZipFile as error:
        raise TrainRealtimeError(
            "train_static_gtfs_invalid",
            "Static train GTFS response is not a ZIP archive",
            503,
        ) from error

    stop_names: dict[str, str] = {}
    for row in stop_rows:
        stop_id = row.get("stop_id")
        stop_name = row.get("stop_name")
        if not stop_id or not stop_name:
            raise TrainRealtimeError(
                "train_static_gtfs_invalid",
                "stops.txt contains a row without stop_id or stop_name",
                503,
            )
        if stop_id in stop_names and stop_names[stop_id] != stop_name:
            raise TrainRealtimeError(
                "train_static_gtfs_invalid",
                f"Duplicate train stop_id has different names: {stop_id}",
                503,
            )
        stop_names[stop_id] = stop_name

    trip_meta: dict[str, tuple[str, str | None]] = {}
    for row in trip_rows:
        trip_id = row.get("trip_id")
        route_id = row.get("route_id")
        if not trip_id or not route_id:
            raise TrainRealtimeError(
                "train_static_gtfs_invalid",
                "trips.txt contains a row without trip_id or route_id",
                503,
            )
        if trip_id in trip_meta:
            raise TrainRealtimeError(
                "train_static_gtfs_invalid",
                f"Duplicate train trip_id: {trip_id}",
                503,
            )
        trip_meta[trip_id] = (route_id, row.get("trip_headsign") or None)

    stops_by_trip: dict[str, list[StaticTrainStop]] = {}
    seen_sequences: set[tuple[str, int]] = set()
    for row in stop_time_rows:
        trip_id = row.get("trip_id")
        stop_id = row.get("stop_id")
        sequence_raw = row.get("stop_sequence")
        if not trip_id or not stop_id or not sequence_raw:
            raise TrainRealtimeError(
                "train_static_gtfs_invalid",
                "stop_times.txt contains a row without trip_id, stop_id, or stop_sequence",
                503,
            )
        if trip_id not in trip_meta:
            raise TrainRealtimeError(
                "train_static_gtfs_invalid",
                f"stop_times.txt references unknown trip_id: {trip_id}",
                503,
            )
        if stop_id not in stop_names:
            raise TrainRealtimeError(
                "train_static_gtfs_invalid",
                f"stop_times.txt references unknown stop_id: {stop_id}",
                503,
            )
        try:
            sequence = int(sequence_raw)
        except ValueError as error:
            raise TrainRealtimeError(
                "train_static_gtfs_invalid",
                f"Invalid stop_sequence for trip {trip_id}: {sequence_raw!r}",
                503,
            ) from error
        key = (trip_id, sequence)
        if key in seen_sequences:
            raise TrainRealtimeError(
                "train_static_gtfs_invalid",
                f"Duplicate stop_sequence for trip {trip_id}: {sequence}",
                503,
            )
        seen_sequences.add(key)
        stops_by_trip.setdefault(trip_id, []).append(
            StaticTrainStop(
                sequence=sequence,
                stop_id=stop_id,
                stop_name=stop_names[stop_id],
                arrival_time=row.get("arrival_time") or None,
                departure_time=row.get("departure_time") or None,
            )
        )

    trips: dict[str, StaticTrainTrip] = {}
    for trip_id, (route_id, headsign) in trip_meta.items():
        stops = stops_by_trip.get(trip_id)
        if not stops:
            raise TrainRealtimeError(
                "train_static_gtfs_invalid",
                f"Static train trip has no stop_times: {trip_id}",
                503,
            )
        stops.sort(key=lambda stop: stop.sequence)
        trips[trip_id] = StaticTrainTrip(
            trip_id=trip_id,
            route_id=route_id,
            headsign=headsign,
            stops=tuple(stops),
        )

    return StaticTrainGtfs(trips=trips)


def _normalize_clock(value: str) -> str:
    parts = value.strip().split(":")
    if len(parts) < 2:
        raise TrainRealtimeError(
            "train_plan_clock_invalid",
            f"Invalid train plan clock: {value!r}",
            400,
        )
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as error:
        raise TrainRealtimeError(
            "train_plan_clock_invalid",
            f"Invalid train plan clock: {value!r}",
            400,
        ) from error
    if hour < 0 or minute < 0 or minute >= 60:
        raise TrainRealtimeError(
            "train_plan_clock_invalid",
            f"Invalid train plan clock: {value!r}",
            400,
        )
    return f"{hour % 24:02d}:{minute:02d}"


def _find_trip_segment(
    trip: StaticTrainTrip,
    from_name: str,
    to_name: str,
) -> tuple[StaticTrainStop, StaticTrainStop] | None:
    origins = [stop for stop in trip.stops if stop.stop_name == from_name]
    destinations = [stop for stop in trip.stops if stop.stop_name == to_name]
    pairs = [
        (origin, destination)
        for origin in origins
        for destination in destinations
        if destination.sequence > origin.sequence
    ]
    if not pairs:
        return None
    if len(pairs) != 1:
        raise TrainRealtimeError(
            "train_static_segment_ambiguous",
            f"Trip {trip.trip_id} contains ambiguous segment {from_name}->{to_name}",
            502,
        )
    return pairs[0]


def resolve_train_vehicle(
    vehicles: tuple[TrainVehicleRecord, ...],
    static_gtfs: StaticTrainGtfs,
    *,
    trip_id: str | None,
    from_name: str | None,
    to_name: str | None,
    arrival_time: str | None,
) -> ResolvedTrainVehicle:
    if trip_id:
        matches = [vehicle for vehicle in vehicles if vehicle.trip_id == trip_id]
        if not matches:
            raise TrainRealtimeError(
                "train_trip_not_reporting",
                f"Realtime train trip is not reporting: {trip_id}",
                404,
            )
        if len(matches) != 1:
            raise TrainRealtimeError(
                "train_trip_ambiguous",
                f"Realtime train trip_id is not unique: {trip_id}",
                409,
            )
        trip = static_gtfs.trips.get(trip_id)
        if trip is None:
            raise TrainRealtimeError(
                "train_static_trip_missing",
                f"Realtime train trip is missing from static GTFS: {trip_id}",
                502,
            )
        if from_name is None or to_name is None:
            raise TrainRealtimeError(
                "train_plan_segment_missing",
                "from_name and to_name are required when resolving a train trip",
                400,
            )
        segment = _find_trip_segment(trip, from_name, to_name)
        if segment is None:
            raise TrainRealtimeError(
                "train_static_segment_missing",
                f"Trip {trip_id} does not contain {from_name}->{to_name}",
                409,
            )
        return ResolvedTrainVehicle(
            vehicle=matches[0],
            trip=trip,
            boarding_sequence=segment[0].sequence,
            destination_sequence=segment[1].sequence,
        )

    if not from_name or not to_name or not arrival_time:
        raise TrainRealtimeError(
            "train_plan_identity_missing",
            "from_name, to_name, and arrival_time are required without trip_id",
            400,
        )

    wanted_arrival = _normalize_clock(arrival_time)
    candidates: list[ResolvedTrainVehicle] = []
    for vehicle in vehicles:
        trip = static_gtfs.trips.get(vehicle.trip_id)
        if trip is None:
            raise TrainRealtimeError(
                "train_static_trip_missing",
                f"Realtime train trip is missing from static GTFS: {vehicle.trip_id}",
                502,
            )
        segment = _find_trip_segment(trip, from_name, to_name)
        if segment is None:
            continue
        destination = segment[1]
        if destination.arrival_time is None:
            raise TrainRealtimeError(
                "train_static_arrival_missing",
                f"Trip {trip.trip_id} destination {to_name} has no arrival_time",
                502,
            )
        if _normalize_clock(destination.arrival_time) != wanted_arrival:
            continue
        candidates.append(
            ResolvedTrainVehicle(
                vehicle=vehicle,
                trip=trip,
                boarding_sequence=segment[0].sequence,
                destination_sequence=destination.sequence,
            )
        )

    if not candidates:
        raise TrainRealtimeError(
            "train_trip_not_found",
            f"No reporting train exactly matches {from_name}->{to_name} arrival {wanted_arrival}",
            404,
        )
    if len(candidates) != 1:
        ids = [candidate.trip.trip_id for candidate in candidates]
        raise TrainRealtimeError(
            "train_trip_ambiguous",
            f"Multiple reporting trains match the ride plan: {ids}",
            409,
        )
    return candidates[0]


async def _fetch_bytes(url: str, timeout_seconds: float = 20.0) -> bytes:
    token = _token()
    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=True,
    ) as client:
        response = await client.get(
            url,
            params={"acl:consumerKey": token},
        )
    if response.status_code != 200:
        raise TrainRealtimeError(
            "train_data_fetch_failed",
            f"Train data fetch failed: HTTP {response.status_code}",
            503,
        )
    if not response.content:
        raise TrainRealtimeError(
            "train_data_fetch_empty",
            "Train data endpoint returned an empty response",
            503,
        )
    return response.content


async def get_realtime_vehicles(
    *,
    force_refresh: bool = False,
) -> tuple[tuple[TrainVehicleRecord, ...], float]:
    global _latest_vehicles
    global _latest_vehicles_refreshed_at
    global _latest_vehicles_fetched_at

    now_monotonic = time.monotonic()
    if (
        not force_refresh
        and _latest_vehicles
        and now_monotonic - _latest_vehicles_refreshed_at < _REALTIME_CACHE_SECONDS
    ):
        return _latest_vehicles, _latest_vehicles_fetched_at

    async with _REALTIME_LOCK:
        now_monotonic = time.monotonic()
        if (
            not force_refresh
            and _latest_vehicles
            and now_monotonic - _latest_vehicles_refreshed_at < _REALTIME_CACHE_SECONDS
        ):
            return _latest_vehicles, _latest_vehicles_fetched_at

        content = await _fetch_bytes(REALTIME_URL, timeout_seconds=15.0)
        records = parse_vehicle_records(content)
        _latest_vehicles = records
        _latest_vehicles_refreshed_at = time.monotonic()
        _latest_vehicles_fetched_at = time.time()
        return records, _latest_vehicles_fetched_at


async def get_static_gtfs() -> StaticTrainGtfs:
    global _static_gtfs
    if _static_gtfs is not None:
        return _static_gtfs

    async with _STATIC_LOCK:
        if _static_gtfs is not None:
            return _static_gtfs
        content = await _fetch_bytes(STATIC_GTFS_URL, timeout_seconds=30.0)
        _static_gtfs = parse_static_gtfs(content)
        return _static_gtfs


def build_location_response(
    resolved: ResolvedTrainVehicle,
    *,
    realtime_fetched_at: float,
) -> dict:
    vehicle = resolved.vehicle
    trip = resolved.trip
    stop_by_sequence = {stop.sequence: stop for stop in trip.stops}
    current_stop = stop_by_sequence.get(vehicle.current_stop_sequence)
    if current_stop is None:
        raise TrainRealtimeError(
            "train_current_sequence_missing",
            f"Trip {trip.trip_id} has no static stop_sequence {vehicle.current_stop_sequence}",
            502,
        )

    now_epoch = time.time()
    return {
        "kind": "train_location",
        "trip_id": trip.trip_id,
        "route_id": trip.route_id,
        "trip_headsign": trip.headsign,
        "vehicle_id": vehicle.vehicle_id,
        "current_stop_sequence": vehicle.current_stop_sequence,
        "current_status": vehicle.current_status,
        "current_stop_id": current_stop.stop_id,
        "current_stop_name": current_stop.stop_name,
        "boarding_sequence": resolved.boarding_sequence,
        "destination_sequence": resolved.destination_sequence,
        "vehicle_lat": vehicle.latitude,
        "vehicle_lon": vehicle.longitude,
        "vehicle_ts": vehicle.timestamp,
        "realtime_fetched_ts": realtime_fetched_at,
        "vehicle_age_seconds": round(max(0.0, now_epoch - vehicle.timestamp), 1),
        "snapshot_age_seconds": round(max(0.0, now_epoch - realtime_fetched_at), 1),
        "trip_stops": [
            {
                "sequence": stop.sequence,
                "stop_id": stop.stop_id,
                "stop_name": stop.stop_name,
                "arrival_time": stop.arrival_time,
                "departure_time": stop.departure_time,
            }
            for stop in trip.stops
        ],
    }
