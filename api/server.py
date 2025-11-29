# server.py
import os
import asyncio
import uuid
import json
from fastapi import FastAPI, HTTPException, Form, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import httpx

# ★計算エンジン（toei_engine.py）から必要なクラス・関数をインポート
# ※ファイル名が違う場合は toei_engine の部分を書き換えてください
from toei_engine import (
    build_graph, nearest_phys, haversine,
    TimetableManager, 
    search_best_routes,  # <--- これを使う
    time_str_to_min, min_to_time_str,
    MAX_WALK_SEG_M
)

load_dotenv()

# -------------------- 設定 & グローバル変数 --------------------
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

@app.on_event("startup")
async def _startup():
    global G, TM
    print("[server] Building Graph...")
    # エンジンの関数を使ってグラフ構築
    G = build_graph(BUSSTOP, BUSROUTE, STATIONS, RAILWAYS, walk_radius=WALK_RAD)
    
    print("[server] Loading Timetables (This may take a while)...")
    TM = TimetableManager()
    TM.load_bus_timetables(BUS_TBL)
    TM.load_train_timetables(TRAIN_TBL)
    
    print("[server] Building Name Index for Fuzzy Matching...")
    TM.build_name_index(G)
    
    print("[server] Ready!")

# -------------------- 計算ロジック --------------------
def compute_route_candidates(alat, alon, blat, blon, pref, start_time="10:00"):
    if G is None or TM is None:
        raise HTTPException(500, "Server not ready")

    # A/B地点の特定
    a_phys, ad = nearest_phys(G, alat, alon, station_only=False)
    b_phys, bd = nearest_phys(G, blat, blon, station_only=True)
    if not b_phys or bd > 500:
        b_phys, bd = nearest_phys(G, blat, blon, station_only=False)

    if not a_phys or not b_phys:
        return {"error": "Nearby stations/busstops not found", "candidates": []}

    print(f"[JOB] Search {pref} from {start_time}")

    # ★変更点: 共通関数を一発呼ぶだけ！
    # toei_engine.py で実装した search_best_routes を使う
    results = search_best_routes(
        G, TM, a_phys, b_phys, 
        mode=pref, 
        start_time=start_time, 
        limit=5
    )

    return {"candidates": results}


# -------------------- API エンドポイント --------------------

async def _run_route_job(job_id, alat, alon, blat, blon, pref, start_time):
    # スレッドプールで実行
    loop = asyncio.get_running_loop()
    ROUTE_JOBS[job_id]["status"] = "running"
    try:
        result = await loop.run_in_executor(
            None,
            compute_route_candidates,
            alat, alon, blat, blon, pref, start_time
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
    time: str = Form("10:00") # 出発時刻
):
    job_id = uuid.uuid4().hex
    ROUTE_JOBS[job_id] = {"status": "pending"}
    
    asyncio.create_task(_run_route_job(job_id, alat, alon, blat, blon, pref, time))
    
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