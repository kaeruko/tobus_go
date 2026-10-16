from __future__ import annotations

import os

from yokohama_fare_coverage import YokohamaFareCoverage
from yokohama_realtime import create_yokohama_bus_realtime_provider
from yokohama_transit import (
    YokohamaBusRouteBackend,
    load_yokohama_bus_dataset,
    required_expected_service_date,
)


def _realtime_mode() -> str:
    value = os.getenv("YOKOHAMA_REALTIME_MODE", "disabled")
    if value not in {"disabled", "enabled"}:
        raise RuntimeError(
            "YOKOHAMA_REALTIME_MODE must be 'disabled' or 'enabled': "
            f"{value!r}"
        )
    return value


async def setup_yokohama_on_startup(app, mode: str) -> None:
    realtime_mode = _realtime_mode()
    if "YOKOHAMA_TRANSFER_WALK_MODE" in os.environ:
        raise RuntimeError("YOKOHAMA_TRANSFER_WALK_MODE was removed; only explicit directed reviews are supported")
    if getattr(app.state, "loading_status", None) == "ready" and (
        getattr(app.state, "realtime_mode", None) != realtime_mode
    ):
        raise RuntimeError("Yokohama realtime mode changed after initialization")
    if (
        getattr(app.state, "loading_status", None) == "ready"
        and getattr(app.state, "transit_dataset", None) is not None
        and getattr(app.state, "route_backend", None) is not None
        and getattr(app.state, "route_engine", None) is not None
        and (realtime_mode == "disabled" or getattr(app.state, "realtime_provider", None) is not None)
    ):
        return

    app.state.city_key = "yokohama"
    app.state.loading_status = "starting"
    app.state.transit_dataset = None
    app.state.route_backend = None
    app.state.route_engine = None
    app.state.realtime_provider = None
    app.state.realtime_bus_supported = False
    app.state.realtime_mode = realtime_mode

    gtfs_dir = os.getenv("YOKOHAMA_BUS_GTFS_DIR")
    if gtfs_dir is None or gtfs_dir == "":
        raise RuntimeError("YOKOHAMA_BUS_GTFS_DIR is required for Yokohama runtime")
    expected_service_date = required_expected_service_date()

    dataset = load_yokohama_bus_dataset(
        gtfs_dir,
        expected_service_date=expected_service_date,
    )
    coverage_path = os.getenv("YOKOHAMA_FARE_COVERAGE_PATH")
    if coverage_path == "":
        raise RuntimeError("YOKOHAMA_FARE_COVERAGE_PATH must not be empty when set")
    fare_coverage = (
        None
        if coverage_path is None
        else YokohamaFareCoverage.load(coverage_path, dataset=dataset)
    )
    backend = YokohamaBusRouteBackend(
        dataset,
        fare_coverage=fare_coverage,
    )
    subway_dir = os.getenv("YOKOHAMA_SUBWAY_GTFS_DIR")
    links_path = os.getenv("YOKOHAMA_REVIEWED_TRANSFERS_PATH")
    if subway_dir == "" or links_path == "":
        raise RuntimeError("Yokohama subway/transfer paths must not be empty when set")
    if links_path is not None and subway_dir is None:
        raise RuntimeError("Yokohama transfer reviews require YOKOHAMA_SUBWAY_GTFS_DIR")
    if subway_dir is not None:
        from yokohama_municipal_backend import (
            YokohamaMunicipalRouteBackend, load_reviewed_transfer_links,
        )
        from yokohama_subway import load_reviewed_yokohama_subway_coverage

        if fare_coverage is None:
            raise RuntimeError("Municipal integration requires YOKOHAMA_FARE_COVERAGE_PATH")
        subway_coverage = load_reviewed_yokohama_subway_coverage(
            subway_dir, expected_service_date=expected_service_date,
        )
        links = () if links_path is None else load_reviewed_transfer_links(
            links_path, fare_coverage, subway_coverage,
        )
        backend = YokohamaMunicipalRouteBackend(
            fare_coverage, subway_coverage, transfer_links=links,
        )
    realtime_provider = (
        create_yokohama_bus_realtime_provider()
        if realtime_mode == "enabled" else None
    )

    app.state.transit_dataset = dataset
    app.state.route_backend = backend
    app.state.route_engine = backend
    app.state.realtime_provider = realtime_provider
    app.state.realtime_bus_supported = realtime_mode == "enabled"
    app.state.loading_status = "ready"

