from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

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
    service_time_to_second,
)


@dataclass(frozen=True, slots=True)
class OdptCalendarRule:
    weekdays: tuple[bool, bool, bool, bool, bool, bool, bool]
    start_date: date
    end_date: date
    added_dates: tuple[date, ...] = ()
    removed_dates: tuple[date, ...] = ()
    # Explicit source convention: civil clocks below this boundary belong
    # to the next civil date of the SAME service day. Zero means no rewrite.
    service_day_start_second: int = 0

    def __post_init__(self):
        if (type(self.weekdays) is not tuple or len(self.weekdays) != 7
                or any(type(value) is not bool for value in self.weekdays)):
            raise ValueError('ODPT weekdays require seven explicit bool values')
        if (type(self.start_date) is not date or type(self.end_date) is not date
                or self.end_date < self.start_date):
            raise ValueError('invalid ODPT calendar date range')
        if (type(self.service_day_start_second) is not int
                or not 0 <= self.service_day_start_second < 86400):
            raise ValueError('ODPT service-day boundary requires integer seconds in [0, 86400)')
        for name in ('added_dates', 'removed_dates'):
            values = getattr(self, name)
            if (type(values) is not tuple or any(type(day) is not date for day in values)
                    or len(set(values)) != len(values)
                    or any(not self.start_date <= day <= self.end_date for day in values)):
                raise ValueError(f'invalid ODPT {name}: explicit unique dates within rule validity required')
        if set(self.added_dates) & set(self.removed_dates):
            raise ValueError('conflicting ODPT service exceptions')


def _clock_fields(obj, key, rule, *, trip_id, sequence):
    raw = obj.get(key)
    if raw is None or raw == '':
        return None, None
    if not isinstance(raw, str):
        raise ValueError(f'invalid ODPT clock type: {trip_id} sequence={sequence} field={key}')
    try:
        seconds = service_time_to_second(raw)
    except ValueError as error:
        raise ValueError(f'invalid ODPT clock: {trip_id} sequence={sequence} field={key}: {error}') from error
    if seconds < rule.service_day_start_second:
        seconds += 86400
    # Only the legacy v1 projection is rounded; scheduled v2 consumes seconds.
    minute = seconds // 60 + (1 if seconds % 60 >= 30 else 0)
    return minute, seconds


def _id(record: Mapping[str, object]) -> str:
    for key in ("owl:sameAs", "@id", "id"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    raise ValueError("ODPT record has no stable id")


def _required_str(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"ODPT record is missing {key}: {_id(record)}")
    return value


def _optional_identity(record, key):
    value = record.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f'invalid ODPT identity: {_id(record)} field={key}')
    return value


def _coordinates(record: Mapping[str, object]) -> tuple[float, float]:
    record_id = _id(record)
    lat = record.get("geo:lat")
    lon = record.get("geo:long")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        raise ValueError(f"ODPT stop/station has invalid coordinates: {record_id}")
    return float(lat), float(lon)


def _title(record: Mapping[str, object]) -> str:
    value = record.get("dc:title")
    if not isinstance(value, str) or not value:
        raise ValueError(f"ODPT record has no dc:title: {_id(record)}")
    return value


def _service_calendar(
    *,
    feed_id: str,
    source_id: str,
    calendar_rules: Mapping[str, OdptCalendarRule],
) -> ServiceCalendar:
    rule = calendar_rules.get(source_id)
    if rule is None:
        raise ValueError(
            f"ODPT calendar rule is not configured: {source_id}. "
            "Calendar semantics must be supplied explicitly."
        )
    if not isinstance(rule, OdptCalendarRule):
        raise ValueError(f'ODPT calendar requires an explicit OdptCalendarRule: {source_id}')
    internal_id = namespace_id(feed_id, source_id)
    return ServiceCalendar(
        id=internal_id,
        source_id=source_id,
        weekdays=rule.weekdays,
        start_date=rule.start_date,
        end_date=rule.end_date,
    )


class OdptTransitAdapter:
    @staticmethod
    def build(
        *,
        metadata: FeedMetadata,
        busstop_poles: Iterable[Mapping[str, object]] = (),
        busroute_patterns: Iterable[Mapping[str, object]] = (),
        bus_timetables: Iterable[Mapping[str, object]] = (),
        stations: Iterable[Mapping[str, object]] = (),
        railways: Iterable[Mapping[str, object]] = (),
        train_timetables: Iterable[Mapping[str, object]] = (),
        calendar_rules: Mapping[str, OdptCalendarRule],
    ) -> TransitDataset:
        feed_id = metadata.feed_id
        busstop_poles = list(busstop_poles)
        busroute_patterns = list(busroute_patterns)
        bus_timetables = list(bus_timetables)
        stations = list(stations)
        railways = list(railways)
        train_timetables = list(train_timetables)

        stops: dict[str, TransitStop] = {}
        for record in [*busstop_poles, *stations]:
            source_id = _id(record)
            internal_id = namespace_id(feed_id, source_id)
            if internal_id in stops:
                raise ValueError(f"duplicate ODPT stop/station id: {source_id}")
            lat, lon = _coordinates(record)
            stops[internal_id] = TransitStop(
                id=internal_id,
                source_id=source_id,
                name=_title(record),
                lat=lat,
                lon=lon,
            )

        routes: dict[str, TransitRoute] = {}
        pattern_to_route: dict[str, str] = {}
        for pattern in busroute_patterns:
            pattern_id = _id(pattern)
            source_route_id = _required_str(pattern, "odpt:busroute")
            internal_route_id = namespace_id(feed_id, source_route_id)
            pattern_to_route[pattern_id] = internal_route_id
            if internal_route_id not in routes:
                title = _title(pattern)
                routes[internal_route_id] = TransitRoute(
                    id=internal_route_id,
                    source_id=source_route_id,
                    short_name=title,
                    long_name=title,
                    mode=TransitMode.BUS,
                )

        for railway in railways:
            source_route_id = _id(railway)
            internal_route_id = namespace_id(feed_id, source_route_id)
            if internal_route_id in routes:
                raise ValueError(f"ODPT route id collision: {source_route_id}")
            title = _title(railway)
            routes[internal_route_id] = TransitRoute(
                id=internal_route_id,
                source_id=source_route_id,
                short_name=title,
                long_name=title,
                mode=TransitMode.RAIL,
            )

        trips: dict[str, TransitTrip] = {}
        stop_times: list[TransitStopTime] = []
        calendars: dict[str, ServiceCalendar] = {}
        exceptions: list[ServiceException] = []

        def ensure_calendar(source_calendar_id: str) -> str:
            internal_id = namespace_id(feed_id, source_calendar_id)
            if internal_id not in calendars:
                calendars[internal_id] = _service_calendar(
                    feed_id=feed_id,
                    source_id=source_calendar_id,
                    calendar_rules=calendar_rules,
                )
                rule = calendar_rules[source_calendar_id]
                exceptions.extend(ServiceException(internal_id, day, kind)
                                  for dates, kind in ((rule.added_dates, 1), (rule.removed_dates, 2))
                                  for day in dates)
            return internal_id

        for timetable in bus_timetables:
            source_trip_id = _id(timetable)
            internal_trip_id = namespace_id(feed_id, source_trip_id)
            if internal_trip_id in trips:
                raise ValueError(f"duplicate ODPT trip id: {source_trip_id}")
            pattern_id = _required_str(timetable, "odpt:busroutePattern")
            route_id = pattern_to_route.get(pattern_id)
            if route_id is None:
                raise ValueError(
                    f"bus timetable references unknown route pattern: {pattern_id}"
                )
            source_calendar_id = _required_str(timetable, "odpt:calendar")
            service_id = ensure_calendar(source_calendar_id)
            trips[internal_trip_id] = TransitTrip(
                id=internal_trip_id,
                source_id=source_trip_id,
                route_id=route_id,
                service_id=service_id,
                headsign=str(timetable.get("dc:title") or ""),
                source_pattern_id=pattern_id,
                source_operator_id=_optional_identity(timetable, 'odpt:operator'),
            )
            objects = timetable.get("odpt:busTimetableObject")
            if not isinstance(objects, list) or not objects:
                raise ValueError(f"bus timetable has no stop objects: {source_trip_id}")
            for obj in objects:
                if not isinstance(obj, Mapping):
                    raise ValueError(f"invalid bus timetable object: {source_trip_id}")
                stop_source_id = _required_str(obj, "odpt:busstopPole")
                stop_id = namespace_id(feed_id, stop_source_id)
                if stop_id not in stops:
                    raise ValueError(
                        f"bus timetable references unknown stop: {stop_source_id}"
                    )
                sequence_raw = obj.get("odpt:index")
                if type(sequence_raw) is not int:
                    raise ValueError(
                        f"bus timetable stop has invalid odpt:index: {source_trip_id}"
                    )
                rule = calendar_rules[source_calendar_id]
                arrival, arrival_seconds = _clock_fields(
                    obj, "odpt:arrivalTime", rule, trip_id=source_trip_id, sequence=sequence_raw)
                departure, departure_seconds = _clock_fields(
                    obj, "odpt:departureTime", rule, trip_id=source_trip_id, sequence=sequence_raw)
                stop_times.append(
                    TransitStopTime(
                        trip_id=internal_trip_id,
                        stop_id=stop_id,
                        sequence=sequence_raw,
                        arrival_minute=arrival,
                        departure_minute=departure,
                        arrival_service_seconds=arrival_seconds,
                        departure_service_seconds=departure_seconds,
                    )
                )

        for timetable in train_timetables:
            source_trip_id = _id(timetable)
            internal_trip_id = namespace_id(feed_id, source_trip_id)
            if internal_trip_id in trips:
                raise ValueError(f"duplicate ODPT trip id: {source_trip_id}")
            source_route_id = _required_str(timetable, "odpt:railway")
            route_id = namespace_id(feed_id, source_route_id)
            if route_id not in routes:
                raise ValueError(
                    f"train timetable references unknown railway: {source_route_id}"
                )
            source_calendar_id = _required_str(timetable, "odpt:calendar")
            service_id = ensure_calendar(source_calendar_id)
            trips[internal_trip_id] = TransitTrip(
                id=internal_trip_id,
                source_id=source_trip_id,
                route_id=route_id,
                service_id=service_id,
                headsign=str(timetable.get("dc:title") or ""),
                train_number=_optional_identity(timetable, 'odpt:trainNumber'),
                source_train_type=_optional_identity(timetable, 'odpt:trainType'),
                source_operator_id=_optional_identity(timetable, 'odpt:operator'),
            )
            objects = timetable.get("odpt:trainTimetableObject")
            if not isinstance(objects, list) or not objects:
                raise ValueError(f"train timetable has no stop objects: {source_trip_id}")
            for sequence, obj in enumerate(objects, start=1):
                if not isinstance(obj, Mapping):
                    raise ValueError(f"invalid train timetable object: {source_trip_id}")
                arrival_station = obj.get("odpt:arrivalStation")
                departure_station = obj.get("odpt:departureStation")
                if (
                    isinstance(arrival_station, str)
                    and isinstance(departure_station, str)
                    and arrival_station != departure_station
                ):
                    raise ValueError(
                        f"train timetable object has different arrival/departure stations: "
                        f"{source_trip_id}"
                    )
                source_stop_id = (
                    departure_station
                    if isinstance(departure_station, str) and departure_station
                    else arrival_station
                )
                if not isinstance(source_stop_id, str) or not source_stop_id:
                    raise ValueError(
                        f"train timetable object has no station: {source_trip_id}"
                    )
                stop_id = namespace_id(feed_id, source_stop_id)
                if stop_id not in stops:
                    raise ValueError(
                        f"train timetable references unknown station: {source_stop_id}"
                    )
                rule = calendar_rules[source_calendar_id]
                arrival, arrival_seconds = _clock_fields(
                    obj, "odpt:arrivalTime", rule, trip_id=source_trip_id, sequence=sequence)
                departure, departure_seconds = _clock_fields(
                    obj, "odpt:departureTime", rule, trip_id=source_trip_id, sequence=sequence)
                stop_times.append(
                    TransitStopTime(
                        trip_id=internal_trip_id,
                        stop_id=stop_id,
                        sequence=sequence,
                        arrival_minute=arrival,
                        departure_minute=departure,
                        arrival_service_seconds=arrival_seconds,
                        departure_service_seconds=departure_seconds,
                    )
                )

        return TransitDataset(
            metadata=metadata,
            stops=stops,
            routes=routes,
            trips=trips,
            stop_times=tuple(stop_times),
            calendars=calendars,
            service_exceptions=tuple(exceptions),
        )

