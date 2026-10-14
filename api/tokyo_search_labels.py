"""Tokyo integration for the shared resource-aware label search.

Keep this module and its public entry points stable for existing callers and
saved SelectedPath identities. Tokyo's data, lower bounds and detail metadata
remain here; the frontier and expansion algorithm live in transit_search_labels.
"""

from __future__ import annotations

# Existing diagnostic tests patch these shared stdlib module objects.
import heapq
import time
from dataclasses import replace

from route_engine import RouteContractError, RouteSearchLimitError
from tokyo_few_transfers_bounds import CostRoundingGuard, make_bounds
from tokyo_time_bounds import make_time_bounds
from tokyo_time_rounding import TimeRoundingGuard
from tokyo_route_signatures import transit_path_signature
from transit_search_labels import (
    SelectedPath as _SharedSelectedPath,
    _Frontier, _Label, _compact_queue,
    _path as _shared_path,
    search_labels as _shared_search_labels,
)


class SelectedPath(_SharedSelectedPath):
    """Ordinary path nodes with query-local clocks and selected vehicle runs.

    List equality/serialization stays compatible with existing callers.  The
    private selection is consumed by detail generation before path is removed
    from the HTTP response.
    """

    def __init__(self, nodes, edge_times, edge_rides, choices, start_minute):
        super().__init__(nodes, edge_times, edge_rides, choices, start_minute)
        self.timetable_manager = choices.manager
        self.use_realtime = choices.use_realtime


def _path(label, choices, start_minute):
    return _shared_path(label, choices, start_minute, SelectedPath)


def _alight_minutes(ride):
    moved_bus = ride.provider == "bus" and ride.sequence != ride.board_sequence
    return 0.0 if moved_bus else 1.0


def search_labels(graph, choices, start, target, *, mode, start_minute,
                  max_search, max_visited, max_travel_min, time_limit_sec,
                  max_total_walk, max_segment_walk, walk_speed,
                  rail_boarding_minutes, advance_time, virtual_connections,
                  edge_uses_rail, heuristic=lambda node: 0.0,
                  max_expanded=None):
    """Delegate with the unchanged Tokyo clocks, bounds and selected runs."""
    def prepare_bounds(check_deadline, deadline):
        bounds = cost_bound = arrival_bound = None
        if mode == "time":
            # Static interval minima are shared by data version; the reverse graph
            # and destination bound live only for this query. Timetable waiting,
            # run continuity and exact walking limits stay in the forward search.
            try:
                bounds = make_time_bounds(
                    graph, choices, target, virtual_connections,
                    edge_uses_rail=edge_uses_rail, walk_speed=walk_speed,
                    rail_boarding_minutes=rail_boarding_minutes,
                    check_deadline=check_deadline, start=start,
                )
            except ValueError as error:
                raise RouteContractError(f"Tokyo time lower bound is invalid: {error}") from error
            check_deadline()
            arrival_bound = TimeRoundingGuard(
                start_minute=start_minute, deadline=deadline,
                max_forward_steps=max_visited,
                max_reverse_steps=bounds.report.get("nodes", 0) + 1,
                max_edge_minutes=bounds.report.get("max_edge_minutes", 0.0),
            )
            bounds.report["arrival_rounding_guard"] = arrival_bound.report

        if mode == "fewTransfers":
            # Query-local: no destination cache can retain graph or service data.
            # The relaxed pair changes ordering only; it never prunes a label or
            # changes the exact walking/run resources in the shared frontier.
            try:
                bounds = make_bounds(
                    graph, target, virtual_connections, edge_uses_rail=edge_uses_rail,
                    max_segment_walk=max_segment_walk, check_deadline=check_deadline,
                )
            except ValueError as error:
                raise RouteContractError(f"Tokyo fewTransfers lower bound is invalid: {error}") from error
            check_deadline()
            # Preserve forward float-cost comparisons near ties. The guard covers
            # every addition in a returned path (bounded by actual heap pops),
            # the relaxed simple path, and the final g+h rounding. Virtual edges
            # count too; this only lowers a queue estimate, never a candidate cost.
            maximum_edge_cost = max(
                bounds.report.get("graph_max_edge_cost", 0.0),
                max((float(cost) for cost, _ in virtual_connections.values()), default=0.0),
            )
            cost_bound = CostRoundingGuard(
                max_edge_cost=maximum_edge_cost, max_forward_steps=max_visited,
                max_reverse_steps=bounds.report.get("allocated_states", 0) + 1,
            )
            bounds.report["cost_rounding_guard"] = {
                "max_edge_cost": maximum_edge_cost,
                "max_forward_steps": max_visited,
                "max_reverse_steps": bounds.report.get("allocated_states", 0) + 1,
            }

        return bounds, cost_bound, arrival_bound

    def ride_options(u, v, current_time, ride, edge):
        if ride.provider.startswith("opaque-"):
            # Explicit graph-only test contract; not a production data fallback.
            arrival = advance_time(u, v, current_time, edge)
            return () if arrival is None else ((arrival, replace(
                ride, sequence=ride.sequence + 1)),)
        return choices.ride_options(u, v, current_time, ride)

    yield from _shared_search_labels(
        graph, choices, start, target, mode=mode, start_minute=start_minute,
        max_search=max_search, max_visited=max_visited,
        max_travel_min=max_travel_min, time_limit_sec=time_limit_sec,
        max_total_walk=max_total_walk, max_segment_walk=max_segment_walk,
        walk_speed=walk_speed, rail_boarding_minutes=rail_boarding_minutes,
        advance_time=advance_time, virtual_connections=virtual_connections,
        edge_uses_rail=edge_uses_rail, heuristic=heuristic,
        max_expanded=max_expanded, prepare_bounds=prepare_bounds,
        path_signature=lambda nodes: transit_path_signature(graph, nodes, transit_only=True),
        path_factory=SelectedPath, compact_queue=_compact_queue,
        ride_options=ride_options, alight_minutes=_alight_minutes,
        walk_meters=lambda edge: (edge.get("meters", 0.0)
                                 if edge.get("meters", 0.0) > 0 else 1.0),
    )
