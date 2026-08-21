from __future__ import annotations

import os

from app.services.city_gtfs_bundle import materialize_city_gtfs_bundle
from sendai_realtime import create_sendai_realtime_provider
from sendai_transit import (
    SENDAI_MANIFEST_FILENAME,
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
    # Mangum runs the ASGI lifespan for each Lambda invocation. Reuse only a
    # fully initialized in-memory runtime from the same warm Lambda container.
    # A partially initialized/failed runtime is never treated as ready.
    if (
        getattr(app.state, "loading_status", None) == "ready"
        and getattr(app.state, "transit_dataset", None) is not None
        and getattr(app.state, "route_backend", None) is not None
        and getattr(app.state, "realtime_provider", None) is not None
    ):
        return

    # Keep startup deterministic. In Lambda mode the explicitly configured
    # validated city bundle is materialized from S3 before the existing Sendai
    # manifest/service-date validation runs. No alternate source is attempted.
    app.state.loading_status = "starting"
    app.state.city_key = "sendai"
    app.state.realtime_bus_supported = True

    gtfs_dir = os.getenv("SENDAI_GTFS_DIR")
    if gtfs_dir is None or gtfs_dir == "":
        raise RuntimeError("SENDAI_GTFS_DIR is required for Sendai runtime")
    expected_service_date = required_expected_service_date()
    walk_radius_m = _positive_int_env("SENDAI_WALK_RADIUS_M", 600)

    if mode == "lambda":
        gtfs_dir = str(
            materialize_city_gtfs_bundle(
                city="sendai",
                target_dir=gtfs_dir,
                manifest_filename=SENDAI_MANIFEST_FILENAME,
            )
        )

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
