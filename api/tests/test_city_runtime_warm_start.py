from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.nagoya_runtime import setup_nagoya_on_startup
from app.sendai_runtime import setup_sendai_on_startup
from app.yokohama_runtime import setup_yokohama_on_startup


class _App:
    def __init__(self) -> None:
        self.state = SimpleNamespace()


class CityRuntimeWarmStartTest(unittest.IsolatedAsyncioTestCase):
    async def test_nagoya_reuses_fully_initialized_runtime_on_second_startup(self) -> None:
        app = _App()
        dataset = object()
        backend = object()

        with (
            patch.dict(
                os.environ,
                {
                    "NAGOYA_GTFS_DIR": "/tmp/gtfs/nagoya",
                    "NAGOYA_GTFS_EXPECTED_REVISION": "2026-03-28",
                },
                clear=False,
            ),
            patch(
                "app.nagoya_runtime.materialize_city_gtfs_bundle",
                return_value="/tmp/gtfs/nagoya",
            ) as materialize,
            patch(
                "app.nagoya_runtime.load_nagoya_dataset",
                return_value=dataset,
            ) as load_dataset,
            patch(
                "app.nagoya_runtime.NagoyaRouteBackend",
                return_value=backend,
            ) as make_backend,
        ):
            await setup_nagoya_on_startup(app, "lambda")
            await setup_nagoya_on_startup(app, "lambda")

        materialize.assert_called_once()
        load_dataset.assert_called_once_with(
            "/tmp/gtfs/nagoya",
            expected_revision="2026-03-28",
        )
        make_backend.assert_called_once()
        self.assertIs(app.state.transit_dataset, dataset)
        self.assertIs(app.state.route_backend, backend)
        self.assertEqual(app.state.loading_status, "ready")

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
        self.assertIs(app.state.realtime_provider, realtime)
        self.assertEqual(app.state.loading_status, "ready")

    async def test_yokohama_reuses_fully_initialized_runtime_on_second_startup(self) -> None:
        app = _App()
        dataset = object()
        backend = object()

        with (
            patch.dict(
                os.environ,
                {
                    "YOKOHAMA_BUS_GTFS_DIR": "/tmp/gtfs/yokohama",
                    "YOKOHAMA_BUS_GTFS_EXPECTED_SERVICE_DATE": "2026-08-29",
                },
                clear=False,
            ),
            patch(
                "app.yokohama_runtime.load_yokohama_bus_dataset",
                return_value=dataset,
            ) as load_dataset,
            patch(
                "app.yokohama_runtime.YokohamaBusRouteBackend",
                return_value=backend,
            ) as make_backend,
        ):
            await setup_yokohama_on_startup(app, "lambda")
            await setup_yokohama_on_startup(app, "lambda")

        load_dataset.assert_called_once_with(
            "/tmp/gtfs/yokohama",
            expected_service_date="2026-08-29",
        )
        make_backend.assert_called_once_with(dataset)
        self.assertIs(app.state.transit_dataset, dataset)
        self.assertIs(app.state.route_backend, backend)
        self.assertIsNone(app.state.realtime_provider)
        self.assertFalse(app.state.realtime_bus_supported)
        self.assertEqual(app.state.loading_status, "ready")


if __name__ == "__main__":
    unittest.main()
