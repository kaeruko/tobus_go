import os
import httpx
import uuid
import asyncio
import datetime
from zoneinfo import ZoneInfo
from app.services.bus_stop_experience import build_route_experiences
from app.services.bus_location_matcher import (
    BusLocationMatchError,
    select_bus_candidate,
)
from app.services.route_step_ids import assign_candidate_step_ids
from app.route_endpoint import register_route_endpoint
from route_engine import normalize_route_preference
from gtfs_loader import gtfs_repo
from tokyo_route_engine import TokyoRouteDependencies, TokyoRouteEngine

from fastapi import HTTPException, Form, Query, Body, BackgroundTasks
from fastapi.responses import Response
import time
from typing import Optional
import json
import logging

logger = logging.getLogger(__name__)

def _busloc_log(ev: dict) -> None:
    print(json.dumps(ev, ensure_ascii=False), flush=True)


def _busloc_candidate_diagnostic(bus: dict) -> dict:
    return {
        "vehicle_id": bus.get("vehicle_id"),
        "route_id": bus.get("odpt:busroute"),
        "trip_id": bus.get("trip_id"),
        "raw_stop_id": bus.get("raw_stop_id"),
        "raw_stop_name": bus.get("raw_stop_name"),
        "from_stop_id": bus.get("odpt:fromBusstopPole"),
        "from_stop_sequence": bus.get("from_stop_sequence"),
        "observed_stop_sequence": bus.get("observed_stop_sequence"),
        "current_status": bus.get("current_status"),
        "feed_timestamp": bus.get("feed_timestamp"),
        "vehicle_timestamp": bus.get("vehicle_timestamp"),
    }


def _busloc_match_diagnostic(
    candidates: list[dict],
    *,
    route_id: str,
    trip_id: str,
    vehicle_id: str | None,
) -> dict:
    route_matches = [
        bus for bus in candidates if bus.get("odpt:busroute") == route_id
    ]
    trip_matches = [
        bus for bus in candidates if bus.get("trip_id") == trip_id
    ]
    vehicle_matches = (
        [
            bus for bus in candidates
            if bus.get("vehicle_id") == vehicle_id
        ]
        if vehicle_id is not None
        else []
    )
    return {
        "candidates_total": len(candidates),
        "route_match_count": len(route_matches),
        "route_trip_match_count": len([
            bus for bus in route_matches if bus.get("trip_id") == trip_id
        ]),
        "requested_vehicle_id": vehicle_id,
        "requested_vehicle_matches": [
            _busloc_candidate_diagnostic(bus) for bus in vehicle_matches
        ],
        "requested_trip_matches": [
            _busloc_candidate_diagnostic(bus) for bus in trip_matches
        ],
    }



_BUS_REALTIME_LEAD_MINUTES = 5


def _bus_realtime_schedule_window(
    *,
    route_id: str,
    trip_id: str,
    boarding_stop_id: str | None,
    scheduled_departure_at: str | None,
) -> dict | None:
    if (boarding_stop_id is None) != (scheduled_departure_at is None):
        raise HTTPException(
            400,
            detail={
                "code": "bus_realtime_schedule_context_incomplete",
                "message": (
                    "boarding_stop_id and scheduled_departure_at must be "
                    "specified together"
                ),
            },
        )
    if boarding_stop_id is None:
        return None

    trip = gtfs_repo.trips.get(trip_id)
    if trip is None:
        raise HTTPException(
            400,
            detail={
                "code": "bus_realtime_static_trip_unknown",
                "message": f"Static GTFS does not contain trip {trip_id}",
            },
        )
    static_route_id = trip.get("route_id")
    if static_route_id != route_id:
        raise HTTPException(
            400,
            detail={
                "code": "bus_realtime_static_route_mismatch",
                "message": (
                    f"Static GTFS trip {trip_id} belongs to route "
                    f"{static_route_id}, not {route_id}"
                ),
            },
        )

    try:
        scheduled = datetime.datetime.fromisoformat(scheduled_departure_at)
    except ValueError as exc:
        raise HTTPException(
            400,
            detail={
                "code": "bus_realtime_departure_time_invalid",
                "message": "scheduled_departure_at must be ISO-8601",
            },
        ) from exc
    if scheduled.tzinfo is None or scheduled.utcoffset() is None:
        raise HTTPException(
            400,
            detail={
                "code": "bus_realtime_departure_timezone_missing",
                "message": "scheduled_departure_at must include a timezone offset",
            },
        )
    if scheduled.second != 0 or scheduled.microsecond != 0:
        raise HTTPException(
            400,
            detail={
                "code": "bus_realtime_departure_precision_invalid",
                "message": "scheduled_departure_at must use minute precision",
            },
        )

    tokyo_tz = ZoneInfo("Asia/Tokyo")
    scheduled_tokyo = scheduled.astimezone(tokyo_tz)
    scheduled_clock_minute = scheduled_tokyo.hour * 60 + scheduled_tokyo.minute

    stops_by_sequence = gtfs_repo.stop_times.get(trip_id)
    if not stops_by_sequence:
        raise RuntimeError(f"GTFS trip has no stop_times: trip_id={trip_id!r}")

    stop_matches = [
        (sequence, stop_time)
        for sequence, stop_time in stops_by_sequence.items()
        if stop_time[0] == boarding_stop_id
        and stop_time[2] % (24 * 60) == scheduled_clock_minute
    ]
    if not stop_matches:
        raise HTTPException(
            409,
            detail={
                "code": "bus_realtime_boarding_schedule_mismatch",
                "message": (
                    "boarding_stop_id and scheduled_departure_at do not match "
                    "the static GTFS trip"
                ),
                "trip_id": trip_id,
                "boarding_stop_id": boarding_stop_id,
                "scheduled_departure_at": scheduled_departure_at,
            },
        )
    if len(stop_matches) != 1:
        raise HTTPException(
            409,
            detail={
                "code": "bus_realtime_boarding_schedule_ambiguous",
                "message": (
                    "Static GTFS contains multiple matching boarding events "
                    "for this trip"
                ),
                "trip_id": trip_id,
                "boarding_stop_id": boarding_stop_id,
                "scheduled_departure_at": scheduled_departure_at,
            },
        )

    boarding_sequence, boarding_stop_time = stop_matches[0]
    boarding_departure_minute = boarding_stop_time[2]
    first_sequence = min(stops_by_sequence)
    first_departure_minute = stops_by_sequence[first_sequence][2]
    check_start_minute = max(
        first_departure_minute,
        boarding_departure_minute - _BUS_REALTIME_LEAD_MINUTES,
    )
    if check_start_minute > boarding_departure_minute:
        raise RuntimeError(
            "GTFS realtime check window is inverted: "
            f"trip_id={trip_id!r} first_departure={first_departure_minute} "
            f"boarding_departure={boarding_departure_minute}"
        )

    check_start_at = scheduled_tokyo - datetime.timedelta(
        minutes=boarding_departure_minute - check_start_minute
    )
    return {
        "boarding_stop_id": boarding_stop_id,
        "boarding_stop_sequence": boarding_sequence,
        "scheduled_departure_at": scheduled_tokyo.isoformat(),
        "realtime_check_start_at": check_start_at.isoformat(),
        "check_start_at": check_start_at,
    }


from toei_engine import (
    nearest_phys,
    haversine,
    get_virtual_connections,
    search_best_routes_once,
    time_str_to_min,
    min_to_time_str,
    get_reachable_stops,
    _rss_mb,
    determine_day_type,
    _gtfs_stop_id,
)

ROUTE_JOBS: dict[str, dict] = {}
_ROUTE_LOCK = asyncio.Lock()

# 簡易TTLキャッシュ
_sv_cache: dict[str, tuple[float, bytes]] = {}
SV_CACHE_TTL_SEC = 60 * 60  # 1時間

ODPT_API_URL = "https://api-public.odpt.org/api/v4"
ODPT_API_KEY = os.getenv("ODPT_API_KEY")

def _cache_get(key: str) -> Optional[bytes]:
    hit = _sv_cache.get(key)
    if not hit:
        return None
    expires_at, data = hit
    if time.time() >= expires_at:
        _sv_cache.pop(key, None)
        return None
    return data

def _cache_set(key: str, data: bytes) -> None:
    _sv_cache[key] = (time.time() + SV_CACHE_TTL_SEC, data)





def normalize_pref(pref: str | None) -> str:
    return normalize_route_preference(pref).api_value

def compute_route_candidates(app, alat, alon, blat, blon, pref, start_time="10:00", date_str=None):
    """Compatibility wrapper; new endpoint traffic uses app.state.route_engine."""

    engine = TokyoRouteEngine(
        app,
        dependencies=TokyoRouteDependencies(
            nearest_phys=nearest_phys,
            haversine=haversine,
            get_virtual_connections=get_virtual_connections,
            search_best_routes_once=search_best_routes_once,
            time_str_to_min=time_str_to_min,
            min_to_time_str=min_to_time_str,
            determine_day_type=determine_day_type,
            assign_candidate_step_ids=assign_candidate_step_ids,
            rss_mb=_rss_mb,
        ),
    )
    return engine.search_legacy(
        alat=alat,
        alon=alon,
        blat=blat,
        blon=blon,
        pref=normalize_pref(pref),
        start_time=start_time,
        date_str=date_str,
    )

async def _fetch_and_update_realtime(app_state):
    tm = app_state.TM
    if not tm: return

    params = {
        "acl:consumerKey": ODPT_API_KEY,
        "odpt:operator": "odpt.Operator:Toei"
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Bus Realtime
        try:
            r_bus = await client.get(f"{ODPT_API_URL}/odpt:Bus", params=params)
            if r_bus.status_code == 200:
                tm.update_bus_realtime(r_bus.json())
                print(f"[INFO] Updated Bus realtime data. {len(tm.bus_realtime_delays)} routes delayed.")
        except Exception as e:
            print(f"[WARN] Failed to update bus realtime: {e}")

        # 2. Train Info Text
        try:
            r_train = await client.get(f"{ODPT_API_URL}/odpt:TrainInformation", params=params)
            if r_train.status_code == 200:
                tm.update_train_info_text(r_train.json())
                print(f"[INFO] Updated Train info text. Suspended: {tm.train_service_suspended}")
        except Exception as e:
            print(f"[WARN] Failed to update train info: {e}")

def _required_bus_stop_english_name_from_graph(
    graph,
    *,
    gtfs_stop_id: str,
) -> str:
    matches: list[tuple[str, str]] = []
    for node, attributes in graph.nodes(data=True):
        if not (
            isinstance(node, tuple)
            and len(node) >= 2
            and node[0] == "phys"
            and isinstance(node[1], str)
        ):
            continue
        if _gtfs_stop_id(node[1]) != gtfs_stop_id:
            continue

        english_name = attributes.get("name_en")
        if not isinstance(english_name, str) or not english_name.strip():
            raise RuntimeError(
                "ODPT bus stop is missing official English name: "
                f"stop_id={gtfs_stop_id!r} odpt_id={node[1]!r}"
            )
        matches.append((node[1], english_name.strip()))

    if not matches:
        raise RuntimeError(
            "GTFS bus stop has no English translation and no exact ODPT pole ID match: "
            f"stop_id={gtfs_stop_id!r}"
        )

    english_names = {english_name for _, english_name in matches}
    if len(english_names) != 1:
        raise RuntimeError(
            "Exact ODPT pole ID matches disagree on official English name: "
            f"stop_id={gtfs_stop_id!r} matches={matches!r}"
        )
    return next(iter(english_names))


def _gtfs_bus_stop_cluster_ids(pole_id: str) -> list[str]:
    match = re.fullmatch(r"(\d{4})-(\d{2})", pole_id)
    if match is None:
        raise RuntimeError(
            "GTFS bus stop_id cannot be clustered by pole ID: "
            f"pole_id={pole_id!r}"
        )
    cluster_prefix = f"{match.group(1)}-"
    cluster_ids = sorted(
        stop_id
        for stop_id in gtfs_repo.stops
        if stop_id.startswith(cluster_prefix)
    )
    if pole_id not in cluster_ids:
        raise RuntimeError(
            "GTFS bus stop cluster does not contain the requested pole: "
            f"pole_id={pole_id!r} cluster_ids={cluster_ids!r}"
        )
    return cluster_ids


def _gtfs_bus_timetable_destinations(
    *,
    route_id: str,
    pole_id: str,
    target_pole_id: str | None,
    pattern_trip_id: str | None = None,
    preferred_pattern_trip_id: str | None = None,
    include_stop_cluster: bool = False,
    day_type=None,
    current_minute: int,
    limit: int,
    include_all: bool,
    delay_min: float,
    graph=None,
) -> list[dict]:
    if include_stop_cluster and target_pole_id is not None:
        raise RuntimeError(
            "include_stop_cluster cannot be combined with target_pole_id"
        )
    if include_stop_cluster and pattern_trip_id is not None:
        raise RuntimeError(
            "include_stop_cluster cannot be combined with pattern_trip_id"
        )

    source_pole_ids = (
        _gtfs_bus_stop_cluster_ids(pole_id)
        if include_stop_cluster
        else [pole_id]
    )
    schedule = []
    for source_pole_id in source_pole_ids:
        for departure_minute, origin_sequence, trip_id in (
            gtfs_repo.timetable_index.get(
                f"{route_id}|{source_pole_id}"
            )
            or []
        ):
            schedule.append(
                (
                    departure_minute,
                    origin_sequence,
                    trip_id,
                    source_pole_id,
                )
            )
    schedule.sort(key=lambda item: (item[0], item[2], item[1], item[3]))

    active_services = (
        day_type.active_service_ids
        if getattr(day_type, "has_gtfs_calendar", False)
        else None
    )
    effective_search_minute = current_minute - delay_min

    preferred_destination_stop_id: str | None = None
    if preferred_pattern_trip_id is not None:
        preferred_trip = gtfs_repo.trips.get(preferred_pattern_trip_id)
        if preferred_trip is None:
            raise RuntimeError(
                "GTFS timetable preferred pattern trip is missing: "
                f"trip_id={preferred_pattern_trip_id!r}"
            )
        if preferred_trip.get("route_id") != route_id:
            raise RuntimeError(
                "GTFS timetable preferred pattern trip route mismatch: "
                f"trip_id={preferred_pattern_trip_id!r} "
                f"expected_route_id={route_id!r} "
                f"actual_route_id={preferred_trip.get('route_id')!r}"
            )
        preferred_stop_times = gtfs_repo.stop_times.get(
            preferred_pattern_trip_id
        )
        if not preferred_stop_times:
            raise RuntimeError(
                "GTFS timetable preferred pattern trip has no stop_times: "
                f"trip_id={preferred_pattern_trip_id!r}"
            )
        _, preferred_final_stop_time = max(preferred_stop_times.items())
        preferred_destination_stop_id = preferred_final_stop_time[0]

    required_stop_signature: tuple[str, ...] | None = None
    if pattern_trip_id is not None:
        pattern_trip = gtfs_repo.trips.get(pattern_trip_id)
        if pattern_trip is None:
            raise RuntimeError(
                "GTFS timetable pattern trip is missing: "
                f"trip_id={pattern_trip_id!r}"
            )
        if pattern_trip.get("route_id") != route_id:
            raise RuntimeError(
                "GTFS timetable pattern trip route mismatch: "
                f"trip_id={pattern_trip_id!r} expected_route_id={route_id!r} "
                f"actual_route_id={pattern_trip.get('route_id')!r}"
            )
        pattern_stop_times = gtfs_repo.stop_times.get(pattern_trip_id)
        if not pattern_stop_times:
            raise RuntimeError(
                "GTFS timetable pattern trip has no stop_times: "
                f"trip_id={pattern_trip_id!r}"
            )
        origin_sequences = [
            sequence
            for sequence, stop_time in sorted(pattern_stop_times.items())
            if stop_time[0] == pole_id
        ]
        if len(origin_sequences) != 1:
            raise RuntimeError(
                "GTFS timetable pattern trip must contain the boarding stop "
                "exactly once: "
                f"trip_id={pattern_trip_id!r} pole_id={pole_id!r} "
                f"occurrences={origin_sequences!r}"
            )
        origin_sequence = origin_sequences[0]
        required_stop_signature = tuple(
            stop_time[0]
            for sequence, stop_time in sorted(pattern_stop_times.items())
            if sequence >= origin_sequence
        )

    upcoming_by_destination: dict[str, list[str]] = {}
    all_by_destination: dict[str, list[str]] = {}

    for departure_minute, origin_sequence, trip_id, source_pole_id in schedule:
        trip = gtfs_repo.trips.get(trip_id)
        if trip is None:
            raise RuntimeError(
                f"GTFS timetable references unknown trip_id={trip_id!r}"
            )
        if active_services is not None:
            service_id = trip.get("service_id")
            if service_id not in active_services:
                continue

        if target_pole_id:
            target_time = gtfs_repo.get_trip_stop_time_after(
                trip_id,
                target_pole_id,
                after_sequence=origin_sequence,
            )
            if target_time is None:
                continue

        stops_by_sequence = gtfs_repo.stop_times.get(trip_id)
        if not stops_by_sequence:
            raise RuntimeError(
                f"GTFS trip has no stop_times: trip_id={trip_id!r}"
            )
        if required_stop_signature is not None:
            candidate_stop_signature = tuple(
                stop_time[0]
                for sequence, stop_time in sorted(stops_by_sequence.items())
                if sequence >= origin_sequence
            )
            if candidate_stop_signature != required_stop_signature:
                continue
        _, final_stop_time = max(stops_by_sequence.items())
        destination_stop_id = final_stop_time[0]
        if destination_stop_id not in gtfs_repo.stops:
            raise RuntimeError(
                "GTFS trip destination is missing from stops: "
                f"trip_id={trip_id!r} stop_id={destination_stop_id!r}"
            )

        departure_text = min_to_time_str(departure_minute)
        if include_all:
            all_by_destination.setdefault(destination_stop_id, []).append(
                departure_text
            )

        if departure_minute >= effective_search_minute:
            upcoming = upcoming_by_destination.setdefault(
                destination_stop_id,
                [],
            )
            if len(upcoming) < max(1, limit):
                upcoming.append(departure_text)

    destination_ids = list(upcoming_by_destination)
    for destination_stop_id in all_by_destination:
        if destination_stop_id not in upcoming_by_destination:
            destination_ids.append(destination_stop_id)
    if preferred_destination_stop_id is not None:
        destination_ids.sort(
            key=lambda destination_stop_id: (
                destination_stop_id != preferred_destination_stop_id
            )
        )

    destinations = []
    for destination_stop_id in destination_ids:
        stop = gtfs_repo.stops[destination_stop_id]
        destination_name = stop.get("name")
        if not isinstance(destination_name, str) or not destination_name.strip():
            raise RuntimeError(
                "GTFS trip destination is missing a Japanese stop name: "
                f"stop_id={destination_stop_id!r}"
            )
        destination_name_en = stop.get("name_en")
        if not isinstance(destination_name_en, str) or not destination_name_en.strip():
            if graph is None:
                raise RuntimeError(
                    "GTFS trip destination is missing an English stop name and "
                    "no ODPT graph was supplied: "
                    f"stop_id={destination_stop_id!r} name={destination_name!r}"
                )
            destination_name_en = _required_bus_stop_english_name_from_graph(
                graph,
                gtfs_stop_id=destination_stop_id,
            )
        else:
            destination_name_en = destination_name_en.strip()

        destination = {
            "destination_pole_id": destination_stop_id,
            "destination_name": destination_name,
            "destination_name_en": destination_name_en,
            "times": upcoming_by_destination.get(destination_stop_id, []),
            "source_pole_ids": sorted(
                {
                    source_pole_id
                    for _, _, trip_id, source_pole_id in schedule
                    if (
                        gtfs_repo.stop_times.get(trip_id)
                        and max(gtfs_repo.stop_times[trip_id].items())[1][0]
                        == destination_stop_id
                    )
                }
            ),
        }
        if include_all:
            destination["all_times"] = all_by_destination.get(
                destination_stop_id,
                [],
            )
        destinations.append(destination)
    return destinations


def _resolve_bus_timetable_day_type(
    date: str | None,
    day_type: str | None,
):
    if date is not None and day_type is not None:
        raise HTTPException(
            400,
            detail={
                "code": "bus_timetable_day_selector_conflict",
                "message": "Specify either date or day_type, not both",
            },
        )

    if day_type is None:
        if date is not None:
            try:
                datetime.datetime.strptime(date, "%Y-%m-%d")
            except ValueError as exc:
                raise HTTPException(
                    400,
                    detail={
                        "code": "bus_timetable_date_invalid",
                        "message": "date must use YYYY-MM-DD format",
                        "date": date,
                    },
                ) from exc
        return determine_day_type(date)

    requested_day_type = day_type.strip().lower()
    supported_day_types = {"weekday", "saturday", "holiday"}
    if requested_day_type not in supported_day_types:
        raise HTTPException(
            400,
            detail={
                "code": "bus_timetable_day_type_invalid",
                "message": "day_type must be weekday, saturday, or holiday",
                "day_type": day_type,
            },
        )

    today = datetime.date.today()
    for offset in range(14):
        candidate = today + datetime.timedelta(days=offset)
        candidate_day_type = determine_day_type(candidate)
        if str(candidate_day_type) == requested_day_type:
            return candidate_day_type

    raise RuntimeError(
        "Could not resolve a representative timetable date for "
        f"day_type={requested_day_type!r}"
    )


def register_routes(app):
    register_route_endpoint(
        app,
        warmup_message=(
            "Server is warming up (loading data). Please try again in 1-2 minutes."
        ),
        lock=_ROUTE_LOCK,
    )

    @app.get("/bus/location")
    async def bus_location(
        route_id: str = Query(...),
        trip_id: str = Query(...),
        boarding_stop_id: str = Query(
            None,
            description="Static GTFS stop ID where the rider boards",
        ),
        scheduled_departure_at: str = Query(
            None,
            description="Timezone-aware ISO-8601 planned departure at boarding_stop_id",
        ),
        vehicle_id: str = Query(None, description="Optional physical bus ID to track specific vehicle"),
        force_refresh: bool = Query(
            False,
            description="Bypass the local GTFS-RT snapshot cache",
        ),
        debug: bool = Query(
            False,
            description="Include the static GTFS stop timetable for diagnostics",
        ),
    ):
        import uuid
        from datetime import datetime, timezone
        
        req_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        base = {
            "kind": "bus_location",
            "req_id": req_id,
            "now": now,
            "route_id": route_id,
            "trip_id": trip_id,
            "boarding_stop_id": boarding_stop_id,
            "scheduled_departure_at": scheduled_departure_at,
            "vehicle_id": vehicle_id,
            "force_refresh": force_refresh,
            "debug": debug,
        }

        schedule_window = _bus_realtime_schedule_window(
            route_id=route_id,
            trip_id=trip_id,
            boarding_stop_id=boarding_stop_id,
            scheduled_departure_at=scheduled_departure_at,
        )
        if schedule_window is not None:
            check_start_at = schedule_window["check_start_at"]
            current_tokyo = datetime.now(ZoneInfo("Asia/Tokyo"))
            if current_tokyo < check_start_at:
                diagnostic = {
                    key: value
                    for key, value in schedule_window.items()
                    if key != "check_start_at"
                }
                _busloc_log({
                    **base,
                    "ok": False,
                    "reason": "REALTIME_NOT_STARTED",
                    "diagnostic": diagnostic,
                })
                raise HTTPException(
                    425,
                    detail={
                        "code": "bus_realtime_not_started",
                        "message": "Realtime lookup has not started for this trip",
                        "diagnostic": diagnostic,
                    },
                )

        tm = app.state.TM
        provider = getattr(app.state, "realtime_provider", None)
        if provider is None:
            _busloc_log({**base, "ok": False, "reason": "REALTIME_PROVIDER_UNAVAILABLE"})
            raise HTTPException(
                503,
                detail={
                    "code": "bus_realtime_unavailable",
                    "message": "Realtime bus positions are not available",
                    "diagnostic": "Tokyo RealtimeProvider is not initialized",
                },
            )
        try:
            candidates_all = list(
                await provider.vehicle_positions(force_refresh=force_refresh)
            )
        except RuntimeError as error:
            _busloc_log({
                **base,
                "ok": False,
                "reason": "REALTIME_UNAVAILABLE",
                "diagnostic": str(error),
            })
            raise HTTPException(
                503,
                detail={
                    "code": "bus_realtime_unavailable",
                    "message": "Realtime bus positions are not available",
                    "diagnostic": str(error),
                },
            ) from error
        if not candidates_all:
            _busloc_log({**base, "ok": False, "reason": "REALTIME_UNAVAILABLE"})
            raise HTTPException(
                503,
                detail={
                    "code": "bus_realtime_unavailable",
                    "message": "Realtime bus positions are not available",
                },
            )

        base["candidates_total"] = len(candidates_all)

        candidates_route = [
            bus for bus in candidates_all
            if bus.get("odpt:busroute") == route_id
        ]
        base["route_match_count"] = len(candidates_route)
        base["trip_match_count"] = len([
            bus for bus in candidates_route if bus.get("trip_id") == trip_id
        ])
        try:
            target_bus = select_bus_candidate(
                candidates_all,
                route_id=route_id,
                trip_id=trip_id,
                vehicle_id=vehicle_id,
            )
        except BusLocationMatchError as exc:
            diagnostic = _busloc_match_diagnostic(
                candidates_all,
                route_id=route_id,
                trip_id=trip_id,
                vehicle_id=vehicle_id,
            )
            _busloc_log({
                **base,
                "ok": False,
                "reason": exc.code,
                "diagnostic": diagnostic,
            })
            detail = {"code": exc.code, "message": exc.message}
            if debug:
                detail["diagnostic"] = diagnostic
            raise HTTPException(
                exc.status_code,
                detail=detail,
            ) from exc

        response = {
            "odpt:bus": target_bus.get("vehicle_id"),
            "vehicle_id": target_bus.get("vehicle_id"),
            "odpt:fromBusstopPole": target_bus.get("odpt:fromBusstopPole"),
            # Use raw lat/lon from V2 engine
            "vehicle_lat": target_bus.get("lat"),
            "vehicle_lon": target_bus.get("lon"),
            "server_now": now,
            "realtime_fetched_ts": getattr(
                tm, "latest_bus_positions_fetched_at", None
            ),
            "feed_ts": target_bus.get("feed_timestamp"),
            "vehicle_ts": target_bus.get("vehicle_timestamp"),
            "raw_stop_id": target_bus.get("raw_stop_id"),
            "raw_stop_name": target_bus.get("raw_stop_name"),
            "raw_stop_name_en": target_bus.get("raw_stop_name_en"),

            # Pass through informative fields
            "next_stop": target_bus.get("next_stop"),
            "next_stop_en": target_bus.get("next_stop_en"),
            "destination": target_bus.get("destination"),
            "trip_id": target_bus.get("trip_id"),
            "trip_stop_ids": target_bus.get("trip_stop_ids", []),
            "before_first_stop": target_bus.get("before_first_stop"),
            "from_stop_sequence": target_bus.get("from_stop_sequence"),
            "observed_stop_sequence": target_bus.get("observed_stop_sequence"),
            "current_status": target_bus.get("current_status"),
        }

        response_epoch = time.time()

        def age_seconds(timestamp):
            if not isinstance(timestamp, (int, float)) or timestamp <= 0:
                return None
            return round(max(0.0, response_epoch - timestamp), 1)

        response["snapshot_age_seconds"] = age_seconds(
            response["realtime_fetched_ts"]
        )
        response["feed_age_seconds"] = age_seconds(response["feed_ts"])
        response["vehicle_age_seconds"] = age_seconds(response["vehicle_ts"])

        if debug:
            from gtfs_loader import gtfs_repo

            response["trip_stop_schedule"] = (
                gtfs_repo.get_trip_stop_schedule(trip_id)
            )
        
        _busloc_log({
            **base,
            "ok": True,
            "bus_id": target_bus.get("vehicle_id"),
            "raw_stop_id": response["raw_stop_id"],
            "raw_stop_name": response["raw_stop_name"],
            "from_stop_id": response["odpt:fromBusstopPole"],
            "observed_stop_sequence": response["observed_stop_sequence"],
            "current_status": response["current_status"],
            "snapshot_age_seconds": response["snapshot_age_seconds"],
            "feed_age_seconds": response["feed_age_seconds"],
            "vehicle_age_seconds": response["vehicle_age_seconds"],
        })
        return response

    @app.post("/realtime/update")
    async def update_realtime_data(background_tasks: BackgroundTasks):
        if not ODPT_API_KEY:
            raise HTTPException(500, "ODPT_API_KEY not configured")
        
        # Trigger update in background to return quickly
        background_tasks.add_task(_fetch_and_update_realtime, app.state)
        return {"status": "accepted"}

    @app.get("/route")
    async def route_poll(job_id: str = Query(...)):
        job = ROUTE_JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return job

    @app.get("/autocomplete")
    async def autocomplete(
        q: str = Query(...),
        lang: str = Query("ja"),
    ):
        from app.services.google_places import autocomplete_legacy_response

        return await autocomplete_legacy_response(q, language=lang)

    @app.get("/details")
    async def details(
        place_id: str = Query(...),
        lang: str = Query("ja"),
    ):
        from app.services.google_places import details_legacy_response

        return await details_legacy_response(place_id, language=lang)

    @app.get("/healthz")
    async def healthz():
        status = getattr(app.state, "loading_status", "unknown")
        return {"ok": True, "status": status}

    @app.post("/route/experience")
    async def route_experience(
        stops: list = Body(...),
    ):
        return {"groups": build_route_experiences(stops)}

    @app.get("/bus/next")
    async def bus_next(
        pole_id: str = Query(...),
        route_id: str = Query(...),
        time: str = Query(None),
        date: str = Query(None),
        day_type: str = Query(None),
        target_pole_id: str = Query(None),
        pattern_trip_id: str = Query(None),
        preferred_pattern_trip_id: str = Query(None),
        include_stop_cluster: bool = Query(False),
        limit: int = Query(5),
        include_all: bool = Query(False),
        debug: bool = Query(True),
    ):
        if getattr(app.state, "loading_status", "starting") != "ready":
             raise HTTPException(503, "Server is warming up (loading data).")

        g = app.state.G
        tm = app.state.TM
        if g is None or tm is None:
            raise HTTPException(500, "Server not ready")

        service_day_type = _resolve_bus_timetable_day_type(
            date,
            day_type,
        )

        if not time:
            now = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
            time = f"{now.hour:02d}:{now.minute:02d}"

        curr_min = time_str_to_min(time)

        uses_gtfs_route = route_id in gtfs_repo.routes
        uses_gtfs_pole = pole_id in gtfs_repo.stops
        if uses_gtfs_route != uses_gtfs_pole:
            raise HTTPException(
                400,
                detail={
                    "code": "bus_timetable_identity_mismatch",
                    "message": (
                        "route_id and pole_id must both use GTFS IDs or both use "
                        "legacy ODPT IDs"
                    ),
                    "route_id": route_id,
                    "pole_id": pole_id,
                },
            )

        if uses_gtfs_route:
            if target_pole_id and target_pole_id not in gtfs_repo.stops:
                raise HTTPException(
                    400,
                    detail={
                        "code": "bus_timetable_target_stop_unknown",
                        "message": "target_pole_id is not a GTFS stop ID",
                        "target_pole_id": target_pole_id,
                    },
                )
            pole = gtfs_repo.stops[pole_id]
            pole_name = pole.get("name")
            if not isinstance(pole_name, str) or not pole_name.strip():
                raise RuntimeError(
                    "GTFS boarding stop is missing a Japanese stop name: "
                    f"stop_id={pole_id!r}"
                )
            pole_name_en = pole.get("name_en")
            if not isinstance(pole_name_en, str) or not pole_name_en.strip():
                pole_name_en = _required_bus_stop_english_name_from_graph(
                    g,
                    gtfs_stop_id=pole_id,
                )
            else:
                pole_name_en = pole_name_en.strip()
            destinations = _gtfs_bus_timetable_destinations(
                route_id=route_id,
                pole_id=pole_id,
                target_pole_id=target_pole_id,
                pattern_trip_id=pattern_trip_id,
                preferred_pattern_trip_id=preferred_pattern_trip_id,
                include_stop_cluster=include_stop_cluster,
                day_type=service_day_type,
                current_minute=curr_min,
                limit=limit,
                include_all=include_all,
                delay_min=tm.bus_realtime_delays.get(route_id, 0.0),
                graph=g,
            )
        else:
            if (
                pattern_trip_id is not None
                or preferred_pattern_trip_id is not None
                or include_stop_cluster
            ):
                raise HTTPException(
                    400,
                    detail={
                        "code": "bus_timetable_pattern_trip_requires_gtfs",
                        "message": (
                            "pattern trip selectors are only supported with "
                            "GTFS route and stop IDs"
                        ),
                        "pattern_trip_id": pattern_trip_id,
                        "preferred_pattern_trip_id": preferred_pattern_trip_id,
                        "include_stop_cluster": include_stop_cluster,
                    },
                )
            pole_name = None
            pole_name_en = None
            if ("phys", pole_id) in g:
                pole_node = g.nodes[("phys", pole_id)]
                pole_name = pole_node.get("name")
                pole_name_en = pole_node.get("name_en")

            trips = tm.get_future_bus_trips(
                pole_id,
                route_id,
                curr_min,
                limit=max(1, limit) * 20,
                pole_name=pole_name,
                day_type=service_day_type,
                target_pole_id=target_pole_id,
                debug=debug,
            )

            groups = {}
            for t in trips:
                dest = t.get("dest") or "unknown"
                groups.setdefault(dest, []).append(min_to_time_str(t["dep"]))

            all_groups = {}
            if include_all:
                all_trips = tm.get_future_bus_trips(
                    pole_id,
                    route_id,
                    0,
                    limit=10000,
                    pole_name=pole_name,
                    day_type=service_day_type,
                    target_pole_id=target_pole_id,
                    debug=debug,
                )
                for t in all_trips:
                    dest = t.get("dest") or "unknown"
                    all_groups.setdefault(dest, []).append(
                        min_to_time_str(t["dep"])
                    )

            destination_ids = list(groups.keys())
            for dest_id in all_groups:
                if dest_id not in groups:
                    destination_ids.append(dest_id)

            destinations = []
            for dest_id in destination_ids:
                times = groups.get(dest_id, [])
                dest_name = None
                dest_name_en = None
                if dest_id != "unknown" and ("phys", dest_id) in g:
                    dest_node = g.nodes[("phys", dest_id)]
                    dest_name = dest_node.get("name")
                    dest_name_en = dest_node.get("name_en")
                destination = {
                    "destination_pole_id": (
                        None if dest_id == "unknown" else dest_id
                    ),
                    "destination_name": dest_name,
                    "destination_name_en": dest_name_en,
                    "times": times[: max(1, limit)],
                }
                if include_all:
                    destination["all_times"] = all_groups.get(dest_id, [])
                destinations.append(destination)

        return {
            "pole_id": pole_id,
            "pole_name": pole_name,
            "pole_name_en": pole_name_en,
            "route_id": route_id,
            "day_type": str(service_day_type),
            "time": time,
            "target_pole_id": target_pole_id,
            "include_all": include_all,
            "destinations": destinations,
        }

    @app.get("/explore/reachable")
    async def find_reachable_places(
        lat: float = Query(..., description="現在地の緯度"),
        lon: float = Query(..., description="現在地の経度")
    ):
        if getattr(app.state, "loading_status", "starting") != "ready":
             raise HTTPException(503, "Server is warming up (loading data).")

        G = app.state.G
        tm = app.state.TM
        
        if G is None or tm is None:
            raise HTTPException(status_code=503, detail="Server not initialized")

        result = get_reachable_stops(G, tm, lat, lon)
        return result

    @app.get("/streetview/thumb")
    async def streetview_thumb(
        lat: float = Query(...),
        lon: float = Query(...),
        w: int = Query(120, ge=32, le=640),
        h: int = Query(120, ge=32, le=640),
        radius: int = Query(80, ge=1, le=5000),
        fov: int = Query(90, ge=10, le=120),
        heading: int = Query(0, ge=0, le=360),
        pitch: int = Query(0, ge=-90, le=90),
    ):
        google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
        if not google_maps_api_key:
            raise HTTPException(500, "GOOGLE_MAPS_API_KEY is missing")

        cache_key = f"{lat:.6f},{lon:.6f}|{w}x{h}|r{radius}|f{fov}|hd{heading}|p{pitch}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return Response(content=cached, media_type="image/jpeg")

        async with httpx.AsyncClient(timeout=8.0) as client:
            meta_url = "https://maps.googleapis.com/maps/api/streetview/metadata"
            meta_params = {
                "location": f"{lat},{lon}",
                "radius": str(radius),
                "key": google_maps_api_key,
            }
            meta = await client.get(meta_url, params=meta_params)
            if meta.status_code != 200:
                raise HTTPException(502, f"StreetView metadata upstream error {meta.status_code}")

            meta_json = meta.json()
            status = meta_json.get("status")
            if status != "OK":
                raise HTTPException(404, f"StreetView not found status={status}")

            pano_id = meta_json.get("pano_id")
            if not pano_id:
                raise HTTPException(404, "StreetView pano_id not found")

            img_url = "https://maps.googleapis.com/maps/api/streetview"
            img_params = {
                "size": f"{w}x{h}",
                "pano": pano_id,
                "fov": str(fov),
                "heading": str(heading),
                "pitch": str(pitch),
                "key": google_maps_api_key,
            }
            img = await client.get(img_url, params=img_params)
            if img.status_code != 200:
                raise HTTPException(502, f"StreetView image upstream error {img.status_code}")

            content = img.content
            _cache_set(cache_key, content)
            return Response(content=content, media_type="image/jpeg")
