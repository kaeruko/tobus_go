from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from route_engine import (
    GeoPoint,
    RouteCandidate,
    RouteInputError,
    RoutePreference,
    RouteSearchRequest,
    RouteSearchResult,
    normalize_route_preference,
    serialize_route_result,
)
from transit_dataset import TransitDataset, TransitMode, TransitStop
from transit_engine import (
    BatchSearchRequest,
    SearchCore,
    SearchEndpoint,
    TransitItinerary,
    TransitLeg,
    itinerary_path_key,
)

_JST = ZoneInfo("Asia/Tokyo")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _clock(minute: int) -> str:
    minute %= 24 * 60
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _parse_departure(date_str: str | None, start_time: str) -> datetime:
    if date_str is None:
        date_part = datetime.now(_JST).date().isoformat()
    else:
        try:
            parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError as error:
            raise ValueError("target_date_str must be YYYY-MM-DD") from error
        if parsed_date.isoformat() != date_str:
            raise ValueError("target_date_str must be zero-padded YYYY-MM-DD")
        date_part = date_str
    try:
        parsed = datetime.strptime(f"{date_part} {start_time}", "%Y-%m-%d %H:%M")
    except ValueError as error:
        raise ValueError("start_time must be HH:MM") from error
    return parsed.replace(tzinfo=_JST)


def _point(stop: TransitStop) -> dict[str, Any]:
    return {
        "name": stop.name,
        "lat": stop.lat,
        "lon": stop.lon,
        "id": stop.id,
    }


class GtfsRouteEngine:
    """Coordinate-to-coordinate route backend backed only by TransitDataset.

    This class deliberately contains no city names and no GTFS field parsing.
    City adapters are responsible only for producing a validated TransitDataset.
    """

    def __init__(
        self,
        dataset: TransitDataset,
        *,
        walk_radius_m: int = 600,
        walk_speed_m_per_min: float = 80.0,
        endpoint_candidate_limit: int = 6,
        max_rides: int = 6,
        search_core: SearchCore | None = None,
    ) -> None:
        if walk_radius_m <= 0:
            raise ValueError("walk_radius_m must be > 0")
        if walk_speed_m_per_min <= 0:
            raise ValueError("walk_speed_m_per_min must be > 0")
        if endpoint_candidate_limit < 1:
            raise ValueError("endpoint_candidate_limit must be >= 1")
        if max_rides < 1:
            raise ValueError("max_rides must be >= 1")
        non_bus = [route.id for route in dataset.routes.values() if route.mode is not TransitMode.BUS]
        if non_bus:
            raise ValueError(
                "GtfsRouteBackend currently accepts bus-only datasets; "
                f"found {non_bus[0]}"
            )
        self.dataset = dataset
        if search_core is None:
            from search_core_factory import create_search_core

            search_core = create_search_core(dataset)
        self.search_core = search_core
        # Compatibility for callers that still inspect the former backend.
        self.engine = self.search_core
        self.walk_radius_m = walk_radius_m
        self.walk_speed_m_per_min = walk_speed_m_per_min
        self.endpoint_candidate_limit = endpoint_candidate_limit
        self.max_rides = max_rides

    def _nearby(self, lat: float, lon: float) -> list[tuple[TransitStop, float]]:
        candidates: list[tuple[TransitStop, float]] = []
        for stop in self.dataset.stops.values():
            distance = _haversine_m(lat, lon, stop.lat, stop.lon)
            if distance <= self.walk_radius_m:
                candidates.append((stop, distance))
        candidates.sort(key=lambda item: (item[1], item[0].id))
        return candidates[: self.endpoint_candidate_limit]

    def _find_best(
        self,
        origins: list[tuple[TransitStop, float]],
        destinations: list[tuple[TransitStop, float]],
        *,
        departure: datetime,
        preference: str,
    ) -> tuple[TransitItinerary, TransitStop, float, TransitStop, float] | None:
        best: tuple[
            tuple[Any, ...],
            TransitItinerary,
            TransitStop,
            float,
            TransitStop,
            float,
        ] | None = None
        origin_endpoints = tuple(
            SearchEndpoint(
                stop_id=origin.id,
                walk_minutes=math.ceil(
                    origin_distance / self.walk_speed_m_per_min
                ),
                walk_meters=origin_distance,
                rank=index,
            )
            for index, (origin, origin_distance) in enumerate(origins)
        )
        destination_endpoints = tuple(
            SearchEndpoint(
                stop_id=destination.id,
                walk_minutes=math.ceil(
                    destination_distance / self.walk_speed_m_per_min
                ),
                walk_meters=destination_distance,
                rank=index,
            )
            for index, (destination, destination_distance) in enumerate(destinations)
        )
        result = self.search_core.search(
            BatchSearchRequest(
                service_date=departure.date(),
                departure_minute=departure.hour * 60 + departure.minute,
                origins=origin_endpoints,
                destinations=destination_endpoints,
                preference=(
                    "fastest" if preference == "time" else "fewest_transfers"
                ),
                max_rides=self.max_rides,
            )
        )
        for pair in result.pairs:
            origin, origin_distance = origins[pair.origin_index]
            destination, destination_distance = destinations[
                pair.destination_index
            ]
            destination_walk = destination_endpoints[
                pair.destination_index
            ].walk_minutes
            itinerary = pair.itinerary
            final_arrival = itinerary.arrival_minute + destination_walk
            path_key = itinerary_path_key(itinerary)
            objective = (
                (
                    final_arrival,
                    itinerary.transfers,
                    itinerary.arrival_minute,
                    origin_endpoints[pair.origin_index].rank,
                    destination_endpoints[pair.destination_index].rank,
                    path_key,
                )
                if preference == "time"
                else (
                    itinerary.transfers,
                    final_arrival,
                    itinerary.arrival_minute,
                    origin_endpoints[pair.origin_index].rank,
                    destination_endpoints[pair.destination_index].rank,
                    path_key,
                )
            )
            row = (
                objective,
                itinerary,
                origin,
                origin_distance,
                destination,
                destination_distance,
            )
            if best is None or row[0] < best[0]:
                best = row
        if best is None:
            return None
        return best[1], best[2], best[3], best[4], best[5]

    def _ride_step(self, leg: TransitLeg, index: int) -> dict[str, Any]:
        route = self.dataset.routes[leg.route_id]
        trip = self.dataset.trips[leg.trip_id]
        stops = [self.dataset.stops[stop_id] for stop_id in leg.stop_ids]
        title = route.short_name or route.long_name
        return {
            "step_id": f"ride-{index}",
            "kind": "bus",
            "title": title,
            "from_": stops[0].name,
            "to": stops[-1].name,
            "minutes": leg.arrival_minute - leg.departure_minute,
            "meters": 0,
            "departure_time": _clock(leg.departure_minute),
            "arrival_time": _clock(leg.arrival_minute),
            "route_id": leg.route_id,
            "trip_id": leg.trip_id,
            "direction_id": trip.direction_id,
            "departureStopId": leg.from_stop_id,
            "arrivalPoleId": leg.to_stop_id,
            "stops": [_point(stop) for stop in stops],
        }

    def _serialize(
        self,
        itinerary: TransitItinerary,
        origin: TransitStop,
        origin_distance: float,
        destination: TransitStop,
        destination_distance: float,
        *,
        alat: float,
        alon: float,
        blat: float,
        blon: float,
        departure: datetime,
        preference: str,
    ) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        points: list[list[float]] = [[alat, alon]]
        origin_walk = math.ceil(origin_distance / self.walk_speed_m_per_min)
        destination_walk = math.ceil(destination_distance / self.walk_speed_m_per_min)
        if origin_walk:
            steps.append(
                {
                    "step_id": "walk-origin",
                    "kind": "walk",
                    "title": "徒歩",
                    "from_": "現在地",
                    "to": origin.name,
                    "minutes": origin_walk,
                    "meters": int(round(origin_distance)),
                    "stops": [],
                }
            )
        points.append([origin.lat, origin.lon])

        current_minute = departure.hour * 60 + departure.minute + origin_walk
        lines: list[str] = []
        for index, leg in enumerate(itinerary.legs):
            if leg.departure_minute > current_minute:
                steps.append(
                    {
                        "step_id": f"wait-{index}",
                        "kind": "wait",
                        "title": "待ち時間",
                        "from_": self.dataset.stops[leg.from_stop_id].name,
                        "to": self.dataset.stops[leg.from_stop_id].name,
                        "place": self.dataset.stops[leg.from_stop_id].name,
                        "minutes": leg.departure_minute - current_minute,
                        "meters": 0,
                        "departure_time": _clock(current_minute),
                        "arrival_time": _clock(leg.departure_minute),
                        "stops": [],
                    }
                )
            ride = self._ride_step(leg, index)
            steps.append(ride)
            if ride["title"] not in lines:
                lines.append(ride["title"])
            for stop_id in leg.stop_ids[1:]:
                stop = self.dataset.stops[stop_id]
                points.append([stop.lat, stop.lon])
            current_minute = leg.arrival_minute

        if destination_walk:
            steps.append(
                {
                    "step_id": "walk-destination",
                    "kind": "walk",
                    "title": "徒歩",
                    "from_": destination.name,
                    "to": "目的地",
                    "minutes": destination_walk,
                    "meters": int(round(destination_distance)),
                    "stops": [],
                }
            )
        points.append([blat, blon])
        total_time = origin_walk + itinerary.total_minutes + destination_walk
        arrival = departure.hour * 60 + departure.minute + total_time
        trip_key = "|".join(leg.trip_id for leg in itinerary.legs) or "walk"
        return {
            "id": f"{self.dataset.metadata.feed_id}:{trip_key}:{departure.date().isoformat()}:{departure.strftime('%H%M')}",
            "lines": lines,
            "rides": itinerary.rides,
            "walking_distance_meters": sum(
                int(step["meters"])
                for step in steps
                if step["kind"] == "walk"
            ),
            "walking_segment_count": int(origin_walk > 0)
            + int(destination_walk > 0),
            "boards": itinerary.rides,
            "transfers": itinerary.transfers,
            "total": total_time,
            "total_time": total_time,
            "steps": steps,
            "points": points,
            "preference": preference,
            "departure_date": departure.isoformat(),
            "origin_coords": [alat, alon],
            "destination_coords": [blat, blon],
            "arrival_time": _clock(arrival),
        }

    def _search_request(self, request: RouteSearchRequest) -> RouteSearchResult:
        origins = self._nearby(request.origin.lat, request.origin.lon)
        destinations = self._nearby(
            request.destination.lat,
            request.destination.lon,
        )
        meta = {
            "destination_reachable": bool(origins and destinations),
            "destination_label": "目的地",
            "fallback_node_name": None,
            "fallback_distance_m": None,
            "walk_limit_m": self.walk_radius_m,
        }
        if not origins or not destinations:
            return RouteSearchResult(candidates=[], meta=meta)

        search_preference = (
            "time"
            if request.preference is RoutePreference.FASTEST
            else "fewTransfers"
        )
        best = self._find_best(
            origins,
            destinations,
            departure=request.departure_at,
            preference=search_preference,
        )
        if best is None:
            meta["destination_reachable"] = True
            return RouteSearchResult(candidates=[], meta=meta)

        itinerary, origin, origin_distance, destination, destination_distance = best
        payload = self._serialize(
            itinerary,
            origin,
            origin_distance,
            destination,
            destination_distance,
            alat=request.origin.lat,
            alon=request.origin.lon,
            blat=request.destination.lat,
            blon=request.destination.lon,
            departure=request.departure_at,
            preference=(
                "time"
                if request.preference is RoutePreference.FASTEST
                else "fewTransfers"
            ),
        )
        meta.update(
            {
                "destination_reachable": True,
                "fallback_node_name": destination.name,
                "fallback_distance_m": destination_distance,
            }
        )
        return RouteSearchResult(
            candidates=[RouteCandidate.from_mapping(payload)],
            meta=meta,
        )

    def search(
        self,
        request: RouteSearchRequest | None = None,
        *,
        alat: float | None = None,
        alon: float | None = None,
        blat: float | None = None,
        blon: float | None = None,
        pref: str | None = None,
        start_time: str | None = None,
        date_str: str | None = None,
    ) -> RouteSearchResult | dict[str, Any]:
        if request is not None:
            if any(
                value is not None
                for value in (alat, alon, blat, blon, pref, start_time, date_str)
            ):
                raise RouteInputError(
                    "RouteSearchRequest cannot be combined with legacy arguments"
                )
            return self._search_request(request)

        if None in (alat, alon, blat, blon, pref, start_time):
            raise ValueError("legacy route search requires all coordinate fields")
        try:
            legacy_request = RouteSearchRequest(
                origin=GeoPoint(float(alat), float(alon)),
                destination=GeoPoint(float(blat), float(blon)),
                departure_at=_parse_departure(date_str, str(start_time)),
                preference=normalize_route_preference(pref),
            )
        except RouteInputError:
            raise
        except (TypeError, ValueError) as error:
            raise RouteInputError(str(error)) from error
        return serialize_route_result(self._search_request(legacy_request))


class GtfsRouteBackend(GtfsRouteEngine):
    """Backward-compatible name for the shared GTFS route engine."""
