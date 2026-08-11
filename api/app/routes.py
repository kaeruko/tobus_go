import os
import httpx
import uuid
import asyncio
import datetime
from app.services.bus_stop_experience import build_route_experiences
from app.services.bus_location_matcher import (
    BusLocationMatchError,
    select_bus_candidate,
)
from app.services.route_step_ids import assign_candidate_step_ids

from fastapi import HTTPException, Form, Query, Body, BackgroundTasks
from fastapi.responses import Response
import time
from typing import Optional
import json
import logging

logger = logging.getLogger(__name__)

def _busloc_log(ev: dict) -> None:
    print(json.dumps(ev, ensure_ascii=False), flush=True)

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
    determine_day_type,
)

ROUTE_JOBS: dict[str, dict] = {}
_ROUTE_LOCK = asyncio.Lock()

# 簡易TTLキャッシュ
_sv_cache: dict[str, tuple[float, bytes]] = {}
SV_CACHE_TTL_SEC = 60 * 60  # 1時間

ODPT_API_URL = "https://api.odpt.org/api/v4"
ODPT_API_KEY = os.getenv("ODPT_API_KEY")

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





def normalize_pref(pref: str | None) -> str:
    if not pref:
        return "cost"
    if pref in ("shortTime", "fast"):
        return "time"
    if pref in ("time", "cost", "fewTransfers"):
        return pref
    return "cost"

def compute_route_candidates(app, alat, alon, blat, blon, pref, start_time="10:00", date_str=None):
    # メモリ使用量と呼び出しパラメータのログ出力
    print(f"[MEM] enter compute_route_candidates rss={_rss_mb():.1f}MB")
    print(f"[USER_DEBUG] compute_route_candidates: start_time={start_time}, date_str={date_str}")
    
    # ユーザー設定の正規化、アプリケーション状態からのインスタンス取得
    pref = normalize_pref(pref)
    g = app.state.G
    tm = app.state.TM
    walk_rad = app.state.WALK_RAD
    si = app.state.SI
    
    # 出発地(A)と目的地(B)の最寄り物理ノード(バス停/駅)を探索
    # Aは駅以外も含む(station_only=False)、Bはまず駅中心に探す
    a_phys, a_dist = nearest_phys(g, alat, alon, station_only=False, spatial_index=si)
    b_phys, bd = nearest_phys(g, blat, blon, station_only=True, spatial_index=si)
    
    # Bが近くに見つからない場合や遠い場合は、バス停も含めて再探索
    if not b_phys or bd > 500:
        b_phys, _ = nearest_phys(g, blat, blon, station_only=False, spatial_index=si)

    # どちらか一方でもノードが見つからなければエラーを返す
    if not a_phys or not b_phys:
        return {"error": "Nearby stations or busstops not found", "candidates": []}

    # 出発地の最寄りノードまでの徒歩時間を概算(80m/min)
    import math
    initial_walk_min = 0
    if a_dist and a_dist > 0:
        initial_walk_min = max(1, math.ceil(a_dist / 80.0))
    
    # 徒歩時間を考慮した実質的な出発時刻(active_start_time)を計算
    active_start_time = start_time
    if initial_walk_min > 0:
        s_min = time_str_to_min(start_time)
        active_start_time = min_to_time_str(s_min + initial_walk_min)

    # 地点Bの正確な位置を「目的地」として設定し、仮想エッジ(virtual_connections)を取得
    destination_label = "目的地"
    dest_node, virtual_connections = get_virtual_connections(
        g, blat, blon, name=destination_label, walk_radius=walk_rad, spatial_index=si
    )
    destination_reachable = len(virtual_connections) > 0
    day_type = determine_day_type(date_str)

    results = []
    # 仮想目的地への到達が可能なら、目的地座標へのルート探索を実行
    if destination_reachable:
        results = search_best_routes_once(
            g, 
            tm,
            a_phys,
            mode=pref,
            start_time=active_start_time, 
            target_date_str=date_str,
            limit=5,
            target_node=dest_node,
            day_type=day_type,
            virtual_dest_connections=virtual_connections,
            target_coords=[blat, blon],
        )

    # 仮想目的地へのルートが見つからなかった場合、最寄り物理ノード(b_phys)までの探索へフォールバック
    if not results:
        results = search_best_routes_once(
            g,
            tm,
            a_phys,
            mode=pref,
            start_time=active_start_time, 
            target_date_str=date_str,
            limit=5,
            target_node=b_phys,
            day_type=day_type,
            virtual_dest_connections=None,
            target_coords=None,
        )

    # 探索結果の後処理: 最初の徒歩区間の追加や座標情報の付与
    for cand in results:
        if initial_walk_min > 0:
            a_node_name = g.nodes[a_phys]["name"]
            
            # 既存の最初のステップが徒歩なら統合、そうでなければ新規徒歩ステップ挿入
            if cand["steps"] and cand["steps"][0]["kind"] == "walk":
                first = cand["steps"][0]
                first["from_"] = "現在地" 
                first["minutes"] += int(initial_walk_min)
                first["meters"] += int(a_dist)
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
        
        # 不要な内部パスデータの削除
        if "path" in cand: del cand["path"]
        assign_candidate_step_ids(cand)

    # メタデータの作成: フォールバック情報など
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

async def _fetch_and_update_realtime(app_state):
    tm = app_state.TM
    if not tm: return

    params = {
        "acl:consumerKey": ODPT_API_KEY,
        "odpt:operator": "odpt.Operator:Toei"
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Bus Realtime
        try:
            r_bus = await client.get(f"{ODPT_API_URL}/odpt:Bus", params=params)
            if r_bus.status_code == 200:
                tm.update_bus_realtime(r_bus.json())
                print(f"[INFO] Updated Bus realtime data. {len(tm.bus_realtime_delays)} routes delayed.")
        except Exception as e:
            print(f"[WARN] Failed to update bus realtime: {e}")

        # 2. Train Info Text
        try:
            r_train = await client.get(f"{ODPT_API_URL}/odpt:TrainInformation", params=params)
            if r_train.status_code == 200:
                tm.update_train_info_text(r_train.json())
                print(f"[INFO] Updated Train info text. Suspended: {tm.train_service_suspended}")
        except Exception as e:
            print(f"[WARN] Failed to update train info: {e}")

def register_routes(app):
    from pydantic import BaseModel

    @app.get("/bus/location")
    async def bus_location(
        route_id: str = Query(...),
        trip_id: str = Query(...),
        vehicle_id: str = Query(None, description="Optional physical bus ID to track specific vehicle")
    ):
        import uuid
        from datetime import datetime, timezone
        
        req_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        base = {
            "kind": "bus_location",
            "req_id": req_id,
            "now": now,
            "route_id": route_id,
            "trip_id": trip_id,
            "vehicle_id": vehicle_id,
        }

        tm = app.state.TM
        if not tm or not tm.latest_bus_positions:
            _busloc_log({**base, "ok": False, "reason": "REALTIME_UNAVAILABLE"})
            raise HTTPException(
                503,
                detail={
                    "code": "bus_realtime_unavailable",
                    "message": "Realtime bus positions are not available",
                },
            )

        candidates_all = tm.latest_bus_positions
        base["candidates_total"] = len(candidates_all)

        candidates_route = [
            bus for bus in candidates_all
            if bus.get("odpt:busroute") == route_id
        ]
        base["route_match_count"] = len(candidates_route)
        base["trip_match_count"] = len([
            bus for bus in candidates_route if bus.get("trip_id") == trip_id
        ])
        try:
            target_bus = select_bus_candidate(
                candidates_all,
                route_id=route_id,
                trip_id=trip_id,
                vehicle_id=vehicle_id,
            )
        except BusLocationMatchError as exc:
            _busloc_log({**base, "ok": False, "reason": exc.code})
            raise HTTPException(
                exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

        response = {
            "odpt:bus": target_bus.get("vehicle_id"),
            "vehicle_id": target_bus.get("vehicle_id"),
            "odpt:fromBusstopPole": target_bus.get("odpt:fromBusstopPole"),
            # Use raw lat/lon from V2 engine
            "vehicle_lat": target_bus.get("lat"),
            "vehicle_lon": target_bus.get("lon"),
            "vehicle_ts": None, # timestamp could be added if needed
            
            # Pass through informative fields
            "next_stop": target_bus.get("next_stop"),
            "destination": target_bus.get("destination"),
            "trip_id": target_bus.get("trip_id"),
        }
        
        _busloc_log({**base, "ok": True, "bus_id": target_bus.get("vehicle_id")})
        return response

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

        loop = asyncio.get_running_loop()
        async with _ROUTE_LOCK:
             print(f"[USER_DEBUG] /route locked, start rss={_rss_mb():.1f}MB")
             result = await loop.run_in_executor(
                None,
                compute_route_candidates,
                app,
                req.alat, req.alon, req.blat, req.blon, normalize_pref(req.pref), req.start_time, req.target_date_str,
             )
             import json
             result_bytes = len(json.dumps(result))
             cand_count = len(result.get("candidates", []))
             print(f"[USER_DEBUG] /route unlocked, end rss={_rss_mb():.1f}MB, response_size={result_bytes} bytes, candidates={cand_count}")
             return result

    @app.post("/realtime/update")
    async def update_realtime_data(background_tasks: BackgroundTasks):
        if not ODPT_API_KEY:
            raise HTTPException(500, "ODPT_API_KEY not configured")
        
        # Trigger update in background to return quickly
        background_tasks.add_task(_fetch_and_update_realtime, app.state)
        return {"status": "accepted"}

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

        G = app.state.G
        tm = app.state.TM
        
        if G is None or tm is None:
            raise HTTPException(status_code=503, detail="Server not initialized")

        result = get_reachable_stops(G, tm, lat, lon)
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

        cache_key = f"{lat:.6f},{lon:.6f}|{w}x{h}|r{radius}|f{fov}|hd{heading}|p{pitch}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return Response(content=cached, media_type="image/jpeg")

        async with httpx.AsyncClient(timeout=8.0) as client:
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
                raise HTTPException(404, f"StreetView not found status={status}")

            pano_id = meta_json.get("pano_id")
            if not pano_id:
                raise HTTPException(404, "StreetView pano_id not found")

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
            _cache_set(cache_key, content)
            return Response(content=content, media_type="image/jpeg")
