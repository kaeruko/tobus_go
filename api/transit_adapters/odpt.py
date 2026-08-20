from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

from transit_dataset import (
    FeedMetadata,
    ServiceCalendar,
    TransitDataset,
    TransitMode,
    TransitRoute,
    TransitStop,
    TransitStopTime,
    TransitTrip,
    namespace_id,
    service_time_to_minute,
)


@dataclass(frozen=True, slots=True)
class OdptCalendarRule:
    weekdays: tuple[bool, bool, bool, bool, bool, bool, bool]
    start_date: date
    end_date: date


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

        def ensure_calendar(source_calendar_id: str) -> str:
            internal_id = namespace_id(feed_id, source_calendar_id)
            if internal_id not in calendars:
                calendars[internal_id] = _service_calendar(
                    feed_id=feed_id,
                    source_id=source_calendar_id,
                    calendar_rules=calendar_rules,
                )
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
                if not isinstance(sequence_raw, int):
                    raise ValueError(
                        f"bus timetable stop has invalid odpt:index: {source_trip_id}"
                    )
                arrival_raw = obj.get("odpt:arrivalTime")
                departure_raw = obj.get("odpt:departureTime")
                arrival = (
                    service_time_to_minute(arrival_raw)
                    if isinstance(arrival_raw, str) and arrival_raw
                    else None
                )
                departure = (
                    service_time_to_minute(departure_raw)
                    if isinstance(departure_raw, str) and departure_raw
                    else None
                )
                stop_times.append(
                    TransitStopTime(
                        trip_id=internal_trip_id,
                        stop_id=stop_id,
                        sequence=sequence_raw,
                        arrival_minute=arrival,
                        departure_minute=departure,
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
                arrival_raw = obj.get("odpt:arrivalTime")
                departure_raw = obj.get("odpt:departureTime")
                arrival = (
                    service_time_to_minute(arrival_raw)
                    if isinstance(arrival_raw, str) and arrival_raw
                    else None
                )
                departure = (
                    service_time_to_minute(departure_raw)
                    if isinstance(departure_raw, str) and departure_raw
                    else None
                )
                stop_times.append(
                    TransitStopTime(
                        trip_id=internal_trip_id,
                        stop_id=stop_id,
                        sequence=sequence,
                        arrival_minute=arrival,
                        departure_minute=departure,
                    )
                )

        return TransitDataset(
            metadata=metadata,
            stops=stops,
            routes=routes,
            trips=trips,
            stop_times=tuple(stop_times),
            calendars=calendars,
        )
