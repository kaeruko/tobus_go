"""Read-only stage 3: common all-node bounds and guarded priority parity.

The common reverse graph is built from common interval maps, never from a
reference bound/observer. Runtime make_time_bounds and TimeRoundingGuard stay
unchanged. Equality and conditional error budgets do not certify an unbounded
legal-suffix step count, route ranking, or production readiness.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import heapq
import math
from types import MappingProxyType

from route_engine import RouteContractError
from tokyo_bound_projection_audit import _checked_walk_minutes, _common_bus_minima, _opaque_bus_lines
from tokyo_dataset_bus_choices import TokyoBusDatasetBinding
from tokyo_dataset_rail_choices import TokyoRailDatasetBinding, _source_digest
from tokyo_rail_interval_audit import _collect_static_rail_minima
from tokyo_time_bounds import TimeBounds, make_time_bounds
from tokyo_time_rounding import TimeRoundingGuard
from tokyo_time_rounding_audit import float_bits, verify_guard_coefficients, verify_guard_equivalence
from tokyo_timetable_choices import TimetableChoices


def _digest_rows(rows, checkpoint):
    digest = hashlib.sha256()
    for row in rows:
        checkpoint()
        encoded = repr(row).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _graph_digest(graph, checkpoint):
    def rows():
        yield ("nodes", len(graph))
        yield from graph.nodes(data=True)
        yield ("edges", graph.number_of_edges())
        yield from graph.edges(data=True)
    return _digest_rows(rows(), checkpoint)


def _sources_digest(manager, repository, checkpoint):
    def rows():
        yield _source_digest(manager)
        yield ("bus_source", repository.feed_id, repository.source_dir)
        for name in ("trips", "stop_times", "stop_time_boarding", "routes", "stops",
                     "route_name_to_id", "service_calendar", "service_exceptions"):
            values = getattr(repository, name)
            yield (name, len(values))
            yield from values.items()
    return _digest_rows(rows(), checkpoint)


@dataclass(frozen=True)
class CommonIntervalInputs:
    rail: object
    bus: object
    manager: object
    repository: object
    source_digest: str
    counts: object

    def check_sources(self, checkpoint=lambda: None):
        if self.source_digest != _sources_digest(self.manager, self.repository, checkpoint):
            raise RouteContractError("static sources changed during destination bound audit")


def collect_common_inputs(rail_binding, bus_binding, manager, repository, *,
                          check_deadline=lambda: None):
    """Build common inputs once, without invoking any passed standalone gate."""
    check_deadline()
    if (type(rail_binding) is not TokyoRailDatasetBinding
            or type(bus_binding) is not TokyoBusDatasetBinding
            or bus_binding.repository is not repository):
        raise RouteContractError("destination audit requires source-bound static common bindings")
    if _source_digest(manager) != rail_binding.source_digest:
        raise RouteContractError("rail source changed since common binding validation")
    # Bus binding has no source digest. Revalidate its exact source rows once
    # before consuming it, rather than trusting an old binding after mutation.
    TokyoBusDatasetBinding(bus_binding.snapshot, repository)
    before = _sources_digest(manager, repository, check_deadline)
    rail, trips, stops, intervals = _collect_static_rail_minima(
        rail_binding.snapshot, check_deadline)
    bus, bus_intervals = _common_bus_minima(bus_binding, check_deadline)
    result = CommonIntervalInputs(
        MappingProxyType(rail), MappingProxyType(bus), manager, repository, before,
        MappingProxyType({"rail_source_trips": trips, "rail_source_stop_times": stops,
                          "rail_source_intervals": intervals,
                          "bus_source_intervals": bus_intervals}),
    )
    result.check_sources(check_deadline)
    check_deadline()
    return result


@dataclass(frozen=True)
class CommonProjection:
    graph: object
    choices: object
    nodes: tuple
    reverse: object
    counts: object
    max_edge_minutes: float
    walk_speed: float
    rail_boarding_minutes: float
    graph_digest: str


def project_common_graph(graph, choices, rail_minima, bus_minima, *, edge_uses_rail,
                         check_deadline=lambda: None, walk_speed=80.0,
                         rail_boarding_minutes=2.0):
    """Preserve graph identities and iteration order; never mutate/contract G."""
    check_deadline()
    if (type(choices) is not TimetableChoices or choices.use_realtime is not False
            or choices.graph is not graph or not choices._has_rail_data
            or not getattr(choices.repository, "trips", None)):
        raise RouteContractError("destination audit requires the static reference Tokyo provider")
    # Match make_time_bounds' declared parameter conversion up front. Tokyo's
    # production rail-boarding constant is an int; elapsed weights are floats.
    walk_speed, rail_boarding_minutes = float(walk_speed), float(rail_boarding_minutes)
    if (not math.isfinite(walk_speed) or walk_speed <= 0
            or not math.isfinite(rail_boarding_minutes) or rail_boarding_minutes < 0):
        raise RouteContractError("destination audit clock parameters are invalid")
    before = _graph_digest(graph, check_deadline)
    opaque = _opaque_bus_lines(graph, choices, edge_uses_rail, check_deadline)
    reverse = {node: [] for node in graph}
    counts = dict(included_edges=0, excluded_edges=0, known_ride_edges=0,
                  zero_ride_edges=0, positive_ride_edges=0, zero_duration_ride_edges=0)
    maximum = 0.0
    for u, v, edge in graph.edges(data=True):
        check_deadline()
        if edge_uses_rail(u, v):
            counts["excluded_edges"] += 1
            continue
        kind, minutes = edge.get("etype"), 0.0
        if kind == "walk":
            minutes = _checked_walk_minutes(edge, walk_speed)
        elif kind == "board" and graph.nodes[v].get("mode") == "rail":
            minutes = rail_boarding_minutes
        elif kind in ("alight", "xfer") and graph.nodes[u].get("mode") == "rail":
            minutes = 1.0
        elif kind == "ride":
            estimate = None
            if graph.nodes[u].get("mode") == "rail":
                estimate = rail_minima.get((u[1], v[1]))
            elif graph.nodes[u].get("mode") == "bus" and choices._line_id(u) not in opaque:
                route = choices._bus_route(u)
                first, last = choices._stop_id(u[1]), choices._stop_id(v[1])
                if route is not None and first is not None and last is not None:
                    estimate = bus_minima.get((route, first, last))
            if estimate is None:
                counts["zero_ride_edges"] += 1
            else:
                minutes = estimate
                counts["known_ride_edges"] += 1
            counts["positive_ride_edges" if minutes > 0 else "zero_duration_ride_edges"] += 1
        if type(minutes) is not float or not math.isfinite(minutes) or minutes < 0:
            raise RouteContractError("common destination projection has invalid edge minutes")
        reverse[v].append((u, minutes))
        counts["included_edges"] += 1
        maximum = max(maximum, minutes)
    if before != _graph_digest(graph, check_deadline):
        raise RouteContractError("Tokyo graph changed during common projection")
    return CommonProjection(
        graph, choices, tuple(graph), MappingProxyType({k: tuple(v) for k, v in reverse.items()}),
        MappingProxyType(counts), maximum, walk_speed, rail_boarding_minutes, before,
    )


def common_destination_bounds(projection, target, virtual_connections, *,
                              check_deadline=lambda: None):
    """The same binary64 reverse-addition order, from common weights only."""
    values, queue, seeded = {}, [], set()
    sequence = 0
    missing = 0
    maximum = projection.max_edge_minutes

    def seed(node, minutes):
        nonlocal sequence
        if minutes < values.get(node, math.inf):
            values[node] = minutes
            heapq.heappush(queue, (minutes, sequence, node))
            sequence += 1

    if target in projection.reverse:
        seed(target, 0.0)
        seeded.add(target)
    for node, (cost, meters) in virtual_connections.items():
        check_deadline()
        cost, meters = float(cost), float(meters)
        if not math.isfinite(cost) or cost < 0 or not math.isfinite(meters) or meters < 0:
            raise RouteContractError("virtual destination cost/meters must be finite and nonnegative")
        if node not in projection.reverse:
            missing += 1
            continue
        minutes = meters / projection.walk_speed
        if not math.isfinite(minutes):
            raise RouteContractError("virtual destination minutes must be finite")
        maximum = max(maximum, minutes)
        seed(node, minutes)
        seeded.add(node)
    while queue:
        check_deadline()
        remaining, _, node = heapq.heappop(queue)
        if remaining != values[node]:
            continue
        for previous, minutes in projection.reverse[node]:
            check_deadline()
            candidate = remaining + minutes
            if not math.isfinite(candidate):
                raise RouteContractError("common reverse Dijkstra addition overflowed")
            if candidate < values.get(previous, math.inf):
                seed(previous, candidate)
    check_deadline()
    return TimeBounds(values, {
        "nodes": len(projection.nodes), "max_reverse_steps": len(projection.nodes) + 1,
        "max_edge_minutes": maximum, "seeded_nodes": len(seeded),
        "missing_virtual_nodes": missing, "unreachable_nodes": len(projection.nodes) - len(values),
        **projection.counts,
    })


def compare_all_nodes(nodes, reference, common, *, check_deadline=lambda: None):
    """Compare both presence and bits: unreachable zero cannot hide a loss."""
    expected_nodes = set(nodes)
    if set(reference._values) - expected_nodes or set(common._values) - expected_nodes:
        raise RouteContractError("destination bound contains nodes outside the original graph")
    for index, node in enumerate(nodes):
        check_deadline()
        present = node in reference._values
        if present != (node in common._values):
            raise RouteContractError("destination bound reachability differs: node_index=" + str(index))
        old, new = reference(node), common(node)
        if old < 0 or new < 0 or float_bits(old) != float_bits(new):
            raise RouteContractError(
                "destination bound bits differ: node_index=" + str(index)
                + " reference=" + old.hex() + " common=" + new.hex())


def verify_destination_case(projection, target, virtual_connections, *, edge_uses_rail,
                            clock_profiles=((600.0, 840.0, 100000), (1439.0, 1679.0, 100000)),
                            check_deadline=lambda: None):
    """Frozen destination parity only; no OD search or unconditional safety flag."""
    check_deadline()
    if projection.graph_digest != _graph_digest(projection.graph, check_deadline):
        raise RouteContractError("Tokyo graph changed since common projection")
    seeds_before = _digest_rows(virtual_connections.items(), check_deadline)
    common = common_destination_bounds(projection, target, virtual_connections,
                                       check_deadline=check_deadline)
    reference = make_time_bounds(
        projection.graph, projection.choices, target, virtual_connections,
        edge_uses_rail=edge_uses_rail, walk_speed=projection.walk_speed,
        rail_boarding_minutes=projection.rail_boarding_minutes, check_deadline=check_deadline,
    )
    if not reference.report["scope"].startswith("static:") or reference.report["invalid_intervals"]:
        raise RouteContractError("reference destination bound disabled or invalid; no zero-bound acceptance")
    for name, value in common.report.items():
        old = reference.report[name]
        same = float_bits(old) == float_bits(value) if type(value) is float else old == value
        if not same:
            raise RouteContractError("destination bound structural coefficient differs: field=" + name)
    compare_all_nodes(projection.nodes, reference, common, check_deadline=check_deadline)
    profiles, checks = [], 0
    if not clock_profiles:
        raise RouteContractError("destination audit requires explicit clock profiles")
    for start, deadline, forward in clock_profiles:
        check_deadline()
        args = dict(start_minute=start, deadline=deadline, max_forward_steps=forward,
                    max_reverse_steps=len(projection.nodes) + 1,
                    max_edge_minutes=reference.report["max_edge_minutes"])
        old_guard = TimeRoundingGuard(**args)
        args["max_edge_minutes"] = common.report["max_edge_minutes"]
        new_guard = TimeRoundingGuard(**args)
        verify_guard_equivalence(old_guard, new_guard)
        proof = verify_guard_coefficients(new_guard, **args)
        clocks = (float(start), math.nextafter(float(start), math.inf),
                  (float(start) + float(deadline)) / 2,
                  math.nextafter(float(deadline), -math.inf), float(deadline))
        for node in projection.nodes:
            check_deadline()
            remaining = common(node)
            if remaining > new_guard._remaining_upper:
                raise RouteContractError("destination bound exceeds guard domain")
            for clock in clocks:
                if not start <= clock <= deadline:
                    raise RouteContractError("destination priority clock is outside guard domain")
                old_priority = old_guard(clock, reference(node))
                new_priority = new_guard(clock, remaining)
                if float_bits(old_priority) != float_bits(new_priority):
                    raise RouteContractError("guarded destination priority bits differ")
                if remaining == 0.0 and float_bits(new_priority) != float_bits(clock):
                    raise RouteContractError("zero remaining bound changed the actual clock")
                checks += 1
        profiles.append({"start_minute": start, "deadline": deadline,
                         "max_forward_steps": forward, "guard": new_guard.report, **proof})
    if projection.graph_digest != _graph_digest(projection.graph, check_deadline):
        raise RouteContractError("Tokyo graph changed during destination comparison")
    if seeds_before != _digest_rows(virtual_connections.items(), check_deadline):
        raise RouteContractError("frozen virtual destination seeds changed during comparison")
    check_deadline()
    return {
        "common_destination_bounds_verified": True,
        "reachability_membership_verified": True, "bound_binary64_bits_verified": True,
        "rounding_guard_equivalence_verified": True,
        "guarded_priority_equivalence_verified": True,
        "conditional_error_coefficients_verified": True,
        "graph_nodes": len(projection.nodes), "all_nodes_compared": len(projection.nodes),
        "reachable_nodes": len(common._values), "priority_pairs_compared": checks,
        "target_in_graph": target in projection.reverse,
        "reference_static_scope": reference.report["scope"],
        **common.report, "clock_profiles": profiles,
        "unexpanded_suffix_step_bound_verified": False,
        "unconditional_priority_admissibility_verified": False,
        "real_timetable_suffix_admissibility_verified": False,
        "common_dataset_route_ranking_verified": False, "true_top_k_verified": False,
    }
