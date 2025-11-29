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
    find_fastest_path, find_top_k_paths, calculate_real_arrival_time,
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

# -------------------- 補助関数: パスをUI用セグメントに変換 --------------------
def segments_detailed(G, path, tm, start_time_str="10:00"):
    """
    エンジンの出力した path (ノードリスト) を、
    フロントエンドが表示しやすい詳細なセグメント情報に変換する。
    """
    segs = []
    cur = None
    
    # 時刻計算用
    curr_time = time_str_to_min(start_time_str)

    def flush():
        nonlocal cur
        if cur:
            # 分計算 (概算)
            if cur["kind"] == "walk":
                cur["minutes"] = max(1, int(cur.get("meters", 0) / 80.0))
            elif cur["kind"] in ("bus", "rail"):
                # ここで正確な所要時間を計算してもいいが、一旦簡易的にエッジ数などで
                cur["minutes"] = max(1, int(cur.get("edges", 0) * 2.0))
            
            segs.append(cur)
            cur = None

    last_phys = None

    for u, v in zip(path, path[1:]):
        edge = G.edges[u, v]
        etype = edge.get("etype")
        
        if u[0] == "phys": last_phys = u

        # --- 徒歩 ---
        if etype == "walk":
            if not cur or cur["kind"] != "walk":
                flush()
                from_name = G.nodes[u]["name"] if u[0]=="phys" else "???"
                cur = {
                    "kind": "walk", "title": "徒歩", "edges": 0,
                    "from_": from_name, "to": None, "meters": 0
                }
            cur["edges"] += 1
            cur["meters"] += edge.get("meters", 0)
            if v[0] == "phys": cur["to"] = G.nodes[v]["name"]
            continue

        # --- 乗り物 (Board / Ride / Alight / Xfer) ---
        # ライン層ノードを取得
        node = v if v[0] == "line" else (u if u[0] == "line" else None)
        if not node: continue

        line_id = G.nodes[node].get("line")
        line_disp = G.nodes[node].get("disp") or "???"
        mode = G.nodes[node].get("mode") # bus or rail

        if etype == "board":
            flush()
            from_name = G.nodes[last_phys]["name"] if last_phys else "???"
            cur = {
                "kind": mode, "title": line_disp, "line": line_id,
                "edges": 0, "from_": from_name, "to": None, "stops": []
            }
            # 乗車駅を追加
            cur["stops"].append({"name": from_name, "is_origin": True})
        
        elif etype == "ride":
            if cur and cur["kind"] in ("bus", "rail"):
                cur["edges"] += 1
                # 停車駅名
                phys_id = v[1] if v[0]=="line" else u[1] # おおよそ
                # 正確には lineノードに対応する physノードの名前
                p_node = ("phys", phys_id)
                stop_name = G.nodes[p_node]["name"] if p_node in G.nodes else G.nodes[node]["name"]
                
                # 直前の駅と名前が違うなら追加
                if not cur["stops"] or cur["stops"][-1]["name"] != stop_name:
                    cur["stops"].append({"name": stop_name})

        elif etype in ("alight", "xfer"):
            if cur and cur["kind"] in ("bus", "rail"):
                to_phys = v if v[0] == "phys" else last_phys
                if to_phys:
                    to_name = G.nodes[to_phys]["name"]
                    cur["to"] = to_name
                    # 最後の駅
                    if not cur["stops"] or cur["stops"][-1]["name"] != to_name:
                        cur["stops"].append({"name": to_name, "is_destination": True})
                    else:
                        cur["stops"][-1]["is_destination"] = True
                flush()

    if cur: flush()
    return segs

# -------------------- 計算ロジック --------------------
def compute_route_candidates(alat, alon, blat, blon, pref, start_time="10:00"):
    """
    pref: "time" (時間優先) / "cost" (楽さ優先)
    """
    if G is None or TM is None:
        raise HTTPException(500, "Server not ready")

    # A/B地点の特定
    a_phys, ad = nearest_phys(G, alat, alon, station_only=False)
    b_phys, bd = nearest_phys(G, blat, blon, station_only=True)
    if not b_phys or bd > 500:
        b_phys, bd = nearest_phys(G, blat, blon, station_only=False)

    if not a_phys or not b_phys:
        return {"error": "Nearby stations/busstops not found", "candidates": []}

    print(f"[JOB] Search {pref} from {start_time} | {G.nodes[a_phys]['name']} -> {G.nodes[b_phys]['name']}")

    candidates = []

    # === モード分岐 ===
    if pref == "time" or pref == "fast":
        # 1. 時間優先モード (Time Mode)
        # find_fastest_path を呼ぶ (1件のみ返る仕様)
        arr_min, path = find_fastest_path(G, TM, a_phys, b_phys, start_time_str=start_time)
        
        if path:
            segs = segments_detailed(G, path, TM, start_time)
            
            # ライン名リスト
            lines = list(dict.fromkeys([s["title"] for s in segs if s["kind"] in ("bus", "rail")]))
            
            start_min = time_str_to_min(start_time)
            duration = int(arr_min - start_min)
            
            candidates.append({
                "id": "Fastest",
                "lines": lines,
                "total_time": duration,
                "arrival_time": min_to_time_str(arr_min),
                "steps": segs,
                "score_label": f"{duration}分"
            })

    else:
        # 2. コスト優先モード (Cost Mode)
        # ジェネレータを使って有効なルートを5件探す
        # ※ toei_engine.py から import した find_top_k_paths が generator対応版になっていればそれを使う
        #   なっていない場合は server 側でループを書く必要があるが、
        #   ここでは engine 側が generator になっている前提で書く。
        
        # もし engine がリストを返す版なら、ここで generator ロジックを再実装する必要あり
        # 安全のため、server側で generator ロジックを回す形にする
        
        # 内部ジェネレータ定義 (engine の find_paths_generator 相当)
        # engine に find_top_k_paths しかない場合はそれを使うが、
        # ユーザーさんの手元の toei_reach_final_v2.py はリストを返す版のはず。
        # なので、ここではリスト版を使って、その後ろでフィルタする。
        # (ただし K=300 とかにして一括取得する)
        
        raw_candidates = find_top_k_paths(G, a_phys, b_phys, K=100) # 多めに取得
        
        valid_count = 0
        dead_routes = set()

        for cand in raw_candidates:
            path = cand["path"]
            
            # ブラックリストチェック
            is_dead = False
            for u, v in zip(path, path[1:]):
                if G.edges[u, v].get("etype") == "board":
                    rid = G.nodes[v].get("route_id")
                    if rid in dead_routes:
                        is_dead = True; break
            if is_dead: continue

            # 答え合わせ
            real_arr = calculate_real_arrival_time(G, TM, path, start_time)
            
            if real_arr:
                # 合格
                segs = segments_detailed(G, path, TM, start_time)
                lines = list(dict.fromkeys([s["title"] for s in segs if s["kind"] in ("bus", "rail")]))
                
                start_min = time_str_to_min(start_time)
                duration = int(real_arr - start_min)
                
                candidates.append({
                    "id": f"Comfort-{valid_count+1}",
                    "lines": lines,
                    "total_time": duration,
                    "arrival_time": min_to_time_str(real_arr),
                    "steps": segs,
                    "score_label": f"楽さ {cand['cost']:.1f} (所要{duration}分)"
                })
                
                valid_count += 1
                if valid_count >= 5: break
            else:
                # 不合格 -> 学習
                # 簡易的に最後のバス路線を犯人とする
                for u, v in reversed(list(zip(path, path[1:]))):
                    if G.edges[u, v].get("etype") == "board" and G.nodes[v].get("mode") == "bus":
                        bad_route = G.nodes[v].get("route_id")
                        dead_routes.add(bad_route)
                        break

    return {"candidates": candidates}


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