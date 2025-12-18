import os
import asyncio
import zipfile
import httpx


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

        # データが存在しない場合は initialize_data.main() でAPIから取得
        data_dir = os.getenv("DATA_DIR", LAMBDA_TMP_DIR)
        required = [
            f"{data_dir}/odpt_BusstopPole.json",
            f"{data_dir}/odpt_BusstopPoleTimetable.json",
            f"{data_dir}/ToeiBus-GTFS/routes.txt",
        ]
        
        if not all(os.path.exists(p) for p in required):
            print("[INFO] Data missing, running initialization...")
            # initialize_data.py は ODPT_API_TOKEN 環境変数が必要です
            import initialize_data
            initialize_data.main()

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
