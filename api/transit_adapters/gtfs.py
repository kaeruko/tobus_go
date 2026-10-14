from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from transit_dataset import (
    FeedMetadata,
    ServiceCalendar,
    ServiceException,
    TransitDataset,
    TransitMode,
    TransitRoute,
    TransitStop,
    TransitStopTime,
    TransitTrip,
    namespace_id,
    service_time_to_minute,
)


_REQUIRED_FILES = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")


def _parse_date(value: str, *, field: str) -> datetime.date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as error:
        raise ValueError(f"invalid {field}: {value!r}") from error


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        return [dict(row) for row in reader]


def _required(row: dict[str, str], key: str, *, file_name: str) -> str:
    value = row.get(key)
    if value is None or value == "":
        raise ValueError(f"{file_name} row is missing {key}")
    return value


def _route_mode(route_type_raw: str) -> TransitMode:
    try:
        route_type = int(route_type_raw)
    except ValueError as error:
        raise ValueError(f"invalid GTFS route_type: {route_type_raw!r}") from error
    if route_type == 3:
        return TransitMode.BUS
    if route_type in (0, 1, 2):
        return TransitMode.RAIL
    raise ValueError(f"unsupported GTFS route_type: {route_type}")


class GtfsTransitAdapter:
    @staticmethod
    def load(
        directory: str | Path, *, metadata: FeedMetadata,
        skip_untimed_intermediate_stops: bool = False,
    ) -> TransitDataset:
        """Load GTFS, optionally omitting verified untimed non-timepoints.

        Strict by default for all existing cities. When opted in, an intermediate
        row with *both* times absent may be omitted only if timepoint=0
        or is absent/blank, but never if explicitly exact (timepoint=1).
        Omitted/blank timepoint on an untimed row violates strict GTFS;
        this compatibility mode is opt-in and still forbids boarding/alighting
        at any such stop. This
        no time is estimated or invented. Every trip must still have timed
        first/last stops, and every stop/sequence is checked before omission.
        """
        root = Path(directory)
        if not root.is_dir():
            raise FileNotFoundError(root)
        for file_name in _REQUIRED_FILES:
            if not (root / file_name).is_file():
                raise FileNotFoundError(root / file_name)
        if not (root / "calendar.txt").is_file() and not (
            root / "calendar_dates.txt"
        ).is_file():
            raise FileNotFoundError(
                f"GTFS requires calendar.txt or calendar_dates.txt: {root}"
            )

        feed_id = metadata.feed_id

        stops: dict[str, TransitStop] = {}
        for row in _read_rows(root / "stops.txt"):
            source_id = _required(row, "stop_id", file_name="stops.txt")
            internal_id = namespace_id(feed_id, source_id)
            if internal_id in stops:
                raise ValueError(f"duplicate stop_id: {source_id}")
            name = _required(row, "stop_name", file_name="stops.txt")
            try:
                lat = float(_required(row, "stop_lat", file_name="stops.txt"))
                lon = float(_required(row, "stop_lon", file_name="stops.txt"))
            except ValueError as error:
                raise ValueError(f"invalid coordinates for stop {source_id}") from error
            stops[internal_id] = TransitStop(
                id=internal_id,
                source_id=source_id,
                name=name,
                lat=lat,
                lon=lon,
            )

        routes: dict[str, TransitRoute] = {}
        for row in _read_rows(root / "routes.txt"):
            source_id = _required(row, "route_id", file_name="routes.txt")
            internal_id = namespace_id(feed_id, source_id)
            if internal_id in routes:
                raise ValueError(f"duplicate route_id: {source_id}")
            short_name = row.get("route_short_name") or ""
            long_name = row.get("route_long_name") or ""
            if short_name == "" and long_name == "":
                raise ValueError(f"route has no name: {source_id}")
            routes[internal_id] = TransitRoute(
                id=internal_id,
                source_id=source_id,
                short_name=short_name,
                long_name=long_name,
                mode=_route_mode(_required(row, "route_type", file_name="routes.txt")),
            )

        trips: dict[str, TransitTrip] = {}
        for row in _read_rows(root / "trips.txt"):
            source_id = _required(row, "trip_id", file_name="trips.txt")
            internal_id = namespace_id(feed_id, source_id)
            if internal_id in trips:
                raise ValueError(f"duplicate trip_id: {source_id}")
            route_id = namespace_id(
                feed_id,
                _required(row, "route_id", file_name="trips.txt"),
            )
            service_id = namespace_id(
                feed_id,
                _required(row, "service_id", file_name="trips.txt"),
            )
            trips[internal_id] = TransitTrip(
                id=internal_id,
                source_id=source_id,
                route_id=route_id,
                service_id=service_id,
                headsign=row.get("trip_headsign") or "",
                direction_id=(row.get("direction_id") or None),
            )

        rows = _read_rows(root / "stop_times.txt")
        boundaries: dict[str, tuple[int, int]] = {}
        seen_all_sequences: set[tuple[str, int]] = set()
        if skip_untimed_intermediate_stops:
            for row in rows:
                trip_id = namespace_id(
                    feed_id, _required(row, "trip_id", file_name="stop_times.txt"),
                )
                stop_id = namespace_id(
                    feed_id, _required(row, "stop_id", file_name="stop_times.txt"),
                )
                try:
                    sequence = int(
                        _required(row, "stop_sequence", file_name="stop_times.txt")
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"invalid stop_sequence for trip {trip_id}"
                    ) from exc
                if trip_id not in trips or stop_id not in stops:
                    raise ValueError(
                        "untimed GTFS validation found unknown trip or stop ID"
                    )
                key = (trip_id, sequence)
                if key in seen_all_sequences:
                    raise ValueError(f"duplicate GTFS stop sequence: {key}")
                seen_all_sequences.add(key)
                if trip_id in boundaries:
                    first, last = boundaries[trip_id]
                    boundaries[trip_id] = min(first, sequence), max(last, sequence)
                else:
                    boundaries[trip_id] = (sequence, sequence)

        stop_times: list[TransitStopTime] = []
        kept_per_trip: dict[str, int] = {}
        omitted_trip_ids: set[str] = set()
        for row in rows:
            trip_id = namespace_id(
                feed_id,
                _required(row, "trip_id", file_name="stop_times.txt"),
            )
            stop_id = namespace_id(
                feed_id,
                _required(row, "stop_id", file_name="stop_times.txt"),
            )
            try:
                sequence = int(
                    _required(row, "stop_sequence", file_name="stop_times.txt")
                )
            except ValueError as error:
                raise ValueError(f"invalid stop_sequence for trip {trip_id}") from error
            arrival_raw = row.get("arrival_time") or ""
            departure_raw = row.get("departure_time") or ""
            arrival = service_time_to_minute(arrival_raw) if arrival_raw else None
            departure = service_time_to_minute(departure_raw) if departure_raw else None
            if arrival is None and departure is None and skip_untimed_intermediate_stops:
                first, last = boundaries[trip_id]
                if sequence in (first, last):
                    raise ValueError(
                        "GTFS first/last stop missing arrival and departure time"
                    )
                # The actual Yokohama subway feed also contains untimed
                # intermediate rows with omitted/empty timepoint. Strict GTFS
                # treats omitted timepoint as exact, so these rows are NOT
                # safe boarding/alighting points. Opt-in subway compatibility
                # may omit them without fabricating a stop time.
                # Explicit 1 or any invalid flag remains a hard error.
                if row.get("timepoint") not in (None, "", "0"):
                    raise ValueError(
                        "GTFS untimed intermediate stop has invalid/exact timepoint"
                    )
                # The stop still exists in the source feed, but without a
                # reliable time it cannot be a boarding/alighting candidate.
                omitted_trip_ids.add(trip_id)
                continue
            kept_per_trip[trip_id] = kept_per_trip.get(trip_id, 0) + 1
            stop_times.append(
                TransitStopTime(
                    trip_id=trip_id,
                    stop_id=stop_id,
                    sequence=sequence,
                    arrival_minute=arrival,
                    departure_minute=departure,
                )
            )

        if skip_untimed_intermediate_stops and any(
            kept_per_trip.get(trip_id, 0) < 2 for trip_id in omitted_trip_ids
        ):
            raise ValueError("GTFS trip has fewer than two timed stops")
        if skip_untimed_intermediate_stops and set(trips) != set(kept_per_trip):
            raise ValueError("GTFS trip has no timed stops")

        calendars: dict[str, ServiceCalendar] = {}
        calendar_path = root / "calendar.txt"
        if calendar_path.is_file():
            for row in _read_rows(calendar_path):
                source_id = _required(row, "service_id", file_name="calendar.txt")
                internal_id = namespace_id(feed_id, source_id)
                if internal_id in calendars:
                    raise ValueError(f"duplicate service_id: {source_id}")
                weekdays = tuple(
                    _required(row, name, file_name="calendar.txt") == "1"
                    for name in (
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                    )
                )
                if any(
                    row[name] not in ("0", "1")
                    for name in (
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                    )
                ):
                    raise ValueError(f"invalid weekday flag for service {source_id}")
                calendars[internal_id] = ServiceCalendar(
                    id=internal_id,
                    source_id=source_id,
                    weekdays=weekdays,  # type: ignore[arg-type]
                    start_date=_parse_date(
                        _required(row, "start_date", file_name="calendar.txt"),
                        field="start_date",
                    ),
                    end_date=_parse_date(
                        _required(row, "end_date", file_name="calendar.txt"),
                        field="end_date",
                    ),
                )

        service_exceptions: list[ServiceException] = []
        calendar_dates_path = root / "calendar_dates.txt"
        if calendar_dates_path.is_file():
            for row in _read_rows(calendar_dates_path):
                source_service_id = _required(
                    row, "service_id", file_name="calendar_dates.txt"
                )
                try:
                    exception_type = int(
                        _required(
                            row, "exception_type", file_name="calendar_dates.txt"
                        )
                    )
                except ValueError as error:
                    raise ValueError(
                        f"invalid exception_type for service {source_service_id}"
                    ) from error
                service_exceptions.append(
                    ServiceException(
                        service_id=namespace_id(feed_id, source_service_id),
                        day=_parse_date(
                            _required(row, "date", file_name="calendar_dates.txt"),
                            field="calendar_dates date",
                        ),
                        exception_type=exception_type,
                    )
                )

        return TransitDataset(
            metadata=metadata,
            stops=stops,
            routes=routes,
            trips=trips,
            stop_times=tuple(stop_times),
            calendars=calendars,
            service_exceptions=tuple(service_exceptions),
        )
