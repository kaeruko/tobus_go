from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.sendai_runtime import setup_sendai_on_startup


class _App:
    def __init__(self) -> None:
        self.state = SimpleNamespace()


class CityRuntimeWarmStartTest(unittest.IsolatedAsyncioTestCase):
    async def test_sendai_reuses_fully_initialized_runtime_on_second_startup(self) -> None:
        app = _App()
        dataset = object()
        backend = object()
        realtime = object()

        with (
            patch.dict(
                os.environ,
                {
                    "SENDAI_GTFS_DIR": "/tmp/gtfs/sendai",
                    "SENDAI_GTFS_EXPECTED_SERVICE_DATE": "2026-08-22",
                },
                clear=False,
            ),
            patch(
                "app.sendai_runtime.materialize_city_gtfs_bundle",
                return_value="/tmp/gtfs/sendai",
            ) as materialize,
            patch(
                "app.sendai_runtime.load_sendai_dataset",
                return_value=dataset,
            ) as load_dataset,
            patch(
                "app.sendai_runtime.SendaiRouteBackend",
                return_value=backend,
            ) as make_backend,
            patch(
                "app.sendai_runtime.create_sendai_realtime_provider",
                return_value=realtime,
            ) as make_realtime,
        ):
            await setup_sendai_on_startup(app, "lambda")
            await setup_sendai_on_startup(app, "lambda")

        materialize.assert_called_once()
        load_dataset.assert_called_once_with(
            "/tmp/gtfs/sendai",
            expected_service_date="2026-08-22",
        )
        make_backend.assert_called_once()
        make_realtime.assert_called_once_with()
        self.assertIs(app.state.transit_dataset, dataset)
        self.assertIs(app.state.route_backend, backend)
        self.assertIs(app.state.route_engine, backend)
        self.assertIs(app.state.realtime_provider, realtime)
        self.assertEqual(app.state.loading_status, "ready")


    async def test_lambda_reviewed_opt_in_loads_explicit_sources_only(self) -> None:
        # A production-capable Lambda still needs every reviewed input. This
        # does not deploy or fetch anything; all external boundaries are mocked.
        app = _App()
        dataset, network, period, reviewed_engine = object(), object(), object(), object()
        with tempfile.TemporaryDirectory() as directory:
            review_path = Path(directory) / "review.json"
            review_path.write_text(json.dumps({"operating_period": {}}), encoding="utf-8")
            env = {
                "APP_CITY": "sendai",
                "SENDAI_REVIEWED_COORDINATES": "1",
                "SENDAI_GTFS_DIR": "/validated/sendai",
                "SENDAI_GTFS_EXPECTED_SERVICE_DATE": "2026-10-16",
                "SENDAI_MUNICIPAL_REVIEW": str(review_path),
                "SENDAI_SUBWAY_PUBLISHED": str(Path(directory) / "published.json"),
                "SENDAI_SUBWAY_REVIEW": str(Path(directory) / "subway_review.json"),
            }
            with (
                patch.dict(os.environ, env),
                patch("app.sendai_runtime.materialize_city_gtfs_bundle",
                    return_value="/validated/sendai") as materialize,
                patch("app.sendai_runtime.load_sendai_dataset",
                    return_value=dataset) as load_dataset,
                patch("app.sendai_runtime.SendaiRouteBackend") as normal_backend,
                patch("sendai_operating_period.OperatingPeriodReview.from_mapping",
                    return_value=period) as read_period,
                patch("sendai_practical_bundle.load_reviewed_subway",
                    return_value=(object(), None)) as load_subway,
                patch("sendai_practical_bundle.build_reviewed_municipal_model",
                    return_value=network) as build_network,
                patch("sendai_coordinate_access.nagamachi_minami_access",
                    return_value=()) as access,
                patch("sendai_coordinate_routes.SendaiCoordinateScope",
                    return_value=reviewed_engine) as make_scope,
                patch("app.sendai_runtime.create_sendai_realtime_provider",
                    return_value=object()),
            ):
                await setup_sendai_on_startup(app, "lambda")
                self.assertIs(app.state.route_engine, reviewed_engine)
                self.assertIs(app.state.sendai_reviewed_network, network)
                materialize.assert_called_once()
                load_dataset.assert_called_once_with("/validated/sendai",
                    expected_service_date="2026-10-16")
                normal_backend.assert_not_called()
                read_period.assert_called_once_with({})
                load_subway.assert_called_once()
                build_network.assert_called_once()
                access.assert_called_once_with(network)
                self.assertEqual(make_scope.call_args.kwargs["environment"], "lambda")

    async def test_reviewed_opt_in_rejects_non_development_local_runtime(self) -> None:
        app = _App()
        with patch.dict(os.environ, {"SENDAI_REVIEWED_COORDINATES": "1"}):
            with self.assertRaisesRegex(RuntimeError, "development or lambda"):
                await setup_sendai_on_startup(app, "local")
        self.assertFalse(hasattr(app.state, "route_engine"))

    async def test_reviewed_lambda_requires_all_inputs_before_network_construction(self) -> None:
        app = _App()
        with (
            patch.dict(os.environ, {
                "SENDAI_REVIEWED_COORDINATES": "1",
                "SENDAI_GTFS_DIR": "/validated/sendai",
                "SENDAI_GTFS_EXPECTED_SERVICE_DATE": "2026-10-16",
            }),
            patch("app.sendai_runtime.materialize_city_gtfs_bundle",
                return_value="/validated/sendai"),
            patch("app.sendai_runtime.load_sendai_dataset", return_value=object()),
            patch("app.sendai_runtime.SendaiRouteBackend") as normal_backend,
            patch("sendai_practical_bundle.build_reviewed_municipal_model") as build_network,
        ):
            for key in ("SENDAI_MUNICIPAL_REVIEW", "SENDAI_SUBWAY_PUBLISHED",
                        "SENDAI_SUBWAY_REVIEW"):
                os.environ.pop(key, None)
            with self.assertRaisesRegex(RuntimeError, "SENDAI_MUNICIPAL_REVIEW is required"):
                await setup_sendai_on_startup(app, "lambda")
            normal_backend.assert_not_called()
            build_network.assert_not_called()

if __name__ == "__main__":
    unittest.main()
