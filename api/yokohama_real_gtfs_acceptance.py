"""Strict, read-only acceptance checks for a *reviewed* Yokohama bus/subway journey.

This is a same-GTFS source consistency check, not independent confirmation of
operator timetables, transfer accessibility, official walking distances or
GTFS redistribution permission. No proximity-mode fallback is permitted.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fare_policy import decorate_route_result_with_fare
from route_engine import (
    GeoPoint, RoutePreference, RouteSearchRequest, serialize_route_result,
)
from route_fare_scope import search_with_fare_scope
from yokohama_municipal_backend import YokohamaMunicipalRouteBackend
from yokohama_municipal_transfer import ExplicitTransferLink

PASS_IDS = ("yokohama_welfare_special_pass", "yokohama_senior_special_pass")


def _time_minutes(value: object, field: str) -> int:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise AssertionError(f"{field} must be HH:MM, got {value!r}")
    hours, minutes = value[:2], value[3:]
    if not hours.isascii() or not minutes.isascii() or not (
        hours.isdigit() and minutes.isdigit()
    ):
        raise AssertionError(f"{field} must have ASCII digits: {value!r}")
    hh, mm = int(hours), int(minutes)
    if not 0 <= hh <= 23 or not 0 <= mm <= 59:
        raise AssertionError(f"{field} outside same-day clock range: {value!r}")
    return hh * 60 + mm


def _verify_ride(step: dict[str, Any], coverage, day: date) -> tuple[int, int]:
    dataset = coverage.dataset
    kind = step.get("kind")
    trip_id, route_id = step.get("trip_id"), step.get("route_id")
    trip = dataset.trips.get(trip_id) if isinstance(trip_id, str) else None
    if trip is None or trip.route_id != route_id:
        raise AssertionError(f"{kind} references unknown/mismatched trip {trip_id!r}")
    if trip.service_id not in dataset.active_service_ids(day):
        raise AssertionError(f"{kind} trip not active on {day.isoformat()}: {trip_id}")
    if route_id not in dataset.routes or dataset.routes[route_id].mode.value != kind:
        raise AssertionError(f"incorrect mode/route identity: {route_id!r}, {kind!r}")
    if step.get("fare_context") != coverage.context_for_step(step):
        raise AssertionError(f"fare context mismatch for trip {trip_id!r}")
    from_id, to_id = step.get("departureStopId"), step.get("arrivalPoleId")
    depart = _time_minutes(step.get("departure_time"), "ride departure")
    arrive = _time_minutes(step.get("arrival_time"), "ride arrival")
    times = [r for r in dataset.stop_times if r.trip_id == trip_id]
    departures = [
        r for r in times
        if r.stop_id == from_id and r.departure_minute == depart
    ]
    arrivals = [
        r for r in times
        if r.stop_id == to_id and r.arrival_minute == arrive
    ]
    if not any(a.sequence < b.sequence for a in departures for b in arrivals):
        raise AssertionError(
            f"ride disagrees with GTFS stop sequence/times: trip={trip_id!r}, "
            f"from={from_id!r} at {depart}, to={to_id!r} at {arrive}"
        )
    if depart >= arrive:
        raise AssertionError(f"nonpositive timetable ride: {trip_id!r}")
    return depart, arrive


def validate_reviewed_candidate(
    candidate: dict[str, Any], *,
    bus_coverage, subway_coverage,
    transfer: ExplicitTransferLink, policy_id: str,
    direction: str, service_date: date, earliest_departure_minute: int,
) -> dict[str, Any]:
    """Verify fare, exact reviewed handoff, and every timed ride against GTFS."""
    if policy_id not in PASS_IDS:
        raise ValueError(f"unsupported Yokohama pass scope: {policy_id!r}")
    if direction not in {"bus_to_rail", "rail_to_bus"}:
        raise ValueError(f"unsupported municipal direction: {direction!r}")
    fare = candidate.get("fare")
    if not isinstance(fare, dict) or any((
        fare.get("policyId") != policy_id,
        fare.get("settlementType") != "free_pass",
        fare.get("status") != "available",
        type(fare.get("payNowYen")) is not int or fare["payNowYen"] != 0,
        type(fare.get("effectiveFareYen")) is not int or fare["effectiveFareYen"] != 0,
    )):
        raise AssertionError(f"fare not verified 0 yen for {policy_id}: {fare!r}")
    steps = candidate.get("steps")
    if not isinstance(steps, list):
        raise AssertionError("route steps are not a list")
    rides = [s for s in steps if s.get("kind") in {"bus", "rail"}]
    if len(rides) < 2:
        raise AssertionError("expected bus and subway ride steps")
    modes = [s["kind"] for s in rides]
    expected = ("bus", "rail") if direction == "bus_to_rail" else ("rail", "bus")
    if modes[0] != expected[0] or modes[-1] != expected[1] or sum(
        modes[i] != modes[i - 1] for i in range(1, len(modes))
    ) != 1:
        raise AssertionError(f"unexpected feed transition: {modes!r}")
    handoffs = [
        s for s in steps
        if s.get("kind") == "walk" and s.get("walking_connection_verified") is True
    ]
    if len(handoffs) != 1:
        raise AssertionError(f"expected exactly one verified walk, got {len(handoffs)}")
    handoff = handoffs[0]
    expected_from, expected_to = (
        (transfer.bus_stop_id, transfer.subway_stop_id)
        if direction == "bus_to_rail"
        else (transfer.subway_stop_id, transfer.bus_stop_id)
    )
    if any((
        handoff.get("departureStopId") != expected_from,
        handoff.get("arrivalPoleId") != expected_to,
        handoff.get("meters") != transfer.walk_meters,
        handoff.get("minutes") != transfer.walk_minutes,
        handoff.get("evidence_url") != transfer.official_evidence_url,
        "distance_basis" in handoff,
    )):
        raise AssertionError("walking handoff differs from reviewed, version-locked link")
    expected_ride_data = []
    coverage_by_mode = {"bus": bus_coverage, "rail": subway_coverage}
    for step in rides:
        depart, arrive = _verify_ride(step, coverage_by_mode[step["kind"]], service_date)
        expected_ride_data.append((depart, arrive))
    if expected_ride_data[0][0] < earliest_departure_minute:
        raise AssertionError("candidate boards before requested departure")
    transition = modes.index(expected[1])
    if expected_ride_data[transition - 1][1] + transfer.walk_minutes > expected_ride_data[transition][0]:
        raise AssertionError("insufficient time to walk to the second vehicle")
    for left, right in zip(expected_ride_data, expected_ride_data[1:]):
        if left[1] > right[0]:
            raise AssertionError("rides overlap in time")
    if candidate.get("arrival_time") is None:
        raise AssertionError("candidate arrival_time is missing")
    final_arrival = _time_minutes(candidate["arrival_time"], "route arrival")
    if final_arrival < expected_ride_data[-1][1]:
        raise AssertionError("arrival clock before final ride finishes")
    return {
        "candidate_id": candidate["id"],
        "policy_id": policy_id,
        "trip_ids": [s["trip_id"] for s in rides],
        "ride_modes": modes,
        "verified_bus_stop_id": transfer.bus_stop_id,
        "verified_subway_stop_id": transfer.subway_stop_id,
        "walk_meters": transfer.walk_meters,
        "walk_minutes": transfer.walk_minutes,
        "arrival_time": candidate["arrival_time"],
        "additional_payment_yen": 0,
    }


def check_real_municipal_od(
    *, bus_coverage, subway_coverage,
    transfer_links: tuple[ExplicitTransferLink, ...],
    bus_transfer_stop_id: str, subway_transfer_stop_id: str,
    origin_stop_id: str, destination_stop_id: str,
    departure: datetime,
) -> dict[str, Any]:
    """Probe ONE explicit OD and transfer pair for both pass policies."""
    if departure.tzinfo is None or departure.utcoffset() is None:
        raise ValueError("departure must be timezone-aware")
    if departure.utcoffset().total_seconds() != 9 * 3600:
        raise ValueError("departure must be in JST (+09:00)")
    if departure.second or departure.microsecond:
        raise ValueError("departure must have minute precision")
    pair = [
        x for x in transfer_links
        if x.bus_stop_id == bus_transfer_stop_id
        and x.subway_stop_id == subway_transfer_stop_id
    ]
    if len(pair) != 1:
        raise ValueError("requested transfer must exist exactly once in reviewed links")
    link = pair[0]
    bus = bus_coverage.dataset
    subway = subway_coverage.dataset
    stops = {**bus.stops, **subway.stops}
    if len(stops) != len(bus.stops) + len(subway.stops):
        raise AssertionError("bus and subway stop ID namespaces overlap")
    if origin_stop_id not in stops or destination_stop_id not in stops:
        raise ValueError("OD stops must be exact feed-namespaced GTFS stop IDs")
    if origin_stop_id.startswith("yokohama_bus:") and destination_stop_id.startswith("yokohama_subway:"):
        direction = "bus_to_rail"
    elif origin_stop_id.startswith("yokohama_subway:") and destination_stop_id.startswith("yokohama_bus:"):
        direction = "rail_to_bus"
    else:
        raise ValueError("OD must cross the bus/subway feed boundary")
    backend = YokohamaMunicipalRouteBackend(
        bus_coverage, subway_coverage, transfer_links=transfer_links,
        estimated_transfer_mode=False,
    )
    results = []
    request = RouteSearchRequest(
        origin=GeoPoint(stops[origin_stop_id].lat, stops[origin_stop_id].lon),
        destination=GeoPoint(stops[destination_stop_id].lat, stops[destination_stop_id].lon),
        departure_at=departure,
        preference=RoutePreference.FASTEST,
        limit=20,
    )
    for policy_id in PASS_IDS:
        result = search_with_fare_scope(backend, request, policy_id)
        payload = serialize_route_result(result)
        decorate_route_result_with_fare(
            city_key="yokohama", result=payload, policy_id=policy_id,
        )
        meta = payload.get("meta", {})
        if (meta.get("walking_transfer_basis") != "reviewed_links_only"
                or meta.get("unverified_walking_transfers_excluded") is not True):
            raise AssertionError("public search unexpectedly enabled estimated transfers")
        expected_from, expected_to = (
            (link.bus_stop_id, link.subway_stop_id)
            if direction == "bus_to_rail"
            else (link.subway_stop_id, link.bus_stop_id)
        )
        matched = [
            c for c in payload["candidates"]
            if any(s.get("kind") == "walk"
                   and s.get("walking_connection_verified") is True
                   and s.get("departureStopId") == expected_from
                   and s.get("arrivalPoleId") == expected_to
                   for s in c.get("steps", ()))
        ]
        if not matched:
            raise AssertionError(
                f"{policy_id} returned no reviewed {direction} transfer for "
                f"{origin_stop_id!r} -> {destination_stop_id!r} at "
                f"{departure.isoformat()}; returned {len(payload['candidates'])} candidates"
            )
        results.append(validate_reviewed_candidate(
            matched[0],
            bus_coverage=bus_coverage, subway_coverage=subway_coverage,
            transfer=link, policy_id=policy_id,
            direction=direction, service_date=departure.date(),
            earliest_departure_minute=departure.hour * 60 + departure.minute,
        ))
    return {
        "status": "PASS_same_feed_source_consistency_only",
        "bus_feed_version": bus.metadata.version,
        "subway_feed_version": subway.metadata.version,
        "date": departure.date().isoformat(),
        "requested_departure": departure.strftime("%H:%M"),
        "origin_stop_id": origin_stop_id,
        "destination_stop_id": destination_stop_id,
        "direction": direction,
        "policies": results,
        "limitations": [
            "This checks returned trips against the SAME installed GTFS, not an independent timetable.",
            "The reviewed-link file is a human assertion, not independent proof of a safe pedestrian path.",
            "Official platform/entrance correspondence, walking distance and accessibility require separate evidence.",
            "ODPT licensing and permission to redistribute GTFS are NOT proven.",
        ],
    }
