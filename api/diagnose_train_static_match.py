#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import io
import json
import os
import zipfile
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

from diagnose_train_vehicle_feed import (
    DEFAULT_URL as DEFAULT_REALTIME_URL,
    TrainVehicleRecord,
    fetch_feed,
    parse_vehicle_records,
)


DEFAULT_STATIC_GTFS_URL = (
    "https://api-public.odpt.org/api/v4/files/Toei/data/"
    "Toei-Train-GTFS.zip"
)


@dataclass(frozen=True)
class StaticTrainTrip:
    trip_id: str
    route_id: str
    headsign: str | None
    stops_by_sequence: dict[int, str]


@dataclass(frozen=True)
class StaticTrainGtfs:
    trips: dict[str, StaticTrainTrip]
    stop_names: dict[str, str]


def _read_csv_from_zip(
    archive: zipfile.ZipFile,
    filename: str,
) -> list[dict[str, str]]:
    names = archive.namelist()
    matches = [
        name for name in names if name == filename or name.endswith(f"/{filename}")
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"GTFS ZIP must contain exactly one {filename}: matches={matches}"
        )

    with archive.open(matches[0]) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(text))


def parse_static_gtfs(content: bytes) -> StaticTrainGtfs:
    if not content:
        raise ValueError("static GTFS response body is empty")

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            trips_rows = _read_csv_from_zip(archive, "trips.txt")
            stop_times_rows = _read_csv_from_zip(archive, "stop_times.txt")
            stops_rows = _read_csv_from_zip(archive, "stops.txt")
    except zipfile.BadZipFile as error:
        raise RuntimeError("static GTFS response is not a valid ZIP") from error

    if not trips_rows:
        raise RuntimeError("trips.txt is empty")
    if not stop_times_rows:
        raise RuntimeError("stop_times.txt is empty")
    if not stops_rows:
        raise RuntimeError("stops.txt is empty")

    stop_names: dict[str, str] = {}
    for row in stops_rows:
        stop_id = row.get("stop_id")
        stop_name = row.get("stop_name")
        if not stop_id:
            raise RuntimeError("stops.txt contains a row without stop_id")
        if not stop_name:
            raise RuntimeError(f"stops.txt stop_id={stop_id!r} has no stop_name")
        if stop_id in stop_names and stop_names[stop_id] != stop_name:
            raise RuntimeError(f"duplicate stop_id with different names: {stop_id}")
        stop_names[stop_id] = stop_name

    trip_meta: dict[str, tuple[str, str | None]] = {}
    for row in trips_rows:
        trip_id = row.get("trip_id")
        route_id = row.get("route_id")
        if not trip_id:
            raise RuntimeError("trips.txt contains a row without trip_id")
        if not route_id:
            raise RuntimeError(f"trips.txt trip_id={trip_id!r} has no route_id")
        if trip_id in trip_meta:
            raise RuntimeError(f"trips.txt contains duplicate trip_id={trip_id!r}")
        trip_meta[trip_id] = (route_id, row.get("trip_headsign") or None)

    stops_by_trip: dict[str, dict[int, str]] = {}
    for row in stop_times_rows:
        trip_id = row.get("trip_id")
        stop_id = row.get("stop_id")
        sequence_text = row.get("stop_sequence")
        if not trip_id:
            raise RuntimeError("stop_times.txt contains a row without trip_id")
        if trip_id not in trip_meta:
            raise RuntimeError(
                f"stop_times.txt references unknown trip_id={trip_id!r}"
            )
        if not stop_id:
            raise RuntimeError(
                f"stop_times.txt trip_id={trip_id!r} contains a row without stop_id"
            )
        if stop_id not in stop_names:
            raise RuntimeError(
                f"stop_times.txt references unknown stop_id={stop_id!r}"
            )
        if sequence_text is None or sequence_text == "":
            raise RuntimeError(
                f"stop_times.txt trip_id={trip_id!r} has no stop_sequence"
            )
        try:
            sequence = int(sequence_text)
        except ValueError as error:
            raise RuntimeError(
                f"invalid stop_sequence={sequence_text!r} for trip_id={trip_id!r}"
            ) from error

        trip_stops = stops_by_trip.setdefault(trip_id, {})
        if sequence in trip_stops:
            raise RuntimeError(
                f"duplicate stop_sequence={sequence} for trip_id={trip_id!r}"
            )
        trip_stops[sequence] = stop_id

    trips: dict[str, StaticTrainTrip] = {}
    for trip_id, (route_id, headsign) in trip_meta.items():
        stops = stops_by_trip.get(trip_id)
        if not stops:
            raise RuntimeError(f"trip_id={trip_id!r} has no stop_times")
        trips[trip_id] = StaticTrainTrip(
            trip_id=trip_id,
            route_id=route_id,
            headsign=headsign,
            stops_by_sequence=stops,
        )

    return StaticTrainGtfs(trips=trips, stop_names=stop_names)


def fetch_static_gtfs(url: str, token: str, timeout_seconds: float) -> bytes:
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
        raise RuntimeError("static GTFS endpoint returned an empty response")
    return response.content


def build_match_summary(
    records: list[TrainVehicleRecord],
    static_gtfs: StaticTrainGtfs,
) -> dict[str, int | float]:
    if not records:
        raise ValueError("records must not be empty")

    realtime_trip_ids = {record.trip_id for record in records if record.trip_id}
    if not realtime_trip_ids:
        raise RuntimeError("VehiclePosition records contain no trip_id")

    matched_trip_ids = realtime_trip_ids.intersection(static_gtfs.trips)
    unmatched_trip_ids = realtime_trip_ids.difference(static_gtfs.trips)

    matched_entities = 0
    entities_with_static_sequence = 0
    for record in records:
        if not record.trip_id or record.trip_id not in static_gtfs.trips:
            continue
        matched_entities += 1
        if record.current_stop_sequence is None:
            continue
        trip = static_gtfs.trips[record.trip_id]
        if record.current_stop_sequence in trip.stops_by_sequence:
            entities_with_static_sequence += 1

    return {
        "vehicle_entities": len(records),
        "realtime_unique_trip_ids": len(realtime_trip_ids),
        "static_trip_ids": len(static_gtfs.trips),
        "matched_trip_ids": len(matched_trip_ids),
        "unmatched_trip_ids": len(unmatched_trip_ids),
        "trip_match_rate_percent": round(
            len(matched_trip_ids) * 100.0 / len(realtime_trip_ids),
            1,
        ),
        "matched_vehicle_entities": matched_entities,
        "with_static_current_sequence": entities_with_static_sequence,
        "without_static_current_sequence": (
            matched_entities - entities_with_static_sequence
        ),
    }


def describe_record(
    record: TrainVehicleRecord,
    static_gtfs: StaticTrainGtfs,
) -> dict[str, object | None]:
    trip_id = record.trip_id
    if not trip_id or trip_id not in static_gtfs.trips:
        raise KeyError(f"trip_id is not present in static GTFS: {trip_id!r}")

    trip = static_gtfs.trips[trip_id]
    sequence = record.current_stop_sequence
    static_stop_id = (
        trip.stops_by_sequence.get(sequence) if sequence is not None else None
    )
    static_stop_name = (
        static_gtfs.stop_names.get(static_stop_id) if static_stop_id else None
    )

    return {
        "trip_id": trip_id,
        "current_stop_sequence": sequence,
        "current_status": record.current_status,
        "static_route_id": trip.route_id,
        "trip_headsign": trip.headsign,
        "static_stop_id": static_stop_id,
        "static_stop_name": static_stop_name,
        "latitude": record.latitude,
        "longitude": record.longitude,
    }


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description=(
            "Compare Toei train GTFS-RT VehiclePosition trip_id / "
            "current_stop_sequence with the static Toei train GTFS."
        )
    )
    parser.add_argument("--realtime-url", default=DEFAULT_REALTIME_URL)
    parser.add_argument("--static-url", default=DEFAULT_STATIC_GTFS_URL)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    if args.limit <= 0:
        raise ValueError("--limit must be greater than 0")

    token = os.getenv("ODPT_API_TOKEN")
    if not token:
        raise RuntimeError("ODPT_API_TOKEN is not set")

    realtime_content = fetch_feed(args.realtime_url, token, args.timeout)
    records = parse_vehicle_records(realtime_content)

    static_content = fetch_static_gtfs(args.static_url, token, args.timeout)
    static_gtfs = parse_static_gtfs(static_content)

    summary = build_match_summary(records, static_gtfs)
    print("=== GTFS-RT / static train trip match ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    matched_records = [
        record
        for record in records
        if record.trip_id is not None and record.trip_id in static_gtfs.trips
    ]
    print("\n=== matched sample entities ===")
    for record in matched_records[: args.limit]:
        print(
            json.dumps(
                describe_record(record, static_gtfs),
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    realtime_trip_ids = sorted(
        {record.trip_id for record in records if record.trip_id is not None}
    )
    unmatched_trip_ids = [
        trip_id for trip_id in realtime_trip_ids if trip_id not in static_gtfs.trips
    ]
    if unmatched_trip_ids:
        print("\n=== unmatched realtime trip_id sample ===")
        for trip_id in unmatched_trip_ids[: args.limit]:
            print(trip_id)


if __name__ == "__main__":
    main()
