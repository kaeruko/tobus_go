import os
import httpx
import uuid
import asyncio
import datetime
from app.services.bus_stop_experience import build_route_experiences

from fastapi import HTTPException, Form, Query, Body
from fastapi.responses import Response
import time
from typing import Optional

from toei_engine import (
    nearest_phys,
    haversine,
    get_virtual_connections,
    search_best_routes_once,
    time_str_to_min,
    min_to_time_str,
    MAX_WALK_SEG_M,
    get_reachable_stops,
    _rss_mb,
)

ROUTE_JOBS: dict[str, dict] = {}
_ROUTE_LOCK = asyncio.Lock()

# 簡易TTLキャッシュ
# key は パラメータを詰めた文字列
# value は expires_at と bytes
_sv_cache: dict[str, tuple[float, bytes]] = {}
SV_CACHE_TTL_SEC = 60 * 60  # 1時間

def _cache_get(key: str) -> Optional[bytes]:
    hit = _sv_cache.get(key)
    if not hit:
        return None
    expires_at, data = hit
    if time.time() >= expires_at:
        _sv_cache.pop(key, None)
        return None
    return data

def _cache_set(key: str, data: bytes) -> None:
    _sv_cache[key] = (time.time() + SV_CACHE_TTL_SEC, data)


def determine_day_type(date_str: str | None) -> str:
    if not date_str:
        target_date = datetime.date.today()
    else:
        try:
            target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = datetime.date.today()

    weekday = target_date.weekday()

    try:
        import japanese_holidays
        is_holiday = japanese_holidays.is_holiday(target_date)
    except ImportError:
        is_holiday = False

    if weekday == 6 or is_holiday:
        return "holiday"
    if weekday == 5:
        return "saturday"
    return "weekday"


def normalize_pref(pref: str | None) -> str:
    """Map UI preference values to engine modes.

    - "shortTime" is a frontend label for fastest search and should use the engine's
      "time" mode (equivalent to "fast").
    - Unknown or missing values fall back to "cost" so the search engine always
      receives a supported mode.
    """

    if not pref:
        return "cost"
    if pref in ("shortTime", "fast"):
        return "time"

    # Only allow recognized modes to reach the engine
    if pref in ("time", "cost", "fewTransfers"):
        return pref

    return "cost"

def compute_route_candidates(app, alat, alon, blat, blon, pref, start_time="10:00", date_str=None):
    print(f"[MEM] enter compute_route_candidates rss={_rss_mb():.1f}MB")
    print(f"[USER_DEBUG] compute_route_candidates: start_time={start_time}, date_str={date_str}")
    pref = normalize_pref(pref)
    g = app.state.G
    tm = app.state.TM
    walk_rad = app.state.WALK_RAD

    si = app.state.SI
    
    # nearest_phys returns (node_id, distance_in_meters)
    a_phys, a_dist = nearest_phys(g, alat, alon, station_only=False, spatial_index=si)
    b_phys, bd = nearest_phys(g, blat, blon, station_only=True, spatial_index=si)
    if not b_phys or bd > 500:
        b_phys, _ = nearest_phys(g, blat, blon, station_only=False, spatial_index=si)

    if not a_phys or not b_phys:
        return {"error": "Nearby stations or busstops not found", "candidates": []}

    # ★追加: 最寄りバス停までの徒歩時間を計算
    import math
    initial_walk_min = 0
    if a_dist and a_dist > 0:
        initial_walk_min = max(1, math.ceil(a_dist / 80.0))
    
    # ★追加: 検索開始時刻を徒歩分だけ遅らせる
    active_start_time = start_time
    if initial_walk_min > 0:
        s_min = time_str_to_min(start_time)
        active_start_time = min_to_time_str(s_min + initial_walk_min)

    destination_label = "目的地"
    dest_node, virtual_connections = get_virtual_connections(
        g, blat, blon, name=destination_label, walk_radius=walk_rad, spatial_index=si
    )
    destination_reachable = len(virtual_connections) > 0

    print(f"[USER_DEBUG] virtual_connections count: {len(virtual_connections)}")
    
    day_type = determine_day_type(date_str)

    results = []
    if destination_reachable:
        print(f"[USER_DEBUG] Attempting first search with virtual destination: {dest_node}")
        results = search_best_routes_once(
            g, # Use original graph! No copy!
            tm,
            a_phys,
            b_phys,
            mode=pref,
            start_time=active_start_time, # ★変更
            target_date_str=date_str,
            limit=5,
            target_node=dest_node,
            day_type=day_type,
            virtual_dest_connections=virtual_connections,
            target_coords=[blat, blon],
        )
        print(f"[USER_DEBUG] First search results count: {len(results)}")

    if not results:
        print("[USER_DEBUG] First search failed or destination unreachable. Falling back to physical node search.")
        results = search_best_routes_once(
            g,
            tm,
            a_phys,
            b_phys,
            mode=pref,
            start_time=active_start_time, # ★変更
            target_date_str=date_str,
            limit=5,
            target_node=b_phys,
            day_type=day_type,
            virtual_dest_connections=None,
            target_coords=None,
        )

    for cand in results:
        # ★追加: 徒歩ステップを先頭に挿入
        if initial_walk_min > 0:
            a_node_name = g.nodes[a_phys]["name"]
            
            # 先頭が徒歩ならマージする
            if cand["steps"] and cand["steps"][0]["kind"] == "walk":
                first = cand["steps"][0]
                first["from_"] = "現在地" # タイトル上書き
                # to はそのまま (例: 押上)
                first["minutes"] += int(initial_walk_min)
                first["meters"] += int(a_dist)
                # edges (曲がり角など) は加算しないか、適当に+1するか。ここではGPS徒歩を1エッジとみなして+1
                first["edges"] = first.get("edges", 0) + 1
                
                cand["points"].insert(0, [alat, alon])
                cand["total_time"] += initial_walk_min
                cand["walk_m"] += a_dist
            else:
                walk_step = {
                    "kind": "walk",
                    "title": "徒歩",
                    "edges": 0,
                    "from_": "現在地", 
                    "to": a_node_name,
                    "meters": int(a_dist),
                    "minutes": int(initial_walk_min)
                }
                cand["steps"].insert(0, walk_step)
                cand["points"].insert(0, [alat, alon])
                cand["total_time"] += initial_walk_min
                cand["walk_m"] += a_dist
        
        cand["origin_coords"] = [alat, alon]
        cand["destination_coords"] = [blat, blon]
        
        # Cleanup large path data from response
        if "path" in cand:
            del cand["path"]

    fallback_distance_m = None
    fallback_node_name = None
    if b_phys in g:
        fallback_node_name = g.nodes[b_phys].get("name")
        b_lat = g.nodes[b_phys].get("lat")
        b_lon = g.nodes[b_phys].get("lon")
        if b_lat is not None and b_lon is not None:
            fallback_distance_m = haversine(blat, blon, b_lat, b_lon)

    meta = {
        "destination_reachable": destination_reachable,
        "destination_label": destination_label,
        "fallback_node_name": fallback_node_name,
        "fallback_distance_m": fallback_distance_m,
        "walk_limit_m": MAX_WALK_SEG_M,
    }

    import gc
    gc.collect()
    print(f"[MEM] leave compute_route_candidates rss={_rss_mb():.1f}MB")
    return {"candidates": results, "meta": meta}

async def _run_route_job(app, job_id, alat, alon, blat, blon, pref, start_time, date_str):
    loop = asyncio.get_running_loop()
    ROUTE_JOBS[job_id]["status"] = "running"
    try:
        result = await loop.run_in_executor(
            None,
            compute_route_candidates,
            app,
            alat, alon, blat, blon, pref, start_time, date_str,
        )
        ROUTE_JOBS[job_id]["status"] = "done"
        ROUTE_JOBS[job_id]["result"] = result
    except Exception as e:
        ROUTE_JOBS[job_id]["status"] = "error"
        ROUTE_JOBS[job_id]["error"] = str(e)

def register_routes(app):
    from pydantic import BaseModel

    class RouteRequest(BaseModel):
        alat: float
        alon: float
        blat: float
        blon: float
        pref: str = "cost"
        start_time: str = "10:00"
        target_date_str: str | None = None

    @app.post("/route")
    async def route_start(req: RouteRequest):
        print(f"[USER_DEBUG] /route called. StartTime={req.start_time}, Date={req.target_date_str}")
        if getattr(app.state, "loading_status", "starting") != "ready":
             raise HTTPException(503, "Server is warming up (loading data). Please try again in 1-2 minutes.")

        # Lambda対策: Jobポーリング方式をやめて同期的に結果を返す
        loop = asyncio.get_running_loop()
        
        # Prevent parallel execution of heavy search
        async with _ROUTE_LOCK:
             print(f"[USER_DEBUG] /route locked, start rss={_rss_mb():.1f}MB")
             result = await loop.run_in_executor(
                None,
                compute_route_candidates,
                app,
                req.alat, req.alon, req.blat, req.blon, normalize_pref(req.pref), req.start_time, req.target_date_str,
             )
             print(f"[USER_DEBUG] /route unlocked, end rss={_rss_mb():.1f}MB")
             return result

    # @app.get("/route") <- ポーリングエンドポイントは実質無効化（残しておいても良いが使わない）
    @app.get("/route")
    async def route_poll(job_id: str = Query(...)):
        job = ROUTE_JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return job

    @app.get("/autocomplete")
    async def autocomplete(q: str = Query(...)):
        key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not key:
            return {"predictions": []}

        url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
        params = {"key": key, "input": q, "language": "ja", "components": "country:jp"}
        async with httpx.AsyncClient(timeout=10.0) as cl:
            r = await cl.get(url, params=params)
        return r.json()

    @app.get("/details")
    async def details(place_id: str = Query(...)):
        key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not key:
            return {"result": {}}

        url = "https://maps.googleapis.com/maps/api/place/details/json"
        params = {"key": key, "place_id": place_id, "language": "ja", "fields": "geometry,name,formatted_address"}
        async with httpx.AsyncClient(timeout=10.0) as cl:
            r = await cl.get(url, params=params)
        return r.json()

    @app.get("/healthz")
    async def healthz():
        status = getattr(app.state, "loading_status", "unknown")
        return {"ok": True, "status": status}

    @app.post("/route/experience")
    async def route_experience(
        stops: list = Body(...),
    ):
        return {"groups": build_route_experiences(stops)}

    @app.get("/bus/next")
    async def bus_next(
        pole_id: str = Query(...),
        route_id: str = Query(...),
        time: str = Query(None),
        date: str = Query(None),
        target_pole_id: str = Query(None),
        limit: int = Query(5),
        debug: bool = Query(True),
    ):
        if getattr(app.state, "loading_status", "starting") != "ready":
             raise HTTPException(503, "Server is warming up (loading data).")

        g = app.state.G
        tm = app.state.TM
        if g is None or tm is None:
            raise HTTPException(500, "Server not ready")

        day_type = determine_day_type(date)

        if not time:
            now = datetime.datetime.now()
            time = f"{now.hour:02d}:{now.minute:02d}"

        curr_min = time_str_to_min(time)

        pole_name = None
        if ("phys", pole_id) in g:
            pole_name = g.nodes[("phys", pole_id)].get("name")

        trips = tm.get_future_bus_trips(
            pole_id,
            route_id,
            curr_min,
            limit=max(1, limit) * 20,
            pole_name=pole_name,
            day_type=day_type,
            target_pole_id=target_pole_id,
            debug=debug,
        )

        groups = {}
        for t in trips:
            dest = t.get("dest") or "unknown"
            groups.setdefault(dest, []).append(min_to_time_str(t["dep"]))

        destinations = []
        for dest_id, times in groups.items():
            dest_name = None
            if dest_id != "unknown" and ("phys", dest_id) in g:
                dest_name = g.nodes[("phys", dest_id)].get("name")
            destinations.append(
                {
                    "destination_pole_id": None if dest_id == "unknown" else dest_id,
                    "destination_name": dest_name,
                    "times": times[: max(1, limit)],
                }
            )

        return {
            "pole_id": pole_id,
            "pole_name": pole_name,
            "route_id": route_id,
            "day_type": day_type,
            "time": time,
            "target_pole_id": target_pole_id,
            "destinations": destinations,
        }

    @app.get("/explore/reachable")
    async def find_reachable_places(
        lat: float = Query(..., description="現在地の緯度"),
        lon: float = Query(..., description="現在地の経度")
    ):
        if getattr(app.state, "loading_status", "starting") != "ready":
             raise HTTPException(503, "Server is warming up (loading data).")

        # 修正箇所: serverからインポートせず、app.stateから取得する
        G = app.state.G
        tm = app.state.TM
        
        if G is None or tm is None:
            raise HTTPException(status_code=503, detail="Server not initialized")

        # toei_engine からインポートした関数を使用
        result = get_reachable_stops(G, tm, lat, lon)
        
        # if not result["found"]:
        #     # 404を返すとクライアントがException扱いしてしまうため、
        #     # 200 OK で found:False を返すように変更
        #     pass
            
        return result

    @app.get("/streetview/thumb")
    async def streetview_thumb(
        lat: float = Query(...),
        lon: float = Query(...),
        w: int = Query(120, ge=32, le=640),
        h: int = Query(120, ge=32, le=640),
        radius: int = Query(80, ge=1, le=5000),
        fov: int = Query(90, ge=10, le=120),
        heading: int = Query(0, ge=0, le=360),
        pitch: int = Query(0, ge=-90, le=90),
    ):
        google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
        if not google_maps_api_key:
            raise HTTPException(500, "GOOGLE_MAPS_API_KEY is missing")

        # キャッシュキー
        cache_key = f"{lat:.6f},{lon:.6f}|{w}x{h}|r{radius}|f{fov}|hd{heading}|p{pitch}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return Response(content=cached, media_type="image/jpeg")

        async with httpx.AsyncClient(timeout=8.0) as client:
            # 1 metadata で近くにストビューがあるか確認して pano を取る
            meta_url = "https://maps.googleapis.com/maps/api/streetview/metadata"
            meta_params = {
                "location": f"{lat},{lon}",
                "radius": str(radius),
                "key": google_maps_api_key,
            }
            meta = await client.get(meta_url, params=meta_params)
            if meta.status_code != 200:
                raise HTTPException(502, f"StreetView metadata upstream error {meta.status_code}")

            meta_json = meta.json()
            status = meta_json.get("status")
            if status != "OK":
                # 画像が無い場所
                # Flutter 側で errorBuilder を効かせたいので 404 で返す
                raise HTTPException(404, f"StreetView not found status={status}")

            pano_id = meta_json.get("pano_id")
            if not pano_id:
                raise HTTPException(404, "StreetView pano_id not found")

            # 2 pano 指定で画像を取得
            img_url = "https://maps.googleapis.com/maps/api/streetview"
            img_params = {
                "size": f"{w}x{h}",
                "pano": pano_id,
                "fov": str(fov),
                "heading": str(heading),
                "pitch": str(pitch),
                "key": google_maps_api_key,
            }
            img = await client.get(img_url, params=img_params)
            if img.status_code != 200:
                raise HTTPException(502, f"StreetView image upstream error {img.status_code}")

            content = img.content
            # Google 側の content type は jpeg 想定
            _cache_set(cache_key, content)
            return Response(content=content, media_type="image/jpeg")