from __future__ import annotations

import asyncio

from fastapi import HTTPException
from pydantic import BaseModel

from app.gtfs_bus_realtime_routes import register_gtfs_bus_vehicle_location_route
from app.route_only_places import register_route_only_places_routes
from yokohama_transit import YOKOHAMA_BUS_FEED_ID


class RouteRequest(BaseModel):
    alat: float
    alon: float
    blat: float
    blon: float
    pref: str = "cost"
    start_time: str = "10:00"
    target_date_str: str | None = None


def register_yokohama_routes(app) -> None:
    @app.post("/route")
    async def route_start(req: RouteRequest):
        if getattr(app.state, "loading_status", "starting") != "ready":
            raise HTTPException(
                503, "Server is warming up (loading Yokohama bus GTFS data)."
            )
        backend = getattr(app.state, "route_backend", None)
        if backend is None:
            raise HTTPException(500, "Yokohama route backend is not initialized")

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
            "city": "yokohama",
            "feed_id": dataset.metadata.feed_id if dataset is not None else None,
            "feed_version": dataset.metadata.version if dataset is not None else None,
            "realtime": {
                "vehicle_positions": True,
                "trip_updates": False,
                "alerts": False,
            },
        }

    register_gtfs_bus_vehicle_location_route(
        app,
        feed_id=YOKOHAMA_BUS_FEED_ID,
    )
    register_route_only_places_routes(app)
