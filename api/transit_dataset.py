from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Mapping, Sequence


class TransitMode(str, Enum):
    BUS = "bus"
    RAIL = "rail"


def namespace_id(feed_id: str, source_id: str) -> str:
    """Return a globally unique internal id without rewriting the source id."""
    if not feed_id or feed_id.strip() != feed_id or ":" in feed_id:
        raise ValueError(f"invalid feed_id: {feed_id!r}")
    if not source_id or source_id.strip() != source_id:
        raise ValueError(f"invalid source_id: {source_id!r}")
    return f"{feed_id}:{source_id}"


def service_time_to_minute(value: str) -> int:
    """Parse a GTFS/ODPT HH:MM[:SS] service-day time, including 24:xx+."""
    parts = value.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"invalid service time: {value!r}")
    if any(part == "" or not part.isdigit() for part in parts):
        raise ValueError(f"invalid service time: {value!r}")
    hour = int(parts[0])
    minute = int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    if minute > 59 or second > 59:
        raise ValueError(f"invalid service time: {value!r}")
    return hour * 60 + minute + (1 if second >= 30 else 0)


@dataclass(frozen=True, slots=True)
class FeedMetadata:
    feed_id: str
    source_type: str
    source_uri: str
    version: str
    fetched_at: datetime

    def __post_init__(self) -> None:
        namespace_id(self.feed_id, "validation")
        if not self.source_type:
            raise ValueError("source_type is required")
        if not self.source_uri:
            raise ValueError("source_uri is required")
        if not self.version:
            raise ValueError("version is required")
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TransitStop:
    id: str
    source_id: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class TransitRoute:
    id: str
    source_id: str
    short_name: str
    long_name: str
    mode: TransitMode


@dataclass(frozen=True, slots=True)
class TransitTrip:
    id: str
    source_id: str
    route_id: str
    service_id: str
    headsign: str
    direction_id: str | None = None


@dataclass(frozen=True, slots=True)
class TransitStopTime:
    trip_id: str
    stop_id: str
    sequence: int
    arrival_minute: int | None
    departure_minute: int | None

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("stop sequence must be non-negative")
        if self.arrival_minute is None and self.departure_minute is None:
            raise ValueError("stop time requires arrival or departure")


@dataclass(frozen=True, slots=True)
class ServiceCalendar:
    id: str
    source_id: str
    weekdays: tuple[bool, bool, bool, bool, bool, bool, bool]
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError(f"calendar end before start: {self.source_id}")

    def active_on(self, day: date) -> bool:
        return self.start_date <= day <= self.end_date and self.weekdays[day.weekday()]


@dataclass(frozen=True, slots=True)
class ServiceException:
    service_id: str
    day: date
    exception_type: int

    def __post_init__(self) -> None:
        if self.exception_type not in (1, 2):
            raise ValueError(f"invalid exception_type: {self.exception_type}")


@dataclass(frozen=True, slots=True)
class TransitDataset:
    metadata: FeedMetadata
    stops: Mapping[str, TransitStop]
    routes: Mapping[str, TransitRoute]
    trips: Mapping[str, TransitTrip]
    stop_times: Sequence[TransitStopTime]
    calendars: Mapping[str, ServiceCalendar]
    service_exceptions: Sequence[ServiceException] = ()

    def __post_init__(self) -> None:
        feed_prefix = f"{self.metadata.feed_id}:"
        for collection_name, collection in (
            ("stops", self.stops),
            ("routes", self.routes),
            ("trips", self.trips),
            ("calendars", self.calendars),
        ):
            for key, value in collection.items():
                if key != value.id:
                    raise ValueError(f"{collection_name} key/id mismatch: {key!r}")
                if not key.startswith(feed_prefix):
                    raise ValueError(f"unnamespaced {collection_name} id: {key!r}")

        if not self.stops:
            raise ValueError("dataset has no stops")
        if not self.routes:
            raise ValueError("dataset has no routes")
        if not self.trips:
            raise ValueError("dataset has no trips")
        if not self.stop_times:
            raise ValueError("dataset has no stop_times")

        seen_trip_sequences: set[tuple[str, int]] = set()
        for trip in self.trips.values():
            if trip.route_id not in self.routes:
                raise ValueError(f"trip references unknown route: {trip.id} -> {trip.route_id}")
        for stop_time in self.stop_times:
            if stop_time.trip_id not in self.trips:
                raise ValueError(f"stop_time references unknown trip: {stop_time.trip_id}")
            if stop_time.stop_id not in self.stops:
                raise ValueError(f"stop_time references unknown stop: {stop_time.stop_id}")
            key = (stop_time.trip_id, stop_time.sequence)
            if key in seen_trip_sequences:
                raise ValueError(f"duplicate stop sequence: {key}")
            seen_trip_sequences.add(key)
        for exception in self.service_exceptions:
            if not exception.service_id.startswith(feed_prefix):
                raise ValueError(f"unnamespaced exception service: {exception.service_id}")

    def active_service_ids(self, day: date) -> frozenset[str]:
        active = {
            service_id
            for service_id, calendar in self.calendars.items()
            if calendar.active_on(day)
        }
        for exception in self.service_exceptions:
            if exception.day != day:
                continue
            if exception.exception_type == 1:
                active.add(exception.service_id)
            else:
                active.discard(exception.service_id)
        return frozenset(active)
