"""Opt-in municipal comparison adapter; public runtime stays on SearchCore v1.

Only independently supplied directional reviews are accepted. The old v1
ExplicitTransferLink is not implicitly converted into two approved directions.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

from fare_policy import evaluate_candidate_fare
from route_engine import RouteContractError
from transit_network import TransitNetworkSnapshot, build_transit_network
from transit_timetable_choices import NetworkRideEvent, search_network
from yokohama_municipal_transfer import _reviewed
from yokohama_fare_coverage import YokohamaFareCoverage


_PASS_IDS = frozenset({"yokohama_welfare_special_pass", "yokohama_senior_special_pass"})


@dataclass(frozen=True, slots=True)
class MunicipalNetworkContext:
    snapshot: TransitNetworkSnapshot
    coverages: Mapping[str, YokohamaFareCoverage]
    policy_id: str


def build_shared_municipal_network(
    bus_coverage, subway_coverage, *, policy_id, walking_links, costs,
) -> MunicipalNetworkContext:
    if policy_id not in _PASS_IDS:
        raise ValueError(f"unsupported municipal pass policy: {policy_id!r}")
    allowed = set()
    for coverage, feed, operator in (
        (bus_coverage, "yokohama_bus", "yokohama_municipal_bus"),
        (subway_coverage, "yokohama_subway", "yokohama_municipal_subway"),
    ):
        selected = _reviewed(coverage, feed, operator)
        if selected is not None:
            allowed.update(selected.dataset.trips)
    snapshot = build_transit_network(
        (bus_coverage.dataset, subway_coverage.dataset),
        allowed_trip_ids=allowed, walking_links=walking_links, costs=costs)
    frozen = {}
    for coverage, dataset in zip((bus_coverage, subway_coverage), snapshot.datasets):
        frozen[dataset.metadata.feed_id] = replace(
            coverage, dataset=dataset,
            route_service_kinds=MappingProxyType(dict(coverage.route_service_kinds)),
            stop_municipalities=MappingProxyType(dict(coverage.stop_municipalities)),
            reviewed_free_trip_uris=(None if coverage.reviewed_free_trip_uris is None
                                    else MappingProxyType(dict(coverage.reviewed_free_trip_uris))))
    return MunicipalNetworkContext(snapshot, MappingProxyType(frozen), policy_id)


def search_shared_municipal_network(context, origin_stop_id, destination_stop_id, **query):
    if query.get("mode") == "fewTransfers" and query["parameters"].few_transfers_tiebreak != "arrival":
        raise ValueError("Yokohama fewTransfers requires an explicit arrival tie-break")
    journeys = search_network(context.snapshot, origin_stop_id, destination_stop_id, **query)
    # Revalidate every selected leg against the original pinned coverage and
    # the requested pass. Never turn an unavailable quote into a free journey.
    for journey in journeys:
        steps = []
        for event in journey.events:
            if not isinstance(event, NetworkRideEvent):
                continue
            if event.trip_id not in context.snapshot.allowed_trip_ids:
                raise RouteContractError("municipal journey contains an unapproved trip")
            coverage = context.coverages[event.trip_id.split(":", 1)[0]]
            step = {"kind": event.mode, "trip_id": event.trip_id, "route_id": event.route_id,
                    "departureStopId": event.from_stop_id, "arrivalPoleId": event.to_stop_id}
            step["fare_context"] = coverage.context_for_step(step)
            steps.append(step)
        quote = evaluate_candidate_fare(
            city_key="yokohama", candidate={"steps": steps},
            policy_id=context.policy_id, normal_fare_yen=None)
        if quote.status != "available" or quote.pay_now_yen != 0:
            raise RouteContractError("municipal shared journey failed independent zero-fare validation")
    return journeys
