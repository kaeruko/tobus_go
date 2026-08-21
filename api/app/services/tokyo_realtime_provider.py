from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


RefreshFunction = Callable[[Any, int], Awaitable[bool]]


class TokyoRealtimeProvider:
    """Adapter from Tokyo's existing cached VehiclePosition runtime.

    The existing refresh/cache implementation remains the source of truth. This
    class only exposes it through the shared RealtimeProvider contract.
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
        return tuple(rows)

    async def trip_updates(self) -> tuple[dict[str, Any], ...]:
        raise NotImplementedError("Tokyo TripUpdates capability is not enabled")

    async def alerts(self) -> tuple[dict[str, Any], ...]:
        raise NotImplementedError("Tokyo GTFS-Realtime Alert capability is not enabled")
