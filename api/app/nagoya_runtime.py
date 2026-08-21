from __future__ import annotations

import os

from app.services.city_gtfs_bundle import materialize_city_gtfs_bundle
from nagoya_transit import (
    NAGOYA_MANIFEST_FILENAME,
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
    # Nagoya never downloads or initializes Toei/ODPT data. In Lambda mode the
    # explicitly configured validated city bundle is materialized from S3 into
    # NAGOYA_GTFS_DIR before the existing manifest loader validates it again.
    app.state.loading_status = "starting"
    app.state.city_key = "nagoya"
    app.state.realtime_bus_supported = False

    gtfs_dir = os.getenv("NAGOYA_GTFS_DIR")
    if gtfs_dir is None or gtfs_dir == "":
        raise RuntimeError("NAGOYA_GTFS_DIR is required for Nagoya runtime")
    expected_revision = required_expected_revision()
    walk_radius_m = _positive_int_env("NAGOYA_WALK_RADIUS_M", 600)

    if mode == "lambda":
        gtfs_dir = str(
            materialize_city_gtfs_bundle(
                city="nagoya",
                target_dir=gtfs_dir,
                manifest_filename=NAGOYA_MANIFEST_FILENAME,
            )
        )

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
