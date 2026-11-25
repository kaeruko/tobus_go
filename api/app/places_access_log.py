"""Minimal Places telemetry; no raw IP, query string or upstream payload."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter

from starlette.types import ASGIApp, Receive, Scope, Send

_ENDPOINTS = {"/autocomplete": "autocomplete", "/details": "details"}
_JST = timezone(timedelta(hours=9))


@dataclass
class _Upstream:
    attempts: int = 0
    status: int | None = None
    tier: str | None = None


_upstream: ContextVar[_Upstream | None] = ContextVar("places_upstream", default=None)


def record_upstream_attempt(tier: str) -> None:
    observation = _upstream.get()
    if observation is not None:
        observation.attempts += 1
        observation.tier = tier


def record_upstream_status(status: int) -> None:
    observation = _upstream.get()
    if observation is not None:
        observation.status = status


def _client_hash(scope: Scope, day: str) -> tuple[str | None, str]:
    # Do not trust arbitrary forwarding headers or a caller-supplied device ID.
    # Mangum exposes the AWS-generated event in the ASGI scope.
    key = os.environ.get("PLACES_ACCESS_LOG_HMAC_KEY", "")
    if not key:
        return None, "key_not_configured"
    if re.fullmatch(r"[0-9a-fA-F]{64}", key) is None:
        return None, "invalid_key_configuration"

    event = scope.get("aws.event")
    if not isinstance(event, dict) or event.get("version") != "2.0":
        return None, "source_unavailable"
    context = event.get("requestContext")
    http = context.get("http") if isinstance(context, dict) else None
    source = http.get("sourceIp") if isinstance(http, dict) else None
    if not isinstance(source, str):
        return None, "source_unavailable"
    try:
        address = ipaddress.ip_address(source)
    except ValueError:
        return None, "invalid_source"
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped

    digest = hmac.new(
        bytes.fromhex(key),
        f"places-access:v1:{day}:{address}".encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:32], "ok"


class PlacesAccessLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        endpoint = _ENDPOINTS.get(scope.get("path", ""))
        if scope["type"] != "http" or endpoint is None:
            await self.app(scope, receive, send)
            return

        started = perf_counter()
        now = datetime.now(_JST)
        day = now.date().isoformat()
        client_hash, hash_status = _client_hash(scope, day)
        observation = _Upstream()
        token = _upstream.set(observation)
        status = 500

        async def observed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        finally:
            _upstream.reset(token)
            print(json.dumps({
                "event": "places_access",
                "endpoint": endpoint,
                "day_jst": day,
                "client_hash": client_hash,
                "client_hash_status": hash_status,
                "status": status,
                "upstream_attempts": observation.attempts,
                "upstream_status": observation.status,
                "upstream_tier": observation.tier,
                "duration_ms": round((perf_counter() - started) * 1000, 1),
            }, separators=(",", ":")), flush=True)
