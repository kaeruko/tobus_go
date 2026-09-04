from __future__ import annotations

import asyncio
import os
import pickle
import time

from gtfs_loader import gtfs_repo
from gtfs_state import download_compiled_lambda_assets, load_compiled_state
from toei_engine import SpatialIndex
from tokyo_route_engine import TokyoRouteEngine

from .runtime import LAMBDA_TMP_DIR, fetch_realtime_data_loop
from .runtime import setup_on_startup as setup_legacy_on_startup


async def setup_on_startup(app, mode: str) -> None:
    """Initialize Tokyo.

    Local development keeps the existing raw-data path. Lambda startup uses the
    prebuilt graph/timetable pickle plus the versioned compiled GTFS state. Any
    missing or mismatched compiled artifact is fatal; it never falls back to the
    expensive CSV parser.
    """
    if mode != "lambda":
        await setup_legacy_on_startup(app, mode)
        if getattr(app.state, "route_engine", None) is None:
            app.state.route_engine = TokyoRouteEngine(app)
        return

    if (
        getattr(app.state, "loading_status", None) == "ready"
        and getattr(app.state, "G", None) is not None
        and getattr(app.state, "TM", None) is not None
    ):
        if getattr(app.state, "route_engine", None) is None:
            app.state.route_engine = TokyoRouteEngine(app)
        print("[INFO] Tokyo Lambda runtime already initialized; reusing cached data.")
        return

    start_time = time.time()
    app.state.loading_status = "starting"

    data_dir = os.getenv("DATA_DIR", LAMBDA_TMP_DIR)
    os.environ["DATA_DIR"] = data_dir
    assets = download_compiled_lambda_assets(data_dir)

    print(f"[INFO] Loading prebuilt data from {assets.prebuilt_path}...")
    try:
        with open(assets.prebuilt_path, "rb") as file:
            data = pickle.load(file)
    except Exception as error:
        raise RuntimeError(
            f"Could not load required Tokyo prebuilt data from {assets.prebuilt_path}"
        ) from error

    if not isinstance(data, dict):
        raise RuntimeError("Tokyo prebuilt data root must be a dictionary")
    missing = [key for key in ("G", "TM") if key not in data]
    if missing:
        raise RuntimeError(
            "Tokyo prebuilt data is missing required keys: " + ", ".join(missing)
        )

    app.state.G = data["G"]
    app.state.TM = data["TM"]
    app.state.SI = data.get("SI")
    app.state.WALK_RAD = data.get("WALK_RAD", 300)

    if app.state.SI is None:
        app.state.SI = SpatialIndex(app.state.G)

    print(
        "[INFO] Loading compiled GTFS state from "
        f"{assets.compiled_state_path}..."
    )
    load_compiled_state(
        gtfs_repo,
        assets.compiled_state_path,
        expected_source_sha256=assets.source_sha256,
    )

    print(f"[INFO] Tokyo static data ready in {time.time() - start_time:.2f}s")

    # Do not block startup on GTFS-Realtime. /bus/location already refreshes
    # through TokyoRealtimeProvider on demand. Keep the existing periodic task as
    # best-effort warm-runtime maintenance without making /warmup wait for it.
    asyncio.create_task(fetch_realtime_data_loop(app.state.TM))

    app.state.route_engine = TokyoRouteEngine(app)
    app.state.loading_status = "ready"
