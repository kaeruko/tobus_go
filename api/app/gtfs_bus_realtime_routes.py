from __future__ import annotations

import math
import time
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException, Query

from transit_dataset import TransitDataset


def _source_id(value: str, *, feed_id: str, field: str) -> str:
    prefix = f"{feed_id}:"
    if not value.startswith(prefix):
        raise HTTPException(
            422,
            detail={
                "code": "invalid_feed_id",
                "message": f"{field} must start with {prefix!r}",
            },
        )
    source = value[len(prefix) :]
    if source == "":
        raise HTTPException(
            422,
            detail={
                "code": "invalid_feed_id",
                "message": f"{field} has an empty source id",
            },
        )
    return source


def _provider(app):
    provider = getattr(app.state, "realtime_provider", None)
    if provider is None:
        raise HTTPException(
            503,
            detail={
                "code": "realtime_provider_unavailable",
                "message": "Realtime provider is not initialized",
            },
        )
    return provider


def _dataset(app, *, feed_id: str) -> TransitDataset:
    dataset = getattr(app.state, "transit_dataset", None)
    if not isinstance(dataset, TransitDataset):
        raise HTTPException(
            500,
            detail={
                "code": "transit_dataset_unavailable",
                "message": "Transit dataset is not initialized",
            },
        )
    if dataset.metadata.feed_id != feed_id:
        raise HTTPException(
            500,
            detail={
                "code": "transit_feed_mismatch",
                "message": (
                    f"Expected transit feed {feed_id!r}, "
                    f"got {dataset.metadata.feed_id!r}"
                ),
            },
        )
    return dataset


def _raise_realtime_failure(error: Exception) -> None:
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        message = f"GTFS-Realtime upstream HTTP {status}"
    else:
        message = str(error) or error.__class__.__name__
    raise HTTPException(
        503,
        detail={
            "code": "realtime_fetch_failed",
            "message": message,
        },
    ) from error


def _service_time(value: int) -> str:
    if value < 0:
        raise RuntimeError(f"negative GTFS service minute: {value}")
    hour = value // 60
    minute = value % 60
    return f"{hour:02d}:{minute:02d}"


def _ordered_trip_schedule(dataset: TransitDataset, trip_id: str) -> list[dict]:
    rows = sorted(
        (row for row in dataset.stop_times if row.trip_id == trip_id),
        key=lambda row: row.sequence,
    )
    if not rows:
        raise RuntimeError(f"static GTFS trip has no stop_times: {trip_id}")

    schedule: list[dict] = []
    for row in rows:
        if row.arrival_minute is None or row.departure_minute is None:
            raise RuntimeError(
                "realtime navigation requires exact arrival/departure times: "
                f"trip={trip_id}, sequence={row.sequence}"
            )
        stop = dataset.stops.get(row.stop_id)
        if stop is None:
            raise RuntimeError(
                f"static GTFS stop is missing for trip schedule: {row.stop_id}"
            )
        schedule.append(
            {
                "sequence": row.sequence,
                "stop_id": row.stop_id,
                "stop_name": stop.name,
                "arrival_minute": row.arrival_minute,
                "departure_minute": row.departure_minute,
                "arrival_time": _service_time(row.arrival_minute),
                "departure_time": _service_time(row.departure_minute),
            }
        )
    return schedule


def _validated_vehicle_position(row: dict) -> tuple[float, float]:
    lat = row.get("lat")
    lon = row.get("lon")
    if (
        isinstance(lat, bool)
        or isinstance(lon, bool)
        or not isinstance(lat, (int, float))
        or not isinstance(lon, (int, float))
    ):
        raise RuntimeError("VehiclePosition is missing numeric latitude/longitude")
    lat = float(lat)
    lon = float(lon)
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise RuntimeError("VehiclePosition latitude/longitude are not finite")
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise RuntimeError(
            f"VehiclePosition latitude/longitude are out of range: {lat}, {lon}"
        )
    if lat == 0 and lon == 0:
        raise RuntimeError("VehiclePosition latitude/longitude must not be (0,0)")
    return lat, lon


def _validate_vehicle_timestamp(row: dict, *, max_age_seconds: float | None) -> None:
    if max_age_seconds is None:
        return
    timestamp = row.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or timestamp <= 0:
        raise RuntimeError("VehiclePosition timestamp is missing")
    age = time.time() - float(timestamp)
    if age > max_age_seconds:
        raise RuntimeError(
            "VehiclePosition is stale: "
            f"age_seconds={age:.1f}, max_age_seconds={max_age_seconds:.1f}"
        )
    if age < -60:
        raise RuntimeError(
            f"VehiclePosition timestamp is too far in the future: {-age:.1f}s"
        )


def _resolve_from_stop(
    *,
    dataset: TransitDataset,
    schedule: list[dict],
    row: dict,
) -> tuple[dict, dict]:
    sequence = row.get("current_stop_sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise RuntimeError("VehiclePosition current_stop_sequence is missing")

    current_index = next(
        (index for index, item in enumerate(schedule) if item["sequence"] == sequence),
        None,
    )
    if current_index is None:
        raise RuntimeError(
            f"VehiclePosition stop sequence is not in static GTFS trip: {sequence}"
        )
    current = schedule[current_index]

    raw_stop_id = row.get("stop_id")
    if raw_stop_id is not None:
        current_stop = dataset.stops[current["stop_id"]]
        if raw_stop_id != current_stop.source_id:
            raise RuntimeError(
                "VehiclePosition/static GTFS stop mismatch: "
                f"realtime={raw_stop_id!r}, static={current_stop.source_id!r}, "
                f"sequence={sequence}"
            )

    status = row.get("current_status")
    if status == 1:  # STOPPED_AT
        return current, current
    if status in {0, 2}:  # INCOMING_AT / IN_TRANSIT_TO
        if current_index == 0:
            raise HTTPException(
                404,
                detail={
                    "code": "bus_realtime_before_first_stop",
                    "message": "The matched vehicle has not reached the first trip stop yet",
                },
            )
        return schedule[current_index - 1], current
    raise RuntimeError(f"unsupported VehicleStopStatus: {status!r}")


def register_gtfs_bus_vehicle_location_route(app, *, feed_id: str) -> None:
    @app.get("/bus/location")
    async def bus_location(
        route_id: str = Query(...),
        trip_id: str = Query(...),
        vehicle_id: str | None = Query(None),
        force_refresh: bool = Query(False),
        debug: bool = Query(False),
    ):
        del debug
        raw_route_id = _source_id(route_id, feed_id=feed_id, field="route_id")
        raw_trip_id = _source_id(trip_id, feed_id=feed_id, field="trip_id")
        dataset = _dataset(app, feed_id=feed_id)

        trip = dataset.trips.get(trip_id)
        if trip is None:
            raise HTTPException(
                422,
                detail={
                    "code": "unknown_static_trip",
                    "message": f"Unknown static GTFS trip: {trip_id!r}",
                },
            )
        if trip.route_id != route_id:
            raise HTTPException(
                422,
                detail={
                    "code": "static_route_trip_mismatch",
                    "message": (
                        f"Static GTFS trip {trip_id!r} belongs to {trip.route_id!r}, "
                        f"not {route_id!r}"
                    ),
                },
            )

        try:
            provider = _provider(app)
            rows = await provider.vehicle_positions(force_refresh=force_refresh)
        except (httpx.HTTPError, RuntimeError) as error:
            _raise_realtime_failure(error)

        matches = [
            row
            for row in rows
            if row.get("trip_id") == raw_trip_id
            and (row.get("route_id") is None or row.get("route_id") == raw_route_id)
            and (vehicle_id is None or row.get("vehicle_id") == vehicle_id)
        ]
        if not matches:
            raise HTTPException(
                404,
                detail={
                    "code": "bus_realtime_not_found",
                    "message": (
                        "No exact VehiclePosition match for "
                        f"route_id={raw_route_id!r}, trip_id={raw_trip_id!r}, "
                        f"vehicle_id={vehicle_id!r}"
                    ),
                },
            )
        if len(matches) != 1:
            raise HTTPException(
                409,
                detail={
                    "code": "bus_realtime_ambiguous",
                    "message": "Multiple exact VehiclePosition matches; specify vehicle_id",
                },
            )

        row = matches[0]
        try:
            lat, lon = _validated_vehicle_position(row)
            max_age_seconds = getattr(provider, "max_feed_age_seconds", None)
            _validate_vehicle_timestamp(row, max_age_seconds=max_age_seconds)
            schedule = _ordered_trip_schedule(dataset, trip_id)
            from_stop, current_stop = _resolve_from_stop(
                dataset=dataset,
                schedule=schedule,
                row=row,
            )
        except HTTPException:
            raise
        except RuntimeError as error:
            _raise_realtime_failure(error)

        return {
            "kind": "bus_location",
            "odpt:bus": row.get("vehicle_id"),
            "vehicle_id": row.get("vehicle_id"),
            "vehicle_lat": lat,
            "vehicle_lon": lon,
            "odpt:fromBusstopPole": from_stop["stop_id"],
            "route_id": route_id,
            "trip_id": trip_id,
            "raw_route_id": raw_route_id,
            "raw_trip_id": raw_trip_id,
            "raw_stop_id": row.get("stop_id"),
            "raw_stop_name": current_stop["stop_name"],
            "from_stop_sequence": from_stop["sequence"],
            "observed_stop_sequence": row.get("current_stop_sequence"),
            "current_status": row.get("current_status"),
            "feed_ts": row.get("feed_timestamp"),
            "vehicle_ts": row.get("timestamp"),
            "trip_stop_ids": [item["stop_id"] for item in schedule],
            "trip_stop_schedule": schedule,
            "server_now": datetime.now(timezone.utc).isoformat(),
        }
