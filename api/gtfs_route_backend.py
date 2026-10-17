from __future__ import annotations

import os
import math
from datetime import datetime
from typing import Any
from types import SimpleNamespace
from fractions import Fraction
from transit_network import TransitNetworkSnapshot
from transit_timetable_choices import NetworkRideEvent, NetworkWalkEvent
from zoneinfo import ZoneInfo

from route_engine import (
    RouteCandidate,
    RouteInputError,
    RouteContractError,
    RoutePreference,
    RouteSearchRequest,
    RouteSearchResult,
)
from transit_network_core import NetworkSearchCore
from transit_dataset import TransitDataset, TransitMode, TransitStop
from transit_search_dto import (
    BatchSearchRequest,
    SearchEndpoint,
    TransitItinerary,
    TransitLeg,
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
    minute = int(minute) % (24 * 60)
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _point(stop: TransitStop) -> dict[str, Any]:
    return {
        "name": stop.name,
        "lat": stop.lat,
        "lon": stop.lon,
        "id": stop.id,
    }


def nearby_stops(stops, lat, lon, *, radius_m, candidate_limit):
    """Geometric candidates only; callers must separately approve access."""
    candidates = [(stop, _haversine_m(lat, lon, stop.lat, stop.lon))
                  for stop in stops.values()]
    candidates = [item for item in candidates if item[1] <= radius_m]
    candidates.sort(key=lambda item: (item[1], item[0].id))
    return candidates[:candidate_limit]


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
        network_snapshot: TransitNetworkSnapshot | None = None,
    ) -> None:
        if "ROUTE_SEARCH_CORE" in os.environ:
            raise RuntimeError("ROUTE_SEARCH_CORE v1 selector is not supported by common v2 city backends")
        if walk_radius_m <= 0:
            raise ValueError("walk_radius_m must be > 0")
        if walk_speed_m_per_min <= 0:
            raise ValueError("walk_speed_m_per_min must be > 0")
        if endpoint_candidate_limit < 1:
            raise ValueError("endpoint_candidate_limit must be >= 1")
        if max_rides < 1:
            raise ValueError("max_rides must be >= 1")
        if network_snapshot is not None:
            if not isinstance(network_snapshot, TransitNetworkSnapshot):
                raise ValueError("explicit v2 network snapshot required")
            dataset = SimpleNamespace(stops=network_snapshot.stops, routes=network_snapshot.routes,
                trips=network_snapshot.trips, metadata=SimpleNamespace(feed_id="municipal_network"))
        # City adapters already validate operators and fare coverage. The
        # shared coordinate backend only needs the validated transport mode:
        # bus and rail use the SAME time-indexed SearchCore. The response
        # must still preserve the mode of each actual timetable leg.
        unsupported = [
            route.id for route in dataset.routes.values()
            if route.mode not in (TransitMode.BUS, TransitMode.RAIL)
        ]
        if unsupported:
            raise ValueError(
                f"GtfsRouteEngine found unsupported mode: {unsupported[0]}"
            )
        self.dataset = dataset
        self.search_core = NetworkSearchCore(dataset, snapshot=network_snapshot)
        self.walk_radius_m = walk_radius_m
        self.walk_speed_m_per_min = walk_speed_m_per_min
        self.endpoint_candidate_limit = endpoint_candidate_limit
        self.max_rides = max_rides

    def _nearby(self, lat: float, lon: float) -> list[tuple[TransitStop, float]]:
        return nearby_stops(self.dataset.stops, lat, lon,
            radius_m=self.walk_radius_m, candidate_limit=self.endpoint_candidate_limit)

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
        if any(departure.hour * 60 + departure.minute + e.walk_minutes >= 1440 for e in origin_endpoints):
            raise RuntimeError("coordinate origin walk crosses unsupported service-day boundary")
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
            objective = (
                (
                    final_arrival,
                    pair.planning_cost,
                    itinerary.arrival_minute,
                    origin_endpoints[pair.origin_index].rank,
                    destination_endpoints[pair.destination_index].rank,
                )
                if preference == "time"
                else (
                    itinerary.transfers,
                    pair.planning_cost,
                    final_arrival,
                    itinerary.arrival_minute,
                    origin_endpoints[pair.origin_index].rank,
                    destination_endpoints[pair.destination_index].rank,
                )
            )
            row = (
                objective,
                itinerary,
                origin,
                origin_distance,
                destination,
                destination_distance,
                pair.journey,
            )
            if best is None or row[0] < best[0]:
                best = row
        if best is None:
            return None
        return best[1], best[2], best[3], best[4], best[5], best[6]

    def _ride_step(self, leg: TransitLeg, index: int) -> dict[str, Any]:
        route = self.dataset.routes[leg.route_id]
        trip = self.dataset.trips[leg.trip_id]
        stops = [self.dataset.stops[stop_id] for stop_id in leg.stop_ids]
        title = route.short_name or route.long_name
        return {
            "step_id": f"ride-{index}",
            "kind": route.mode.value,
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
        network_journey,
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
        events = network_journey.events
        for index, leg in enumerate(events):
            if leg.departure_minute > current_minute:
                place = (self.dataset.stops[leg.from_stop_id].name
                         if isinstance(leg, NetworkRideEvent) else "乗換地点")
                steps.append({"step_id": f"wait-{index}", "kind": "wait", "title": "待ち時間",
                    "from_": place, "to": place, "place": place,
                    "minutes": leg.departure_minute - current_minute, "meters": 0,
                    "departure_time": _clock(current_minute), "arrival_time": _clock(leg.departure_minute), "stops": []})
            if isinstance(leg, NetworkWalkEvent):
                link = leg.pinned_link.link
                steps.append({"step_id": f"walk-transfer-{index}", "kind": "walk", "title": "徒歩乗換",
                    "from_": self.dataset.stops[link.from_stop_id].name,
                    "to": self.dataset.stops[link.to_stop_id].name,
                    "minutes": leg.arrival_minute - leg.departure_minute, "meters": link.walk_meters,
                    "departure_time": _clock(leg.departure_minute), "arrival_time": _clock(leg.arrival_minute),
                    "departureStopId": link.from_stop_id, "arrivalPoleId": link.to_stop_id,
                    "walking_connection_verified": True, "walking_time_verified": True,
                    "evidence_url": link.official_evidence_url,
                    "includes_station_access": link.includes_station_access, "stops": []})
                stop = self.dataset.stops[link.to_stop_id]
                points.append([stop.lat, stop.lon])
            elif isinstance(leg, NetworkRideEvent):
                ride = self._ride_step(leg, index)
                steps.append(ride)
                if ride["title"] not in lines:
                    lines.append(ride["title"])
                for stop_id in leg.stop_ids[1:]:
                    stop = self.dataset.stops[stop_id]
                    points.append([stop.lat, stop.lon])
            else:
                raise RouteContractError("coordinate serializer requires an explicitly supported network event")
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
        payload = {
            "id": f"{self.dataset.metadata.feed_id}:{trip_key}:{departure.date().isoformat()}:{departure.strftime('%H%M')}",
            "lines": lines,
            "rides": itinerary.rides,
            "walking_distance_meters": sum(
                int(step["meters"])
                for step in steps
                if step["kind"] == "walk"
            ),
            "walking_segment_count": sum(step["kind"] == "walk" for step in steps),
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

        def json_minutes(value):
            if isinstance(value, Fraction):
                return int(value) if value.denominator == 1 else float(value)
            if isinstance(value, dict):
                return {key: json_minutes(item) for key, item in value.items()}
            if isinstance(value, list):
                return [json_minutes(item) for item in value]
            return value
        return json_minutes(payload)

    def _search_request(self, request: RouteSearchRequest) -> RouteSearchResult:
        if request.preference not in (RoutePreference.FASTEST, RoutePreference.FEWEST_TRANSFERS):
            raise RouteInputError("common v2 city backend does not accept Tokyo comfort/cost preference")
        # A bus-only request must never silently board rail just because the
        # reusable GTFS backend now supports both transport modes. A
        # multimodal feed needs explicit bus-filtered search first.
        if request.bus_only and any(
            route.mode is TransitMode.RAIL for route in self.dataset.routes.values()
        ):
            raise RouteInputError(
                "bus_only requires a bus-only GTFS dataset; "
                "mixed-mode filtering is not configured"
            )
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

        itinerary, origin, origin_distance, destination, destination_distance, journey = best
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
            network_journey=journey,
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

    def search(self, request: RouteSearchRequest) -> RouteSearchResult:
        if not isinstance(request, RouteSearchRequest):
            raise RouteInputError("explicit RouteSearchRequest required")
        return self._search_request(request)
