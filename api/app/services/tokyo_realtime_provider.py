from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .vehicle_progress import resolve_vehicle_stop_progress


RefreshFunction = Callable[[Any, int], Awaitable[bool]]


def _normalize_tokyo_vehicle(row: dict[str, Any]) -> dict[str, Any]:
    """Expose Tokyo's legacy cached row through the shared VehiclePosition shape."""

    observed_sequence = row.get("observed_stop_sequence")
    if (
        isinstance(observed_sequence, bool)
        or not isinstance(observed_sequence, int)
        or observed_sequence <= 0
    ):
        raise RuntimeError(
            "Tokyo VehiclePosition current_stop_sequence must be a positive integer"
        )

    legacy_from_sequence = row.get("from_stop_sequence")
    previous_sequence = None
    if observed_sequence > 1:
        if legacy_from_sequence is None:
            raise RuntimeError(
                "Tokyo VehiclePosition previous stop sequence is missing "
                f"after the first stop: current_stop_sequence={observed_sequence}"
            )
        previous_sequence = legacy_from_sequence

    progress = resolve_vehicle_stop_progress(
        observed_stop_sequence=observed_sequence,
        current_status=row.get("current_status"),
        previous_stop_sequence=previous_sequence,
    )

    route_id = row.get("route_id") or row.get("odpt:busroute")
    if not isinstance(route_id, str) or not route_id:
        raise RuntimeError("Tokyo VehiclePosition route_id is missing")

    normalized = dict(row)
    normalized.update(
        {
            "route_id": route_id,
            "stop_id": row.get("raw_stop_id"),
            "current_stop_sequence": observed_sequence,
            "from_stop_sequence": progress.from_stop_sequence,
            "before_first_stop": progress.before_first_stop,
            "timestamp": row.get("vehicle_timestamp"),
        }
    )

    if progress.before_first_stop:
        # There is no previously reached stop yet. Keep the actual vehicle
        # position and reported first stop, but never claim the first stop has
        # already been departed.
        normalized["odpt:fromBusstopPole"] = None
        normalized["next_stop"] = row.get("raw_stop_name")
        normalized["next_stop_id"] = row.get("raw_stop_id")

    return normalized


class TokyoRealtimeProvider:
    """Adapter from Tokyo's existing cached VehiclePosition runtime.

    The existing refresh/cache implementation remains the source of truth. This
    adapter normalizes Tokyo rows to the same VehiclePosition semantics used by
    the other city runtimes before exposing them through RealtimeProvider.
    """

    def __init__(self, timetable_manager: Any, refresh: RefreshFunction) -> None:
        if timetable_manager is None:
            raise ValueError("TokyoRealtimeProvider requires a timetable manager")
        self._tm = timetable_manager
        self._refresh = refresh

    async def vehicle_positions(
        self, *, force_refresh: bool = False
    ) -> tuple[dict[str, Any], ...]:
        ok = await self._refresh(
            self._tm,
            0 if force_refresh else 45,
        )
        if not ok:
            detail = getattr(
                self._tm,
                "latest_bus_positions_error",
                "Tokyo VehiclePosition refresh failed",
            )
            raise RuntimeError(str(detail))
        rows = getattr(self._tm, "latest_bus_positions", None)
        if not rows:
            raise RuntimeError("Tokyo VehiclePosition refresh returned no positions")
        return tuple(_normalize_tokyo_vehicle(row) for row in rows)

    async def trip_updates(self) -> tuple[dict[str, Any], ...]:
        raise NotImplementedError("Tokyo TripUpdates capability is not enabled")

    async def alerts(self) -> tuple[dict[str, Any], ...]:
        raise NotImplementedError("Tokyo GTFS-Realtime Alert capability is not enabled")
