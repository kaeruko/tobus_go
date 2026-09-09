from __future__ import annotations

from typing import Any

from app.services import train_route_identity_legacy as _legacy

# Re-export the existing implementation. The resolver below is intentionally
# replaced so route identity only inspects trains that can actually arrive at
# the route's stated arrival time. This prevents unrelated late-night trains
# (for example 2302A at 23:10) from poisoning a 16:xx route candidate.
TrainRouteIdentityError = _legacy.TrainRouteIdentityError
route_result_has_rail = _legacy.route_result_has_rail
enrich_route_result_train_trip_ids = _legacy.enrich_route_result_train_trip_ids


def _resolve_odpt_rail_run(
    stops: list[dict[str, str]],
    *,
    ready_minute: int,
    route_arrival_minute: int,
    timetable_manager: Any,
    day_type: Any,
):
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

    # A route that arrives after midnight has a smaller wall-clock minute than
    # its departure. Compare on a service-day axis in that one explicit case.
    arrival_limit = route_arrival_minute
    if arrival_limit < ready_minute:
        arrival_limit += 24 * 60

    eligible: list[tuple[float, str]] = []
    seen_train_numbers: set[str] = set()
    for record in _legacy._dedupe_train_records(first_records):
        if record.get("next_sta") != second_id:
            continue
        train_number = _legacy._required_text(record.get("train_num"), "train_num")
        scheduled_departure = _legacy._required_int(record.get("dep"), "dep")
        actual_departure = _legacy._actual_train_minute(
            timetable_manager,
            origin_id,
            train_number,
            scheduled_departure,
        )
        comparison_departure = actual_departure
        if arrival_limit >= 24 * 60 and comparison_departure < ready_minute:
            comparison_departure += 24 * 60
        if comparison_departure < ready_minute:
            continue
        # A train departing after the route's stated arrival cannot be the
        # train represented by this route step. Do not inspect it at all.
        if comparison_departure > arrival_limit:
            continue
        if train_number in seen_train_numbers:
            continue
        seen_train_numbers.add(train_number)
        eligible.append((comparison_departure, train_number))

    if not eligible:
        raise TrainRouteIdentityError(
            "rail_odpt_run_not_found",
            f"no ODPT train can serve {origin_id}->{second_id} between "
            f"{ready_minute} and route arrival {route_arrival_minute}",
        )

    eligible.sort(key=lambda item: (item[0], item[1]))
    complete_runs: list[tuple[int, Any]] = []
    incomplete_errors: list[TrainRouteIdentityError] = []
    for _, train_number in eligible:
        try:
            run, actual_arrival = _legacy._resolve_odpt_run_for_train(
                stops,
                train_number=train_number,
                ready_minute=ready_minute,
                target=target,
                timetable_manager=timetable_manager,
            )
        except TrainRouteIdentityError as error:
            if error.code == "rail_odpt_run_segment_missing":
                incomplete_errors.append(error)
                continue
            raise
        complete_runs.append((int(actual_arrival), run))

    if not complete_runs:
        if len(eligible) == 1 and len(incomplete_errors) == 1:
            raise incomplete_errors[0]
        raise TrainRouteIdentityError(
            "rail_odpt_run_not_found",
            "no single ODPT train covers the complete route stop sequence: "
            f"stops={[stop['id'] for stop in stops]}, "
            f"eligible={[train_number for _, train_number in eligible]}",
        )

    matching = [
        run
        for actual_arrival, run in complete_runs
        if actual_arrival == route_arrival_minute
    ]
    if not matching:
        resolved_arrivals = [
            f"{run.train_number}:{actual_arrival}"
            for actual_arrival, run in complete_runs
        ]
        raise TrainRouteIdentityError(
            "rail_route_arrival_mismatch",
            "no complete ODPT train run matches the route rail arrival: "
            f"route={route_arrival_minute}, candidates={resolved_arrivals}",
        )
    if len(matching) != 1:
        raise TrainRouteIdentityError(
            "rail_odpt_run_ambiguous",
            "multiple complete ODPT trains match the route rail arrival: "
            f"route={route_arrival_minute}, "
            f"trains={[run.train_number for run in matching]}",
        )
    return matching[0]


# enrich_route_result_train_trip_ids is defined in the legacy module, so its
# global lookup must point at the corrected resolver.
_legacy._resolve_odpt_rail_run = _resolve_odpt_rail_run
