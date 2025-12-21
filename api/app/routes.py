import os
import httpx
import uuid
import asyncio
import datetime
from app.services.bus_stop_experience import build_route_experiences

from fastapi import HTTPException, Form, Query, Body

from toei_engine import (
    nearest_phys,
    haversine,
    get_virtual_connections,
    search_best_routes_once,
    time_str_to_min,
    min_to_time_str,
    MAX_WALK_SEG_M,
    get_reachable_stops,
)

ROUTE_JOBS: dict[str, dict] = {}

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

def compute_route_candidates(app, alat, alon, blat, blon, pref, start_time="10:00", date_str=None):
    print(f"[USER_DEBUG] compute_route_candidates: start_time={start_time}, date_str={date_str}")
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

    day_type = determine_day_type(date_str)

    results = []
    if destination_reachable:
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

    if not results:
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
            start_node_name = g.nodes[a_phys]["name"]
            walk_step = {
                "kind": "walk",
                "title": "徒歩",
                "edges": 0,
                # "出発地" だと漠然としているので "現在地" に統一すると分かりやすいかも
                "from_": "現在地", 
                "to": start_node_name,
                "meters": int(a_dist),
                "minutes": int(initial_walk_min)
            }
            cand["steps"].insert(0, walk_step)
            cand["walk_m"] += a_dist
            cand["total_time"] += initial_walk_min
            cand["points"].insert(0, [alat, alon])
        
        cand["origin_coords"] = [alat, alon]
        cand["destination_coords"] = [blat, blon]

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

        job_id = uuid.uuid4().hex
        ROUTE_JOBS[job_id] = {"status": "pending"}
        asyncio.create_task(_run_route_job(app, job_id, req.alat, req.alon, req.blat, req.blon, req.pref, req.start_time, req.target_date_str))
        return {"job_id": job_id}

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