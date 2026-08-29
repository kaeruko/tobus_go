from __future__ import annotations

from fastapi import HTTPException


def register_yokohama_routes(app) -> None:
    @app.get("/healthz")
    async def healthz():
        return {
            "ok": False,
            "status": getattr(app.state, "loading_status", "not_configured"),
            "city": "yokohama",
            "feeds": [],
            "realtime": False,
        }

    @app.post("/route")
    async def route_unconfigured():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "yokohama_transit_not_configured",
                "message": "Yokohama transit data is not configured.",
            },
        )
