from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel

from route_engine import (
    GeoPoint,
    RouteContractError,
    RouteEngineUnavailableError,
    RouteInputError,
    RouteSearchLimitError,
    RouteSearchRequest,
    UnsupportedPreferenceError,
    normalize_route_preference,
    serialize_route_result,
)


_JST = ZoneInfo("Asia/Tokyo")


class ApiRouteRequest(BaseModel):
    alat: float
    alon: float
    blat: float
    blon: float
    pref: str = "cost"
    start_time: str = "10:00"
    target_date_str: str | None = None
    limit: int = 5


def to_domain_request(request: ApiRouteRequest) -> RouteSearchRequest:
    date_value = request.target_date_str or datetime.now(_JST).date().isoformat()
    try:
        departure = datetime.strptime(
            f"{date_value} {request.start_time}",
            "%Y-%m-%d %H:%M",
        )
    except ValueError as error:
        raise RouteInputError(
            "target_date_str and start_time must use YYYY-MM-DD and HH:MM"
        ) from error
    if departure.strftime("%Y-%m-%d") != date_value:
        raise RouteInputError("target_date_str must be zero-padded YYYY-MM-DD")
    if departure.strftime("%H:%M") != request.start_time:
        raise RouteInputError("start_time must be zero-padded HH:MM")
    return RouteSearchRequest(
        origin=GeoPoint(request.alat, request.alon),
        destination=GeoPoint(request.blat, request.blon),
        departure_at=departure.replace(tzinfo=_JST),
        preference=normalize_route_preference(request.pref),
        limit=request.limit,
    )


def _http_error(error: Exception) -> HTTPException:
    detail: dict[str, Any] = {
        "code": "route_engine_error",
        "message": str(error),
    }
    if isinstance(error, UnsupportedPreferenceError):
        detail["code"] = "unsupported_route_preference"
        return HTTPException(422, detail=detail)
    if isinstance(error, RouteInputError):
        detail["code"] = "invalid_route_input"
        return HTTPException(422, detail=detail)
    if isinstance(error, RouteSearchLimitError):
        detail["code"] = "route_search_limit"
        detail["diagnostic"] = str(error)
        return HTTPException(503, detail=detail)
    if isinstance(error, RouteEngineUnavailableError):
        detail["code"] = "route_engine_unavailable"
        return HTTPException(503, detail=detail)
    if isinstance(error, RouteContractError):
        detail["code"] = "route_contract_violation"
        return HTTPException(500, detail=detail)
    return HTTPException(500, detail=detail)


def register_route_endpoint(
    app: Any,
    *,
    warmup_message: str,
    lock: asyncio.Lock | None = None,
) -> None:
    route_lock = lock or asyncio.Lock()

    @app.post("/route")
    async def route_start(request: ApiRouteRequest):
        if getattr(app.state, "loading_status", "starting") != "ready":
            raise HTTPException(503, warmup_message)

        engine = getattr(app.state, "route_engine", None)
        if engine is None:
            raise _http_error(
                RouteEngineUnavailableError("route engine is not initialized")
            )

        try:
            domain_request = to_domain_request(request)
            loop = asyncio.get_running_loop()
            async with route_lock:
                result = await loop.run_in_executor(
                    None,
                    engine.search,
                    domain_request,
                )
            return serialize_route_result(result)
        except (
            RouteInputError,
            RouteSearchLimitError,
            RouteEngineUnavailableError,
            RouteContractError,
        ) as error:
            raise _http_error(error) from error
