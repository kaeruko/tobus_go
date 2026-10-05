"""Offline Tokyo fastest-arrival experiment: static reverse elapsed bounds.

This module never changes production search. The relaxed graph ignores waiting,
services, vehicle runs and walking resources. Its nonnegative elapsed weights
are lower bounds for the forward transitions of the current Tokyo graph.
Concrete timetable ride minima are used only for static queries. Realtime or
unmapped rides use zero; unreachable and unknown nodes also return zero.
"""

from __future__ import annotations

import heapq
import math
import time


def _finite_nonnegative(value, description):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{description} must be finite and nonnegative") from error
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{description} must be finite and nonnegative")
    return result


def _adjacent_minutes(departure, arrival):
    """Downward-round a difference of the stored service-day float clocks."""
    try:
        departure, arrival = float(departure), float(arrival)
    except (TypeError, ValueError, OverflowError):
        return None
    if (not math.isfinite(departure) or not math.isfinite(arrival)
            or departure < 0 or arrival < 0):
        return None
    duration = arrival - departure
    if not math.isfinite(duration) or duration < 0:
        return None
    return max(0.0, math.nextafter(duration, -math.inf)) if duration else 0.0


class TimeBounds:
    __slots__ = ("_values", "report")

    def __init__(self, values, report):
        self._values = values
        self.report = report

    def __call__(self, node):
        return self._values.get(node, 0.0)


def make_time_bounds(graph, choices, target, virtual_connections, *,
                     edge_uses_rail, walk_speed=80.0, rail_boarding_minutes=2.0,
                     check_deadline=lambda: None):
    """Build node-only bounds against the same query-local timetable snapshot.

    For concrete rides, a label cannot leave after the selected run's departure.
    Thus next-arrival minus current-departure bounds its elapsed ride time;
    continued rides may additionally include dwell. Taking the minimum over
    all available runs/calendars and permitting arbitrary run changes is a
    relaxation. This includes later departures that arrive sooner.

    Rail boarding preparation is two minutes and bus boarding has zero fixed
    preparation. A moved bus can alight or transfer in zero minutes, so all
    bus alight/xfer edges use zero, including fresh bus boardings. Rail edges
    use one minute, relying on the production graph's consistent provider/mode
    metadata. Unknown modes/edges use zero.

    Uniform pinned delays mathematically cancel over a ride, but this first
    experiment deliberately uses zero ride bounds whenever realtime is active.
    No timetable minimum is inferred from distance or legacy comfort weights.
    Only queue ordering may consume these bounds; they must not prune states.
    """
    started = time.perf_counter()
    check_deadline()
    walk_speed = _finite_nonnegative(walk_speed, "walk speed")
    if walk_speed == 0:
        raise ValueError("walk speed must be positive")
    rail_boarding_minutes = _finite_nonnegative(rail_boarding_minutes, "rail boarding minutes")
    realtime = bool(choices.use_realtime)
    rail_minima, bus_minima = {}, {}
    rail_records = bus_trips = bus_stops = invalid_intervals = 0
    scanned = 0

    def checkpoint():
        nonlocal scanned
        scanned += 1
        if (scanned & 1023) == 0:
            check_deadline()

    if not realtime:
        for attribute in ("train_patterns_weekday", "train_patterns_weekend"):
            for station, records in getattr(choices.manager, attribute, {}).items():
                checkpoint()
                for record in records:
                    checkpoint()
                    rail_records += 1
                    following = record.get("next_sta")
                    if following is None:
                        continue
                    minutes = _adjacent_minutes(record.get("dep"), record.get("arr"))
                    if minutes is None:
                        invalid_intervals += 1
                        continue
                    key = station, following
                    rail_minima[key] = min(rail_minima.get(key, math.inf), minutes)
        repository = choices.repository
        for trip_id, stop_times in getattr(repository, "stop_times", {}).items():
            checkpoint()
            bus_trips += 1
            trip = getattr(repository, "trips", {}).get(trip_id)
            if not trip or trip.get("route_id") is None:
                continue
            route = trip["route_id"]
            previous = None
            # Keep the same sequence ordering as TimetableChoices._bus_run.
            for _sequence, stop in sorted(stop_times.items()):
                checkpoint()
                bus_stops += 1
                if previous is not None:
                    minutes = _adjacent_minutes(previous[2], stop[1])
                    if minutes is None:
                        invalid_intervals += 1
                    else:
                        key = route, previous[0], stop[0]
                        bus_minima[key] = min(bus_minima.get(key, math.inf), minutes)
                previous = stop
    check_deadline()

    reverse = {}
    for node in graph:
        checkpoint()
        reverse[node] = []
    included_edges = excluded_edges = known_ride_edges = zero_ride_edges = 0
    positive_ride_edges = zero_duration_ride_edges = 0
    maximum_edge_minutes = 0.0

    for u, v, edge in graph.edges(data=True):
        checkpoint()
        if edge_uses_rail(u, v):
            excluded_edges += 1
            continue
        kind = edge.get("etype")
        minutes = 0.0
        if kind == "walk":
            try:
                meters = float(edge.get("meters", 0.0))
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError("walking meters must be finite") from error
            if not math.isfinite(meters):
                raise ValueError("walking meters must be finite")
            minutes = (meters if meters > 0 else 1.0) / walk_speed
        elif kind == "board":
            if graph.nodes[v].get("mode") == "rail":
                minutes = rail_boarding_minutes
        elif kind in ("alight", "xfer"):
            if graph.nodes[u].get("mode") == "rail":
                minutes = 1.0
        elif kind == "ride":
            estimate = None
            if not realtime and graph.nodes[u].get("mode") == "rail":
                estimate = rail_minima.get((u[1], v[1]))
            elif not realtime and graph.nodes[u].get("mode") == "bus":
                route = choices._bus_route(u)
                first, following = choices._stop_id(u[1]), choices._stop_id(v[1])
                if route is not None and first is not None and following is not None:
                    estimate = bus_minima.get((route, first, following))
            if estimate is not None:
                minutes = estimate
                known_ride_edges += 1
            else:
                zero_ride_edges += 1
            if minutes > 0:
                positive_ride_edges += 1
            else:
                zero_duration_ride_edges += 1
        if not math.isfinite(minutes) or minutes < 0:
            raise ValueError("elapsed edge minutes must be finite and nonnegative")
        reverse[v].append((u, minutes))
        included_edges += 1
        maximum_edge_minutes = max(maximum_edge_minutes, minutes)
    check_deadline()

    values = {}
    queue = []
    seeded = set()
    missing_virtual_nodes = 0
    queue_peak = 0
    queue_sequence = 0

    def seed(node, minutes):
        nonlocal queue_peak, queue_sequence
        if minutes < values.get(node, math.inf):
            values[node] = minutes
            # A monotonic sequence avoids ordering unrelated tuple node types.
            heapq.heappush(queue, (minutes, queue_sequence, node))
            queue_sequence += 1
            queue_peak = max(queue_peak, len(queue))

    if target in graph:
        seed(target, 0.0)
        seeded.add(target)
    for node, (cost, meters) in (virtual_connections or {}).items():
        checkpoint()
        _finite_nonnegative(cost, "virtual connection cost")
        meters = _finite_nonnegative(meters, "virtual walking meters")
        if node not in graph:
            missing_virtual_nodes += 1
            continue
        minutes = meters / walk_speed
        if not math.isfinite(minutes):
            raise ValueError("virtual walking minutes must be finite")
        maximum_edge_minutes = max(maximum_edge_minutes, minutes)
        seed(node, minutes)
        seeded.add(node)
    check_deadline()

    popped = settled = relaxed_edges = 0
    while queue:
        checkpoint()
        remaining, _, node = heapq.heappop(queue)
        popped += 1
        if remaining != values[node]:
            continue
        settled += 1
        for previous, minutes in reverse[node]:
            checkpoint()
            relaxed_edges += 1
            candidate = remaining + minutes
            if candidate < values.get(previous, math.inf):
                seed(previous, candidate)
    check_deadline()
    report = {
        "scope": "realtime: zero ride bounds" if realtime else "static: all-calendar adjacent timetable minima",
        "nodes": len(graph), "allocated_states": len(graph),
        "max_reverse_steps": len(graph) + 1,
        "included_edges": included_edges, "excluded_edges": excluded_edges,
        "known_ride_edges": known_ride_edges, "zero_ride_edges": zero_ride_edges,
        "positive_ride_edges": positive_ride_edges,
        "zero_duration_ride_edges": zero_duration_ride_edges,
        "max_edge_minutes": maximum_edge_minutes,
        "rail_records_scanned": rail_records, "bus_trips_scanned": bus_trips,
        "bus_stops_scanned": bus_stops,
        "rail_interval_pairs": len(rail_minima), "bus_interval_pairs": len(bus_minima),
        "invalid_intervals": invalid_intervals,
        "scan_checkpoints": scanned, "settled_nodes": settled,
        "queue_pops": popped, "queue_peak": queue_peak, "relaxed_edges": relaxed_edges,
        "seeded_nodes": len(seeded), "missing_virtual_nodes": missing_virtual_nodes,
        "unreachable_nodes": len(graph) - len(values),
        "walking_resources": "fully relaxed",
        "unreachable_policy": "zero bound; priority only, no pruning",
        "build_ms": (time.perf_counter() - started) * 1000.0,
    }
    return TimeBounds(values, report)
