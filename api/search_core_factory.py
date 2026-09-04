from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Callable

from transit_dataset import TransitDataset
from route_engine import RouteSearchLimitError
from transit_engine import (
    BatchSearchRequest,
    BatchSearchResult,
    PythonTransitSearchCore,
    SearchCore,
    SearchDiagnostics,
    SearchEndpoint,
    TransitItinerary,
    itinerary_path_key,
)


_LOGGER = logging.getLogger(__name__)
_SUPPORTED_MODES = ("python", "rust", "shadow")


def _walk_signature(
    endpoints: tuple[SearchEndpoint, ...],
    index: int,
) -> dict[str, Any]:
    if not isinstance(index, int) or index < 0 or index >= len(endpoints):
        return {"invalid_endpoint_index": index}
    endpoint = endpoints[index]
    return {
        "walk_minutes": endpoint.walk_minutes,
        "walk_meters": endpoint.walk_meters,
        "rank": endpoint.rank,
    }


def _result_signature(
    result: BatchSearchResult,
    request: BatchSearchRequest,
) -> dict[str, Any]:
    return {
        "diagnostics": {
            "route_found": result.diagnostics.route_found,
            "visited_states": result.diagnostics.visited_states,
            "queue_peak": result.diagnostics.queue_peak,
            "generated_labels": result.diagnostics.generated_labels,
            "origin_searches": result.diagnostics.origin_searches,
            "termination_reason": result.diagnostics.termination_reason,
        },
        "pairs": [
            {
                "origin_index": pair.origin_index,
                "destination_index": pair.destination_index,
                "origin": _walk_signature(
                    request.origins,
                    pair.origin_index,
                ),
                "destination": _walk_signature(
                    request.destinations,
                    pair.destination_index,
                ),
                "departure_minute": pair.itinerary.departure_minute,
                "arrival_minute": pair.itinerary.arrival_minute,
                "final_arrival_minute": (
                    pair.itinerary.arrival_minute
                    + request.destinations[
                        pair.destination_index
                    ].walk_minutes
                    if (
                        isinstance(pair.destination_index, int)
                        and 0 <= pair.destination_index < len(request.destinations)
                    )
                    else None
                ),
                "rides": pair.itinerary.rides,
                "transfers": pair.itinerary.transfers,
                "path": itinerary_path_key(pair.itinerary),
            }
            for pair in result.pairs
        ],
    }


class ShadowTransitSearchCore:
    """Return Python results while comparing Rust on the same immutable request."""

    def __init__(
        self,
        python_core: SearchCore,
        rust_core: SearchCore,
        *,
        mismatch_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.python_core = python_core
        self.rust_core = rust_core
        self._mismatch_callback = mismatch_callback

    def search(self, request: BatchSearchRequest) -> BatchSearchResult:
        python_result, python_error = self._run(self.python_core, request)
        rust_result, rust_error = self._run(self.rust_core, request)
        comparison = {
            "python_error": self._error_category(python_error),
            "rust_error": self._error_category(rust_error),
            "python": (
                None
                if python_result is None
                else _result_signature(python_result, request)
            ),
            "rust": (
                None
                if rust_result is None
                else _result_signature(rust_result, request)
            ),
        }
        if comparison["python_error"] != comparison["rust_error"] or (
            comparison["python"] != comparison["rust"]
        ):
            report = {
                "event": "route_search_shadow_mismatch",
                "preference": request.preference,
                "service_date": request.service_date.isoformat(),
                "departure_minute": request.departure_minute,
                **comparison,
            }
            _LOGGER.error("%s", json.dumps(report, ensure_ascii=False))
            if self._mismatch_callback is not None:
                self._mismatch_callback(report)

        if python_error is not None:
            raise python_error
        if python_result is None:
            raise RuntimeError("Python shadow core returned neither result nor error")
        return python_result

    @staticmethod
    def _run(
        core: SearchCore,
        request: BatchSearchRequest,
    ) -> tuple[BatchSearchResult | None, Exception | None]:
        try:
            return core.search(request), None
        except Exception as error:  # compared, then Python's error is re-raised
            return None, error

    @staticmethod
    def _error_category(error: Exception | None) -> dict[str, str | None] | None:
        if error is None:
            return None
        limit_reason = None
        if isinstance(error, RouteSearchLimitError):
            match = re.search(r"\breason=([^\s]+)", str(error))
            if match is not None:
                limit_reason = match.group(1)
        return {
            "category": type(error).__name__,
            "termination_reason": limit_reason,
        }

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


def create_search_core(
    dataset: TransitDataset,
    *,
    mode: str | None = None,
    diagnostics_callback: Callable[[SearchDiagnostics], None] | None = None,
    mismatch_callback: Callable[[dict[str, Any]], None] | None = None,
) -> SearchCore:
    selected_mode = os.getenv("ROUTE_SEARCH_CORE", "python") if mode is None else mode
    if selected_mode not in _SUPPORTED_MODES:
        raise RuntimeError(
            "ROUTE_SEARCH_CORE must be one of "
            f"{', '.join(_SUPPORTED_MODES)}; got {selected_mode!r}"
        )
    if selected_mode == "python":
        return PythonTransitSearchCore(
            dataset,
            diagnostics_callback=diagnostics_callback,
        )

    from rust_transit_search_core import RustTransitSearchCore

    if selected_mode == "rust":
        return RustTransitSearchCore(
            dataset,
            diagnostics_callback=diagnostics_callback,
        )
    return ShadowTransitSearchCore(
        PythonTransitSearchCore(
            dataset,
            diagnostics_callback=diagnostics_callback,
        ),
        RustTransitSearchCore(dataset),
        mismatch_callback=mismatch_callback,
    )
