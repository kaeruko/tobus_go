from __future__ import annotations

import os

from sendai_realtime import create_sendai_realtime_provider
from sendai_transit import (
    SendaiRouteBackend,
    load_sendai_dataset,
    required_expected_service_date,
)


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be > 0")
    return value


async def setup_sendai_on_startup(app, mode: str) -> None:
    # Keep startup deterministic. Static data must already be provisioned and
    # validated; startup does not fetch another source or fall back to Tokyo.
    del mode

    app.state.loading_status = "starting"
    app.state.city_key = "sendai"
    app.state.realtime_bus_supported = True

    gtfs_dir = os.getenv("SENDAI_GTFS_DIR")
    if gtfs_dir is None or gtfs_dir == "":
        raise RuntimeError("SENDAI_GTFS_DIR is required for Sendai runtime")
    expected_service_date = required_expected_service_date()
    walk_radius_m = _positive_int_env("SENDAI_WALK_RADIUS_M", 600)

    dataset = load_sendai_dataset(
        gtfs_dir,
        expected_service_date=expected_service_date,
    )
    backend = SendaiRouteBackend(
        dataset,
        walk_radius_m=walk_radius_m,
    )

    app.state.transit_dataset = dataset
    app.state.route_backend = backend
    app.state.realtime_provider = create_sendai_realtime_provider()
    app.state.loading_status = "ready"
