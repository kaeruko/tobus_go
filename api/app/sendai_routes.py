from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import Body, HTTPException, Query
from pydantic import BaseModel

from app.gtfs_bus_realtime_routes import register_gtfs_bus_vehicle_location_route
from app.route_only_places import register_route_only_places_routes
from sendai_transit import SENDAI_FEED_ID


class RouteRequest(BaseModel):
    alat: float
    alon: float
    blat: float
    blon: float
    pref: str = "cost"
    start_time: str = "10:00"
    target_date_str: str | None = None


def _source_id(value: str, *, field: str) -> str:
    prefix = f"{SENDAI_FEED_ID}:"
    if not value.startswith(prefix):
        raise HTTPException(
            422,
            detail={
                "code": "invalid_sendai_id",
                "message": f"{field} must start with {prefix!r}",
            },
        )
    source = value[len(prefix) :]
    if source == "":
        raise HTTPException(
            422,
            detail={
                "code": "invalid_sendai_id",
                "message": f"{field} has an empty source id",
            },
        )
    return source


def _provider(app):
    provider = getattr(app.state, "realtime_provider", None)
    if provider is None:
        raise HTTPException(
            503,
            detail={
                "code": "realtime_provider_unavailable",
                "message": "Sendai realtime provider is not initialized",
            },
        )
    return provider


def _raise_realtime_failure(error: Exception) -> None:
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        message = f"GTFS-Realtime upstream HTTP {status}"
    else:
        message = str(error) or error.__class__.__name__
    raise HTTPException(
        503,
        detail={
            "code": "realtime_fetch_failed",
            "message": message,
        },
    ) from error


def register_sendai_routes(app) -> None:
    @app.post("/route")
    async def route_start(req: RouteRequest):
        if getattr(app.state, "loading_status", "starting") != "ready":
            raise HTTPException(
                503, "Server is warming up (loading Sendai GTFS data)."
            )
        backend = getattr(app.state, "route_backend", None)
        if backend is None:
            raise HTTPException(500, "Sendai route backend is not initialized")
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
            "city": "sendai",
            "feed_id": dataset.metadata.feed_id if dataset is not None else None,
            "feed_version": dataset.metadata.version if dataset is not None else None,
            "realtime": {
                "vehicle_positions": True,
                "trip_updates": True,
                "alerts": True,
            },
        }

    register_gtfs_bus_vehicle_location_route(
        app,
        feed_id=SENDAI_FEED_ID,
    )

    @app.get("/realtime/trip-updates")
    async def trip_updates(
        trip_id: str | None = Query(None),
        route_id: str | None = Query(None),
    ):
        raw_trip_id = _source_id(trip_id, field="trip_id") if trip_id else None
        raw_route_id = _source_id(route_id, field="route_id") if route_id else None
        try:
            rows = await _provider(app).trip_updates()
        except (httpx.HTTPError, RuntimeError) as error:
            _raise_realtime_failure(error)
        filtered = [
            row
            for row in rows
            if (raw_trip_id is None or row.get("trip_id") == raw_trip_id)
            and (raw_route_id is None or row.get("route_id") == raw_route_id)
        ]
        return {"updates": filtered}

    @app.get("/realtime/alerts")
    async def alerts():
        try:
            rows = await _provider(app).alerts()
        except (httpx.HTTPError, RuntimeError) as error:
            _raise_realtime_failure(error)
        return {"alerts": list(rows)}

    @app.post("/realtime/update")
    async def realtime_update():
        provider = _provider(app)
        try:
            vehicle_positions, trip_updates_rows, alert_rows = await asyncio.gather(
                provider.vehicle_positions(),
                provider.trip_updates(),
                provider.alerts(),
            )
        except (httpx.HTTPError, RuntimeError) as error:
            _raise_realtime_failure(error)
        return {
            "ok": True,
            "vehicle_positions": len(vehicle_positions),
            "trip_updates": len(trip_updates_rows),
            "alerts": len(alert_rows),
        }

    register_route_only_places_routes(app)

    @app.post("/route/experience")
    async def route_experience_unsupported(stops: list[Any] = Body(...)):
        del stops
        raise HTTPException(
            404,
            detail={
                "code": "feature_unsupported",
                "message": "Route experience is not available in Sendai route-only mode",
            },
        )
