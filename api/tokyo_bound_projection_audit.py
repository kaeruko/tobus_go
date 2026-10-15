"""Opt-in read-only comparison of Tokyo A* relaxed graph projection.

The old bound is the oracle: audit-only observers expose the EXACT weights
that make_time_bounds places in its reverse graph and its initial destination
seeds. A separately traversed complete common bus/rail snapshot supplies the
expected adjacent minima. No route searches, bounds switch, realtime, writes
to source artifacts or fallback to a zero bound are performed here.

This proves graph projection only; destination distances, floating-point guard,
admissibility, full candidate ranking and production readiness remain separate.
"""
from __future__ import annotations

import hashlib
import math

from route_engine import RouteContractError
from reviewed_walk_time import walk_edge_elapsed_minutes
from tokyo_dataset_bus_choices import TokyoBusDatasetBinding
from tokyo_dataset_rail_choices import TokyoRailDatasetBinding, _source_digest
from tokyo_rail_interval_audit import _collect_static_rail_minima
from tokyo_time_bounds import _adjacent_minutes, make_time_bounds
from tokyo_timetable_choices import TimetableChoices


def _common_bus_minima(binding, check_deadline):
    """Independent all-service adjacency projection, not the prior min audit."""
    if type(binding) is not TokyoBusDatasetBinding:
        raise RouteContractError("projection requires a validated common bus binding")
    snapshot = binding.snapshot
    minima = {}
    count = 0
    for trip_key, trip in snapshot.trips.items():
        check_deadline()
        rows = snapshot.rows_by_trip[trip_key]
        route = snapshot.routes[trip.route_id].source_id
        for first, second in zip(rows, rows[1:]):
            check_deadline()
            key = (route, snapshot.stops[first.stop_id].source_id,
                   snapshot.stops[second.stop_id].source_id)
            value = _adjacent_minutes(first.departure_minute, second.arrival_minute)
            if value is None:
                raise RouteContractError("common bus projection has an invalid interval")
            minima[key] = min(value, minima.get(key, math.inf))
            count += 1
    if not minima:
        raise RouteContractError("common bus projection has no intervals")
    return minima, count


def _identity_digest(first, second=None):
    return hashlib.sha256(repr((first, second)).encode("utf-8")).hexdigest()


def _opaque_bus_lines(graph, choices, edge_uses_rail, checkpoint):
    """Conservatively disable concrete bus minima for opaque board entries."""
    opaque = set()
    for u, v, edge in graph.edges(data=True):
        checkpoint()
        if edge_uses_rail(u, v):
            continue
        kind = edge.get("etype")
        a_mode, b_mode = graph.nodes[u].get("mode"), graph.nodes[v].get("mode")
        if b_mode in ("bus", "rail") and kind not in ("board", "ride"):
            raise RouteContractError("projection reference would use a zero bound for a noncanonical entry")
        if kind == "ride" and (a_mode != b_mode or (
            a_mode in ("bus", "rail") and choices._line_id(u) != choices._line_id(v)
        )):
            raise RouteContractError("projection reference would use a zero bound for an incompatible ride")
        if kind == "board" and b_mode == "bus":
            route = choices._bus_route(v)
            stop = choices._stop_id(u[1])
            loaded = bool(getattr(choices.repository, "trips", {}))
            concrete = loaded and route is not None and stop is not None
            unsupported_odpt = loaded and choices._has_bus_data and "BusstopPole" in str(u[1])
            if not concrete and not unsupported_odpt:
                opaque.add(choices._line_id(v))
    return opaque


def _checked_walk_minutes(edge, walk_speed):
    try:
        meters = float(edge.get("meters", 0.0))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("walking meters must be finite") from exc
    if not math.isfinite(meters):
        raise ValueError("walking meters must be finite")
    return walk_edge_elapsed_minutes(edge, speed_m_per_min=walk_speed)


def _compare_projection(
    graph, choices, rail_minima, bus_minima, target, virtual_connections, *,
    edge_uses_rail, check_deadline=lambda: None, walk_speed=80.0,
    rail_boarding_minutes=2.0, observed_edge_transform=None,
):
    """Observe every reference edge and seed, compare an independent projection.

    observed_edge_transform is a synthetic-test-only fault injector: never use
    it in a local-source audit. A mismatch must stop without another provider.
    """
    if type(choices) is not TimetableChoices or choices.use_realtime is not False:
        raise RouteContractError("projection audit requires a static reference Tokyo provider")
    if not math.isfinite(walk_speed) or walk_speed <= 0 or not math.isfinite(rail_boarding_minutes) or rail_boarding_minutes < 0:
        raise ValueError("projection walk speed/rail boarding minutes must be finite")
    if not getattr(choices, "_has_rail_data", False) or not choices.repository.trips:
        raise RouteContractError("projection audit requires both concrete rail and bus data")

    opaque = _opaque_bus_lines(graph, choices, edge_uses_rail, check_deadline)
    expected_edges = {}
    stats = {"included_edges": 0, "excluded_edges": 0, "rail_rides": 0,
             "bus_rides": 0, "known_ride_edges": 0, "zero_ride_edges": 0,
             "walk_edges": 0, "board_edges": 0, "alight_transfer_edges": 0}
    for u, v, edge in graph.edges(data=True):
        check_deadline()
        if edge_uses_rail(u, v):
            expected_edges[u, v] = None
            stats["excluded_edges"] += 1
            continue
        kind = edge.get("etype")
        value = 0.0
        if kind == "walk":
            value = _checked_walk_minutes(edge, walk_speed)
            stats["walk_edges"] += 1
        elif kind == "board":
            stats["board_edges"] += 1
            if graph.nodes[v].get("mode") == "rail":
                value = rail_boarding_minutes
        elif kind in ("alight", "xfer"):
            stats["alight_transfer_edges"] += 1
            if graph.nodes[u].get("mode") == "rail":
                value = 1.0
        elif kind == "ride":
            estimate = None
            if graph.nodes[u].get("mode") == "rail":
                stats["rail_rides"] += 1
                estimate = rail_minima.get((u[1], v[1]))
            elif (graph.nodes[u].get("mode") == "bus"
                  and choices._line_id(u) not in opaque):
                stats["bus_rides"] += 1
                route = choices._bus_route(u)
                first, last = choices._stop_id(u[1]), choices._stop_id(v[1])
                if route is not None and first is not None and last is not None:
                    estimate = bus_minima.get((route, first, last))
            if estimate is None:
                stats["zero_ride_edges"] += 1
            else:
                stats["known_ride_edges"] += 1
                value = estimate
        if not math.isfinite(value) or value < 0:
            raise RouteContractError("common graph projection contains invalid edge time")
        expected_edges[u, v] = value
        stats["included_edges"] += 1

    expected_seeds = []
    if target in graph:
        expected_seeds.append((target, 0.0))
    missing_virtual = 0
    for node, (cost, meters) in (virtual_connections or {}).items():
        check_deadline()
        try:
            cost, meters = float(cost), float(meters)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("virtual destination cost/meters must be finite") from exc
        if not math.isfinite(cost) or cost < 0 or not math.isfinite(meters) or meters < 0:
            raise ValueError("virtual destination cost/meters must be finite and nonnegative")
        if node not in graph:
            missing_virtual += 1
            continue
        minute = meters / walk_speed
        if not math.isfinite(minute):
            raise ValueError("virtual destination minutes must be finite")
        expected_seeds.append((node, minute))

    witnessed = set()
    observed_seeds = []
    def observe_edge(u, v, value):
        key = u, v
        if key not in expected_edges or key in witnessed:
            raise RouteContractError("reference graph projection has missing or repeated edge")
        witnessed.add(key)
        if observed_edge_transform is not None:
            value = observed_edge_transform(u, v, value)
        if value != expected_edges[key]:
            raise RouteContractError(
                "common graph edge weight differs: edge_sha256="
                + _identity_digest(u, v)
                + " expected=" + repr(expected_edges[key])
                + " reference=" + repr(value)
            )
    def observe_seed(node, value):
        observed_seeds.append((node, value))

    reference = make_time_bounds(
        graph, choices, target, virtual_connections,
        edge_uses_rail=edge_uses_rail, check_deadline=check_deadline,
        walk_speed=walk_speed, rail_boarding_minutes=rail_boarding_minutes,
        projection_edge_observer=observe_edge,
        projection_seed_observer=observe_seed,
    )
    check_deadline()
    if not reference.report["scope"].startswith("static:"):
        raise RouteContractError("reference graph bound disabled; no zero-bound acceptance")
    if len(witnessed) != len(expected_edges) or observed_seeds != expected_seeds:
        raise RouteContractError("common graph projection edge/seed coverage differs")
    if reference.report["included_edges"] != stats["included_edges"] or (
        reference.report["excluded_edges"] != stats["excluded_edges"] or
        reference.report["known_ride_edges"] != stats["known_ride_edges"] or
        reference.report["zero_ride_edges"] != stats["zero_ride_edges"] or
        reference.report["missing_virtual_nodes"] != missing_virtual
    ):
        raise RouteContractError("common graph projection reference counters differ")
    if (reference.report["rail_interval_pairs"] != len(rail_minima)
            or reference.report["bus_interval_pairs"] != len(bus_minima)):
        raise RouteContractError("common graph projection source pair scope differs")
    return {
        "common_graph_edge_projection_verified": True,
        "common_graph_seed_projection_verified": True,
        "edge_projection_uses_reference_provider": True,
        "graph_nodes": len(graph), "graph_edges": len(expected_edges),
        "target_in_graph": target in graph, "virtual_seed_entries": len(expected_seeds) - int(target in graph),
        "missing_virtual_nodes": missing_virtual,
        "reference_static_scope": reference.report["scope"],
        "opaque_bus_lines": len(opaque),
        **stats,
        "common_rail_interval_pairs": len(rail_minima),
        "common_bus_interval_pairs": len(bus_minima),
        "destination_bounds_verified": False,
        "priority_rounding_verified": False,
        "realtime_verified": False,
        "common_dataset_route_ranking_verified": False,
        "true_top_k_verified": False,
    }


def verify_static_graph_projection(
    graph, manager, repository, rail_binding, bus_binding, *,
    target, virtual_connections=None, edge_uses_rail,
    check_deadline=lambda: None, walk_speed=80.0, rail_boarding_minutes=2.0,
):
    """Compare complete common source interval lookup at every Tokyo graph edge.

    Full all-calendar scopes are used even when an edge is currently unboardable.
    Does NOT invoke previously passed standalone rail/bus interval audits.
    """
    check_deadline()
    if type(rail_binding) is not TokyoRailDatasetBinding or (
        type(bus_binding) is not TokyoBusDatasetBinding
    ):
        raise RouteContractError("both validated static Tokyo common bindings are required")
    if bus_binding.repository is not repository:
        raise RouteContractError("projection requires the source-bound bus repository")
    if _source_digest(manager) != rail_binding.source_digest:
        raise RouteContractError("rail source changed since common binding validation")
    rail_minima, rail_trips, rail_stops, rail_intervals = _collect_static_rail_minima(
        rail_binding.snapshot, check_deadline
    )
    bus_minima, bus_intervals = _common_bus_minima(bus_binding, check_deadline)
    check_deadline()
    # The date/profile does not restrict the all-calendar static minima.
    # Use an explicit artificial date solely to construct the unmodified
    # reference provider; no real timetable boarding or route search happens.
    from datetime import date
    from toei_engine import ServiceDayType
    day = date(2026, 9, 4)
    profile = ServiceDayType("weekday", day, repository.get_active_service_ids(day), True)
    choices = TimetableChoices(graph, manager, day_type=profile, use_realtime=False,
                               deadline=3000, bus_repository=repository)
    report = _compare_projection(
        graph, choices, rail_minima, bus_minima, target, virtual_connections or {},
        edge_uses_rail=edge_uses_rail, check_deadline=check_deadline,
        walk_speed=walk_speed, rail_boarding_minutes=rail_boarding_minutes,
    )
    check_deadline()
    if _source_digest(manager) != rail_binding.source_digest:
        raise RouteContractError("rail source changed during graph projection")
    return {
        **report, "common_rail_source_trips": rail_trips,
        "common_rail_source_stop_times": rail_stops,
        "common_rail_source_intervals": rail_intervals,
        "common_bus_source_intervals": bus_intervals,
        "calendar_scope": "all_source_calendars_no_date_filter",
        "graph_provider": "unchanged_tokyo_reference",
        "common_bounds_provider": "not_selected_audit_only",
    }
