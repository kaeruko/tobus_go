from __future__ import annotations

import bisect
import heapq
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from time import perf_counter
from typing import Callable, Literal, Protocol, runtime_checkable

from route_engine import RouteSearchLimitError
from transit_dataset import TransitDataset, TransitMode, TransitStopTime


SearchPreference = Literal["fastest", "fewest_transfers"]
TransitPathKey = tuple[
    tuple[str, str, str, str, int, int, tuple[str, ...]],
    ...,
]


@dataclass(frozen=True, slots=True)
class TransitLeg:
    trip_id: str
    route_id: str
    mode: TransitMode
    from_stop_id: str
    to_stop_id: str
    departure_minute: int
    arrival_minute: int
    stop_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransitItinerary:
    departure_minute: int
    arrival_minute: int
    legs: tuple[TransitLeg, ...]

    @property
    def rides(self) -> int:
        return len(self.legs)

    @property
    def transfers(self) -> int:
        return max(0, self.rides - 1)

    @property
    def total_minutes(self) -> int:
        return self.arrival_minute - self.departure_minute


def itinerary_path_key(itinerary: TransitItinerary) -> TransitPathKey:
    return tuple(
        (
            leg.trip_id,
            leg.route_id,
            leg.from_stop_id,
            leg.to_stop_id,
            leg.departure_minute,
            leg.arrival_minute,
            leg.stop_ids,
        )
        for leg in itinerary.legs
    )


@dataclass(frozen=True, slots=True)
class SearchDiagnostics:
    preference: SearchPreference
    elapsed_seconds: float
    route_found: bool
    visited_states: int = 0
    queue_peak: int = 0
    generated_labels: int = 0
    origin_searches: int = 0
    termination_reason: str = "completed"


@dataclass(frozen=True, slots=True)
class SearchEndpoint:
    stop_id: str
    walk_minutes: int = 0
    walk_meters: float = 0.0
    rank: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.stop_id, str) or not self.stop_id:
            raise ValueError("stop_id is required")
        if (
            isinstance(self.walk_minutes, bool)
            or not isinstance(self.walk_minutes, int)
            or self.walk_minutes < 0
        ):
            raise ValueError("walk_minutes must be an integer >= 0")
        if (
            isinstance(self.walk_meters, bool)
            or not isinstance(self.walk_meters, (int, float))
            or not math.isfinite(self.walk_meters)
            or self.walk_meters < 0
        ):
            raise ValueError("walk_meters must be finite and >= 0")
        if (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank < 0
        ):
            raise ValueError("rank must be an integer >= 0")


@dataclass(frozen=True, slots=True)
class SearchLimits:
    max_visited_states: int = 2_000_000
    max_queue_size: int = 2_000_000
    max_generated_labels: int = 5_000_000
    time_limit_seconds: float = 15.0

    def __post_init__(self) -> None:
        for name, value in (
            ("max_visited_states", self.max_visited_states),
            ("max_queue_size", self.max_queue_size),
            ("max_generated_labels", self.max_generated_labels),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an integer >= 1")
        if (
            isinstance(self.time_limit_seconds, bool)
            or not isinstance(self.time_limit_seconds, (int, float))
            or not math.isfinite(self.time_limit_seconds)
            or self.time_limit_seconds <= 0
        ):
            raise ValueError("time_limit_seconds must be finite and > 0")


@dataclass(frozen=True, slots=True)
class BatchSearchRequest:
    service_date: date
    departure_minute: int
    origins: tuple[SearchEndpoint, ...]
    destinations: tuple[SearchEndpoint, ...]
    preference: SearchPreference
    max_rides: int = 6
    limits: SearchLimits = field(default_factory=SearchLimits)

    def __post_init__(self) -> None:
        if not isinstance(self.service_date, date):
            raise ValueError("service_date must be a date")
        if (
            isinstance(self.departure_minute, bool)
            or not isinstance(self.departure_minute, int)
            or self.departure_minute < 0
        ):
            raise ValueError("departure_minute must be an integer >= 0")
        if not self.origins:
            raise ValueError("origins must not be empty")
        if not self.destinations:
            raise ValueError("destinations must not be empty")
        if self.preference not in ("fastest", "fewest_transfers"):
            raise ValueError(f"unsupported search preference: {self.preference!r}")
        if isinstance(self.max_rides, bool) or not isinstance(self.max_rides, int):
            raise ValueError("max_rides must be an integer")
        if self.max_rides < 1:
            raise ValueError("max_rides must be >= 1")


@dataclass(frozen=True, slots=True)
class PairSearchResult:
    origin_index: int
    destination_index: int
    itinerary: TransitItinerary


@dataclass(frozen=True, slots=True)
class BatchSearchResult:
    pairs: tuple[PairSearchResult, ...]
    diagnostics: SearchDiagnostics


@dataclass(slots=True)
class _SearchCounters:
    visited_states: int = 0
    queue_peak: int = 0
    generated_labels: int = 0
    origin_searches: int = 0


@runtime_checkable
class SearchCore(Protocol):
    def search(self, request: BatchSearchRequest) -> BatchSearchResult:
        ...


class TransitRouteEngine:
    """Static route engine that consumes only TransitDataset."""

    def __init__(
        self,
        dataset: TransitDataset,
        *,
        diagnostics_callback: Callable[[SearchDiagnostics], None] | None = None,
    ):
        self.dataset = dataset
        self._diagnostics_callback = diagnostics_callback
        self._trip_stop_times: dict[str, tuple[TransitStopTime, ...]] = {}
        self._departures_by_stop: dict[str, list[tuple[int, str, int]]] = {}

        grouped: dict[str, list[TransitStopTime]] = {}
        for stop_time in dataset.stop_times:
            grouped.setdefault(stop_time.trip_id, []).append(stop_time)

        for trip_id, rows in grouped.items():
            rows.sort(key=lambda row: row.sequence)
            previous_sequence: int | None = None
            previous_clock: int | None = None
            for row in rows:
                if previous_sequence is not None and row.sequence <= previous_sequence:
                    raise ValueError(f"trip stop_sequence is not increasing: {trip_id}")
                event_clock = (
                    row.departure_minute
                    if row.departure_minute is not None
                    else row.arrival_minute
                )
                if (
                    previous_clock is not None
                    and event_clock is not None
                    and event_clock < previous_clock
                ):
                    raise ValueError(f"trip times go backwards: {trip_id}")
                previous_sequence = row.sequence
                if event_clock is not None:
                    previous_clock = event_clock
                if row.departure_minute is not None:
                    self._departures_by_stop.setdefault(row.stop_id, []).append(
                        (row.departure_minute, trip_id, row.sequence)
                    )
            self._trip_stop_times[trip_id] = tuple(rows)

        missing_stop_times = set(dataset.trips) - set(self._trip_stop_times)
        if missing_stop_times:
            sample = sorted(missing_stop_times)[0]
            raise ValueError(f"trip has no stop_times: {sample}")

        for departures in self._departures_by_stop.values():
            departures.sort()

    def search_fastest(
        self,
        origin_stop_id: str,
        destination_stop_id: str,
        *,
        departure: datetime,
        max_rides: int = 6,
    ) -> TransitItinerary | None:
        result = self.search(
            BatchSearchRequest(
                service_date=departure.date(),
                departure_minute=departure.hour * 60 + departure.minute,
                origins=(SearchEndpoint(origin_stop_id),),
                destinations=(SearchEndpoint(destination_stop_id),),
                preference="fastest",
                max_rides=max_rides,
            )
        )
        return result.pairs[0].itinerary if result.pairs else None

    def search_fewest_transfers(
        self,
        origin_stop_id: str,
        destination_stop_id: str,
        *,
        departure: datetime,
        max_rides: int = 6,
    ) -> TransitItinerary | None:
        result = self.search(
            BatchSearchRequest(
                service_date=departure.date(),
                departure_minute=departure.hour * 60 + departure.minute,
                origins=(SearchEndpoint(origin_stop_id),),
                destinations=(SearchEndpoint(destination_stop_id),),
                preference="fewest_transfers",
                max_rides=max_rides,
            )
        )
        return result.pairs[0].itinerary if result.pairs else None

    def search(self, request: BatchSearchRequest) -> BatchSearchResult:
        for endpoint in (*request.origins, *request.destinations):
            if endpoint.stop_id not in self.dataset.stops:
                raise KeyError(f"unknown stop: {endpoint.stop_id}")

        started_at = perf_counter()
        counters = _SearchCounters()
        pairs: list[PairSearchResult] = []
        try:
            for origin_index, origin in enumerate(request.origins):
                self._check_limits(
                    request.limits,
                    counters,
                    started_at,
                    queue_size=0,
                )
                counters.origin_searches += 1
                found = self._search_destinations(
                    origin.stop_id,
                    request.destinations,
                    service_date=request.service_date,
                    departure_minute=(
                        request.departure_minute + origin.walk_minutes
                    ),
                    objective=request.preference,
                    max_rides=request.max_rides,
                    limits=request.limits,
                    counters=counters,
                    started_at=started_at,
                )
                for destination_index in range(len(request.destinations)):
                    itinerary = found.get(destination_index)
                    if itinerary is not None:
                        pairs.append(
                            PairSearchResult(
                                origin_index=origin_index,
                                destination_index=destination_index,
                                itinerary=itinerary,
                            )
                        )
        except RouteSearchLimitError:
            self._emit_diagnostics(
                request.preference,
                started_at,
                counters,
                route_found=bool(pairs),
                termination_reason="limit",
            )
            raise

        diagnostics = self._emit_diagnostics(
            request.preference,
            started_at,
            counters,
            route_found=bool(pairs),
            termination_reason="completed" if pairs else "exhausted",
        )
        return BatchSearchResult(tuple(pairs), diagnostics)

    def _emit_diagnostics(
        self,
        preference: SearchPreference,
        started_at: float,
        counters: _SearchCounters,
        *,
        route_found: bool,
        termination_reason: str,
    ) -> SearchDiagnostics:
        diagnostics = SearchDiagnostics(
            preference=preference,
            elapsed_seconds=perf_counter() - started_at,
            route_found=route_found,
            visited_states=counters.visited_states,
            queue_peak=counters.queue_peak,
            generated_labels=counters.generated_labels,
            origin_searches=counters.origin_searches,
            termination_reason=termination_reason,
        )
        if self._diagnostics_callback is not None:
            self._diagnostics_callback(diagnostics)
        return diagnostics

    @staticmethod
    def _check_limits(
        limits: SearchLimits,
        counters: _SearchCounters,
        started_at: float,
        *,
        queue_size: int,
    ) -> None:
        elapsed = perf_counter() - started_at
        reason: str | None = None
        if elapsed > limits.time_limit_seconds:
            reason = "time_limit_seconds"
        elif counters.visited_states > limits.max_visited_states:
            reason = "max_visited_states"
        elif queue_size > limits.max_queue_size:
            reason = "max_queue_size"
        elif counters.generated_labels > limits.max_generated_labels:
            reason = "max_generated_labels"
        if reason is not None:
            raise RouteSearchLimitError(
                "GTFS search safety limit exceeded: "
                f"reason={reason} visited={counters.visited_states} "
                f"queue={queue_size} queue_peak={counters.queue_peak} "
                f"generated={counters.generated_labels} "
                f"elapsed_sec={elapsed:.3f}"
            )

    def _search_destinations(
        self,
        origin_stop_id: str,
        destinations: tuple[SearchEndpoint, ...],
        *,
        service_date: date,
        departure_minute: int,
        objective: SearchPreference,
        max_rides: int,
        limits: SearchLimits,
        counters: _SearchCounters,
        started_at: float,
    ) -> dict[int, TransitItinerary]:
        start_minute = departure_minute
        destination_indices: dict[str, list[int]] = {}
        for index, destination in enumerate(destinations):
            destination_indices.setdefault(destination.stop_id, []).append(index)

        found: dict[int, TransitItinerary] = {}
        for destination_index in destination_indices.get(origin_stop_id, ()):
            found[destination_index] = TransitItinerary(
                start_minute,
                start_minute,
                (),
            )
        if len(found) == len(destinations):
            return found

        active_services = self.dataset.active_service_ids(service_date)
        if not active_services:
            return found

        start_state = (origin_stop_id, 0)
        best_label: dict[
            tuple[str, int], tuple[int, TransitPathKey]
        ] = {start_state: (start_minute, ())}
        predecessor: dict[
            tuple[str, int], tuple[tuple[str, int], TransitLeg]
        ] = {}
        queue: list[
            tuple[tuple[int, int], TransitPathKey, int, str, int]
        ] = []

        def priority(time_minute: int, rides: int) -> tuple[int, int]:
            if objective == "fastest":
                return (time_minute, rides)
            return (rides, time_minute)

        serial = 0
        heapq.heappush(
            queue,
            (priority(start_minute, 0), (), serial, origin_stop_id, 0),
        )
        counters.queue_peak = max(counters.queue_peak, len(queue))

        while queue and len(found) < len(destinations):
            queued_priority, queued_path_key, _, stop_id, rides_used = (
                heapq.heappop(queue)
            )
            state = (stop_id, rides_used)
            current_label = best_label.get(state)
            if current_label is None:
                continue
            current_time, current_path_key = current_label
            if (
                queued_priority != priority(current_time, rides_used)
                or queued_path_key != current_path_key
            ):
                continue

            counters.visited_states += 1
            if (
                counters.visited_states > limits.max_visited_states
                or counters.visited_states % 256 == 0
            ):
                self._check_limits(
                    limits,
                    counters,
                    started_at,
                    queue_size=len(queue),
                )

            for destination_index in destination_indices.get(stop_id, ()):
                if destination_index not in found:
                    found[destination_index] = self._reconstruct(
                        predecessor,
                        state,
                        departure_minute=start_minute,
                        arrival_minute=current_time,
                    )
            if len(found) == len(destinations):
                break
            if rides_used >= max_rides:
                continue

            departures = self._departures_by_stop.get(stop_id, ())
            index = bisect.bisect_left(departures, (current_time, "", -1))
            for departure_minute, trip_id, origin_sequence in departures[index:]:
                trip = self.dataset.trips[trip_id]
                if trip.service_id not in active_services:
                    continue
                route = self.dataset.routes[trip.route_id]
                rows = self._trip_stop_times[trip_id]
                downstream = [row for row in rows if row.sequence > origin_sequence]
                if not downstream:
                    continue
                next_rides = rides_used + 1
                traversed = [stop_id]
                for row in downstream:
                    traversed.append(row.stop_id)
                    if row.arrival_minute is None:
                        continue
                    next_state = (row.stop_id, next_rides)
                    leg = TransitLeg(
                        trip_id=trip.id,
                        route_id=trip.route_id,
                        mode=route.mode,
                        from_stop_id=stop_id,
                        to_stop_id=row.stop_id,
                        departure_minute=departure_minute,
                        arrival_minute=row.arrival_minute,
                        stop_ids=tuple(traversed),
                    )
                    next_path_key = current_path_key + (
                        (
                            leg.trip_id,
                            leg.route_id,
                            leg.from_stop_id,
                            leg.to_stop_id,
                            leg.departure_minute,
                            leg.arrival_minute,
                            leg.stop_ids,
                        ),
                    )
                    next_label = (row.arrival_minute, next_path_key)
                    prior = best_label.get(next_state)
                    if prior is not None and prior <= next_label:
                        continue
                    best_label[next_state] = next_label
                    predecessor[next_state] = (state, leg)
                    serial += 1
                    counters.generated_labels += 1
                    heapq.heappush(
                        queue,
                        (
                            priority(row.arrival_minute, next_rides),
                            next_path_key,
                            serial,
                            row.stop_id,
                            next_rides,
                        ),
                    )
                    counters.queue_peak = max(counters.queue_peak, len(queue))
                    if (
                        len(queue) > limits.max_queue_size
                        or counters.generated_labels > limits.max_generated_labels
                        or counters.generated_labels % 256 == 0
                    ):
                        self._check_limits(
                            limits,
                            counters,
                            started_at,
                            queue_size=len(queue),
                        )
        return found

    @staticmethod
    def _reconstruct(
        predecessor: dict[
            tuple[str, int], tuple[tuple[str, int], TransitLeg]
        ],
        state: tuple[str, int],
        *,
        departure_minute: int,
        arrival_minute: int,
    ) -> TransitItinerary:
        legs: list[TransitLeg] = []
        cursor = state
        while cursor in predecessor:
            previous, leg = predecessor[cursor]
            legs.append(leg)
            cursor = previous
        legs.reverse()
        return TransitItinerary(
            departure_minute=departure_minute,
            arrival_minute=arrival_minute,
            legs=tuple(legs),
        )


class PythonTransitSearchCore(TransitRouteEngine):
    """Named Python implementation of the replaceable SearchCore boundary."""
