import os
import asyncio
import zipfile
import boto3
import httpx

import initialize_data
from toei_engine import build_graph, TimetableManager

DATA_ZIP_NAME = "toei_data.zip"
LAMBDA_TMP_DIR = "/tmp/data"

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

def download_data_from_s3_if_needed() -> None:
    bucket = os.getenv("S3_BUCKET_NAME")
    if not bucket:
        return

    data_dir = os.getenv("DATA_DIR", LAMBDA_TMP_DIR)
    os.makedirs(data_dir, exist_ok=True)

    marker = f"{data_dir}/odpt_BusstopPole.json"
    if os.path.exists(marker):
        return

    try:
        s3 = boto3.client("s3")
        zip_path = f"/tmp/{DATA_ZIP_NAME}"
        print(f"[INFO] Downloading {bucket}/{DATA_ZIP_NAME} to {zip_path}")
        s3.download_file(bucket, DATA_ZIP_NAME, zip_path)

        print(f"[INFO] Extracting {zip_path} to /tmp")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall("/tmp")
    except Exception as e:
        print(f"[ERROR] Failed to download/extract from S3: {e}")
        # Initialize data fallback will run next if files are missing

async def fetch_realtime_data_loop(tm: TimetableManager) -> None:
    token = os.getenv("ODPT_API_TOKEN")
    if not token:
        return

    url = "https://api.odpt.org/api/v4/odpt:Train"
    params = {
        "odpt:operator": "odpt.Operator:Toei",
        "acl:consumerKey": token,
    }

    while True:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(url, params=params)
                if r.status_code == 200:
                    tm.update_delays(r.json())
        except Exception:
            pass

        await asyncio.sleep(60)

async def setup_on_startup(app, mode: str) -> None:
    if mode == "lambda":
        os.environ["DATA_DIR"] = os.getenv("DATA_DIR", LAMBDA_TMP_DIR)

        download_data_from_s3_if_needed()

        data_dir = os.getenv("DATA_DIR", LAMBDA_TMP_DIR)
        required = [
            f"{data_dir}/odpt_BusstopPole.json",
            f"{data_dir}/odpt_BusstopPoleTimetable.json",
            f"{data_dir}/ToeiBus-GTFS/routes.txt",
        ]
        if not all(os.path.exists(p) for p in required):
            initialize_data.main(data_dir=data_dir)

    p = _paths()

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

    gtfs_dir = os.path.join(p["DATA_DIR"], "ToeiBus-GTFS")
    if os.path.exists(gtfs_dir):
        tm.load_gtfs_mappings(gtfs_dir)

    app.state.G = g
    app.state.TM = tm
    app.state.WALK_RAD = p["WALK_RAD"]

    asyncio.create_task(fetch_realtime_data_loop(tm))
