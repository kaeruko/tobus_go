import os
import asyncio
import pickle
import time
import httpx

import initialize_data
from toei_engine import build_graph, TimetableManager

LAMBDA_TMP_DIR = "/tmp/data"
# 事前ビルドされたファイルのパス（コンテナ内の配置場所）
PREBUILT_DATA_PATH = os.getenv("PREBUILT_DATA_PATH", "data/app_data.pkl")

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
    """
    アプリケーション起動時の初期化処理
    事前ビルド済みデータ(app_data.pkl)があればそれを高速ロードする
    """
    start_time = time.time()
    
    # 完全に準備が整うまで、loading_status は starting のままにする
    # (routes.py で 503 を返すために必要)
    app.state.loading_status = "starting"

    # 1. 高速起動パス: Pickleファイルからのロード
    if os.path.exists(PREBUILT_DATA_PATH):
        print(f"[INFO] Loading prebuilt data from {PREBUILT_DATA_PATH}...")
        try:
            with open(PREBUILT_DATA_PATH, "rb") as f:
                data = pickle.load(f)
            
            app.state.G = data["G"]
            app.state.TM = data["TM"]
            app.state.SI = data.get("SI")
            app.state.WALK_RAD = data.get("WALK_RAD", 300)
            
            if not app.state.SI:
                from toei_engine import SpatialIndex
                app.state.SI = SpatialIndex(app.state.G)

            print(f"[INFO] Data loaded in {time.time() - start_time:.2f}s")
            
            # リアルタイムデータの取得タスクを開始
            asyncio.create_task(fetch_realtime_data_loop(app.state.TM))
            
            app.state.loading_status = "ready"
            return
        except Exception as e:
            print(f"[WARNING] Failed to load prebuilt data: {e}. Falling back to slow load.")


    # 2. 低速起動パス (フォールバック): 生データから構築
    # Lambda環境かつデータがない場合のみダウンロード/生成
    if mode == "lambda":
        # S3から事前ビルド済みデータを取得トライ
        bucket_name = os.getenv("S3_BUCKET_NAME")
        if not os.path.exists(PREBUILT_DATA_PATH) and bucket_name:
            import boto3
            import botocore
            
            s3_key = "app_data.pkl" 
            dest_path = "/tmp/app_data.pkl"
            print(f"[INFO] Trying to download s3://{bucket_name}/{s3_key} to {dest_path} ...")
            
            try:
                s3 = boto3.client("s3")
                s3.download_file(bucket_name, s3_key, dest_path)
                print("[INFO] S3 download successful.")
                
                # ダウンロードしたファイルをロードしてみる
                # (再帰呼び出しは避けて、ここでロード処理を共通化してもいいが、
                #  今回はシンプルにパスを書き換えるアプローチで)
                #  -> NOTE: setup_on_startup の冒頭で PREBUILT_DATA_PATH を見てるが、
                #     変数は再代入しても関数冒頭のチェックは通過済みなので、ここでもう一度ロードロジックを書くか、
                #     あるいは再度この関数を呼ぶ？ -> 再度呼ぶのは無限ループリスクあり。
                #     ここではダウンロード成功したら、ロード処理（1.のロジック）と同じことを行う
                
                print(f"[INFO] Loading downloaded data from {dest_path}...")
                with open(dest_path, "rb") as f:
                    data = pickle.load(f)
                
                app.state.G = data["G"]
                app.state.TM = data["TM"]
                app.state.SI = data.get("SI")
                app.state.WALK_RAD = data.get("WALK_RAD", 300)
                
                if not app.state.SI:
                    from toei_engine import SpatialIndex
                    app.state.SI = SpatialIndex(app.state.G)

                print(f"[INFO] Data loaded from S3 in {time.time() - start_time:.2f}s")
                asyncio.create_task(fetch_realtime_data_loop(app.state.TM))
                app.state.loading_status = "ready"
                return

            except Exception as e:
                print(f"[WARNING] S3 download failed: {e}. Falling back to raw initialization.")

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

    gtfs_dir = os.path.join(p["DATA_DIR"], "ToeiBus-GTFS")
    if os.path.exists(gtfs_dir):
        tm.load_gtfs_mappings(gtfs_dir)

    app.state.G = g
    app.state.TM = tm
    app.state.WALK_RAD = p["WALK_RAD"]

    print(f"[INFO] Slow initialization finished in {time.time() - start_time:.2f}s")
    asyncio.create_task(fetch_realtime_data_loop(tm))
    
    app.state.loading_status = "ready"
