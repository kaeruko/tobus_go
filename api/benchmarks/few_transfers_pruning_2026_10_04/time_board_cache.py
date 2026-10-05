"""Offline-only reuse of a query's concrete Tokyo boarding choices.

This changes neither the product search nor its priorities.  Each reached
boarding edge lazily retains all concrete options from the query start, then
uses the actual (already prepared) readiness clock to select the same suffix.
Building at the query start is deliberate: first reaching an edge later must
not make its cached options depend on which prefix was expanded first.

The query-local timetable snapshot, service calendar and travel deadline remain
fixed.  RideState is immutable, and its departure/sequence do not depend on the
readiness clock.  Rail's two preparation minutes are applied by search_labels
before board_options; they must not be added again by this adapter.
Rail uses its effective departure clocks.  Bus must retain the original
scheduled clocks and compare ``ready - delay``: reversing a float addition
with a subtraction is not necessarily exact at a departure boundary.

This is a measurement prototype, not production deadline handling.  The checks
before/after a cache miss cannot interrupt the original per-edge enumeration
(or its first full rail-index build).  Retaining departures before a node's
first actual readiness can also consume more memory than rebuilding a suffix.
"""

from __future__ import annotations

import bisect
import math
import time

from tokyo_timetable_choices import RideState, TimetableChoices


def install_board_cache(choices, start_minute, *, check_deadline=lambda: None):
    """Install a lazy query-local cache; return its mutable measurement report.

    Opaque timetable doubles and custom boarding implementations keep their
    original behavior.  A concrete edge which unexpectedly returns opaque,
    nonfinite or unsorted options also falls back instead of caching them.
    """
    original = choices.board_options
    report = {
        "enabled": False,
        "disabled_reason": None,
        "requests": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "fallback_calls": 0,
        "fallback_keys": 0,
        "keys": 0,
        "options_retained": 0,
        "largest_key_options": 0,
        "build_ms": 0.0,
        "start_minute": start_minute,
        "deadline_checks_during_original_enumeration": False,
    }
    if not choices.can_wait_offboard:
        report["disabled_reason"] = "waiting_not_established"
        return report
    if (not isinstance(choices, TimetableChoices)
            or getattr(original, "__func__", None) is not TimetableChoices.board_options):
        report["disabled_reason"] = "custom_boarding_implementation"
        return report
    if not math.isfinite(start_minute):
        report["disabled_reason"] = "nonfinite_query_start"
        return report

    report["enabled"] = True
    cache = {}
    uncached = set()

    def forward(u, v, ready):
        report["fallback_calls"] += 1
        return original(u, v, ready)

    def concrete_edge(u, v):
        mode = choices.graph.nodes[v].get("mode")
        if mode == "rail":
            return choices._has_rail_data
        if mode == "bus":
            return (choices.repository is not None
                    and bool(getattr(choices.repository, "trips", {}))
                    and choices._bus_route(v) is not None
                    and choices._stop_id(u[1]) is not None)
        return False

    def cached_options(u, v, ready):
        report["requests"] += 1
        if (not math.isfinite(ready) or ready < start_minute
                or ready > choices.deadline):
            return forward(u, v, ready)
        key = (u, v)
        if key in uncached:
            return forward(u, v, ready)
        stored = cache.get(key)
        if stored is None:
            if not concrete_edge(u, v):
                uncached.add(key)
                report["fallback_keys"] = len(uncached)
                return forward(u, v, ready)
            report["cache_misses"] += 1
            check_deadline()
            started = time.perf_counter()
            try:
                options = tuple(original(u, v, start_minute))
                clocks = tuple(departure for departure, _ in options)
            finally:
                report["build_ms"] += (time.perf_counter() - started) * 1000.0
            check_deadline()
            validation_started = time.perf_counter()
            safe = (all(math.isfinite(clock) for clock in clocks)
                    and all(left <= right for left, right in zip(clocks, clocks[1:]))
                    and all(isinstance(state, RideState)
                            and state.provider in ("bus", "rail")
                            for _, state in options))
            delay = 0.0
            if safe and choices.graph.nodes[v].get("mode") == "bus":
                # Match the exact timetable-index clock, not an inverse float
                # calculation or a potentially different stop-times record.
                source_key = (choices._bus_route(v), choices._stop_id(u[1]))
                entries = choices._bus_departures[source_key][0]
                scheduled_by_choice = {}
                for scheduled, sequence, trip_id in entries:
                    choice_key = (trip_id, sequence)
                    if (choice_key in scheduled_by_choice
                            and scheduled_by_choice[choice_key] != scheduled):
                        safe = False
                        break
                    scheduled_by_choice[choice_key] = scheduled
                if safe:
                    try:
                        clocks = tuple(scheduled_by_choice[(state.trip_id, state.board_sequence)]
                                       for _, state in options)
                    except KeyError:
                        safe = False
                    delay = choices._bus_delay(v)
                    safe = (safe and math.isfinite(delay)
                            and all(math.isfinite(clock) for clock in clocks)
                            and all(left <= right for left, right in zip(clocks, clocks[1:])))
            report["build_ms"] += (time.perf_counter() - validation_started) * 1000.0
            check_deadline()
            if not safe:
                uncached.add(key)
                report["fallback_keys"] = len(uncached)
                return forward(u, v, ready)
            stored = cache[key] = (options, clocks, delay)
            report["keys"] = len(cache)
            report["options_retained"] += len(options)
            report["largest_key_options"] = max(report["largest_key_options"], len(options))
        else:
            report["cache_hits"] += 1
        options, clocks, delay = stored
        return options[bisect.bisect_left(clocks, ready - delay):]

    choices.board_options = cached_options
    return report
