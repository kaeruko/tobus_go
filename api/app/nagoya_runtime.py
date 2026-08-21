from __future__ import annotations

import os

from nagoya_transit import (
    NagoyaRouteBackend,
    load_nagoya_dataset,
    required_expected_revision,
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


async def setup_nagoya_on_startup(app, mode: str) -> None:
    # `mode` is deliberately accepted to match the shared app-factory startup
    # contract. Nagoya does not download or initialize any Toei/ODPT data.
    del mode

    app.state.loading_status = "starting"
    app.state.city_key = "nagoya"
    app.state.realtime_bus_supported = False

    gtfs_dir = os.getenv("NAGOYA_GTFS_DIR")
    if gtfs_dir is None or gtfs_dir == "":
        raise RuntimeError("NAGOYA_GTFS_DIR is required for Nagoya runtime")
    expected_revision = required_expected_revision()
    walk_radius_m = _positive_int_env("NAGOYA_WALK_RADIUS_M", 600)

    dataset = load_nagoya_dataset(
        gtfs_dir,
        expected_revision=expected_revision,
    )
    backend = NagoyaRouteBackend(
        dataset,
        walk_radius_m=walk_radius_m,
    )
    app.state.transit_dataset = dataset
    app.state.route_backend = backend
    app.state.loading_status = "ready"
