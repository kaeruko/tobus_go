from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from transit_dataset import TransitDataset, TransitMode, TransitStop
from transit_engine import TransitItinerary, TransitLeg, TransitRouteEngine

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


class GtfsRouteBackend:
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
        self.engine = TransitRouteEngine(dataset)
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
        best: tuple[tuple[int, int, int], TransitItinerary, TransitStop, float, TransitStop, float] | None = None
        for origin, origin_distance in origins:
            origin_walk = math.ceil(origin_distance / self.walk_speed_m_per_min)
            transit_departure = departure + timedelta(minutes=origin_walk)
            for destination, destination_distance in destinations:
                if preference == "time":
                    itinerary = self.engine.search_fastest(
                        origin.id,
                        destination.id,
                        departure=transit_departure,
                        max_rides=self.max_rides,
                    )
                else:
                    itinerary = self.engine.search_fewest_transfers(
                        origin.id,
                        destination.id,
                        departure=transit_departure,
                        max_rides=self.max_rides,
                    )
                if itinerary is None:
                    continue
                destination_walk = math.ceil(destination_distance / self.walk_speed_m_per_min)
                total = origin_walk + itinerary.total_minutes + destination_walk
                objective = (
                    (total, itinerary.transfers, itinerary.arrival_minute)
                    if preference == "time"
                    else (itinerary.transfers, total, itinerary.arrival_minute)
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

    def search(
        self,
        *,
        alat: float,
        alon: float,
        blat: float,
        blon: float,
        pref: str,
        start_time: str,
        date_str: str | None,
    ) -> dict[str, Any]:
        for name, value, low, high in (
            ("alat", alat, -90.0, 90.0),
            ("blat", blat, -90.0, 90.0),
            ("alon", alon, -180.0, 180.0),
            ("blon", blon, -180.0, 180.0),
        ):
            if not math.isfinite(value) or value < low or value > high:
                raise ValueError(f"{name} is out of range")
        if pref in ("shortTime", "fast", "time"):
            preference = "time"
        elif pref in ("fewTransfers", "cost"):
            preference = "fewTransfers"
        else:
            raise ValueError(f"unsupported route preference: {pref!r}")
        departure = _parse_departure(date_str, start_time)
        origins = self._nearby(alat, alon)
        destinations = self._nearby(blat, blon)
        if not origins or not destinations:
            return {
                "candidates": [],
                "meta": {
                    "destination_reachable": False,
                    "destination_label": "目的地",
                    "fallback_node_name": None,
                    "fallback_distance_m": None,
                    "walk_limit_m": self.walk_radius_m,
                },
            }
        best = self._find_best(
            origins,
            destinations,
            departure=departure,
            preference="time" if preference == "time" else "fewTransfers",
        )
        if best is None:
            return {
                "candidates": [],
                "meta": {
                    "destination_reachable": True,
                    "destination_label": "目的地",
                    "fallback_node_name": None,
                    "fallback_distance_m": None,
                    "walk_limit_m": self.walk_radius_m,
                },
            }
        itinerary, origin, origin_distance, destination, destination_distance = best
        return {
            "candidates": [
                self._serialize(
                    itinerary,
                    origin,
                    origin_distance,
                    destination,
                    destination_distance,
                    alat=alat,
                    alon=alon,
                    blat=blat,
                    blon=blon,
                    departure=departure,
                    preference=preference,
                )
            ],
            "meta": {
                "destination_reachable": True,
                "destination_label": "目的地",
                "fallback_node_name": destination.name,
                "fallback_distance_m": destination_distance,
                "walk_limit_m": self.walk_radius_m,
            },
        }
