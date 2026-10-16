from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
import re
from typing import Mapping, Sequence


class TransitMode(str, Enum):
    BUS = "bus"
    RAIL = "rail"



@dataclass(frozen=True, slots=True)
class PublishedMinuteProvenance:
    """A published minute or an explicit proxy, never observed arrival seconds."""
    basis: str
    source_uri: str
    source_sha256: str
    row_number: int
    column_number: int
    published_clock: str
    service_minute: int
    precision_minutes: int = 1

    def __post_init__(self):
        if self.basis not in ("published_departure_minute", "published_clock_arrival_proxy"):
            raise ValueError("unsupported published-minute basis")
        if (not isinstance(self.source_uri, str) or not self.source_uri.startswith("https://")
                or re.fullmatch(r"[a-f0-9]{64}", self.source_sha256) is None
                or type(self.row_number) is not int or self.row_number < 2
                or type(self.column_number) is not int or self.column_number < 3
                or type(self.service_minute) is not int or self.service_minute < 0
                or type(self.precision_minutes) is not int or self.precision_minutes != 1
                or re.fullmatch(r"(?:[0-9]|1[0-9]|2[0-3]):[0-5][0-9]", self.published_clock) is None):
            raise ValueError("invalid published-minute provenance")
        hour, minute = map(int, self.published_clock.split(":"))
        if self.service_minute % 1440 != hour * 60 + minute:
            raise ValueError("published clock/service minute mismatch")

    @property
    def is_estimate(self):
        return self.basis == "published_clock_arrival_proxy"

def namespace_id(feed_id: str, source_id: str) -> str:
    """Return a globally unique internal id without rewriting the source id."""
    if not feed_id or feed_id.strip() != feed_id or ":" in feed_id:
        raise ValueError(f"invalid feed_id: {feed_id!r}")
    if not source_id or source_id.strip() != source_id:
        raise ValueError(f"invalid source_id: {source_id!r}")
    return f"{feed_id}:{source_id}"


def service_time_to_second(value: str) -> int:
    """Parse an exact service-day HH:MM[:SS] clock, including 24:xx+."""
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
    return hour * 3600 + minute * 60 + second


def service_time_to_minute(value: str) -> int:
    """Preserve the existing v1 rounded-minute contract."""
    seconds = service_time_to_second(value)
    return seconds // 60 + (1 if seconds % 60 >= 30 else 0)


@dataclass(frozen=True, slots=True)
class FeedMetadata:
    feed_id: str
    source_type: str
    source_uri: str
    version: str
    fetched_at: datetime
    clock_profile: str = "source"

    def __post_init__(self) -> None:
        namespace_id(self.feed_id, "validation")
        if self.clock_profile not in ("source", "sendai_published_minute_v1"):
            raise ValueError("unsupported feed clock profile")
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
    name_en: str | None = None

    def __post_init__(self):
        if self.name_en is not None and (not isinstance(self.name_en, str) or not self.name_en.strip()):
            raise ValueError(f'invalid official English stop name: {self.id}')


@dataclass(frozen=True, slots=True)
class TransitRoute:
    id: str
    source_id: str
    short_name: str
    long_name: str
    mode: TransitMode
    name_en: str | None = None

    def __post_init__(self):
        if self.name_en is not None and (not isinstance(self.name_en, str) or not self.name_en.strip()):
            raise ValueError(f'invalid official English route name: {self.id}')


@dataclass(frozen=True, slots=True)
class TransitTrip:
    id: str
    source_id: str
    route_id: str
    service_id: str
    headsign: str
    direction_id: str | None = None
    # Original source identities, not inferred fare classification or realtime.
    source_pattern_id: str | None = None
    train_number: str | None = None
    source_train_type: str | None = None
    source_operator_id: str | None = None
    source_pattern_title: str | None = None

    def __post_init__(self):
        for name in ('source_pattern_id', 'train_number', 'source_train_type', 'source_operator_id'):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value
                                      or value.strip() != value):
                raise ValueError(f'invalid source trip metadata: {self.id} field={name}')
        if self.source_pattern_title is not None and (not isinstance(self.source_pattern_title, str)
                                                       or not self.source_pattern_title.strip()):
            raise ValueError(f'invalid source pattern title: {self.id}')


@dataclass(frozen=True, slots=True)
class TransitStopTime:
    trip_id: str
    stop_id: str
    sequence: int
    arrival_minute: int | None
    departure_minute: int | None
    pickup_type: int = 0
    drop_off_type: int = 0
    arrival_service_seconds: int | None = None
    departure_service_seconds: int | None = None
    arrival_provenance: PublishedMinuteProvenance | None = None
    departure_provenance: PublishedMinuteProvenance | None = None
    model_day_offset_minutes: int = 0

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("stop sequence must be non-negative")
        if self.arrival_minute is None and self.departure_minute is None:
            raise ValueError("stop time requires arrival or departure")
        for name in ("pickup_type", "drop_off_type"):
            value = getattr(self, name)
            if type(value) is not int or value not in (0, 1, 2, 3):
                raise ValueError(f"invalid {name}: {value!r}")
        for name in ("arrival_service_seconds", "departure_service_seconds"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"invalid {name}: {value!r}")


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
            if self.metadata.clock_profile == "sendai_published_minute_v1":
                for kind in ("arrival", "departure"):
                    clock = getattr(stop_time, kind + "_minute")
                    provenance = getattr(stop_time, kind + "_provenance")
                    if getattr(stop_time, kind + "_service_seconds") is not None:
                        raise ValueError("practical minute clocks cannot assert source seconds")
                    if clock is None:
                        if provenance is not None:
                            raise ValueError("provenance without model clock")
                    elif (not isinstance(provenance, PublishedMinuteProvenance)
                          or provenance.is_estimate != (kind == "arrival")
                          or type(clock) is not int or clock < 0
                          or type(stop_time.model_day_offset_minutes) is not int
                          or stop_time.model_day_offset_minutes < 0
                          or stop_time.model_day_offset_minutes % 1440 != 0
                          or clock != provenance.service_minute + stop_time.model_day_offset_minutes):
                        raise ValueError("practical clock requires matching typed provenance")
            elif (stop_time.arrival_provenance is not None or stop_time.departure_provenance is not None
                  or stop_time.model_day_offset_minutes != 0):
                raise ValueError("published minute provenance requires explicit practical profile")

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


