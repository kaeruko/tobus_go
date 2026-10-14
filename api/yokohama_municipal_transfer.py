"""Offline two-feed municipal pass transfer planning using shared TransitRouteEngine.

NOT wired to the public runtime. Explicit links require reviewed evidence.
Geometry-based links are only provisional development hints, not verified
walking connections or walking times; never expose them as confirmed routes.
Fare coverage must be independently reviewed before either search mode.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Union
from urllib.parse import urlsplit

from fare_policy import FarePolicyContext, RideFareContext, get_fare_policy
from route_engine import RouteContractError
from transit_dataset import TransitMode, TransitDataset
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
class GeometricTransferEstimate:
    """Provisional cross-feed link: GTFS stop centers, NOT a measured footpath."""

    bus_stop_id: str
    subway_stop_id: str
    straight_line_distance_m: float
    walk_meters: int
    walk_minutes: int

    def __post_init__(self) -> None:
        if (
            not self.bus_stop_id.startswith(_BUS_FEED + ":")
            or not self.subway_stop_id.startswith(_RAIL_FEED + ":")
        ):
            raise ValueError("geometric transfer requires feed-namespaced stop IDs")
        if (
            not math.isfinite(self.straight_line_distance_m)
            or self.straight_line_distance_m < 0
        ):
            raise ValueError("geometric distance must be finite and nonnegative")
        if type(self.walk_meters) is not int or self.walk_meters < 0:
            raise ValueError("geometric walk_meters must be a nonnegative integer")
        if type(self.walk_minutes) is not int or self.walk_minutes < 0:
            raise ValueError("geometric walk_minutes must be a nonnegative integer")
        if self.walk_meters + 1 < self.straight_line_distance_m:
            raise ValueError("geometric walk cannot understate straight-line distance")
        if self.walk_minutes < math.ceil(self.walk_meters / 80):
            raise ValueError("geometric walking time cannot understate assumed speed")


@dataclass(frozen=True, slots=True)
class MunicipalTransferPlan:
    first_legs: tuple[TransitLeg, ...]
    second_legs: tuple[TransitLeg, ...]
    first_mode: str
    second_mode: str
    transfer: ExplicitTransferLink | GeometricTransferEstimate
    transfer_arrival_minute: int
    onward_ready_minute: int
    final_arrival_minute: int
    policy_id: str
    additional_payment_yen: int

    @property
    def walking_connection_verified(self) -> bool:
        return isinstance(self.transfer, ExplicitTransferLink)


def _haversine_m(a, b) -> float:
    lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lon)
    central = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2)
        * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(min(1.0, math.sqrt(central)))


def _active_stop_ids(
    dataset: TransitDataset, day, *, use_departure: bool
) -> set[str]:
    services = dataset.active_service_ids(day)
    active_trips = {
        trip_id for trip_id, trip in dataset.trips.items()
        if trip.service_id in services
    }
    return {
        row.stop_id for row in dataset.stop_times
        if row.trip_id in active_trips
        and (
            row.departure_minute is not None if use_departure
            else row.arrival_minute is not None
        )
    }


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


def _search_municipal_transfer_with_link(
    *,
    bus_coverage: YokohamaFareCoverage,
    subway_coverage: YokohamaFareCoverage,
    origin_stop_id: str,
    destination_stop_id: str,
    depart_at: datetime,
    transfer: ExplicitTransferLink | GeometricTransferEstimate,
    policy_id: str,
) -> MunicipalTransferPlan | None:
    """Find one cross-feed walking transfer using existing timetable search.

    Offline only. Geometric links are unverified hypotheses, NOT public routes.
    Cross-midnight transfers are refused until service-day handling is proven.
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
    straight_m = _haversine_m(bus_stop, subway_stop)
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
    """Preserve the separately evidenced/manual link test entrypoint."""
    if not isinstance(transfer, ExplicitTransferLink):
        raise ValueError("explicit transfer requires a reviewed ExplicitTransferLink")
    return _search_municipal_transfer_with_link(
        bus_coverage=bus_coverage, subway_coverage=subway_coverage,
        origin_stop_id=origin_stop_id, destination_stop_id=destination_stop_id,
        depart_at=depart_at, transfer=transfer, policy_id=policy_id,
    )


def search_geometric_municipal_transfers(
    *,
    bus_coverage: YokohamaFareCoverage,
    subway_coverage: YokohamaFareCoverage,
    origin_stop_id: str,
    destination_stop_id: str,
    depart_at: datetime,
    policy_id: str,
    radius_m: int = 300,
    max_candidate_links: int = 40,
) -> tuple[MunicipalTransferPlan, ...]:
    """Offline provisional bus↔subway candidate search with GTFS spatial links.

    Reuses each feed's unchanged TransitRouteEngine for actual GTFS trips and
    YokohamaFareCoverage for fare approval. Walking is conservatively estimated
    from straight-line separation, NOT proven physically possible. Do not wire
    these outputs to /route; human review/real walking directions still needed.
    The returned list is sorted by scheduled arrival and contains at most one
    cross-feed transfer (not a globally optimal cross-network search).
    """
    if type(radius_m) is not int or not 1 <= radius_m <= 600:
        raise ValueError("radius_m must be an integer from 1 to 600")
    if type(max_candidate_links) is not int or not 1 <= max_candidate_links <= 100:
        raise ValueError("max_candidate_links must be between 1 and 100")
    if policy_id not in _PASS_IDS:
        raise ValueError("Yokohama transfer requires an explicit welfare/senior pass")
    if (
        depart_at.tzinfo is None
        or depart_at.utcoffset() != timedelta(hours=9)
    ):
        raise ValueError("Yokohama transfer requires an aware JST datetime")

    bus = _reviewed(bus_coverage, _BUS_FEED, "yokohama_municipal_bus")
    rail = _reviewed(subway_coverage, _RAIL_FEED, "yokohama_municipal_subway")
    if bus is None or rail is None:
        return ()

    if origin_stop_id in bus.dataset.stops and destination_stop_id in rail.dataset.stops:
        bus_first = True
        before = _active_stop_ids(bus.dataset, depart_at.date(), use_departure=False)
        after = _active_stop_ids(rail.dataset, depart_at.date(), use_departure=True)
    elif origin_stop_id in rail.dataset.stops and destination_stop_id in bus.dataset.stops:
        bus_first = False
        before = _active_stop_ids(rail.dataset, depart_at.date(), use_departure=False)
        after = _active_stop_ids(bus.dataset, depart_at.date(), use_departure=True)
    else:
        raise ValueError("transfer requires one bus and one subway endpoint")

    # Find all nearby poles/stations from scheduled, reviewed service. No
    # name-based same-stop merge; GTFS pole IDs remain distinct by direction.
    pairs: list[tuple[float, str, str]] = []
    for bus_id in (before if bus_first else after):
        bus_stop = bus.dataset.stops[bus_id]
        for rail_id in (after if bus_first else before):
            rail_stop = rail.dataset.stops[rail_id]
            dist = _haversine_m(bus_stop, rail_stop)
            if math.isfinite(dist) and dist <= radius_m:
                pairs.append((dist, bus_id, rail_id))
    pairs.sort(key=lambda item: (item[0], item[1], item[2]))

    # The cap is an explicit safety bound. Do not claim search completeness
    # if legitimate candidates would be discarded by the cap.
    if len(pairs) > max_candidate_links:
        raise ValueError(
            "too many proximity transfer links; narrow radius or raise "
            "max_candidate_links, no truncated free routes returned"
        )

    plans: list[MunicipalTransferPlan] = []
    for distance, bus_id, rail_id in pairs:
        # Tokyo already uses Haversine-based station/bus proximity. This is
        # deliberately a cautious timetable probe, not a measured footpath:
        # 1.5x distance, plus two minutes for transfer access/boarding.
        estimated_meters = max(
            math.ceil(distance * 1.5), math.ceil(distance)
        )
        estimated_minutes = math.ceil(estimated_meters / 80) + 2
        estimate = GeometricTransferEstimate(
            bus_stop_id=bus_id,
            subway_stop_id=rail_id,
            straight_line_distance_m=distance,
            walk_meters=estimated_meters,
            walk_minutes=estimated_minutes,
        )
        plan = _search_municipal_transfer_with_link(
            bus_coverage=bus_coverage, subway_coverage=subway_coverage,
            origin_stop_id=origin_stop_id,
            destination_stop_id=destination_stop_id,
            depart_at=depart_at,
            transfer=estimate, policy_id=policy_id,
        )
        if plan is not None:
            plans.append(plan)
    plans.sort(key=lambda p: (
        p.final_arrival_minute,
        len(p.first_legs) + len(p.second_legs),
        p.transfer.walk_minutes,
        p.transfer.bus_stop_id, p.transfer.subway_stop_id,
    ))
    return tuple(plans)
