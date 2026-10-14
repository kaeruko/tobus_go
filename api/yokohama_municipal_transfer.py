"""Isolated two-feed, one-walk transfer probe for Yokohama municipal passes.

NOT wired to the public runtime. Transfer links and fare coverages must be
independently reviewed. Never infer transfers by name or GTFS coordinates.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from fare_policy import FarePolicyContext, RideFareContext, get_fare_policy
from route_engine import RouteContractError
from transit_dataset import TransitMode
from transit_engine import TransitLeg, TransitRouteEngine
from yokohama_fare_coverage import YokohamaFareCoverage

_PASS_IDS = frozenset({
    "yokohama_welfare_special_pass", "yokohama_senior_special_pass",
})
_BUS_FEED = "yokohama_bus"
_RAIL_FEED = "yokohama_subway"


@dataclass(frozen=True, slots=True)
class ExplicitTransferLink:
    bus_stop_id: str
    subway_stop_id: str
    walk_meters: int
    walk_minutes: int
    official_evidence_url: str

    def __post_init__(self) -> None:
        if not self.bus_stop_id.startswith(_BUS_FEED + ":"):
            raise ValueError("transfer bus stop must be feed-namespaced")
        if not self.subway_stop_id.startswith(_RAIL_FEED + ":"):
            raise ValueError("transfer subway stop must be feed-namespaced")
        if type(self.walk_meters) is not int or self.walk_meters < 0:
            raise ValueError("transfer walk_meters must be nonnegative integer")
        if type(self.walk_minutes) is not int or self.walk_minutes < 0:
            raise ValueError("transfer walk_minutes must be nonnegative integer")
        if self.walk_minutes < math.ceil(self.walk_meters / 80):
            raise ValueError("transfer walk_minutes cannot be less than walking time")
        parsed = urlsplit(self.official_evidence_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not (
                parsed.hostname == "city.yokohama.lg.jp"
                or parsed.hostname.endswith(".city.yokohama.lg.jp")
            )
            or parsed.username or parsed.password or parsed.fragment
        ):
            raise ValueError("transfer link requires Yokohama official HTTPS evidence")


@dataclass(frozen=True, slots=True)
class MunicipalTransferPlan:
    first_legs: tuple[TransitLeg, ...]
    second_legs: tuple[TransitLeg, ...]
    first_mode: str
    second_mode: str
    transfer: ExplicitTransferLink
    transfer_arrival_minute: int
    onward_ready_minute: int
    final_arrival_minute: int
    policy_id: str
    additional_payment_yen: int


def _reviewed(coverage: YokohamaFareCoverage, feed: str, operator: str):
    if (
        coverage.dataset.metadata.feed_id != feed
        or coverage.operator_id != operator
    ):
        raise ValueError(f"wrong {feed} fare coverage identity")
    if any(
        route.mode is not (TransitMode.BUS if feed == _BUS_FEED else TransitMode.RAIL)
        for route in coverage.dataset.routes.values()
    ):
        raise ValueError(f"wrong {feed} route mode")
    return coverage.municipal_free_coverage()


def _step(leg: TransitLeg, coverage: YokohamaFareCoverage):
    data = {
        "kind": leg.mode.value,
        "route_id": leg.route_id,
        "trip_id": leg.trip_id,
        "departureStopId": leg.from_stop_id,
        "arrivalPoleId": leg.to_stop_id,
    }
    data["fare_context"] = coverage.context_for_step(data)
    return RideFareContext.from_step(data)


def search_explicit_municipal_transfer(
    *,
    bus_coverage: YokohamaFareCoverage,
    subway_coverage: YokohamaFareCoverage,
    origin_stop_id: str,
    destination_stop_id: str,
    depart_at: datetime,
    transfer: ExplicitTransferLink,
    policy_id: str,
) -> MunicipalTransferPlan | None:
    """Find one explicitly defined cross-feed walking transfer.

    This is an offline prototype for reviewed stop IDs, not a route API.  It
    does not claim to find the globally optimal itinerary or infer footpaths.
    Cross-midnight transfers are intentionally refused pending service-day
    handling across two different feeds.
    """
    if policy_id not in _PASS_IDS:
        raise ValueError("Yokohama transfer requires an explicit welfare/senior pass")
    if (
        depart_at.tzinfo is None or depart_at.utcoffset() != timedelta(hours=9)
    ):
        raise ValueError("Yokohama transfer requires an aware JST datetime")
    bus = _reviewed(bus_coverage, _BUS_FEED, "yokohama_municipal_bus")
    rail = _reviewed(subway_coverage, _RAIL_FEED, "yokohama_municipal_subway")
    if bus is None or rail is None:
        return None
    if (
        transfer.bus_stop_id not in bus.dataset.stops
        or transfer.subway_stop_id not in rail.dataset.stops
    ):
        raise ValueError("transfer stop missing from reviewed datasets")
    # Explicit, independently sourced transfer information is still needed.
    # Coordinates can only reject physically impossible or understated walks.
    bus_stop = bus.dataset.stops[transfer.bus_stop_id]
    subway_stop = rail.dataset.stops[transfer.subway_stop_id]
    lat1, lon1 = math.radians(bus_stop.lat), math.radians(bus_stop.lon)
    lat2, lon2 = math.radians(subway_stop.lat), math.radians(subway_stop.lon)
    central = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2)
        * math.sin((lon2 - lon1) / 2) ** 2
    )
    straight_m = 2 * 6_371_000 * math.asin(min(1.0, math.sqrt(central)))
    if not math.isfinite(straight_m) or straight_m > 600:
        raise ValueError("explicit transfer stops too far apart")
    if transfer.walk_meters + 1 < straight_m:
        raise ValueError("explicit walking distance shorter than straight line")
    if (
        origin_stop_id in bus.dataset.stops
        and destination_stop_id in rail.dataset.stops
    ):
        first, second = bus, rail
        first_end, second_start = transfer.bus_stop_id, transfer.subway_stop_id
        modes = ("bus", "rail")
    elif (
        origin_stop_id in rail.dataset.stops
        and destination_stop_id in bus.dataset.stops
    ):
        first, second = rail, bus
        first_end, second_start = transfer.subway_stop_id, transfer.bus_stop_id
        modes = ("rail", "bus")
    else:
        raise ValueError("transfer requires one bus and one subway endpoint")

    first_route = TransitRouteEngine(first.dataset).search_fastest(
        origin_stop_id, first_end, departure=depart_at, max_rides=3,
    )
    if first_route is None or not first_route.legs:
        return None
    first_arrival = first_route.arrival_minute
    next_minute = first_arrival + transfer.walk_minutes
    if next_minute >= 24 * 60:
        raise ValueError("cross-midnight municipal transfer is not yet supported")
    onward_departure = depart_at.replace(
        hour=next_minute // 60, minute=next_minute % 60, second=0, microsecond=0,
    )
    second_route = TransitRouteEngine(second.dataset).search_fastest(
        second_start, destination_stop_id,
        departure=onward_departure, max_rides=3,
    )
    if second_route is None or not second_route.legs:
        return None
    if second_route.departure_minute != next_minute:
        raise RouteContractError("second feed search used incorrect transfer time")
    if second_route.legs[0].departure_minute < next_minute:
        raise RouteContractError("cross-feed boarding precedes completed walk")
    rides = (
        *(_step(leg, first) for leg in first_route.legs),
        *(_step(leg, second) for leg in second_route.legs),
    )
    quote = get_fare_policy("yokohama", policy_id).apply(
        FarePolicyContext(
            city_key="yokohama",
            normal_fare_yen=None,
            ride_modes=tuple(ride.mode for ride in rides),
            rides=tuple(rides),
        )
    )
    if (
        quote.status != "available"
        or quote.pay_now_yen != 0
        or quote.effective_fare_yen != 0
    ):
        raise RouteContractError("municipal transfer includes unverified fare")
    return MunicipalTransferPlan(
        first_legs=first_route.legs,
        second_legs=second_route.legs,
        first_mode=modes[0],
        second_mode=modes[1],
        transfer=transfer,
        transfer_arrival_minute=first_arrival,
        onward_ready_minute=next_minute,
        final_arrival_minute=second_route.arrival_minute,
        policy_id=policy_id,
        additional_payment_yen=0,
    )
