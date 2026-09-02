import asyncio
import os
import pickle
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.tokyo_runtime_fast import setup_on_startup
from gtfs_state import LambdaCompiledAssets


class TokyoRuntimeFastTest(unittest.IsolatedAsyncioTestCase):
    async def test_lambda_startup_loads_static_state_without_waiting_for_realtime(self):
        with tempfile.TemporaryDirectory() as directory:
            prebuilt_path = os.path.join(directory, "app_data.pkl")
            compiled_path = os.path.join(directory, "gtfs_state.pkl.gz")
            with open(prebuilt_path, "wb") as file:
                pickle.dump(
                    {
                        "G": "graph",
                        "TM": "timetable",
                        "SI": "spatial-index",
                        "WALK_RAD": 300,
                    },
                    file,
                )
            with open(compiled_path, "wb") as file:
                file.write(b"compiled-placeholder")

            app = SimpleNamespace(state=SimpleNamespace())
            periodic_refresh = AsyncMock(return_value=None)
            with (
                patch(
                    "app.tokyo_runtime_fast.download_compiled_lambda_assets",
                    return_value=LambdaCompiledAssets(
                        prebuilt_path=prebuilt_path,
                        compiled_state_path=compiled_path,
                        source_sha256="a" * 64,
                    ),
                ),
                patch("app.tokyo_runtime_fast.load_compiled_state") as load_state,
                patch(
                    "app.tokyo_runtime_fast.fetch_realtime_data_loop",
                    periodic_refresh,
                ),
            ):
                await setup_on_startup(app, "lambda")
                await asyncio.sleep(0)

            self.assertEqual(app.state.loading_status, "ready")
            self.assertEqual(app.state.G, "graph")
            self.assertEqual(app.state.TM, "timetable")
            self.assertEqual(app.state.SI, "spatial-index")
            load_state.assert_called_once()
            periodic_refresh.assert_awaited_once_with("timetable")

    async def test_lambda_startup_reuses_initialized_runtime(self):
        app = SimpleNamespace(
            state=SimpleNamespace(
                loading_status="ready",
                G=object(),
                TM=object(),
            )
        )
        with patch(
            "app.tokyo_runtime_fast.download_compiled_lambda_assets"
        ) as download:
            await setup_on_startup(app, "lambda")
        download.assert_not_called()

    async def test_local_mode_keeps_existing_runtime_path(self):
        app = SimpleNamespace(state=SimpleNamespace())
        legacy = AsyncMock(return_value=None)
        with patch("app.tokyo_runtime_fast.setup_legacy_on_startup", legacy):
            await setup_on_startup(app, "local")
        legacy.assert_awaited_once_with(app, "local")

    async def test_missing_prebuilt_keys_fail_before_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            prebuilt_path = os.path.join(directory, "app_data.pkl")
            with open(prebuilt_path, "wb") as file:
                pickle.dump({"G": "graph"}, file)
            compiled_path = os.path.join(directory, "gtfs_state.pkl.gz")
            with open(compiled_path, "wb") as file:
                file.write(b"unused")

            app = SimpleNamespace(state=SimpleNamespace())
            with patch(
                "app.tokyo_runtime_fast.download_compiled_lambda_assets",
                return_value=LambdaCompiledAssets(
                    prebuilt_path=prebuilt_path,
                    compiled_state_path=compiled_path,
                    source_sha256="a" * 64,
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "missing required keys"):
                    await setup_on_startup(app, "lambda")

            self.assertEqual(app.state.loading_status, "starting")


if __name__ == "__main__":
    unittest.main()
