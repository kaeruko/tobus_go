"""Batch/coordinate connection layer over SearchCore v2, with no search loop.

Shared request/result records are connection-layer DTOs only. All route
expansion, dominance, pruning and candidate ordering run in search_network ->
transit_search_labels.search_labels, the same implementation Tokyo delegates to.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter
from route_engine import RouteSearchLimitError

from transit_dataset import TransitMode
from transit_search_dto import (BatchSearchRequest, SearchDiagnostics, TransitItinerary, TransitLeg)
from transit_network import NetworkCosts, build_transit_network
from transit_timetable_choices import NetworkRideEvent, NetworkJourney, NetworkSearchParameters, search_network


@dataclass(frozen=True)
class NetworkPairResult:
    origin_index: int
    destination_index: int
    itinerary: TransitItinerary
    planning_cost: float
    journey: NetworkJourney


@dataclass(frozen=True)
class NetworkBatchResult:
    pairs: tuple[NetworkPairResult, ...]
    diagnostics: SearchDiagnostics


class NetworkSearchCore:
    def __init__(self, dataset, *, snapshot=None):
        self.snapshot = (build_transit_network((dataset,), allowed_trip_ids=dataset.trips,
            walking_links=(), costs=NetworkCosts()) if snapshot is None else snapshot)

    def search(self, request: BatchSearchRequest):
        if not isinstance(request, BatchSearchRequest):
            raise ValueError("explicit batch request required")
        if any(d.metadata.clock_profile != "source" for d in self.snapshot.datasets):
            raise ValueError("coordinate API requires an explicit estimate-aware serializer for practical profiles")
        started = perf_counter()
        pairs = []
        # Endpoint combinations are connection-layer inputs, never an alternate
        # timetable algorithm. Every pair uses identical v2 parameters.
        parameters = NetworkSearchParameters(max_candidates=1, max_boardings=request.max_rides)
        mode = "time" if request.preference == "fastest" else "fewTransfers"
        for i, origin in enumerate(request.origins):
            for j, destination in enumerate(request.destinations):
                remaining = parameters.time_limit_seconds - (perf_counter() - started)
                if remaining <= 0:
                    raise RouteSearchLimitError("v2 coordinate batch deadline exceeded", reason="time_limit")
                pair_parameters = replace(parameters, time_limit_seconds=remaining)
                journeys = search_network(self.snapshot, origin.stop_id, destination.stop_id,
                    service_date=request.service_date,
                    departure_minute=request.departure_minute + origin.walk_minutes,
                    mode=mode, parameters=pair_parameters)
                for journey in journeys:
                    legs = tuple(TransitLeg(e.trip_id, e.route_id, TransitMode(e.mode),
                        e.from_stop_id, e.to_stop_id, e.departure_minute, e.arrival_minute,
                        e.stop_ids) for e in journey.events if isinstance(e, NetworkRideEvent))
                    itinerary = TransitItinerary(request.departure_minute + origin.walk_minutes,
                                                  journey.arrival_minute, legs)
                    pairs.append(NetworkPairResult(i, j, itinerary, journey.cost, journey))
        return NetworkBatchResult(tuple(pairs), SearchDiagnostics(request.preference,
            perf_counter() - started, bool(pairs), origin_searches=len(request.origins)))
