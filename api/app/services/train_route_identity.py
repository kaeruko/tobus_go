from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.train_realtime import StaticTrainGtfs, StaticTrainTrip


class TrainRouteIdentityError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class _ResolvedOdptRailRun:
    train_number: str
    scheduled_departure_minute: int
    scheduled_arrival_minute: int


def route_result_has_rail(result: dict[str, Any]) -> bool:
    candidates = result.get("candidates")
    if candidates is None:
        return False
    if not isinstance(candidates, list):
        raise TrainRouteIdentityError(
            "route_candidates_invalid",
            "route result candidates must be a list",
        )
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise TrainRouteIdentityError(
                "route_candidate_invalid",
                "route candidate must be an object",
            )
        steps = candidate.get("steps")
        if not isinstance(steps, list):
            raise TrainRouteIdentityError(
                "route_steps_invalid",
                f"route candidate {candidate.get('id')!r} has invalid steps",
            )
        for step in steps:
            if isinstance(step, dict) and step.get("kind") == "rail":
                return True
    return False


def enrich_route_result_train_trip_ids(
    result: dict[str, Any],
    *,
    timetable_manager: Any,
    day_type: Any,
    static_gtfs: StaticTrainGtfs,
) -> dict[str, Any]:
    candidates = result.get("candidates")
    if candidates is None:
        return result
    if not isinstance(candidates, list):
        raise TrainRouteIdentityError(
            "route_candidates_invalid",
            "route result candidates must be a list",
        )

    enriched_candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []

    for raw_candidate in candidates:
        if not isinstance(raw_candidate, dict):
            raise TrainRouteIdentityError(
                "route_candidate_invalid",
                "route candidate must be an object",
            )
        candidate = dict(raw_candidate)
        raw_steps = candidate.get("steps")
        if not isinstance(raw_steps, list):
            raise TrainRouteIdentityError(
                "route_steps_invalid",
                f"route candidate {candidate.get('id')!r} has invalid steps",
            )
        steps = [dict(step) if isinstance(step, dict) else step for step in raw_steps]
        candidate["steps"] = steps

        try:
            for step in steps:
                if not isinstance(step, dict):
                    raise TrainRouteIdentityError(
                        "route_step_invalid",
                        f"route candidate {candidate.get('id')!r} contains a non-object step",
                    )
                if step.get("kind") != "rail":
                    continue
                _enrich_rail_step(
                    step,
                    timetable_manager=timetable_manager,
                    day_type=day_type,
                    static_gtfs=static_gtfs,
                )
        except TrainRouteIdentityError as error:
            rejected.append(
                {
                    "candidate_id": str(candidate.get("id") or ""),
                    "code": error.code,
                    "message": error.message,
                }
            )
            continue

        enriched_candidates.append(candidate)

    out = dict(result)
    out["candidates"] = enriched_candidates
    if rejected:
        raw_meta = out.get("meta")
        if raw_meta is None:
            meta: dict[str, Any] = {}
        elif isinstance(raw_meta, dict):
            meta = dict(raw_meta)
        else:
            raise TrainRouteIdentityError(
                "route_meta_invalid",
                "route result meta must be an object",
            )
        meta["train_identity_rejected_candidates"] = rejected
        out["meta"] = meta
    return out


def _enrich_rail_step(
    step: dict[str, Any],
    *,
    timetable_manager: Any,
    day_type: Any,
    static_gtfs: StaticTrainGtfs,
) -> None:
    step_id = _required_text(step.get("step_id"), "step_id")
    stops = _required_route_stops(step, step_id)
    ready_minute = _clock_to_minute(
        _required_text(step.get("departure_time"), "departure_time"),
        label=f"rail step {step_id} departure_time",
    )
    route_arrival_minute = _clock_to_minute(
        _required_text(step.get("arrival_time"), "arrival_time"),
        label=f"rail step {step_id} arrival_time",
    )

    resolved_odpt = _resolve_odpt_rail_run(
        stops,
        ready_minute=ready_minute,
        timetable_manager=timetable_manager,
        day_type=day_type,
    )

    # The route engine may apply a realtime delay to the displayed arrival.
    # Identity matching must use the underlying scheduled clocks, but we still
    # verify that the route's displayed arrival is the same run after delay.
    actual_arrival = _actual_train_minute(
        timetable_manager,
        stops[-2]["id"],
        resolved_odpt.train_number,
        resolved_odpt.scheduled_arrival_minute,
    )
    if int(actual_arrival) != route_arrival_minute:
        raise TrainRouteIdentityError(
            "rail_route_arrival_mismatch",
            "route rail arrival does not match the exact ODPT train run: "
            f"step={step_id}, route={route_arrival_minute}, "
            f"resolved={int(actual_arrival)}, train={resolved_odpt.train_number}",
        )

    static_trip = _resolve_static_trip(
        static_gtfs,
        stop_names=[stop["name"] for stop in stops],
        scheduled_departure_minute=resolved_odpt.scheduled_departure_minute,
        scheduled_arrival_minute=resolved_odpt.scheduled_arrival_minute,
        step_id=step_id,
    )

    existing_trip_id = step.get("trip_id")
    if existing_trip_id is not None and str(existing_trip_id).strip():
        normalized_existing = str(existing_trip_id).strip()
        if normalized_existing != static_trip.trip_id:
            raise TrainRouteIdentityError(
                "rail_existing_trip_id_mismatch",
                "route rail trip_id conflicts with exact static GTFS match: "
                f"step={step_id}, existing={normalized_existing}, "
                f"resolved={static_trip.trip_id}",
            )

    step["trip_id"] = static_trip.trip_id
    step["route_id"] = static_trip.route_id


def _required_route_stops(
    step: dict[str, Any],
    step_id: str,
) -> list[dict[str, str]]:
    raw_stops = step.get("stops")
    if not isinstance(raw_stops, list) or len(raw_stops) < 2:
        raise TrainRouteIdentityError(
            "rail_route_stops_missing",
            f"rail step {step_id} must contain at least two stops",
        )
    stops: list[dict[str, str]] = []
    for index, raw_stop in enumerate(raw_stops):
        if not isinstance(raw_stop, dict):
            raise TrainRouteIdentityError(
                "rail_route_stop_invalid",
                f"rail step {step_id} stop[{index}] is not an object",
            )
        station_id = _required_text(raw_stop.get("id") or raw_stop.get("stop_id"), "id")
        name = _required_text(raw_stop.get("name"), "name")
        stops.append({"id": station_id, "name": name})
    return stops


def _resolve_odpt_rail_run(
    stops: list[dict[str, str]],
    *,
    ready_minute: int,
    timetable_manager: Any,
    day_type: Any,
) -> _ResolvedOdptRailRun:
    target = (
        timetable_manager.train_patterns_weekday
        if str(day_type) == "weekday"
        else timetable_manager.train_patterns_weekend
    )
    origin_id = stops[0]["id"]
    second_id = stops[1]["id"]
    first_records = target.get(origin_id)
    if not first_records:
        raise TrainRouteIdentityError(
            "rail_odpt_origin_missing",
            f"ODPT train timetable has no departures from {origin_id}",
        )

    eligible: list[tuple[float, dict[str, Any]]] = []
    for record in _dedupe_train_records(first_records):
        if record.get("next_sta") != second_id:
            continue
        train_number = _required_text(record.get("train_num"), "train_num")
        actual_departure = _actual_train_minute(
            timetable_manager,
            origin_id,
            train_number,
            _required_int(record.get("dep"), "dep"),
        )
        if actual_departure >= ready_minute:
            eligible.append((actual_departure, record))

    if not eligible:
        raise TrainRouteIdentityError(
            "rail_odpt_run_not_found",
            f"no ODPT train can serve {origin_id}->{second_id} after {ready_minute}",
        )
    eligible.sort(key=lambda item: item[0])
    earliest = eligible[0][0]
    earliest_records = [record for actual, record in eligible if actual == earliest]
    train_numbers = {
        _required_text(record.get("train_num"), "train_num")
        for record in earliest_records
    }
    if len(train_numbers) != 1:
        raise TrainRouteIdentityError(
            "rail_odpt_run_ambiguous",
            f"multiple ODPT trains share the earliest departure: {sorted(train_numbers)}",
        )
    train_number = next(iter(train_numbers))

    first_scheduled_departure: int | None = None
    final_scheduled_arrival: int | None = None
    previous_actual_arrival: float | None = None

    for index in range(len(stops) - 1):
        current_id = stops[index]["id"]
        next_id = stops[index + 1]["id"]
        records = [
            record
            for record in _dedupe_train_records(target.get(current_id) or [])
            if record.get("next_sta") == next_id
            and _required_text(record.get("train_num"), "train_num") == train_number
        ]
        if len(records) != 1:
            raise TrainRouteIdentityError(
                "rail_odpt_run_segment_missing",
                "the selected ODPT train does not uniquely cover the route segment: "
                f"train={train_number}, {current_id}->{next_id}, matches={len(records)}",
            )
        record = records[0]
        scheduled_departure = _required_int(record.get("dep"), "dep")
        scheduled_arrival = _required_int(record.get("arr"), "arr")
        if scheduled_arrival < scheduled_departure:
            raise TrainRouteIdentityError(
                "rail_odpt_clock_invalid",
                f"ODPT train segment goes backwards in time: {scheduled_departure}->{scheduled_arrival}",
            )

        actual_departure = _actual_train_minute(
            timetable_manager,
            current_id,
            train_number,
            scheduled_departure,
        )
        actual_arrival = _actual_train_minute(
            timetable_manager,
            current_id,
            train_number,
            scheduled_arrival,
        )
        if index == 0 and actual_departure < ready_minute:
            raise TrainRouteIdentityError(
                "rail_odpt_run_departed",
                f"selected ODPT train already departed: {actual_departure} < {ready_minute}",
            )
        if previous_actual_arrival is not None and actual_departure < previous_actual_arrival:
            raise TrainRouteIdentityError(
                "rail_odpt_run_discontinuous",
                "selected ODPT train timetable is discontinuous: "
                f"train={train_number}, previous_arrival={previous_actual_arrival}, "
                f"departure={actual_departure}",
            )

        if first_scheduled_departure is None:
            first_scheduled_departure = scheduled_departure
        final_scheduled_arrival = scheduled_arrival
        previous_actual_arrival = actual_arrival

    if first_scheduled_departure is None or final_scheduled_arrival is None:
        raise TrainRouteIdentityError(
            "rail_odpt_run_empty",
            f"ODPT train run contains no segments: train={train_number}",
        )
    return _ResolvedOdptRailRun(
        train_number=train_number,
        scheduled_departure_minute=first_scheduled_departure,
        scheduled_arrival_minute=final_scheduled_arrival,
    )


def _resolve_static_trip(
    static_gtfs: StaticTrainGtfs,
    *,
    stop_names: list[str],
    scheduled_departure_minute: int,
    scheduled_arrival_minute: int,
    step_id: str,
) -> StaticTrainTrip:
    if len(stop_names) < 2:
        raise TrainRouteIdentityError(
            "rail_static_stops_missing",
            f"rail step {step_id} must contain at least two stop names",
        )

    matches: list[StaticTrainTrip] = []
    for trip in static_gtfs.trips.values():
        trip_names = [stop.stop_name.strip() for stop in trip.stops]
        starts = [
            index
            for index in range(0, len(trip_names) - len(stop_names) + 1)
            if trip_names[index : index + len(stop_names)] == stop_names
        ]
        if not starts:
            continue
        if len(starts) != 1:
            raise TrainRouteIdentityError(
                "rail_static_segment_ambiguous",
                f"static trip {trip.trip_id} contains the route stop sequence more than once",
            )
        start = starts[0]
        origin = trip.stops[start]
        destination = trip.stops[start + len(stop_names) - 1]
        if origin.departure_time is None or destination.arrival_time is None:
            continue
        static_departure = _clock_to_minute(
            origin.departure_time,
            label=f"static trip {trip.trip_id} departure_time",
        )
        static_arrival = _clock_to_minute(
            destination.arrival_time,
            label=f"static trip {trip.trip_id} arrival_time",
        )
        if (
            static_departure == scheduled_departure_minute
            and static_arrival == scheduled_arrival_minute
        ):
            matches.append(trip)

    if not matches:
        raise TrainRouteIdentityError(
            "rail_static_trip_not_found",
            "no static GTFS trip exactly matches the ODPT train run: "
            f"step={step_id}, stops={stop_names}, "
            f"departure={scheduled_departure_minute}, arrival={scheduled_arrival_minute}",
        )
    if len(matches) != 1:
        raise TrainRouteIdentityError(
            "rail_static_trip_ambiguous",
            "multiple static GTFS trips exactly match the ODPT train run: "
            f"step={step_id}, trip_ids={[trip.trip_id for trip in matches]}",
        )
    return matches[0]


def _actual_train_minute(
    timetable_manager: Any,
    station_id: str,
    train_number: str,
    scheduled_minute: int,
) -> float:
    delays = getattr(timetable_manager, "realtime_delays", None)
    if not isinstance(delays, dict):
        raise TrainRouteIdentityError(
            "rail_delay_state_invalid",
            "timetable manager realtime_delays must be a dict",
        )
    raw_delay = delays.get(train_number, 0)
    if not isinstance(raw_delay, (int, float)):
        raise TrainRouteIdentityError(
            "rail_delay_value_invalid",
            f"train delay must be numeric: train={train_number}, delay={raw_delay!r}",
        )
    delay_minutes = float(raw_delay) / 60.0

    status_text = getattr(timetable_manager, "train_status_text", None)
    if not isinstance(status_text, dict):
        raise TrainRouteIdentityError(
            "rail_status_state_invalid",
            "timetable manager train_status_text must be a dict",
        )
    if delay_minutes == 0:
        railway_id = _railway_id_from_station_id(station_id)
        if railway_id is not None and "遅延" in str(status_text.get(railway_id, "")):
            delay_minutes = 10.0
    return scheduled_minute + delay_minutes


def _railway_id_from_station_id(station_id: str) -> str | None:
    if "Toei." not in station_id:
        return None
    parts = station_id.split(".")
    if len(parts) < 2:
        return None
    return f"odpt.Railway:Toei.{parts[1]}"


def _dedupe_train_records(records: list[Any]) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, dict):
            raise TrainRouteIdentityError(
                "rail_odpt_record_invalid",
                f"ODPT train timetable record must be an object: {raw!r}",
            )
        key = (
            raw.get("dep"),
            raw.get("arr"),
            raw.get("next_sta"),
            raw.get("train_num"),
        )
        unique[key] = raw
    return list(unique.values())


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise TrainRouteIdentityError(
            "rail_identity_text_missing",
            f"{label} must be a string: {value!r}",
        )
    normalized = value.strip()
    if not normalized:
        raise TrainRouteIdentityError(
            "rail_identity_text_missing",
            f"{label} must not be empty",
        )
    return normalized


def _required_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrainRouteIdentityError(
            "rail_identity_number_missing",
            f"{label} must be numeric: {value!r}",
        )
    integer = int(value)
    if integer != value:
        raise TrainRouteIdentityError(
            "rail_identity_number_invalid",
            f"{label} must be an integer minute: {value!r}",
        )
    return integer


def _clock_to_minute(value: str, *, label: str) -> int:
    parts = value.strip().split(":")
    if len(parts) < 2:
        raise TrainRouteIdentityError(
            "rail_identity_clock_invalid",
            f"{label} is invalid: {value!r}",
        )
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as error:
        raise TrainRouteIdentityError(
            "rail_identity_clock_invalid",
            f"{label} is invalid: {value!r}",
        ) from error
    if hour < 0 or minute < 0 or minute >= 60:
        raise TrainRouteIdentityError(
            "rail_identity_clock_invalid",
            f"{label} is invalid: {value!r}",
        )
    return hour * 60 + minute
