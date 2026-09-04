from __future__ import annotations

import os

from yokohama_realtime import create_yokohama_bus_realtime_provider
from yokohama_transit import (
    YokohamaBusRouteBackend,
    load_yokohama_bus_dataset,
    required_expected_service_date,
)


async def setup_yokohama_on_startup(app, mode: str) -> None:
    if (
        getattr(app.state, "loading_status", None) == "ready"
        and getattr(app.state, "transit_dataset", None) is not None
        and getattr(app.state, "route_backend", None) is not None
        and getattr(app.state, "route_engine", None) is not None
        and getattr(app.state, "realtime_provider", None) is not None
    ):
        return

    del mode
    app.state.city_key = "yokohama"
    app.state.loading_status = "starting"
    app.state.transit_dataset = None
    app.state.route_backend = None
    app.state.route_engine = None
    app.state.realtime_provider = None
    app.state.realtime_bus_supported = False

    gtfs_dir = os.getenv("YOKOHAMA_BUS_GTFS_DIR")
    if gtfs_dir is None or gtfs_dir == "":
        raise RuntimeError("YOKOHAMA_BUS_GTFS_DIR is required for Yokohama runtime")
    expected_service_date = required_expected_service_date()

    dataset = load_yokohama_bus_dataset(
        gtfs_dir,
        expected_service_date=expected_service_date,
    )
    backend = YokohamaBusRouteBackend(
        dataset,
    )
    realtime_provider = create_yokohama_bus_realtime_provider()

    app.state.transit_dataset = dataset
    app.state.route_backend = backend
    app.state.route_engine = backend
    app.state.realtime_provider = realtime_provider
    app.state.realtime_bus_supported = True
    app.state.loading_status = "ready"
