#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
from dataclasses import asdict, dataclass

import requests
from dotenv import load_dotenv
from google.transit import gtfs_realtime_pb2


DEFAULT_URL = (
    "https://api-public.odpt.org/api/v4/gtfs/realtime/"
    "toei_odpt_train_vehicle"
)


@dataclass(frozen=True)
class TrainVehicleRecord:
    entity_id: str
    vehicle_id: str | None
    trip_id: str | None
    route_id: str | None
    direction_id: int | None
    current_stop_sequence: int | None
    stop_id: str | None
    current_status: str | None
    timestamp: int | None
    latitude: float | None
    longitude: float | None


def parse_vehicle_records(content: bytes) -> list[TrainVehicleRecord]:
    if not content:
        raise ValueError("GTFS-RT response body is empty")

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(content)

    records: list[TrainVehicleRecord] = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue

        vehicle = entity.vehicle
        trip = vehicle.trip

        direction_id = (
            int(trip.direction_id) if trip.HasField("direction_id") else None
        )
        current_stop_sequence = (
            int(vehicle.current_stop_sequence)
            if vehicle.HasField("current_stop_sequence")
            else None
        )
        current_status = (
            gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus.Name(
                vehicle.current_status
            )
            if vehicle.HasField("current_status")
            else None
        )
        timestamp = int(vehicle.timestamp) if vehicle.HasField("timestamp") else None

        latitude = None
        longitude = None
        if vehicle.HasField("position"):
            latitude = float(vehicle.position.latitude)
            longitude = float(vehicle.position.longitude)

        vehicle_id = vehicle.vehicle.id if vehicle.vehicle.id else None
        trip_id = trip.trip_id if trip.trip_id else None
        route_id = trip.route_id if trip.route_id else None
        stop_id = vehicle.stop_id if vehicle.stop_id else None

        records.append(
            TrainVehicleRecord(
                entity_id=entity.id,
                vehicle_id=vehicle_id,
                trip_id=trip_id,
                route_id=route_id,
                direction_id=direction_id,
                current_stop_sequence=current_stop_sequence,
                stop_id=stop_id,
                current_status=current_status,
                timestamp=timestamp,
                latitude=latitude,
                longitude=longitude,
            )
        )

    if not records:
        raise RuntimeError("GTFS-RT feed contains no VehiclePosition entities")

    return records


def coverage_summary(records: list[TrainVehicleRecord]) -> dict[str, int]:
    if not records:
        raise ValueError("records must not be empty")

    fields = (
        "vehicle_id",
        "trip_id",
        "route_id",
        "direction_id",
        "current_stop_sequence",
        "stop_id",
        "current_status",
        "timestamp",
        "latitude",
        "longitude",
    )
    summary = {"vehicle_entities": len(records)}
    for field in fields:
        summary[f"with_{field}"] = sum(
            1 for record in records if getattr(record, field) is not None
        )
    return summary


def fetch_feed(url: str, token: str, timeout_seconds: float) -> bytes:
    if not token:
        raise ValueError("ODPT_API_TOKEN is required")
    if timeout_seconds <= 0:
        raise ValueError("timeout must be greater than 0")

    response = requests.get(
        url,
        params={"acl:consumerKey": token},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    if not response.content:
        raise RuntimeError("GTFS-RT endpoint returned an empty response")
    return response.content


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description=(
            "Inspect Toei train GTFS-RT VehiclePosition fields needed for "
            "real-time remaining-station display."
        )
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--route-id",
        help="Optional exact GTFS route_id filter (for example an Asakusa route).",
    )
    args = parser.parse_args()

    if args.limit <= 0:
        raise ValueError("--limit must be greater than 0")

    token = os.getenv("ODPT_API_TOKEN")
    if not token:
        raise RuntimeError("ODPT_API_TOKEN is not set")

    content = fetch_feed(args.url, token, args.timeout)
    records = parse_vehicle_records(content)

    if args.route_id:
        records = [record for record in records if record.route_id == args.route_id]
        if not records:
            raise RuntimeError(
                f"No VehiclePosition entities matched route_id={args.route_id!r}"
            )

    print("=== GTFS-RT train VehiclePosition coverage ===")
    print(json.dumps(coverage_summary(records), ensure_ascii=False, indent=2))

    print("\n=== sample entities ===")
    for record in records[: args.limit]:
        print(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
