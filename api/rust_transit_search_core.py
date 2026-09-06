from __future__ import annotations

from datetime import datetime
from typing import Callable

from route_engine import RouteEngineUnavailableError, RouteSearchLimitError
from transit_dataset import TransitDataset
from transit_engine import (
    BatchSearchRequest,
    BatchSearchResult,
    PairSearchResult,
    SearchDiagnostics,
    SearchEndpoint,
    TransitItinerary,
    TransitLeg,
)


class RustTransitSearchCore:
    """PyO3-backed SearchCore with an immutable, integer-indexed GTFS snapshot."""

    def __init__(
        self,
        dataset: TransitDataset,
        *,
        diagnostics_callback: Callable[[SearchDiagnostics], None] | None = None,
    ) -> None:
        try:
            from _transit_search_core import TransitSearchIndex
        except ImportError as error:
            raise RouteEngineUnavailableError(
                "Rust route search extension is not installed"
            ) from error

        self.dataset = dataset
        self._diagnostics_callback = diagnostics_callback
        self._stop_ids = tuple(sorted(dataset.stops))
        self._route_ids = tuple(sorted(dataset.routes))
        self._trip_ids = tuple(sorted(dataset.trips))
        service_ids = {
            trip.service_id for trip in dataset.trips.values()
        } | set(dataset.calendars) | {
            exception.service_id for exception in dataset.service_exceptions
        }
        self._service_ids = tuple(sorted(service_ids))
        self._stop_indices = {
            stop_id: index for index, stop_id in enumerate(self._stop_ids)
        }
        route_indices = {
            route_id: index for index, route_id in enumerate(self._route_ids)
        }
        service_indices = {
            service_id: index
            for index, service_id in enumerate(self._service_ids)
        }

        rows_by_trip = {trip_id: [] for trip_id in self._trip_ids}
        for row in dataset.stop_times:
            rows_by_trip[row.trip_id].append(row)

        trip_route_indices: list[int] = []
        trip_service_indices: list[int] = []
        trip_offsets = [0]
        trip_stop_indices: list[int] = []
        arrival_minutes: list[int] = []
        departure_minutes: list[int] = []
        for trip_id in self._trip_ids:
            trip = dataset.trips[trip_id]
            trip_route_indices.append(route_indices[trip.route_id])
            trip_service_indices.append(service_indices[trip.service_id])
            rows = sorted(rows_by_trip[trip_id], key=lambda row: row.sequence)
            for row in rows:
                trip_stop_indices.append(self._stop_indices[row.stop_id])
                arrival_minutes.append(
                    -1 if row.arrival_minute is None else row.arrival_minute
                )
                departure_minutes.append(
                    -1 if row.departure_minute is None else row.departure_minute
                )
            trip_offsets.append(len(trip_stop_indices))

        self._index = TransitSearchIndex(
            len(self._stop_ids),
            len(self._route_ids),
            len(self._service_ids),
            trip_route_indices,
            trip_service_indices,
            trip_offsets,
            trip_stop_indices,
            arrival_minutes,
            departure_minutes,
        )

    def search(self, request: BatchSearchRequest) -> BatchSearchResult:
        if request.max_rides > 255:
            raise ValueError("Rust SearchCore requires max_rides <= 255")
        try:
            origin_rows = [
                (self._stop_indices[endpoint.stop_id], endpoint.walk_minutes)
                for endpoint in request.origins
            ]
            destination_rows = [
                (self._stop_indices[endpoint.stop_id], endpoint.walk_minutes)
                for endpoint in request.destinations
            ]
        except KeyError as error:
            raise KeyError(f"unknown stop: {error.args[0]}") from error

        active_service_ids = self.dataset.active_service_ids(
            request.service_date
        )
        active_services = [
            service_id in active_service_ids
            for service_id in self._service_ids
        ]
        raw_pairs, raw_diagnostics = self._index.search(
            active_services,
            request.departure_minute,
            origin_rows,
            destination_rows,
            request.preference,
            request.max_rides,
            request.limits.max_visited_states,
            request.limits.max_queue_size,
            request.limits.max_generated_labels,
            request.limits.time_limit_seconds,
        )
        (
            visited_states,
            queue_peak,
            generated_labels,
            origin_searches,
            native_termination_reason,
            elapsed_nanoseconds,
        ) = raw_diagnostics
        is_limit = native_termination_reason.startswith("limit:")
        diagnostics = SearchDiagnostics(
            preference=request.preference,
            elapsed_seconds=elapsed_nanoseconds / 1_000_000_000,
            route_found=bool(raw_pairs),
            visited_states=visited_states,
            queue_peak=queue_peak,
            generated_labels=generated_labels,
            origin_searches=origin_searches,
            termination_reason=(
                "limit" if is_limit else native_termination_reason
            ),
        )
        if self._diagnostics_callback is not None:
            self._diagnostics_callback(diagnostics)
        if is_limit:
            reason = native_termination_reason.split(":", 1)[1]
            raise RouteSearchLimitError(
                "GTFS search safety limit exceeded: "
                f"reason={reason} visited={visited_states} "
                f"queue_peak={queue_peak} generated={generated_labels} "
                f"elapsed_sec={diagnostics.elapsed_seconds:.3f}"
            )

        pairs = tuple(self._convert_pair(raw) for raw in raw_pairs)
        return BatchSearchResult(pairs=pairs, diagnostics=diagnostics)

    def _convert_pair(self, raw: tuple) -> PairSearchResult:
        (
            origin_index,
            destination_index,
            departure_minute,
            arrival_minute,
            raw_legs,
        ) = raw
        legs = []
        for raw_leg in raw_legs:
            (
                trip_index,
                route_index,
                from_stop_index,
                to_stop_index,
                leg_departure,
                leg_arrival,
                stop_indices,
            ) = raw_leg
            route_id = self._route_ids[route_index]
            legs.append(
                TransitLeg(
                    trip_id=self._trip_ids[trip_index],
                    route_id=route_id,
                    mode=self.dataset.routes[route_id].mode,
                    from_stop_id=self._stop_ids[from_stop_index],
                    to_stop_id=self._stop_ids[to_stop_index],
                    departure_minute=leg_departure,
                    arrival_minute=leg_arrival,
                    stop_ids=tuple(
                        self._stop_ids[index] for index in stop_indices
                    ),
                )
            )
        return PairSearchResult(
            origin_index=origin_index,
            destination_index=destination_index,
            itinerary=TransitItinerary(
                departure_minute=departure_minute,
                arrival_minute=arrival_minute,
                legs=tuple(legs),
            ),
        )

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
