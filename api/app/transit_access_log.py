"""Minimal transit usage telemetry; no request or response payloads."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from time import perf_counter

from starlette.types import ASGIApp, Receive, Scope, Send

from .places_access_log import _client_hash

_JST = timezone(timedelta(hours=9))
_ENDPOINTS = {
    ("POST", "/route"): "route_search",
    ("GET", "/bus/location"): "realtime",
    ("GET", "/train/location"): "realtime",
    ("GET", "/bus/next"): "timetable",
    ("POST", "/train/resolve-route-identities"): "train_identity",
}


class TransitAccessLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        feature = _ENDPOINTS.get((scope.get("method"), path))
        if feature is None:
            await self.app(scope, receive, send)
            return

        started = perf_counter()
        day = datetime.now(_JST).date().isoformat()
        client_hash, hash_status = _client_hash(scope, day)
        status = 500

        async def observed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        finally:
            print(json.dumps({
                "event": "transit_access",
                "endpoint": path,
                "feature": feature,
                "day_jst": day,
                "client_hash": client_hash,
                "client_hash_status": hash_status,
                "status": status,
                "duration_ms": round((perf_counter() - started) * 1000, 1),
            }, separators=(",", ":")), flush=True)
