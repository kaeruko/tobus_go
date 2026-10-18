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
        and getattr(app.state, "route_engine", None) is not None
        and getattr(app.state, "realtime_provider", None) is not None
    ):
        return

    # Keep startup deterministic. In Lambda mode the explicitly configured
    # validated city bundle is materialized from S3 before the existing Sendai
    # manifest/service-date validation runs. No alternate source is attempted.
    app.state.loading_status = "starting"
    app.state.city_key = "sendai"
    app.state.realtime_bus_supported = True

    coordinate_opt_in = os.getenv("SENDAI_REVIEWED_COORDINATES", "0")
    if coordinate_opt_in not in {"0", "1"}:
        raise RuntimeError("SENDAI_REVIEWED_COORDINATES must be 0 or 1")
    if coordinate_opt_in == "1" and mode not in {"development", "lambda"}:
        raise RuntimeError("reviewed Sendai coordinates require development or lambda runtime")

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
    def normal_backend_factory():
        return SendaiRouteBackend(dataset, walk_radius_m=walk_radius_m)
    backend = normal_backend_factory() if coordinate_opt_in == "0" else None
    engine = backend
    if coordinate_opt_in == "1":
        import json
        from pathlib import Path
        from sendai_practical_bundle import load_reviewed_subway, build_reviewed_municipal_model
        from sendai_operating_period import OperatingPeriodReview
        from sendai_coordinate_routes import SendaiCoordinateScope
        from sendai_coordinate_access import nagamachi_minami_access
        def required_path(name):
            value = os.getenv(name)
            if not value:
                raise RuntimeError(f"{name} is required for reviewed Sendai coordinates")
            return Path(value)
        if mode == "lambda":
            # The exact reviewed inputs live inside the SAME S3 GTFS bundle.
            # Do not read loose Lambda environment paths, test fixtures or an
            # unrelated source on production startup.
            from app.services.sendai_review_bundle import validated_reviewed_paths
            reviewed_paths = validated_reviewed_paths(Path(gtfs_dir))
            review_path = reviewed_paths["municipal"]
            published_path = reviewed_paths["subway_published"]
            subway_review_path = reviewed_paths["subway_review"]
        else:
            review_path = required_path("SENDAI_MUNICIPAL_REVIEW")
            published_path = required_path("SENDAI_SUBWAY_PUBLISHED")
            subway_review_path = required_path("SENDAI_SUBWAY_REVIEW")
        review = json.loads(review_path.read_text(encoding="utf-8"))
        period = OperatingPeriodReview.from_mapping(review["operating_period"])
        subway, _ = load_reviewed_subway(published_path,
            subway_review_path, operating_period=period)
        network = build_reviewed_municipal_model(subway, dataset, review,
            accept_experimental_bus_transfers=True)
        engine = SendaiCoordinateScope(backend, network, period, environment=mode,
            access_reviews=nagamachi_minami_access(network), normal_backend_factory=normal_backend_factory)
        app.state.sendai_reviewed_network = network
        app.state.sendai_operating_period = period

    app.state.transit_dataset = dataset
    app.state.route_backend = backend if backend is not None else engine
    app.state.route_engine = engine
    app.state.realtime_provider = create_sendai_realtime_provider()
    app.state.loading_status = "ready"

