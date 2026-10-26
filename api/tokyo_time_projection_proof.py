"""Opt-in proof gate for static Tokyo time priorities; never a search backend.

An operational suffix can have arbitrarily many transitions. Erase cycles
ONLY in its relaxed graph projection. The retained original clock increments
are nonnegative and sum to at most the original elapsed clock. Consequently
only a simple projected path's edges incur the one-ULP transition allowance.
Nf >= Nr = len(G)+1 therefore suffices without bounding operational suffixes.

The gate checks the COMPLETE edge/seed schema, source interval enclosures,
reverse Bellman inequalities and the unchanged guard's exact error budgets.
Reviewed transition-code fingerprints make an upstream semantic change an
explicit proof-review failure. Sampled suffixes are regression evidence, not
the universal transition-coverage premise. No runtime module imports this gate.
"""
from __future__ import annotations

import ast
from collections import defaultdict, deque
from fractions import Fraction
import hashlib
import inspect
import json
import math
import sys
import textwrap
from types import MappingProxyType

import networkx as nx

from route_engine import RouteContractError
import reviewed_walk_time as walking
import toei_engine as engine
import tokyo_search_labels as integration
import tokyo_timetable_choices as timetable
import transit_search_labels as forward
from gtfs_loader import GtfsRepository
from tokyo_dataset_rail_choices import _source_digest
from tokyo_destination_bounds_audit import (
    CommonIntervalInputs, CommonProjection, _digest_rows, _graph_digest,
)
from tokyo_time_bounds import TimeBounds
import tokyo_time_rounding as rounding
from tokyo_time_rounding_audit import (
    float_bits, verify_guard_coefficients, verify_guard_equivalence,
)


_CONTRACT_OBJECTS = {
    "forward.search_labels": forward.search_labels,
    "integration.search_labels": integration.search_labels,
    "integration._alight_minutes": integration._alight_minutes,
    "engine._tokyo_label_search": engine._tokyo_label_search,
    "engine.advance_time": engine.advance_time,
    "engine._edge_uses_rail": engine._edge_uses_rail,
    "engine.time_str_to_min": engine.time_str_to_min,
    "walking.walk_edge_elapsed_minutes": walking.walk_edge_elapsed_minutes,
    "walking.walk_edge_is_available": walking.walk_edge_is_available,
    "walking.walk_edge_resource_meters": walking.walk_edge_resource_meters,
    "timetable": timetable,
    "rounding": rounding,
    "TimeBounds": TimeBounds,
    "GtfsRepository.get_stop_time_boarding": GtfsRepository.get_stop_time_boarding,
}
# Generated from the reviewed transition ASTs. The 2026-10-26 timetable update
# memoizes only query-fixed bus occurrence compatibility. Its key contains the
# exact board edge, trip and stop sequence; readiness and frozen realtime delay
# still select departures on every call. Both accepted and rejected outcomes
# are identical to the reviewed checks, while exceptions remain uncached. It
# therefore does not add/remove an exact transition or change its clock, so the
# static projection remains the same relaxation and lower bound.
# Ignore only Python 3.12's added empty type_params field, not executable code.
_REVIEWED_AST_SHA256 = {
    "forward.search_labels": "49f8b921f08f0910b1d641d242b34adaaee608d307bf14ce501e2bced8669475",
    "integration.search_labels": "3dde3b854fc3a6072184129c7386655a1a2150fe2692ce3cc36a810ca42e6375",
    "integration._alight_minutes": "b12f86c9f461e9269ec5df73c7c1456f8ace23fcf425e1db6260344110d50bf7",
    "engine._tokyo_label_search": "8c4f330b3b7e01596402ae5390b684dd27877910871945dbe070c400c8c8a8a6",
    "engine.advance_time": "d8323f8f8046a46d1f35bb46f0c7cf586ed9a446163e3d12b15585dee484dcf9",
    "engine._edge_uses_rail": "131d5efe0129771b745203e425ef73b6321217f600ae22a56ce2e4975e1cc451",
    "engine.time_str_to_min": "d0f4bd80a6985fd7b4dc53be59b68c06b4197927663ccb5fbec31e9f000b37e5",
    "walking.walk_edge_elapsed_minutes": "b5fe6b98356e9c1f70720418e8b874381a0acfac2f5d39278b6b599235548380",
    "walking.walk_edge_is_available": "9d1170a0dae0605fb54f02448bf9c96b30844ce90b0ee2a5f8dcf6425f0d8685",
    "walking.walk_edge_resource_meters": "b00038d1ec0db276e1fe537990f3b567041abf6c6eddbf579a235e2782be461f",
    "timetable": "88e6ee8e815bd3dafa786a0f88f92e4fd9996b23123cf6b0a6e9ea2560a73840",
    "rounding": "7598a5971723c1a49e770519129d0aeb8c8d28d0594931ee1126fb7ce158fe32",
    "TimeBounds": "6c5a77b3aa915378b64d3aba8aea6a12f86e9dd10282134cdb9e61e0248ec914",
    "GtfsRepository.get_stop_time_boarding": "8f1916cb58100ae85244de3592392df92ee9c537567106891650809bee0127fe",
}
_MODULE_BINDINGS = {
    module: {name: value for name, value in vars(module).items()
             if inspect.isfunction(value) and value.__module__ == module.__name__}
    for module in (timetable, rounding)
}
_CLASS_BINDINGS = {
    cls: {name: value for name, value in vars(cls).items() if inspect.isfunction(value)}
    for cls in (timetable.TimetableChoices, rounding.TimeRoundingGuard, TimeBounds)
}


def _stop(reason, **context):
    # Indices/counts only: never log source IDs, coordinates or itineraries.
    fields = " ".join(f"{name}={value}" for name, value in context.items())
    raise RouteContractError(f"static time proof rejected: reason={reason}" + (" " + fields if fields else ""))


def _ast_form(value):
    if isinstance(value, ast.AST):
        return [type(value).__name__, [[name, _ast_form(item)]
                for name, item in ast.iter_fields(value)
                if not (name == "type_params" and item == [])]]
    if isinstance(value, list):
        return [_ast_form(item) for item in value]
    if value is Ellipsis:
        return ["Ellipsis"]
    return value


def _ast_digest(value):
    source = textwrap.dedent(inspect.getsource(value))
    tree = _ast_form(ast.parse(source))
    return hashlib.sha256(json.dumps(tree, ensure_ascii=False, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def _check_reviewed_contract(choices, checkpoint):
    current = {
        "forward.search_labels": forward.search_labels,
        "integration.search_labels": integration.search_labels,
        "integration._alight_minutes": integration._alight_minutes,
        "engine._tokyo_label_search": engine._tokyo_label_search,
        "engine.advance_time": engine.advance_time,
        "engine._edge_uses_rail": engine._edge_uses_rail,
        "engine.time_str_to_min": engine.time_str_to_min,
        "walking.walk_edge_elapsed_minutes": walking.walk_edge_elapsed_minutes,
        "walking.walk_edge_is_available": walking.walk_edge_is_available,
        "walking.walk_edge_resource_meters": walking.walk_edge_resource_meters,
        "timetable": timetable, "rounding": rounding, "TimeBounds": TimeBounds,
        "GtfsRepository.get_stop_time_boarding": GtfsRepository.get_stop_time_boarding,
    }
    if current.keys() != _REVIEWED_AST_SHA256.keys():
        _stop("incomplete_reviewed_transition_contract")
    for index, (name, value) in enumerate(current.items()):
        checkpoint()
        if value is not _CONTRACT_OBJECTS[name] or _ast_digest(value) != _REVIEWED_AST_SHA256[name]:
            _stop("unreviewed_transition_implementation", contract_index=index)
    for module, bindings in _MODULE_BINDINGS.items():
        for name, value in bindings.items():
            if getattr(module, name, None) is not value:
                _stop("replaced_transition_helper")
    for cls, bindings in _CLASS_BINDINGS.items():
        for name, value in bindings.items():
            if getattr(cls, name, None) is not value:
                _stop("replaced_transition_method")
            if cls is timetable.TimetableChoices and getattr(getattr(choices, name, None), "__func__", None) is not value:
                _stop("custom_provider_method")
    if (engine.WALK_SPEED_M_PER_MIN != 80.0 or engine.RAIL_BOARDING_MINUTES != 2
            or integration._shared_search_labels is not forward.search_labels
            or integration.TimeRoundingGuard is not rounding.TimeRoundingGuard
            or integration._alight_minutes is not _CONTRACT_OBJECTS["integration._alight_minutes"]
            or engine.walk_edge_elapsed_minutes is not walking.walk_edge_elapsed_minutes
            or engine.walk_edge_is_available is not walking.walk_edge_is_available
            or integration.walk_edge_resource_meters is not walking.walk_edge_resource_meters):
        _stop("different_transition_parameters_or_hooks")


def _check_binary64_environment():
    info = sys.float_info
    one, half = float(1), math.ldexp(float(1), -53)
    two_up = math.nextafter(math.nextafter(one, math.inf), math.inf)
    smallest = math.ulp(0.0)
    if (info.radix != 2 or info.mant_dig != 53 or info.max_exp != 1024 or info.rounds != 1
            or one + half != one or one + 3 * half != two_up
            or smallest <= 0 or smallest + smallest <= smallest or smallest * one != smallest):
        _stop("unsupported_binary64_arithmetic_environment")


def _number(value, field):
    if type(value) not in (int, float):
        _stop("invalid_numeric_type", field=field)
    result = float(value)  # Same explicit int/float arithmetic domain as Tokyo.
    if not math.isfinite(result) or result < 0:
        _stop("nonfinite_or_negative_number", field=field)
    return result


def _clock(value, field):
    # The reviewed source bindings require exact integral service-day minutes.
    if type(value) is not int or not 0 <= value <= 2**53:
        _stop("nonexact_source_clock", field=field)
    return value


def _check_snapshot_containers(inputs, projection):
    """The proof and execution must read the same fixed, ordinary rows."""
    repository = inputs.repository
    for name in ("trips", "stop_times", "routes", "stops", "timetable_index", "stop_time_boarding",
                 "route_name_to_id"):
        if type(getattr(repository, name)) not in (dict, defaultdict):
            _stop("custom_source_container", field=name)
    for name in ("train_patterns_weekday", "train_patterns_weekend"):
        if type(getattr(inputs.manager, name)) not in (dict, defaultdict):
            _stop("custom_source_container", field=name)
        if getattr(projection.choices.manager, name) is not getattr(inputs.manager, name):
            _stop("different_static_source_owner", field=name)
    for values in (inputs.rail, inputs.bus):
        if type(values) is not MappingProxyType:
            _stop("immutable_interval_map_required")
        for key, value in values.items():
            if values[key] is not value or values.get(key) is not value:
                _stop("interval_map_lookup_differs")
    if type(projection.reverse) is not MappingProxyType:
        _stop("immutable_reverse_map_required")
    for node, rows in projection.reverse.items():
        if (type(rows) is not tuple or projection.reverse[node] is not rows
                or projection.reverse.get(node) is not rows):
            _stop("reverse_map_lookup_differs")


def _proof_state(projection, inputs, bounds, guard, virtual, checkpoint):
    """Seal caller-owned proof inputs as well as the source/graph snapshots."""
    def rows():
        yield ("virtual", tuple(virtual.items()))
        yield ("index", tuple(inputs.repository.timetable_index.items()))
        yield ("rail_minima", tuple(inputs.rail.items()))
        yield ("bus_minima", tuple(inputs.bus.items()))
        yield ("reverse", tuple(projection.reverse.items()))
        yield ("bounds", tuple(bounds._values.items()))
        yield ("guard", guard._enabled, guard._start, guard._deadline,
               guard._remaining_upper, guard._error, tuple(guard.report.items()))
    return _digest_rows(rows(), checkpoint)


def _source_ceilings(inputs, checkpoint):
    """Exact interval inequalities, not a rerun of any interval-min parity gate."""
    rail, bus, expected_index = {}, {}, defaultdict(list)
    rail_count = bus_count = stop_count = 0
    for name in ("train_patterns_weekday", "train_patterns_weekend"):
        for station, records in getattr(inputs.manager, name).items():
            checkpoint()
            if type(records) not in (list, tuple):
                _stop("custom_rail_source_rows")
            for record in records:
                checkpoint()
                if type(record) is not dict:
                    _stop("custom_rail_source_record")
                departure = _clock(record["dep"], "rail_departure")
                arrival = _clock(record["arr"], "rail_arrival")
                following = record.get("next_sta")
                if following is None or arrival < departure:
                    _stop("invalid_rail_interval", record_index=rail_count)
                key = station, following
                duration = arrival - departure  # Exact integers, no bound helper.
                rail[key] = min(rail.get(key, duration), duration)
                rail_count += 1
    repository = inputs.repository
    if set(repository.trips) != set(repository.stop_times):
        _stop("bus_trip_occurrence_scope_differs")
    for trip_index, (trip_id, trip) in enumerate(repository.trips.items()):
        checkpoint()
        if (type(trip_id) is not str or type(trip) is not dict
                or type(repository.stop_times[trip_id]) not in (dict, defaultdict)):
            _stop("custom_bus_source_rows", trip_index=trip_index)
        route = trip["route_id"]
        if route not in repository.routes:
            _stop("unknown_bus_route", trip_index=trip_index)
        rows = sorted(repository.stop_times[trip_id].items())
        if len(rows) < 2:
            _stop("bus_run_has_no_interval", trip_index=trip_index)
        previous = None
        for position, (sequence, row) in enumerate(rows):
            checkpoint()
            if type(row) is not tuple or len(row) != 3:
                _stop("custom_bus_stop_time_row", trip_index=trip_index, position=position)
            stop, arrival, departure = row
            arrival, departure = _clock(arrival, "bus_arrival"), _clock(departure, "bus_departure")
            if (type(sequence) is not int or sequence < 0
                    or type(stop) is not str or stop not in repository.stops):
                _stop("invalid_bus_occurrence", trip_index=trip_index, position=position)
            if arrival > departure or previous is not None and arrival < previous[1]:
                _stop("decreasing_bus_source_clock", trip_index=trip_index, position=position)
            pickup, dropoff = repository.get_stop_time_boarding(trip_id, sequence)
            if (type(pickup) is not int or type(dropoff) is not int
                    or pickup not in (0, 1, 2, 3) or dropoff not in (0, 1, 2, 3)
                    or position < len(rows) - 1 and pickup not in (0, 1)
                    or position > 0 and dropoff != 0):
                _stop("unsupported_boarding_condition", trip_index=trip_index, position=position)
            expected_index[f"{route}|{stop}"].append((departure, sequence, trip_id))
            if previous is not None:
                key = route, previous[0], stop
                duration = arrival - previous[1]
                bus[key] = min(bus.get(key, duration), duration)
                bus_count += 1
            previous = stop, departure
            stop_count += 1
    if not rail or not bus:
        _stop("incomplete_static_rail_bus_scope")
    if set(repository.timetable_index) != set(expected_index):
        _stop("bus_departure_index_scope_differs")
    for index, (key, entries) in enumerate(expected_index.items()):
        checkpoint()
        actual = repository.timetable_index[key]
        for position, (scheduled, sequence, trip_id) in enumerate(actual):
            _clock(scheduled, "bus_index_departure")
            if type(sequence) is not int or type(trip_id) is not str:
                _stop("invalid_bus_departure_index_type", index=index, position=position)
        if actual != sorted(entries):
            _stop("bus_departure_index_inconsistent", index=index)
    return rail, bus, {"rail_source_intervals_checked": rail_count,
                       "bus_source_intervals_checked": bus_count,
                       "bus_source_stop_times_checked": stop_count}


def _roles(graph, checkpoint):
    result = {}
    for index, (node, data) in enumerate(graph.nodes(data=True)):
        checkpoint()
        if (type(data) is not dict or type(node) is not tuple or len(node) not in (2, 3)
                or type(node[1]) is not str or not node[1]):
            _stop("unsupported_node_schema", node_index=index)
        if node[0] == "phys" and len(node) == 2 and data.get("mode") is None:
            result[node] = "phys"
        elif (node[0] == "line" and len(node) == 3 and type(node[2]) is str
              and type(data.get("mode")) is str and data["mode"] in ("rail", "bus")):
            result[node] = data["mode"]
        else:
            _stop("unsupported_node_schema", node_index=index)
    return result


def _projected_edges(projection, inputs, scope, ceilings, checkpoint):
    graph, choices = projection.graph, projection.choices
    roles = _roles(graph, checkpoint)
    if tuple(graph) != projection.nodes or set(projection.reverse) != set(graph):
        _stop("projection_node_coverage_differs")
    observed = {}
    for node, rows in projection.reverse.items():
        checkpoint()
        for previous, weight in rows:
            if previous not in graph or (previous, node) in observed:
                _stop("extra_or_duplicate_projected_edge")
            float_bits(weight)
            if weight < 0:
                _stop("negative_projected_weight")
            observed[previous, node] = weight
    # A separate fresh resolver prevents stale query-local route/stop aliases
    # from acquiring a proof. It does not execute board/ride or retry a query.
    resolver = timetable.TimetableChoices(graph, choices.manager, day_type=choices.day_type,
        use_realtime=False, deadline=choices.deadline, bus_repository=inputs.repository)
    counts = defaultdict(int)
    maximum = 0.0
    for index, (u, v, edge) in enumerate(graph.edges(data=True)):
        checkpoint()
        if type(edge) is not dict:
            _stop("custom_edge_attribute_container", edge_index=index)
        excluded = scope == "bus_only_rail_excluded" and engine._edge_uses_rail(graph, u, v)
        if excluded:
            if (u, v) in observed:
                _stop("excluded_edge_in_projection", edge_index=index)
            counts["excluded_edges"] += 1
            continue
        if (u, v) not in observed:
            _stop("legal_edge_missing_from_projection", edge_index=index)
        kind, a, b = edge.get("etype"), roles[u], roles[v]
        _number(edge.get("w", 0.0), "edge_cost")
        expected = 0.0
        if kind == "walk" and a == b == "phys":
            if type(edge.get("meters", 0)) not in (int, float):
                _stop("custom_walking_distance_type", edge_index=index)
            expected = walking.walk_edge_elapsed_minutes(edge, speed_m_per_min=projection.walk_speed)
        elif kind == "board" and a == "phys" and b in ("rail", "bus") and u[1] == v[1]:
            if b == "bus":
                route, stop = resolver._bus_route(v), resolver._stop_id(u[1])
                if (route is None or stop not in inputs.repository.stops
                        or choices._bus_route(v) != route or choices._stop_id(u[1]) != stop):
                    _stop("opaque_or_stale_bus_boarding", edge_index=index)
            expected = 2.0 if b == "rail" else 0.0
        elif kind == "ride" and a == b and a in ("rail", "bus") and u[2] == v[2] and edge.get("mode") == a:
            if a == "rail":
                key = u[1], v[1]
                values, ceiling = inputs.rail, ceilings[0]
            else:
                route = resolver._bus_route(u)
                first, last = resolver._stop_id(u[1]), resolver._stop_id(v[1])
                if (route is None or choices._bus_route(u) != route
                        or choices._stop_id(u[1]) != first or choices._stop_id(v[1]) != last):
                    _stop("opaque_or_stale_bus_ride", edge_index=index)
                key = route, first, last
                values, ceiling = inputs.bus, ceilings[1]
            if key not in values or key not in ceiling:
                _stop("unwitnessed_concrete_ride", edge_index=index)
            expected = values[key]
            float_bits(expected)
            if expected < 0 or Fraction.from_float(expected) > ceiling[key]:
                _stop("ride_weight_exceeds_source_interval", edge_index=index)
        elif kind in ("alight", "xfer") and a in ("rail", "bus") and b == "phys":
            expected = 1.0 if a == "rail" else 0.0
        else:
            _stop("uncovered_forward_transition", edge_index=index)
        weight = observed.pop((u, v))
        if float_bits(weight) != float_bits(expected):
            _stop("projected_transition_weight_differs", edge_index=index)
        maximum = max(maximum, weight)
        counts["included_edges"] += 1
        counts["transition_" + kind] += 1
    if observed:
        _stop("extra_projected_edge", count=len(observed))
    if (counts["included_edges"] != projection.counts["included_edges"]
            or counts["excluded_edges"] != projection.counts["excluded_edges"]
            or float_bits(maximum) != float_bits(projection.max_edge_minutes)):
        _stop("projection_counts_or_maximum_differ")
    return roles, dict(counts), maximum


def _seeds(projection, target, virtual, checkpoint):
    seeds = [(target, 0.0)] if target in projection.reverse else []
    missing = 0
    for node, (cost, meters) in virtual.items():
        checkpoint()
        _number(cost, "virtual_cost")
        meters = _number(meters, "virtual_meters")
        if node not in projection.reverse:
            missing += 1
            continue
        weight = meters / projection.walk_speed
        float_bits(weight)
        seeds.append((node, weight))
    if not seeds:
        _stop("no_present_destination_seed")
    return seeds, missing


def _check_bound_inequalities(projection, bounds, seeds, guard, checkpoint):
    """O(V+E) reachability and Bellman checks, independent of Dijkstra."""
    reachable, queue = set(), deque(node for node, _ in seeds)
    while queue:
        checkpoint()
        node = queue.popleft()
        if node in reachable:
            continue
        reachable.add(node)
        queue.extend(previous for previous, _ in projection.reverse[node])
    if set(bounds._values) != reachable:
        _stop("bound_reachability_membership_differs")
    for value in bounds._values.values():
        checkpoint()
        float_bits(value)
        if not 0 <= value <= guard._remaining_upper:
            _stop("bound_outside_guard_domain")
    for index, (node, weight) in enumerate(seeds):
        if bounds._values[node] > weight:
            _stop("seed_bound_inequality_failed", seed_index=index)
    checked = 0
    for node in reachable:
        checkpoint()
        for previous, weight in projection.reverse[node]:
            checkpoint()
            candidate = bounds._values[node] + weight
            if not math.isfinite(candidate):
                _stop("reverse_addition_overflow")
            if bounds._values[previous] > candidate:
                _stop("reverse_bellman_inequality_failed", edge_index=checked)
            checked += 1
    return len(reachable), checked


def verify_static_time_projection(projection, inputs, bounds, guard, target, virtual_connections, *,
                                  start, mode, scope, check_deadline=lambda: None):
    """Certify scoped priority admissibility, not route length, parity or top-k.

    All executable transition rules must be the reviewed canonical Tokyo
    integration, with a fresh static reference provider and physical start.
    This function neither invokes search nor constructs/replaces any bound or
    guard supplied by its caller. Failure never produces a partial certificate.
    """
    check_deadline()
    if (type(projection) is not CommonProjection or type(inputs) is not CommonIntervalInputs
            or type(bounds) is not TimeBounds or type(guard) is not rounding.TimeRoundingGuard):
        _stop("unsupported_proof_input_type")
    # The executable TimeBounds/forward loop use .get(), while the proof
    # enumerates .items(). Do not certify custom container implementations
    # whose lookups can have different semantics from their enumerated rows.
    if type(bounds._values) is not dict:
        _stop("plain_bound_values_required")
    if not guard._enabled or guard.report.get("enabled") is not True:
        _stop("rounding_guard_disabled", detail=guard.report.get("disabled_reason", "disabled"))
    if type(virtual_connections) is not dict:
        _stop("plain_virtual_seed_mapping_required")
    _check_binary64_environment()
    if mode != "time" or scope not in ("full_graph", "bus_only_rail_excluded"):
        _stop("unsupported_proof_scope")
    graph, choices = projection.graph, projection.choices
    if (type(graph) is not nx.DiGraph or type(choices) is not timetable.TimetableChoices
            or choices.graph is not graph or choices.use_realtime is not False
            or type(choices.manager) is not engine.TimetableManager
            or type(inputs.manager) is not engine.TimetableManager
            or type(inputs.repository) is not GtfsRepository or choices.repository is not inputs.repository
            or choices._has_rail_data is not True or choices._has_bus_data is not True
            or choices.can_wait_offboard is not True):
        _stop("noncanonical_or_realtime_provider")
    _check_reviewed_contract(choices, check_deadline)
    if (projection.walk_speed != 80.0 or projection.rail_boarding_minutes != 2.0
            or choices.rail_boarding_minutes != 2):
        _stop("different_transition_parameters")
    for name in ("_runs", "_positions", "_rail_departures", "_rail_clocks", "_rail_delays",
                 "_rail_segments", "_bus_departures", "_bus_run_cache", "_concrete_board_options",
                 "_bus_pattern_terminals"):
        if (type(getattr(choices, name)) not in (dict, defaultdict)
                or len(getattr(choices, name)) or choices._rail_built):
            _stop("provider_already_used", cache=name)
    if type(choices._line_route_cache) is not dict or type(choices._bus_pole_stop_ids) is not dict:
        _stop("custom_provider_lookup_cache")
    _check_snapshot_containers(inputs, projection)
    inputs.check_sources(check_deadline)
    if (_source_digest(choices.manager) != _source_digest(inputs.manager)
            or projection.graph_digest != _graph_digest(graph, check_deadline)):
        _stop("static_snapshot_differs")
    before = _proof_state(projection, inputs, bounds, guard, virtual_connections, check_deadline)
    ceilings = _source_ceilings(inputs, check_deadline)
    roles, counts, maximum = _projected_edges(projection, inputs, scope, ceilings, check_deadline)
    if start not in roles or roles[start] != "phys":
        _stop("start_without_physical_no_ride_invariant")
    seeds, missing = _seeds(projection, target, virtual_connections, check_deadline)
    maximum = max(maximum, *(weight for _, weight in seeds))
    nf, nr = guard.report.get("max_forward_steps"), guard.report.get("max_reverse_steps")
    if type(nf) is not int or type(nr) is not int or nr != len(graph) + 1:
        _stop("reverse_step_count_differs")
    if nf < nr:
        _stop("projection_step_budget_insufficient", declared_nf=nf, required_nr=nr)
    if float_bits(guard.report["max_edge_minutes"]) != float_bits(maximum):
        _stop("guard_maximum_excludes_edge_or_seed")
    args = dict(start_minute=guard.report["start_minute"], deadline=guard.report["deadline"],
                max_forward_steps=nf, max_reverse_steps=nr, max_edge_minutes=maximum)
    if not 0 <= args["start_minute"] <= args["deadline"] <= 2**53:
        _stop("clock_domain_outside_exact_source_scope")
    coefficients = verify_guard_coefficients(guard, **args)
    verify_guard_equivalence(guard, rounding.TimeRoundingGuard(**args))
    reachable, inequalities = _check_bound_inequalities(projection, bounds, seeds, guard, check_deadline)
    inputs.check_sources(check_deadline)
    if (projection.graph_digest != _graph_digest(graph, check_deadline)
            or before != _proof_state(projection, inputs, bounds, guard, virtual_connections, check_deadline)):
        _stop("proof_inputs_changed_during_verification")
    _check_binary64_environment()
    check_deadline()
    return {
        "static_time_priority_admissibility_verified": True,
        "proof": "cycle_erased_relaxed_projection_with_original_clock_increments",
        "proof_scope": "canonical_static_Tokyo_time_physical_start",
        "reviewed_transition_contract": "bus_compat_cache_20261026_static_time_projection_v1",
        "reviewed_contract_entries": len(_REVIEWED_AST_SHA256),
        "forward_transition_coverage_verified": True,
        "nondecreasing_operational_clocks_verified": True,
        "one_edge_rounding_condition_verified": True,
        "simple_projection_step_bound_verified": True,
        "reverse_bound_inequalities_verified": True,
        "conditional_error_coefficients_verified": coefficients["conditional_error_coefficients_verified"],
        "source_calendar_scope": "all_source_calendars_no_date_filter",
        "mode": mode, "graph_scope": scope,
        "nodes": len(graph), "reachable_nodes": reachable,
        "destination_seed_entries": len(seeds), "missing_virtual_nodes": missing,
        "reverse_edge_inequalities_checked": inequalities,
        "max_forward_steps": nf, "simple_projection_step_bound": nr,
        "max_reverse_steps": nr, "max_edge_minutes": maximum,
        "start_minute": args["start_minute"], "deadline": args["deadline"],
        **counts, **ceilings[2],
        "unexpanded_suffix_step_bound_verified": False,
        "unconditional_priority_admissibility_verified": False,
        "real_timetable_suffix_admissibility_verified": False,
        "common_dataset_route_ranking_verified": False, "true_top_k_verified": False,
        "realtime_verified": False, "operational_calendar_verified": False,
        "runtime_selection": "not_selected_audit_only",
    }
