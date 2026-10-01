from __future__ import annotations

import datetime
import gc
import math
from dataclasses import dataclass
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.services.route_step_ids import assign_candidate_step_ids
from route_engine import (
    RouteCandidate,
    RouteContractError,
    RouteSearchRequest,
    RouteSearchResult,
)
from toei_engine import (
    MAX_WALK_SEG_M,
    _rss_mb,
    determine_day_type,
    get_virtual_connections,
    haversine,
    min_to_time_str,
    nearest_phys,
    search_best_routes_once,
    time_str_to_min,
)


_TOKYO_TIMEZONE = ZoneInfo("Asia/Tokyo")
_REALTIME_SEARCH_HORIZON_MINUTES = 60
_REALTIME_SEARCH_PAST_GRACE_MINUTES = 5


def _tokyo_now() -> datetime.datetime:
    return datetime.datetime.now(_TOKYO_TIMEZONE)


def _should_use_realtime(
    *,
    date_str: str | None,
    start_time: str,
    now: datetime.datetime,
) -> bool:
    if now.tzinfo is None:
        raise RouteContractError("Tokyo route realtime policy requires a timezone-aware now")

    now_tokyo = now.astimezone(_TOKYO_TIMEZONE)
    service_date = (
        datetime.date.fromisoformat(date_str)
        if date_str is not None
        else now_tokyo.date()
    )
    hour, minute = map(int, start_time.split(":"))
    departure_at = datetime.datetime(
        service_date.year,
        service_date.month,
        service_date.day,
        tzinfo=_TOKYO_TIMEZONE,
    ) + datetime.timedelta(hours=hour, minutes=minute)
    delta_minutes = (departure_at - now_tokyo).total_seconds() / 60.0
    return (
        -_REALTIME_SEARCH_PAST_GRACE_MINUTES
        <= delta_minutes
        <= _REALTIME_SEARCH_HORIZON_MINUTES
    )


@dataclass(frozen=True, slots=True)
class TokyoRouteDependencies:
    nearest_phys: Callable[..., Any] = nearest_phys
    haversine: Callable[..., float] = haversine
    get_virtual_connections: Callable[..., Any] = get_virtual_connections
    search_best_routes_once: Callable[..., list[dict[str, Any]]] = (
        search_best_routes_once
    )
    time_str_to_min: Callable[[str], int] = time_str_to_min
    min_to_time_str: Callable[[int], str] = min_to_time_str
    determine_day_type: Callable[[str | None], str] = determine_day_type
    assign_candidate_step_ids: Callable[[dict[str, Any]], Any] = (
        assign_candidate_step_ids
    )
    rss_mb: Callable[[], float] = _rss_mb
    now: Callable[[], datetime.datetime] = _tokyo_now


def _require_official_english_candidate(candidate: dict[str, Any]) -> None:
    ride_steps = [
        step
        for step in candidate.get("steps", [])
        if step.get("kind") in ("bus", "rail")
    ]
    if not ride_steps:
        return

    lines = candidate.get("lines")
    lines_en = candidate.get("lines_en")
    if not isinstance(lines, list) or not isinstance(lines_en, list):
        raise RouteContractError("Tokyo route candidate is missing lines/lines_en")
    if len(lines_en) != len(lines):
        raise RouteContractError(
            "Tokyo route candidate has incomplete official English line labels: "
            f"ja={lines!r}, en={lines_en!r}"
        )

    for step in ride_steps:
        step_id = step.get("step_id") or "<unassigned>"
        for key in ("title_en", "from_en", "to_en"):
            value = step.get(key)
            if not isinstance(value, str) or not value.strip():
                raise RouteContractError(
                    "Tokyo ride step is missing official English transit text: "
                    f"step_id={step_id}, field={key}"
                )
        stops = step.get("stops")
        if not isinstance(stops, list) or not stops:
            raise RouteContractError(
                f"Tokyo ride step has no stops for English validation: {step_id}"
            )
        for index, stop in enumerate(stops):
            value = stop.get("name_en") if isinstance(stop, dict) else None
            if not isinstance(value, str) or not value.strip():
                raise RouteContractError(
                    "Tokyo route stop is missing official English name: "
                    f"step_id={step_id}, stop_index={index}"
                )


class TokyoRouteEngine:
    """Adapter from the shared route contract to the existing ODPT engine."""

    def __init__(
        self,
        app: Any,
        *,
        dependencies: TokyoRouteDependencies | None = None,
    ) -> None:
        self.app = app
        self.dependencies = dependencies or TokyoRouteDependencies()

    def search(self, request: RouteSearchRequest) -> RouteSearchResult:
        payload = self.search_legacy(
            alat=request.origin.lat,
            alon=request.origin.lon,
            blat=request.destination.lat,
            blon=request.destination.lon,
            pref=request.preference.api_value,
            bus_only=request.bus_only,
            start_time=request.departure_at.strftime("%H:%M"),
            date_str=request.departure_at.date().isoformat(),
            limit=request.limit,
        )

        candidates = [
            RouteCandidate.from_mapping(candidate)
            for candidate in payload.get("candidates", [])
        ]
        extra = {
            key: value
            for key, value in payload.items()
            if key not in ("candidates", "meta")
        }
        return RouteSearchResult(
            candidates=candidates,
            meta=dict(payload.get("meta", {})),
            extra=extra,
        )

    def search_legacy(
        self,
        *,
        alat: float,
        alon: float,
        blat: float,
        blon: float,
        pref: str,
        bus_only: bool = False,
        start_time: str = "10:00",
        date_str: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Run Tokyo search and preserve its Flutter-compatible dictionary."""

        deps = self.dependencies
        use_realtime = _should_use_realtime(
            date_str=date_str,
            start_time=start_time,
            now=deps.now(),
        )
        print(f"[MEM] enter TokyoRouteEngine.search rss={deps.rss_mb():.1f}MB")
        print(
            "[USER_DEBUG] TokyoRouteEngine.search: "
            f"pref={pref}, bus_only={bus_only}, "
            f"start_time={start_time}, date_str={date_str}, "
            f"use_realtime={use_realtime}",
            flush=True,
        )

        g = self.app.state.G
        timetable = self.app.state.TM
        walk_radius = self.app.state.WALK_RAD
        spatial_index = self.app.state.SI

        origin_node, origin_distance = deps.nearest_phys(
            g,
            alat,
            alon,
            station_only=False,
            spatial_index=spatial_index,
        )
        destination_node, destination_distance = deps.nearest_phys(
            g,
            blat,
            blon,
            station_only=True,
            spatial_index=spatial_index,
        )
        if not destination_node or destination_distance > 500:
            destination_node, _ = deps.nearest_phys(
                g,
                blat,
                blon,
                station_only=False,
                spatial_index=spatial_index,
            )

        if not origin_node or not destination_node:
            return {
                "error": "Nearby stations or busstops not found",
                "candidates": [],
                "meta": {},
            }

        initial_walk_minutes = 0
        if origin_distance and origin_distance > 0:
            initial_walk_minutes = max(1, math.ceil(origin_distance / 80.0))

        active_start_time = start_time
        if initial_walk_minutes > 0:
            active_start_time = deps.min_to_time_str(
                deps.time_str_to_min(start_time) + initial_walk_minutes
            )

        destination_label = "目的地"
        destination_walk_radius = MAX_WALK_SEG_M
        virtual_destination, virtual_connections = deps.get_virtual_connections(
            g,
            blat,
            blon,
            name=destination_label,
            walk_radius=destination_walk_radius,
            spatial_index=spatial_index,
        )
        destination_reachable = bool(virtual_connections)
        day_type = deps.determine_day_type(date_str)

        print(
            "[ROUTE_DEBUG] Tokyo destination setup: "
            f"pref={pref} origin_node={origin_node} "
            f"selected_destination_node={destination_node} "
            f"graph_walk_radius={walk_radius} "
            f"destination_walk_radius={destination_walk_radius} "
            f"virtual_destination={virtual_destination} "
            f"virtual_connections={len(virtual_connections)} "
            f"destination_reachable={destination_reachable}",
            flush=True,
        )

        results: list[dict[str, Any]] = []
        if destination_reachable:
            print(
                "[ROUTE_DEBUG] Tokyo primary search start: "
                f"pref={pref} target=virtual_destination "
                f"connections={len(virtual_connections)}",
                flush=True,
            )
            results = deps.search_best_routes_once(
                g,
                timetable,
                origin_node,
                mode=pref,
                start_time=active_start_time,
                target_date_str=date_str,
                limit=limit,
                target_node=virtual_destination,
                day_type=day_type,
                virtual_dest_connections=virtual_connections,
                target_coords=[blat, blon],
                use_realtime=use_realtime,
                bus_only=bus_only,
            )
            print(
                "[ROUTE_DEBUG] Tokyo primary search done: "
                f"pref={pref} candidates={len(results)}",
                flush=True,
            )

        if not results:
            print(
                "[ROUTE_DEBUG] Tokyo fallback search start: "
                f"pref={pref} target={destination_node}",
                flush=True,
            )
            results = deps.search_best_routes_once(
                g,
                timetable,
                origin_node,
                mode=pref,
                start_time=active_start_time,
                target_date_str=date_str,
                limit=limit,
                target_node=destination_node,
                day_type=day_type,
                virtual_dest_connections=None,
                target_coords=None,
                use_realtime=use_realtime,
                bus_only=bus_only,
            )
            print(
                "[ROUTE_DEBUG] Tokyo fallback search done: "
                f"pref={pref} candidates={len(results)}",
                flush=True,
            )

        for candidate in results:
            if initial_walk_minutes > 0:
                origin_name = g.nodes[origin_node]["name"]
                origin_name_en = g.nodes[origin_node].get("name_en")
                if candidate["steps"] and candidate["steps"][0]["kind"] == "walk":
                    first = candidate["steps"][0]
                    first["from_"] = "現在地"
                    first["from_en"] = "Current location"
                    first["minutes"] += int(initial_walk_minutes)
                    first["meters"] += int(origin_distance)
                    first["edges"] = first.get("edges", 0) + 1
                    candidate["points"].insert(0, [alat, alon])
                    candidate["total_time"] += initial_walk_minutes
                    candidate["walking_distance_meters"] += int(origin_distance)
                else:
                    candidate["steps"].insert(
                        0,
                        {
                            "kind": "walk",
                            "title": "徒歩",
                            "edges": 0,
                            "from_": "現在地",
                            "from_en": "Current location",
                            "to": origin_name,
                            "to_en": origin_name_en,
                            "meters": int(origin_distance),
                            "minutes": int(initial_walk_minutes),
                        },
                    )
                    candidate["points"].insert(0, [alat, alon])
                    candidate["total_time"] += initial_walk_minutes
                    candidate["walking_distance_meters"] += int(origin_distance)
                    candidate["walking_segment_count"] += 1

            _require_official_english_candidate(candidate)
            candidate["official_english_names"] = True
            candidate["origin_coords"] = [alat, alon]
            candidate["destination_coords"] = [blat, blon]
            candidate.pop("path", None)
            deps.assign_candidate_step_ids(candidate)

            # The legacy graph may retain sub-meter floats on walk edges. The
            # adapter owns conversion to the integer Flutter contract.
            walk_steps = [
                step for step in candidate["steps"] if step.get("kind") == "walk"
            ]
            for step in walk_steps:
                step["meters"] = int(round(step.get("meters", 0)))
            candidate["walking_distance_meters"] = sum(
                step["meters"] for step in walk_steps
            )
            candidate["walking_segment_count"] = len(walk_steps)

        fallback_distance_m = None
        fallback_node_name = None
        fallback_node_name_en = None
        if destination_node in g:
            fallback_node_name = g.nodes[destination_node].get("name")
            fallback_node_name_en = g.nodes[destination_node].get("name_en")
            fallback_lat = g.nodes[destination_node].get("lat")
            fallback_lon = g.nodes[destination_node].get("lon")
            if fallback_lat is not None and fallback_lon is not None:
                fallback_distance_m = deps.haversine(
                    blat,
                    blon,
                    fallback_lat,
                    fallback_lon,
                )

        gc.collect()
        print(f"[MEM] leave TokyoRouteEngine.search rss={deps.rss_mb():.1f}MB")
        return {
            "candidates": results,
            "meta": {
                "destination_reachable": destination_reachable,
                "destination_label": destination_label,
                "fallback_node_name": fallback_node_name,
                "fallback_node_name_en": fallback_node_name_en,
                "fallback_distance_m": fallback_distance_m,
                "walk_limit_m": MAX_WALK_SEG_M,
                "realtime_applied": use_realtime,
                "bus_only": bus_only,
            },
        }
