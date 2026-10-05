"""Tokyo fastest-arrival reverse bounds over a relaxed elapsed-time graph.

Only queue priority may use the bound. Waiting, services, vehicle runs and
walking resources are relaxed; the exact forward search remains unchanged.
Completed static interval indexes live on their data owners, while destination
bounds live for one query. Realtime uses the same adjacent minima together with
the caller's TimeRoundingGuard, which covers pinned-delay clock rounding.
"""

from __future__ import annotations

import heapq
import math
import time

from tokyo_timetable_choices import TimetableChoices


_RAIL_INDEX_ATTRIBUTE = "_tokyo_time_rail_interval_index"
_BUS_INDEX_ATTRIBUTE = "_tokyo_time_bus_interval_index"
_INDEX_VERSION = 1
_STANDARD_BOARD_OPTIONS = TimetableChoices.board_options
_STANDARD_RIDE_OPTIONS = TimetableChoices.ride_options


class _IntervalIndex:
    __slots__ = ("version", "token", "sources", "minima", "records", "trips", "stops", "invalid")

    def __init__(self, token, sources, minima, *, records=0, trips=0, stops=0, invalid=0):
        self.version = _INDEX_VERSION
        self.token, self.sources, self.minima = token, sources, minima
        self.records, self.trips, self.stops, self.invalid = records, trips, stops, invalid


def _rail_sources(manager):
    return tuple(getattr(manager, name, None) for name in
                 ("train_patterns_weekday", "train_patterns_weekend"))


def _rail_token(manager, sources, check_deadline):
    rows = []
    for source in sources:
        entries = []
        for index, (station, records) in enumerate((source or {}).items()):
            if (index & 1023) == 0:
                check_deadline()
            entries.append((station, id(records), len(records)))
        rows.append((id(source), len(source or {}), tuple(entries)))
    return (getattr(manager, "_tokyo_time_bounds_generation", 0), tuple(rows))


def _bus_sources(repository):
    return (getattr(repository, "trips", None), getattr(repository, "stop_times", None))


def _bus_token(repository, sources):
    trips, stops = sources
    return (id(trips), id(stops), len(trips or {}), len(stops or {}),
            getattr(repository, "source_dir", None), getattr(repository, "feed_id", None),
            getattr(repository, "_tokyo_time_bounds_generation", 0))


def _cached(owner, attribute, token):
    value = getattr(owner, attribute, None)
    return value if (isinstance(value, _IntervalIndex)
                     and getattr(value, "version", None) == _INDEX_VERSION
                     and value.token == token) else None


def _publish(owner, attribute, value):
    if owner is not None:
        try:
            setattr(owner, attribute, value)
        except AttributeError:
            pass  # Read-only or slotted custom fixtures get a query-local index.


def invalidate_static_time_index(manager=None, repository=None):
    """Call after in-place schedule edits; complete map replacement is automatic.

    Rail station-list replacement/append is also detected by its identity and
    length signature. Same-length edits inside records, and nested bus edits,
    require this hook before publishing the updated static data. Realtime
    updates need no invalidation. Static edits must not overlap an active query,
    matching TimetableChoices' existing immutable-static-snapshot contract.
    """
    for owner, attribute in ((manager, _RAIL_INDEX_ATTRIBUTE),
                             (repository, _BUS_INDEX_ATTRIBUTE)):
        if owner is None:
            continue
        try:
            delattr(owner, attribute)
        except AttributeError:
            pass
        try:
            owner._tokyo_time_bounds_generation = getattr(
                owner, "_tokyo_time_bounds_generation", 0) + 1
        except AttributeError:
            pass


def _build_rail_index(token, sources, checkpoint):
    minima = {}
    records_count = invalid = 0
    for source in sources:
        for station, records in (source or {}).items():
            checkpoint()
            for record in records:
                checkpoint()
                records_count += 1
                following = record.get("next_sta")
                if following is None:
                    continue
                key = station, following
                minutes = _adjacent_minutes(record.get("dep"), record.get("arr"))
                if minutes is None:
                    invalid += 1
                    # Never let another valid record turn an uncertain pair
                    # into a positive bound (e.g. a negative source clock that
                    # becomes boardable after a realtime shift).
                    minima[key] = 0.0
                    continue
                minima[key] = min(minima.get(key, math.inf), minutes)
    return _IntervalIndex(token, sources, minima, records=records_count, invalid=invalid)


def _build_bus_index(token, sources, checkpoint):
    trips, stop_times = sources
    minima = {}
    trip_count = stop_count = invalid = 0
    for trip_id, rows in (stop_times or {}).items():
        checkpoint()
        trip_count += 1
        trip = (trips or {}).get(trip_id)
        if not trip or trip.get("route_id") is None:
            continue
        previous = None
        for _sequence, stop in sorted(rows.items()):
            checkpoint()
            stop_count += 1
            if previous is not None:
                key = trip["route_id"], previous[0], stop[0]
                minutes = _adjacent_minutes(previous[2], stop[1])
                if minutes is None:
                    invalid += 1
                    minima[key] = 0.0
                else:
                    minima[key] = min(minima.get(key, math.inf), minutes)
            previous = stop
    return _IntervalIndex(token, sources, minima, trips=trip_count, stops=stop_count, invalid=invalid)


def _indexes(manager, repository, check_deadline, *, force=False):
    started = time.perf_counter()
    scans = 0

    def checkpoint():
        nonlocal scans
        scans += 1
        if (scans & 1023) == 0:
            check_deadline()

    check_deadline()
    rail_sources, bus_sources = _rail_sources(manager), _bus_sources(repository)
    rail_token = _rail_token(manager, rail_sources, check_deadline)
    bus_token = _bus_token(repository, bus_sources)
    rail = None if force else _cached(manager, _RAIL_INDEX_ATTRIBUTE, rail_token)
    bus = None if force else _cached(repository, _BUS_INDEX_ATTRIBUTE, bus_token)
    rail_reused, bus_reused = rail is not None, bus is not None
    if rail is None:
        rail = _build_rail_index(rail_token, rail_sources, checkpoint)
    check_deadline()
    if bus is None:
        bus = _build_bus_index(bus_token, bus_sources, checkpoint)
    check_deadline()
    # Build both in locals. An exception or changing source cannot publish a
    # half-completed index for another query to observe.
    if (rail_token != _rail_token(manager, _rail_sources(manager), check_deadline)
            or bus_token != _bus_token(repository, _bus_sources(repository))):
        raise ValueError("static Tokyo timetables changed during index construction")
    if not rail_reused:
        _publish(manager, _RAIL_INDEX_ATTRIBUTE, rail)
    if not bus_reused:
        _publish(repository, _BUS_INDEX_ATTRIBUTE, bus)
    return rail, bus, {
        "rail_index_reused": rail_reused, "bus_index_reused": bus_reused,
        "rail_records_scanned": 0 if rail_reused else rail.records,
        "bus_trips_scanned": 0 if bus_reused else bus.trips,
        "bus_stops_scanned": 0 if bus_reused else bus.stops,
        "rail_source_records": rail.records, "bus_source_trips": bus.trips,
        "bus_source_stops": bus.stops,
        "index_scan_checkpoints": scans,
        "index_build_ms": (time.perf_counter() - started) * 1000.0,
    }


def prepare_static_time_index(manager, repository, *, check_deadline=lambda: None, force=False):
    """Warm completed indexes after startup data loading, before manager freezing.

    The original manager's rail index is inherited by shallow query snapshots;
    the bus index is attached to the persistent repository. Container identity,
    rail station-list sizes, repository source identity and explicit generation
    invalidate reuse. In-place updates must call invalidate_static_time_index.
    No destination, graph, live delay or query frontier is cached.
    """
    return _indexes(manager, repository, check_deadline, force=force)[2]

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
                     check_deadline=lambda: None, start=None):
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

    Uniform pinned delays cancel over a ride in real arithmetic. For realtime,
    the caller must use TimeRoundingGuard to cover both endpoint clock-rounding
    errors, reverse additions and g+h. It also preserves static float clocks.
    A line start without an active ride, noncanonical entries into ride nodes,
    or inconsistent ride modes/lines disable the entire bound. Opaque/custom
    evaluators do not acquire concrete-run minima. No timetable
    minimum is inferred from distance or legacy comfort weights. Only queue
    ordering may consume these bounds; they must not prune states.
    """
    started = time.perf_counter()
    check_deadline()
    walk_speed = _finite_nonnegative(walk_speed, "walk speed")
    if walk_speed == 0:
        raise ValueError("walk speed must be positive")
    rail_boarding_minutes = _finite_nonnegative(rail_boarding_minutes, "rail boarding minutes")
    realtime = bool(getattr(choices, "use_realtime", False))
    rail_minima, bus_minima = {}, {}
    invalid_intervals = 0
    scanned = 0

    def checkpoint():
        nonlocal scanned
        scanned += 1
        if (scanned & 1023) == 0:
            check_deadline()

    standard = (
        type(choices) is TimetableChoices
        and getattr(choices.board_options, "__func__", None) is _STANDARD_BOARD_OPTIONS
        and getattr(choices.ride_options, "__func__", None) is _STANDARD_RIDE_OPTIONS
    )
    has_concrete = (getattr(choices, "_has_rail_data", False)
                    or bool(getattr(getattr(choices, "repository", None), "trips", {})))
    def zero_bound(scope):
        check_deadline()
        report = {
            "scope": scope,
            "nodes": len(graph), "allocated_states": len(graph),
            "max_reverse_steps": len(graph) + 1, "max_edge_minutes": 0.0,
            "included_edges": 0, "excluded_edges": 0,
            "known_ride_edges": 0, "zero_ride_edges": 0,
            "positive_ride_edges": 0, "zero_duration_ride_edges": 0,
            "rail_records_scanned": 0, "bus_trips_scanned": 0, "bus_stops_scanned": 0,
            "rail_interval_pairs": 0, "bus_interval_pairs": 0,
            "invalid_intervals": 0, "scan_checkpoints": 0,
            "settled_nodes": 0, "queue_pops": 0, "queue_peak": 0,
            "relaxed_edges": 0, "seeded_nodes": 0, "missing_virtual_nodes": 0,
            "unreachable_nodes": len(graph), "walking_resources": "fully relaxed",
            "unreachable_policy": "zero bound; priority only, no pruning",
            "rail_index_reused": False, "bus_index_reused": False,
            "index_build_ms": 0.0, "index_scan_checkpoints": 0,
            "interval_index_version": _INDEX_VERSION,
            "build_ms": (time.perf_counter() - started) * 1000.0,
        }
        return TimeBounds({}, report)
    if not standard or not has_concrete:
        return zero_bound("custom or opaque-only evaluator: zero bound")
    if (start is not None and start in graph
            and graph.nodes[start].get("mode") in ("bus", "rail")
            and (graph.nodes[start].get("kind") == "line"
                 or isinstance(start, tuple) and start and start[0] == "line")):
        return zero_bound("line start without a concrete ride: zero bound")
    opaque_bus_lines = set()
    for u, v, edge in graph.edges(data=True):
        checkpoint()
        if edge_uses_rail(u, v):
            continue
        kind = edge.get("etype")
        first_mode, next_mode = graph.nodes[u].get("mode"), graph.nodes[v].get("mode")
        if next_mode in ("bus", "rail") and kind not in ("board", "ride"):
            return zero_bound("noncanonical entry into a ride node: zero bound")
        if kind == "ride":
            if first_mode != next_mode:
                return zero_bound("ride endpoint modes differ: zero bound")
            if first_mode in ("bus", "rail") and choices._line_id(u) != choices._line_id(v):
                return zero_bound("ride endpoint lines differ: zero bound")
        if kind != "board" or next_mode != "bus":
            continue
        route = choices._bus_route(v)
        stop = choices._stop_id(u[1])
        repository_loaded = bool(getattr(choices.repository, "trips", {}))
        concrete = repository_loaded and route is not None and stop is not None
        unavailable_odpt = (repository_loaded and choices._has_bus_data
                            and "BusstopPole" in str(u[1]))
        if not concrete and not unavailable_odpt:
            opaque_bus_lines.add(choices._line_id(v))
    check_deadline()
    rail_index, bus_index, index_report = _indexes(
        choices.manager, choices.repository, check_deadline)
    rail_minima, bus_minima = rail_index.minima, bus_index.minima
    invalid_intervals = rail_index.invalid + bus_index.invalid

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
            if choices._has_rail_data and graph.nodes[u].get("mode") == "rail":
                estimate = rail_minima.get((u[1], v[1]))
            elif (graph.nodes[u].get("mode") == "bus"
                  and choices._line_id(u) not in opaque_bus_lines):
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
        "scope": ("realtime: guarded all-calendar adjacent timetable minima" if realtime
                  else "static: all-calendar adjacent timetable minima"),
        "nodes": len(graph), "allocated_states": len(graph),
        "max_reverse_steps": len(graph) + 1,
        "included_edges": included_edges, "excluded_edges": excluded_edges,
        "known_ride_edges": known_ride_edges, "zero_ride_edges": zero_ride_edges,
        "positive_ride_edges": positive_ride_edges,
        "zero_duration_ride_edges": zero_duration_ride_edges,
        "max_edge_minutes": maximum_edge_minutes,
        "rail_records_scanned": index_report["rail_records_scanned"],
        "bus_trips_scanned": index_report["bus_trips_scanned"],
        "bus_stops_scanned": index_report["bus_stops_scanned"],
        "rail_interval_pairs": len(rail_minima), "bus_interval_pairs": len(bus_minima),
        "invalid_intervals": invalid_intervals,
        "scan_checkpoints": scanned, "settled_nodes": settled,
        "queue_pops": popped, "queue_peak": queue_peak, "relaxed_edges": relaxed_edges,
        "seeded_nodes": len(seeded), "missing_virtual_nodes": missing_virtual_nodes,
        "unreachable_nodes": len(graph) - len(values),
        "walking_resources": "fully relaxed",
        "unreachable_policy": "zero bound; priority only, no pruning",
        "opaque_bus_lines": len(opaque_bus_lines),
        "interval_index_version": _INDEX_VERSION,
        **index_report,
        "build_ms": (time.perf_counter() - started) * 1000.0,
    }
    return TimeBounds(values, report)
