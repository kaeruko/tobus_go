import os
import asyncio
import hashlib
import json
import pickle
import time
import zipfile
import httpx

import initialize_data
from toei_engine import build_graph, TimetableManager, parse_realtime_gtfs
from gtfs_loader import gtfs_repo

LAMBDA_TMP_DIR = "/tmp/data"
_REALTIME_REFRESH_LOCK = asyncio.Lock()
# 事前ビルドされたファイルのパス（コンテナ内の配置場所）
PREBUILT_DATA_PATH = os.getenv("PREBUILT_DATA_PATH", "data/app_data.pkl")


def _gtfs_key_from_state(s3, bucket_name: str) -> tuple[str, str | None]:
    state_key = os.getenv("S3_GTFS_STATE_KEY")
    if not state_key:
        return os.getenv("S3_GTFS_KEY", "ToeiBus-GTFS.zip"), None

    try:
        response = s3.get_object(Bucket=bucket_name, Key=state_key)
        state = json.loads(response["Body"].read())
        object_key = state["object_key"]
        expected_sha256 = state["sha256"]
    except Exception as error:
        raise RuntimeError(
            f"Could not resolve GTFS state from S3 key {state_key}"
        ) from error
    if not isinstance(object_key, str) or not object_key:
        raise RuntimeError("GTFS state has no object_key")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise RuntimeError("GTFS state has an invalid sha256")
    return object_key, expected_sha256


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_gtfs_archive(zip_path: str, data_dir: str) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        root = os.path.realpath(data_dir)
        file_names = [
            member.filename.replace("\\", "/")
            for member in archive.infolist()
            if not member.is_dir()
        ]
        # The ODPT source ZIP stores GTFS files at its root.  Older deployment
        # artifacts wrapped them in ToeiBus-GTFS/, so both layouts are accepted.
        has_root_routes = "routes.txt" in file_names
        extraction_root = (
            os.path.join(root, "ToeiBus-GTFS") if has_root_routes else root
        )
        os.makedirs(extraction_root, exist_ok=True)
        extraction_root = os.path.realpath(extraction_root)
        for member in archive.infolist():
            target = os.path.realpath(
                os.path.join(extraction_root, member.filename)
            )
            if os.path.commonpath([extraction_root, target]) != extraction_root:
                raise RuntimeError(
                    f"Unsafe path in GTFS archive: {member.filename}"
                )
        archive.extractall(extraction_root)


def _download_lambda_data(data_dir: str = LAMBDA_TMP_DIR) -> str:
    bucket_name = os.getenv("S3_BUCKET_NAME")
    if not bucket_name:
        raise RuntimeError("S3_BUCKET_NAME is required in lambda mode")

    prebuilt_key = os.getenv("S3_PREBUILT_KEY", "app_data.pkl")
    prebuilt_path = os.path.join(data_dir, "app_data.pkl")
    gtfs_marker = os.path.join(data_dir, "ToeiBus-GTFS", "routes.txt")
    gtfs_zip_path = os.path.join(data_dir, ".ToeiBus-GTFS.zip")

    os.makedirs(data_dir, exist_ok=True)

    import boto3

    s3 = boto3.client("s3")
    gtfs_key, expected_gtfs_sha256 = _gtfs_key_from_state(s3, bucket_name)
    if not os.path.exists(prebuilt_path):
        print(f"[INFO] Downloading prebuilt data from S3 key {prebuilt_key}...")
        s3.download_file(bucket_name, prebuilt_key, prebuilt_path)

    if not os.path.exists(gtfs_marker):
        print(f"[INFO] Downloading GTFS data from S3 key {gtfs_key}...")
        s3.download_file(bucket_name, gtfs_key, gtfs_zip_path)
        if (
            expected_gtfs_sha256
            and _sha256_file(gtfs_zip_path) != expected_gtfs_sha256
        ):
            raise RuntimeError("Downloaded GTFS SHA-256 does not match state")
        _extract_gtfs_archive(gtfs_zip_path, data_dir)
        os.remove(gtfs_zip_path)

    if not os.path.exists(gtfs_marker):
        raise RuntimeError(f"GTFS archive did not contain {gtfs_marker}")

    return prebuilt_path


def _env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    return int(v) if v else default


def _paths() -> dict:
    data_dir = os.getenv("DATA_DIR", "data")
    return {
        "DATA_DIR": data_dir,
        "BUSSTOP": os.getenv("BUSSTOP", f"{data_dir}/odpt_BusstopPole.json"),
        "BUSROUTE": os.getenv("BUSROUTE", f"{data_dir}/odpt_BusroutePattern.json"),
        "STATIONS": os.getenv("STATIONS", f"{data_dir}/odpt_Station.json"),
        "RAILWAYS": os.getenv("RAILWAYS", f"{data_dir}/odpt_Railway.json"),
        "BUS_TBL": os.getenv("BUS_TBL", f"{data_dir}/odpt_BusstopPoleTimetable.json"),
        "TRAIN_TBL": os.getenv("TRAIN_TBL", f"{data_dir}/odpt_TrainTimetable.json"),
        "WALK_RAD": _env_int("WALK_RADIUS", 300),
    }


def _invalidate_realtime_bus_positions(
    tm: TimetableManager,
    error: str,
) -> None:
    """Invalidate the current snapshot so callers cannot reuse stale positions."""
    tm.latest_bus_positions = []
    tm.latest_bus_positions_refreshed_at = 0.0
    tm.latest_bus_positions_fetched_at = 0.0
    tm.latest_bus_positions_error = error


async def refresh_realtime_bus_positions(
    tm: TimetableManager,
    max_age_seconds: int = 45,
) -> bool:
    token = os.getenv("ODPT_API_TOKEN")
    if not token:
        error = "ODPT_API_TOKEN not set"
        _invalidate_realtime_bus_positions(tm, error)
        print(f"[WARN] {error}. Realtime data will not be available.")
        return False

    refreshed_at = getattr(tm, "latest_bus_positions_refreshed_at", 0.0)
    if (
        tm.latest_bus_positions
        and refreshed_at
        and time.monotonic() - refreshed_at < max_age_seconds
    ):
        return True

    async with _REALTIME_REFRESH_LOCK:
        refreshed_at = getattr(tm, "latest_bus_positions_refreshed_at", 0.0)
        if (
            tm.latest_bus_positions
            and refreshed_at
            and time.monotonic() - refreshed_at < max_age_seconds
        ):
            return True

        try:
            url_gtfs = "https://api-public.odpt.org/api/v4/gtfs/realtime/ToeiBus"
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    url_gtfs,
                    params={"acl:consumerKey": token},
                )
            if response.status_code != 200:
                error = f"GTFS-RT HTTP {response.status_code}"
                _invalidate_realtime_bus_positions(tm, error)
                print(f"[WARN] Failed to fetch GTFS-RT: {response.status_code}")
                return False

            tm.latest_bus_positions = parse_realtime_gtfs(response.content)
            tm.latest_bus_positions_refreshed_at = time.monotonic()
            tm.latest_bus_positions_fetched_at = time.time()
            tm.latest_bus_positions_error = None
            print(
                "[INFO] Updated realtime bus positions: "
                f"{len(tm.latest_bus_positions)} vehicles"
            )
            return True
        except Exception as error:
            _invalidate_realtime_bus_positions(tm, repr(error))
            print(f"[WARN] Failed to refresh GTFS-RT: {error}")
            return False


async def fetch_realtime_data_loop(tm: TimetableManager) -> None:
    token = os.getenv("ODPT_API_TOKEN")
    if not token:
        print("[WARN] ODPT_API_TOKEN not set. Realtime data will not be available.")
        return

    url_train = "https://api-public.odpt.org/api/v4/odpt:Train"
    params_base = {
        "odpt:operator": "odpt.Operator:Toei",
        "acl:consumerKey": token,
    }

    print("[INFO] Starting Realtime Data Fetch Loop (Train & Bus)...")

    while True:
        await asyncio.sleep(60)

        try:
            async with httpx.AsyncClient() as client:
                # 1. Fetch Train Data
                r_train = await client.get(url_train, params=params_base)
                if r_train.status_code == 200:
                    tm.update_delays(r_train.json())

        except Exception as e:
            print(f"[WARN] Realtime fetch error: {e}")

        await refresh_realtime_bus_positions(tm, max_age_seconds=0)


async def setup_on_startup(app, mode: str) -> None:
    """
    アプリケーション起動時の初期化処理
    事前ビルド済みデータ(app_data.pkl)があればそれを高速ロードする
    """
    if (
        getattr(app.state, "loading_status", None) == "ready"
        and getattr(app.state, "G", None) is not None
        and getattr(app.state, "TM", None) is not None
    ):
        if getattr(app.state, "route_engine", None) is None:
            from tokyo_route_engine import TokyoRouteEngine

            app.state.route_engine = TokyoRouteEngine(app)
        print("[INFO] Runtime already initialized; reusing cached data.")
        return

    start_time = time.time()

    # 完全に準備が整うまで、loading_status は starting のままにする
    # (routes.py で 503 を返すために必要)
    app.state.loading_status = "starting"

    prebuilt_data_path = PREBUILT_DATA_PATH
    if mode == "lambda" and not os.path.exists(prebuilt_data_path):
        os.environ["DATA_DIR"] = os.getenv("DATA_DIR", LAMBDA_TMP_DIR)
        prebuilt_data_path = _download_lambda_data(os.environ["DATA_DIR"])

    # 1. 高速起動パス: Pickleファイルからのロード
    if os.path.exists(prebuilt_data_path):
        print(f"[INFO] Loading prebuilt data from {prebuilt_data_path}...")
        try:
            with open(prebuilt_data_path, "rb") as f:
                data = pickle.load(f)

            app.state.G = data["G"]
            app.state.TM = data["TM"]
            app.state.SI = data.get("SI")
            app.state.WALK_RAD = data.get("WALK_RAD", 300)

            if not app.state.SI:
                from toei_engine import SpatialIndex
                app.state.SI = SpatialIndex(app.state.G)

            # Ensure GTFS repo is loaded (critical for ID injection)
            # The pickle only includes TM/G/SI, not the singleton state of gtfs_repo
            paths = _paths()
            gtfs_dir = os.path.join(paths["DATA_DIR"], "ToeiBus-GTFS")
            if os.path.exists(gtfs_dir):
                print(f"[INFO] Explicitly loading GTFS data from {gtfs_dir}...")
                gtfs_repo.load_data(gtfs_dir)
            else:
                print(f"[WARN] GTFS directory {gtfs_dir} not found. Reverse lookup may fail.")

            print(f"[INFO] Data loaded in {time.time() - start_time:.2f}s")

            # Lambdaはレスポンス後にイベントループを凍結するため、
            # 初回分だけは起動完了前に待って取得する。
            await refresh_realtime_bus_positions(
                app.state.TM,
                max_age_seconds=0,
            )
            asyncio.create_task(fetch_realtime_data_loop(app.state.TM))

            from tokyo_route_engine import TokyoRouteEngine

            app.state.route_engine = TokyoRouteEngine(app)
            app.state.loading_status = "ready"
            return
        except Exception as e:
            print(f"[WARNING] Failed to load prebuilt data: {e}. Falling back to slow load.")

    # 2. 低速起動パス (フォールバック): 生データから構築
    # Lambda環境で事前データを読み込めなかった場合のみ生データから再生成
    if mode == "lambda":
        # 以下、生データからの構築フォールバック
        os.environ["DATA_DIR"] = os.getenv("DATA_DIR", LAMBDA_TMP_DIR)
        data_dir = os.getenv("DATA_DIR", LAMBDA_TMP_DIR)

        required = [
            f"{data_dir}/odpt_BusstopPole.json",
            f"{data_dir}/odpt_BusstopPoleTimetable.json",
            f"{data_dir}/ToeiBus-GTFS/routes.txt",
        ]

        if not all(os.path.exists(p) for p in required):
            print("[INFO] Data missing, running initialization...")
            initialize_data.main(data_dir=data_dir)

    p = _paths()

    print("[INFO] Building Graph from raw JSON...")
    g = build_graph(
        p["BUSSTOP"],
        p["BUSROUTE"],
        p["STATIONS"],
        p["RAILWAYS"],
        walk_radius=p["WALK_RAD"],
    )

    tm = TimetableManager()
    tm.load_bus_timetables(p["BUS_TBL"])
    tm.load_bus_route_patterns(p["BUSROUTE"])
    tm.load_train_timetables(p["TRAIN_TBL"])
    tm.build_name_index(g)

    from toei_engine import SpatialIndex
    si = SpatialIndex(g)
    app.state.SI = si

    # GTFS Logic Removed
    # gtfs_dir = os.path.join(p["DATA_DIR"], "ToeiBus-GTFS")
    # if os.path.exists(gtfs_dir):
    #     tm.load_gtfs_mappings(gtfs_dir)

    app.state.G = g
    app.state.TM = tm
    app.state.WALK_RAD = p["WALK_RAD"]

    print(f"[INFO] Slow initialization finished in {time.time() - start_time:.2f}s")

    # [ADDED] Save the built data to pickle so next startup is fast
    try:
        print(f"[INFO] Saving prebuilt data to {PREBUILT_DATA_PATH}...")
        save_data = {
            "G": g,
            "TM": tm,
            "SI": si,
            "WALK_RAD": p["WALK_RAD"]
        }
        with open(PREBUILT_DATA_PATH, "wb") as f:
            pickle.dump(save_data, f)
        print("[INFO] Prebuilt data saved successfully.")
    except Exception as e:
        print(f"[WARN] Failed to save prebuilt data: {e}")

    asyncio.create_task(fetch_realtime_data_loop(tm))

    # [ADDED] Initialize GtfsRepository
    gtfs_dir = os.path.join(p["DATA_DIR"], "ToeiBus-GTFS")
    if os.path.exists(gtfs_dir):
        print(f"[INFO] Loading GTFS Static Data from {gtfs_dir}...")
        try:
            gtfs_repo.load_data(gtfs_dir)
        except Exception as e:
            print(f"[WARN] Failed to load GTFS data: {e}")
    else:
        print(f"[WARN] GTFS directory not found: {gtfs_dir}")

    from tokyo_route_engine import TokyoRouteEngine

    app.state.route_engine = TokyoRouteEngine(app)
    app.state.loading_status = "ready"
