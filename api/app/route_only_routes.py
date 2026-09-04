from __future__ import annotations

from typing import Any

from fastapi import Body, HTTPException

from app.route_endpoint import register_route_endpoint


def register_route_only_core_routes(
    app,
    *,
    city_key: str,
    city_display_name: str,
    realtime_health: bool | dict[str, bool],
    warmup_data_label: str | None = None,
) -> None:
    if not city_key or city_key.strip() != city_key:
        raise ValueError(f"invalid route-only city key: {city_key!r}")
    if not city_display_name:
        raise ValueError("route-only city display name is required")
    data_label = warmup_data_label or f"{city_display_name} GTFS data"
    register_route_endpoint(
        app,
        warmup_message=f"Server is warming up (loading {data_label}).",
    )

    @app.get("/healthz")
    async def healthz():
        status = getattr(app.state, "loading_status", "unknown")
        dataset = getattr(app.state, "transit_dataset", None)
        return {
            "ok": status == "ready",
            "status": status,
            "city": city_key,
            "feed_id": dataset.metadata.feed_id if dataset is not None else None,
            "feed_version": dataset.metadata.version if dataset is not None else None,
            "realtime": realtime_health,
        }

    @app.post("/route/experience")
    async def route_experience_unsupported(stops: list[Any] = Body(...)):
        del stops
        raise HTTPException(
            404,
            detail={
                "code": "feature_unsupported",
                "message": (
                    "Route experience is not available in "
                    f"{city_display_name} route-only mode"
                ),
            },
        )


def register_unsupported_bus_realtime_routes(
    app,
    *,
    message: str,
) -> None:
    if not message:
        raise ValueError("unsupported realtime message is required")

    @app.get("/bus/location")
    async def bus_location_unsupported():
        raise HTTPException(
            503,
            detail={
                "code": "bus_realtime_unsupported",
                "message": message,
            },
        )

    @app.post("/realtime/update")
    async def realtime_update_unsupported():
        raise HTTPException(
            503,
            detail={
                "code": "bus_realtime_unsupported",
                "message": message,
            },
        )
