from __future__ import annotations

import asyncio
import os

import httpx
from fastapi import Body, HTTPException, Query
from pydantic import BaseModel


class RouteRequest(BaseModel):
    alat: float
    alon: float
    blat: float
    blon: float
    pref: str = "cost"
    start_time: str = "10:00"
    target_date_str: str | None = None


def register_nagoya_routes(app) -> None:
    @app.post("/route")
    async def route_start(req: RouteRequest):
        if getattr(app.state, "loading_status", "starting") != "ready":
            raise HTTPException(
                503, "Server is warming up (loading Nagoya GTFS data)."
            )
        backend = getattr(app.state, "route_backend", None)
        if backend is None:
            raise HTTPException(500, "Nagoya route backend is not initialized")

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None,
                lambda: backend.search(
                    alat=req.alat,
                    alon=req.alon,
                    blat=req.blat,
                    blon=req.blon,
                    pref=req.pref,
                    start_time=req.start_time,
                    date_str=req.target_date_str,
                ),
            )
        except (ValueError, RuntimeError) as error:
            raise HTTPException(422, detail=str(error)) from error

    @app.get("/healthz")
    async def healthz():
        status = getattr(app.state, "loading_status", "unknown")
        dataset = getattr(app.state, "transit_dataset", None)
        return {
            "ok": status == "ready",
            "status": status,
            "city": "nagoya",
            "feed_id": dataset.metadata.feed_id if dataset is not None else None,
            "feed_version": dataset.metadata.version if dataset is not None else None,
            "realtime": False,
        }

    @app.get("/bus/location")
    async def bus_location_unsupported():
        raise HTTPException(
            503,
            detail={
                "code": "bus_realtime_unsupported",
                "message": "Nagoya backend does not expose an official open realtime feed",
            },
        )

    @app.post("/realtime/update")
    async def realtime_update_unsupported():
        raise HTTPException(
            503,
            detail={
                "code": "bus_realtime_unsupported",
                "message": "Nagoya backend does not expose an official open realtime feed",
            },
        )

    @app.get("/autocomplete")
    async def autocomplete(q: str = Query(...)):
        key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not key:
            return {"predictions": []}
        url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
        params = {
            "key": key,
            "input": q,
            "language": "ja",
            "components": "country:jp",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
        return response.json()

    @app.get("/details")
    async def details(place_id: str = Query(...)):
        key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not key:
            return {"result": {}}
        url = "https://maps.googleapis.com/maps/api/place/details/json"
        params = {
            "key": key,
            "place_id": place_id,
            "language": "ja",
            "fields": "geometry,name,formatted_address",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
        return response.json()

    @app.post("/route/experience")
    async def route_experience_unsupported(stops: list = Body(...)):
        del stops
        raise HTTPException(
            404,
            detail={
                "code": "feature_unsupported",
                "message": "Route experience is not available in Nagoya route-only mode",
            },
        )
