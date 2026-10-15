"""Read-only comparison of common rail intervals and Tokyo's static A* input.

This audit does not project graph edges, build destination bounds, publish an
index, select a provider or run a route search. All source calendars participate.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import math

from route_engine import RouteContractError
from tokyo_dataset_rail_choices import TokyoRailDatasetBinding, _source_digest
from tokyo_time_bounds import _adjacent_minutes, _build_rail_index, _rail_sources


def _collect_static_rail_minima(snapshot, check_deadline):
    """Traverse source occurrences, including unboardable and repeated stops."""
    check_deadline()
    if (len(snapshot.datasets) != 1
            or any(route.mode.value != 'rail' for route in snapshot.routes.values())
            or snapshot.allowed_trip_ids != frozenset(snapshot.datasets[0].trips)
            or set(snapshot.trips) != set(snapshot.datasets[0].trips)
            or set(snapshot.rows_by_trip) != set(snapshot.trips)):
        raise RouteContractError('rail interval audit requires complete rail-only source scope')
    minima = {}
    stops = intervals = 0
    for trip_key in snapshot.trips:
        check_deadline()
        rows = snapshot.rows_by_trip[trip_key]
        if len(rows) < 2:
            raise RouteContractError('rail interval audit requires at least two timed occurrences')
        stops += len(rows)
        # No active-service, pickup/drop-off or graph-edge filter belongs here.
        # Sequence gaps do not license skipping an actual adjacent occurrence.
        for previous, following in zip(rows, rows[1:]):
            check_deadline()
            if following.sequence <= previous.sequence:
                raise RouteContractError('rail interval audit requires ordered source occurrences')
            for clock in (previous.departure_minute, following.arrival_minute):
                if (type(clock) is not Fraction or clock.denominator != 1
                        or not 0 <= clock <= 2**53):
                    raise RouteContractError('rail interval audit requires exact integral source minutes; no rounding')
            key = (snapshot.stops[previous.stop_id].source_id,
                   snapshot.stops[following.stop_id].source_id)
            # Match the old static binary64 subtraction/downward guard exactly;
            # do not include the dwell before the current stop's departure.
            minutes = _adjacent_minutes(previous.departure_minute, following.arrival_minute)
            if minutes is None:
                raise RouteContractError('rail interval audit contains an invalid adjacent interval')
            minima[key] = min(minima.get(key, math.inf), minutes)
            intervals += 1
    check_deadline()
    if not minima:
        raise RouteContractError('rail interval audit exercised no adjacent intervals')
    return minima, len(snapshot.trips), stops, intervals


def verify_static_rail_interval_minima(binding, manager, *, check_deadline=lambda: None):
    """Verify the validated complete source binding, then compare fresh indexes.

    Reuse neither the old owner's cache nor query-specific active trips. Source
    contents are checked before/after, including same-length edits whose minima
    might happen to stay equal. Exceptions propagate without another data path.
    """
    if type(binding) is not TokyoRailDatasetBinding:
        raise RouteContractError('rail interval audit requires an explicit validated rail binding')
    check_deadline()
    if _source_digest(manager) != binding.source_digest:
        raise RouteContractError('Tokyo rail source changed since binding validation')
    check_deadline()
    minima, trips, stops, intervals = _collect_static_rail_minima(binding.snapshot, check_deadline)
    # Call the pure old rail builder directly. _indexes would inspect bus data
    # and publish caches, both outside this audit's deliberately narrow scope.
    reference = _build_rail_index(None, _rail_sources(manager), check_deadline)
    check_deadline()
    if _source_digest(manager) != binding.source_digest:
        raise RouteContractError('Tokyo rail source changed during interval audit')
    if reference.invalid or reference.records != intervals:
        raise RouteContractError('Tokyo common rail interval coverage differs: '
            f'common_intervals={intervals} reference_records={reference.records} '
            f'reference_invalid={reference.invalid}')
    if minima != reference.minima:
        missing = set(reference.minima)-minima.keys()
        extra = set(minima)-reference.minima.keys()
        different = {key for key in minima.keys() & reference.minima.keys()
                     if minima[key] != reference.minima[key]}
        pair = min(missing | extra | different)
        digest = hashlib.sha256(json.dumps(pair, ensure_ascii=True).encode('ascii')).hexdigest()
        raise RouteContractError('Tokyo common rail interval minimum differs: '
            f'missing_keys={len(missing)} extra_keys={len(extra)} '
            f'different_values={len(different)} segment_sha256={digest} '
            f'common={minima.get(pair)!r} reference={reference.minima.get(pair)!r}')
    check_deadline()
    if _source_digest(manager) != binding.source_digest:
        raise RouteContractError('Tokyo rail source changed before interval audit completion')
    return {
        'common_rail_interval_minima_verified': True,
        'rail_interval_pairs': len(minima),
        'rail_source_trips': trips,
        'rail_source_stop_times': stops,
        'rail_source_intervals': intervals,
        'rail_reference_records': reference.records,
        'rail_source_calendars': len({trip.service_id for trip in binding.snapshot.trips.values()}),
        'rail_invalid_intervals': 0,
    }
