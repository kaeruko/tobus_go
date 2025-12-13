# server.py
from mangum import Mangum
import os
import asyncio
import uuid
import json
from fastapi import FastAPI, HTTPException, Form, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import httpx
import datetime

# ★計算エンジン（toei_engine.py）から必要なクラス・関数をインポート
# ※ファイル名が違う場合は toei_engine の部分を書き換えてください
from toei_engine import (
    build_graph, nearest_phys, haversine,
    TimetableManager,
    search_best_routes,
    search_best_routes_with_retry, # <--- 追加
    add_virtual_destination_node,
    time_str_to_min, min_to_time_str,
    MAX_WALK_SEG_M
)
import toei_engine
print(f"[DEBUG_SERVER] Loaded toei_engine from: {toei_engine.__file__}")

load_dotenv()

# -------------------- 設定 & グローバル変数 --------------------
ODPT_API_TOKEN = os.getenv("ODPT_API_TOKEN") # ★.envに追加してください
ROUTE_JOBS: dict[str, dict] = {}
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

DATA_DIR   = os.getenv("DATA_DIR", "data")
BUSSTOP    = os.getenv("BUSSTOP",   f"{DATA_DIR}/odpt_BusstopPole.json")
BUSROUTE   = os.getenv("BUSROUTE",  f"{DATA_DIR}/odpt_BusroutePattern.json")
STATIONS   = os.getenv("STATIONS",  f"{DATA_DIR}/odpt_Station.json")
RAILWAYS   = os.getenv("RAILWAYS",  f"{DATA_DIR}/odpt_Railway.json")
# 時刻表パス
BUS_TBL    = os.getenv("BUS_TBL",   f"{DATA_DIR}/odpt_BusstopPoleTimetable.json")
TRAIN_TBL  = os.getenv("TRAIN_TBL", f"{DATA_DIR}/odpt_TrainTimetable.json")

WALK_RAD   = int(os.getenv("WALK_RADIUS", "300"))

app = FastAPI(title="Toei Route API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ★グローバル変数: グラフ(G) と 時刻表マネージャー(TM)
G = None
TM = None

# ★追加: 定期実行タスク
async def fetch_realtime_data_loop():
    """
    1分ごとに ODPT API からリアルタイム列車情報を取得し、
    TimetableManager に反映させるバックグラウンドタスク
    """
    if not ODPT_API_TOKEN:
        print("[WARN] ODPT_API_TOKEN not set. Realtime updates disabled.")
        return

    url = "https://api.odpt.org/api/v4/odpt:Train"
    params = {
        "odpt:operator": "odpt.Operator:Toei",
        "acl:consumerKey": ODPT_API_TOKEN
    }

    while True:
        try:
            async with httpx.AsyncClient() as client:
                # print("[server] Fetching realtime train data...")
                r = await client.get(url, params=params)
                if r.status_code == 200:
                    data = r.json()
                    # エンジン側の辞書を更新
                    if TM:
                        TM.update_delays(data)
                else:
                    print(f"[Error] API fetch failed: {r.status_code}")
        except Exception as e:
            print(f"[Error] Realtime fetch loop error: {e}")

        # 60秒待機
        await asyncio.sleep(60)

@app.on_event("startup")
async def _startup():
    global G, TM

    # ★データはDockerイメージ内にあるので初期化不要
    print("[server] Building Graph...")
    # エンジンの関数を使ってグラフ構築
    G = build_graph(BUSSTOP, BUSROUTE, STATIONS, RAILWAYS, walk_radius=WALK_RAD)
    
    print("[server] Loading Timetables (This may take a while)...")
    TM = TimetableManager()
    TM.load_bus_timetables(BUS_TBL)
    TM.load_bus_route_patterns(BUSROUTE)
    TM.load_train_timetables(TRAIN_TBL)
    
    print("[server] Building Name Index for Fuzzy Matching...")
    TM.build_name_index(G)
    
    gtfs_dir = os.path.join(DATA_DIR, "ToeiBus-GTFS")
    if os.path.exists(gtfs_dir):
        TM.load_gtfs_mappings(gtfs_dir)
    else:
        print(f"[WARN] GTFS dir not found at {gtfs_dir}")
    
    # ★追加: バックグラウンドタスクの開始
    asyncio.create_task(fetch_realtime_data_loop())
    
    print("[server] Ready!")

# -------------------- 計算ロジック --------------------
def determine_day_type(date_str):
    """
    日付文字列 (YYYY-MM-DD) から day_type を判定
    Returns: "weekday", "saturday", or "holiday"
    """
    if not date_str:
        # デフォルトは今日
        target_date = datetime.date.today()
    else:
        try:
            target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            print(f"[WARN] Invalid date format: {date_str}, using today")
            target_date = datetime.date.today()
    
    # 曜日判定 (0=月曜, 6=日曜)
    weekday = target_date.weekday()
    
    # 祝日判定
    try:
        import japanese_holidays
        is_holiday = japanese_holidays.is_holiday(target_date)
    except ImportError:
        print("[WARN] japanese_holidays not installed. Install with: pip install japanese-holidays")
        is_holiday = False
    
    # 日曜日または祝日
    if weekday == 6 or is_holiday:
        return "holiday"
    # 土曜日
    elif weekday == 5:
        return "saturday"
    # 平日
    else:
        return "weekday"

def compute_route_candidates(alat, alon, blat, blon, pref, start_time="10:00", date_str=None):
    if G is None or TM is None:
        raise HTTPException(500, "Server not ready")

    # A/B地点の特定
    a_phys, ad = nearest_phys(G, alat, alon, station_only=False)
    b_phys, bd = nearest_phys(G, blat, blon, station_only=True)
    if not b_phys or bd > 500:
        b_phys, bd = nearest_phys(G, blat, blon, station_only=False)

    if not a_phys or not b_phys:
        return {"error": "Nearby stations/busstops not found", "candidates": []}

    virtual_graph, dest_node, conn_count = add_virtual_destination_node(
        G, blat, blon, name="目的地", walk_radius=WALK_RAD
    )
    if conn_count == 0:
        print(
            f"[DEBUG_DEST] No nearby Toei nodes within walk radius {WALK_RAD}m for destination."
        )

    # 日付から day_type を判定
    day_type = determine_day_type(date_str)
    print(f"[JOB] Search {pref} from {start_time}, date={date_str}, day_type={day_type}")

    # ★変更点: 共通関数を一発呼ぶだけ！
    # toei_engine.py で実装した search_best_routes を使う
    # ★変更: リトライ付き検索を使用
    results = search_best_routes_with_retry(
        virtual_graph,
        TM,
        a_phys,
        b_phys,
        mode=pref, # pref_mode を pref に修正
        start_time=start_time, # time_str を start_time に修正
        target_date_str=date_str,  # 日付を渡す
        limit=5,
        target_node=dest_node,
    )

    if not results:
        print(
            f"[DEBUG_DEST] Virtual destination search produced no candidates. Fallback to nearest node {b_phys}."
        )
        results = search_best_routes_with_retry(
            G,
            TM,
            a_phys,
            b_phys,
            mode=pref,
            start_time=start_time,
            target_date_str=date_str,
            limit=5,
        )
    else:
        for cand in results:
            steps = cand.get("steps") or []
            if not steps:
                continue
            last = steps[-1]
            meters = last.get("meters") or last.get("distance") or 0
            print(
                f"[DEBUG_DEST] Candidate {cand.get('id')} last_kind={last.get('kind')} "
                f"to={last.get('to')} meters={meters}"
            )

    return {"candidates": results}


# -------------------- API エンドポイント --------------------

async def _run_route_job(job_id, alat, alon, blat, blon, pref, start_time, date_str):
    # スレッドプールで実行
    loop = asyncio.get_running_loop()
    ROUTE_JOBS[job_id]["status"] = "running"
    try:
        result = await loop.run_in_executor(
            None,
            compute_route_candidates,
            alat, alon, blat, blon, pref, start_time, date_str
        )
        ROUTE_JOBS[job_id]["status"] = "done"
        ROUTE_JOBS[job_id]["result"] = result
    except Exception as e:
        import traceback
        traceback.print_exc()
        ROUTE_JOBS[job_id]["status"] = "error"
        ROUTE_JOBS[job_id]["error"] = str(e)

@app.post("/route")
async def route_start(
    alat: float = Form(...),
    alon: float = Form(...),
    blat: float = Form(...),
    blon: float = Form(...),
    pref: str = Form("cost"), # cost | time
    time: str = Form("10:00"), # 出発時刻
    date: str = Form(None) # 出発日付 (YYYY-MM-DD形式、オプション)
):
    job_id = uuid.uuid4().hex
    ROUTE_JOBS[job_id] = {"status": "pending"}
    
    asyncio.create_task(_run_route_job(job_id, alat, alon, blat, blon, pref, time, date))
    
    return {"job_id": job_id}

@app.get("/route")
async def route_poll(job_id: str = Query(...)):
    job = ROUTE_JOBS.get(job_id)
    if not job: raise HTTPException(404, "Job not found")
    return job

# (以下 autocomplete などは既存のまま)
@app.get("/autocomplete")
async def autocomplete(q: str = Query(...)):
    if not GOOGLE_MAPS_API_KEY: return {"predictions": []}
    url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
    params = {"key": GOOGLE_MAPS_API_KEY, "input": q, "language": "ja", "components": "country:jp"}
    async with httpx.AsyncClient(timeout=10.0) as cl:
        r = await cl.get(url, params=params)
    return r.json()

@app.get("/details")
async def details(place_id: str = Query(...)):
    if not GOOGLE_MAPS_API_KEY: return {"result": {}}
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {"key": GOOGLE_MAPS_API_KEY, "place_id": place_id, "language":"ja", "fields":"geometry,name,formatted_address"}
    async with httpx.AsyncClient(timeout=10.0) as cl:
        r = await cl.get(url, params=params)
    return r.json()


handler = Mangum(app)