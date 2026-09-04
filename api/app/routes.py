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
from app.route_endpoint import register_route_endpoint
from route_engine import normalize_route_preference
from tokyo_route_engine import TokyoRouteDependencies, TokyoRouteEngine

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
    get_reachable_stops,
    _rss_mb,
    determine_day_type,
)

ROUTE_JOBS: dict[str, dict] = {}
_ROUTE_LOCK = asyncio.Lock()

# 簡易TTLキャッシュ
_sv_cache: dict[str, tuple[float, bytes]] = {}
SV_CACHE_TTL_SEC = 60 * 60  # 1時間

ODPT_API_URL = "https://api-public.odpt.org/api/v4"
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
    return normalize_route_preference(pref).api_value

def compute_route_candidates(app, alat, alon, blat, blon, pref, start_time="10:00", date_str=None):
    """Compatibility wrapper; new endpoint traffic uses app.state.route_engine."""

    engine = TokyoRouteEngine(
        app,
        dependencies=TokyoRouteDependencies(
            nearest_phys=nearest_phys,
            haversine=haversine,
            get_virtual_connections=get_virtual_connections,
            search_best_routes_once=search_best_routes_once,
            time_str_to_min=time_str_to_min,
            min_to_time_str=min_to_time_str,
            determine_day_type=determine_day_type,
            assign_candidate_step_ids=assign_candidate_step_ids,
            rss_mb=_rss_mb,
        ),
    )
    return engine.search_legacy(
        alat=alat,
        alon=alon,
        blat=blat,
        blon=blon,
        pref=normalize_pref(pref),
        start_time=start_time,
        date_str=date_str,
    )

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
    register_route_endpoint(
        app,
        warmup_message=(
            "Server is warming up (loading data). Please try again in 1-2 minutes."
        ),
        lock=_ROUTE_LOCK,
    )

    @app.get("/bus/location")
    async def bus_location(
        route_id: str = Query(...),
        trip_id: str = Query(...),
        vehicle_id: str = Query(None, description="Optional physical bus ID to track specific vehicle"),
        force_refresh: bool = Query(
            False,
            description="Bypass the local GTFS-RT snapshot cache",
        ),
        debug: bool = Query(
            False,
            description="Include the static GTFS stop timetable for diagnostics",
        ),
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
            "force_refresh": force_refresh,
            "debug": debug,
        }

        tm = app.state.TM
        provider = getattr(app.state, "realtime_provider", None)
        if provider is None:
            _busloc_log({**base, "ok": False, "reason": "REALTIME_PROVIDER_UNAVAILABLE"})
            raise HTTPException(
                503,
                detail={
                    "code": "bus_realtime_unavailable",
                    "message": "Realtime bus positions are not available",
                    "diagnostic": "Tokyo RealtimeProvider is not initialized",
                },
            )
        try:
            candidates_all = list(
                await provider.vehicle_positions(force_refresh=force_refresh)
            )
        except RuntimeError as error:
            _busloc_log({
                **base,
                "ok": False,
                "reason": "REALTIME_UNAVAILABLE",
                "diagnostic": str(error),
            })
            raise HTTPException(
                503,
                detail={
                    "code": "bus_realtime_unavailable",
                    "message": "Realtime bus positions are not available",
                    "diagnostic": str(error),
                },
            ) from error
        if not candidates_all:
            _busloc_log({**base, "ok": False, "reason": "REALTIME_UNAVAILABLE"})
            raise HTTPException(
                503,
                detail={
                    "code": "bus_realtime_unavailable",
                    "message": "Realtime bus positions are not available",
                },
            )

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
            "server_now": now,
            "realtime_fetched_ts": getattr(
                tm, "latest_bus_positions_fetched_at", None
            ),
            "feed_ts": target_bus.get("feed_timestamp"),
            "vehicle_ts": target_bus.get("vehicle_timestamp"),
            "raw_stop_id": target_bus.get("raw_stop_id"),
            "raw_stop_name": target_bus.get("raw_stop_name"),
            
            # Pass through informative fields
            "next_stop": target_bus.get("next_stop"),
            "destination": target_bus.get("destination"),
            "trip_id": target_bus.get("trip_id"),
            "trip_stop_ids": target_bus.get("trip_stop_ids", []),
            "before_first_stop": target_bus.get("before_first_stop"),
            "from_stop_sequence": target_bus.get("from_stop_sequence"),
            "observed_stop_sequence": target_bus.get("observed_stop_sequence"),
            "current_status": target_bus.get("current_status"),
        }

        response_epoch = time.time()

        def age_seconds(timestamp):
            if not isinstance(timestamp, (int, float)) or timestamp <= 0:
                return None
            return round(max(0.0, response_epoch - timestamp), 1)

        response["snapshot_age_seconds"] = age_seconds(
            response["realtime_fetched_ts"]
        )
        response["feed_age_seconds"] = age_seconds(response["feed_ts"])
        response["vehicle_age_seconds"] = age_seconds(response["vehicle_ts"])

        if debug:
            from gtfs_loader import gtfs_repo

            response["trip_stop_schedule"] = (
                gtfs_repo.get_trip_stop_schedule(trip_id)
            )
        
        _busloc_log({
            **base,
            "ok": True,
            "bus_id": target_bus.get("vehicle_id"),
            "raw_stop_id": response["raw_stop_id"],
            "raw_stop_name": response["raw_stop_name"],
            "from_stop_id": response["odpt:fromBusstopPole"],
            "observed_stop_sequence": response["observed_stop_sequence"],
            "current_status": response["current_status"],
            "snapshot_age_seconds": response["snapshot_age_seconds"],
            "feed_age_seconds": response["feed_age_seconds"],
            "vehicle_age_seconds": response["vehicle_age_seconds"],
        })
        return response

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
        from app.services.google_places import autocomplete_legacy_response

        return await autocomplete_legacy_response(q)

    @app.get("/details")
    async def details(place_id: str = Query(...)):
        from app.services.google_places import details_legacy_response

        return await details_legacy_response(place_id)

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
