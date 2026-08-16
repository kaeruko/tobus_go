from __future__ import annotations

import asyncio
import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime

from app.services.train_realtime import (
    STATIC_GTFS_URL,
    TrainRealtimeError,
    _fetch_bytes,
)


_CALENDAR_LOCK = asyncio.Lock()
_calendar_index: "TrainServiceCalendarIndex | None" = None


@dataclass(frozen=True)
class TrainServiceCalendarRule:
    service_id: str
    weekdays: tuple[bool, bool, bool, bool, bool, bool, bool]
    start_date: date
    end_date: date


@dataclass(frozen=True)
class TrainServiceCalendarIndex:
    trip_service_ids: dict[str, str]
    calendar_rules: dict[str, TrainServiceCalendarRule]
    exceptions: dict[date, dict[str, int]]

    def active_trip_ids(self, target_date: date) -> frozenset[str]:
        active_services = {
            service_id
            for service_id, rule in self.calendar_rules.items()
            if rule.start_date <= target_date <= rule.end_date
            and rule.weekdays[target_date.weekday()]
        }
        for service_id, exception_type in self.exceptions.get(target_date, {}).items():
            if exception_type == 1:
                active_services.add(service_id)
            elif exception_type == 2:
                active_services.discard(service_id)
            else:
                raise TrainRealtimeError(
                    "train_static_calendar_invalid",
                    f"Unsupported calendar_dates exception_type: {exception_type}",
                    502,
                )
        return frozenset(
            trip_id
            for trip_id, service_id in self.trip_service_ids.items()
            if service_id in active_services
        )


def _read_csv_optional(
    archive: zipfile.ZipFile,
    filename: str,
) -> list[dict[str, str]] | None:
    matches = [
        name
        for name in archive.namelist()
        if name == filename or name.endswith(f"/{filename}")
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise TrainRealtimeError(
            "train_static_calendar_invalid",
            f"Static train GTFS contains multiple {filename}: {matches}",
            502,
        )
    with archive.open(matches[0]) as raw:
        return list(
            csv.DictReader(
                io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""),
            )
        )


def _required(row: dict[str, str], key: str, filename: str) -> str:
    value = (row.get(key) or "").strip()
    if not value:
        raise TrainRealtimeError(
            "train_static_calendar_invalid",
            f"{filename} contains a row without {key}",
            502,
        )
    return value


def _gtfs_date(value: str, filename: str, field: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as error:
        raise TrainRealtimeError(
            "train_static_calendar_invalid",
            f"{filename} contains invalid {field}: {value!r}",
            502,
        ) from error


def _flag(value: str, field: str) -> bool:
    if value == "0":
        return False
    if value == "1":
        return True
    raise TrainRealtimeError(
        "train_static_calendar_invalid",
        f"calendar.txt contains invalid {field}: {value!r}",
        502,
    )


def parse_train_service_calendar(content: bytes) -> TrainServiceCalendarIndex:
    if not content:
        raise TrainRealtimeError(
            "train_static_calendar_empty",
            "Static train GTFS response is empty",
            503,
        )
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            trips = _read_csv_optional(archive, "trips.txt")
            calendars = _read_csv_optional(archive, "calendar.txt")
            calendar_dates = _read_csv_optional(archive, "calendar_dates.txt")
    except zipfile.BadZipFile as error:
        raise TrainRealtimeError(
            "train_static_calendar_invalid",
            "Static train GTFS response is not a ZIP archive",
            502,
        ) from error

    if trips is None:
        raise TrainRealtimeError(
            "train_static_calendar_invalid",
            "Static train GTFS has no trips.txt",
            502,
        )
    if calendars is None and calendar_dates is None:
        raise TrainRealtimeError(
            "train_static_calendar_invalid",
            "Static train GTFS has no service calendar data",
            502,
        )

    trip_service_ids: dict[str, str] = {}
    for row in trips:
        trip_id = _required(row, "trip_id", "trips.txt")
        service_id = _required(row, "service_id", "trips.txt")
        if trip_id in trip_service_ids:
            raise TrainRealtimeError(
                "train_static_calendar_invalid",
                f"Duplicate trip_id in trips.txt: {trip_id}",
                502,
            )
        trip_service_ids[trip_id] = service_id

    weekday_fields = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )
    rules: dict[str, TrainServiceCalendarRule] = {}
    for row in calendars or []:
        service_id = _required(row, "service_id", "calendar.txt")
        if service_id in rules:
            raise TrainRealtimeError(
                "train_static_calendar_invalid",
                f"Duplicate service_id in calendar.txt: {service_id}",
                502,
            )
        start = _gtfs_date(
            _required(row, "start_date", "calendar.txt"),
            "calendar.txt",
            "start_date",
        )
        end = _gtfs_date(
            _required(row, "end_date", "calendar.txt"),
            "calendar.txt",
            "end_date",
        )
        if end < start:
            raise TrainRealtimeError(
                "train_static_calendar_invalid",
                f"calendar.txt date range is reversed for {service_id}",
                502,
            )
        rules[service_id] = TrainServiceCalendarRule(
            service_id=service_id,
            weekdays=tuple(
                _flag(_required(row, field, "calendar.txt"), field)
                for field in weekday_fields
            ),
            start_date=start,
            end_date=end,
        )

    exceptions: dict[date, dict[str, int]] = {}
    for row in calendar_dates or []:
        service_id = _required(row, "service_id", "calendar_dates.txt")
        target = _gtfs_date(
            _required(row, "date", "calendar_dates.txt"),
            "calendar_dates.txt",
            "date",
        )
        raw_type = _required(row, "exception_type", "calendar_dates.txt")
        if raw_type not in ("1", "2"):
            raise TrainRealtimeError(
                "train_static_calendar_invalid",
                f"Unsupported calendar_dates exception_type: {raw_type!r}",
                502,
            )
        day = exceptions.setdefault(target, {})
        if service_id in day:
            raise TrainRealtimeError(
                "train_static_calendar_invalid",
                f"Duplicate calendar_dates service/date: {service_id}/{target}",
                502,
            )
        day[service_id] = int(raw_type)

    known_services = set(rules)
    for day in exceptions.values():
        known_services.update(day)
    missing = sorted(set(trip_service_ids.values()) - known_services)
    if missing:
        raise TrainRealtimeError(
            "train_static_calendar_invalid",
            f"trips.txt references unknown service_id values: {missing}",
            502,
        )

    return TrainServiceCalendarIndex(
        trip_service_ids=trip_service_ids,
        calendar_rules=rules,
        exceptions=exceptions,
    )


def parse_service_date(target_date_str: str | None) -> date:
    if target_date_str is None or not target_date_str.strip():
        raise TrainRealtimeError(
            "train_service_date_missing",
            "target_date_str is required to resolve an exact train trip_id",
            400,
        )
    try:
        return date.fromisoformat(target_date_str.strip())
    except ValueError as error:
        raise TrainRealtimeError(
            "train_service_date_invalid",
            f"Invalid target_date_str: {target_date_str!r}",
            400,
        ) from error


async def get_active_train_trip_ids(
    target_date_str: str | None,
) -> frozenset[str]:
    global _calendar_index
    target_date = parse_service_date(target_date_str)
    if _calendar_index is None:
        async with _CALENDAR_LOCK:
            if _calendar_index is None:
                _calendar_index = parse_train_service_calendar(
                    await _fetch_bytes(STATIC_GTFS_URL, timeout_seconds=30.0)
                )
    active_trip_ids = _calendar_index.active_trip_ids(target_date)
    if not active_trip_ids:
        raise TrainRealtimeError(
            "train_static_service_date_empty",
            f"Static train GTFS has no active trips on {target_date.isoformat()}",
            502,
        )
    return active_trip_ids
