import asyncio
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from app.app_factory import install_city_isolation
from app.places_access_log import PlacesAccessLogMiddleware, _client_hash
from app.services import google_places


_KEY = "ab" * 32
_IP = "192.0.2.10"


def _event(ip):
    return {"version": "2.0", "requestContext": {"http": {"sourceIp": ip}}}


def _app(ip=_IP):
    app = FastAPI()
    install_city_isolation(app, "tokyo")
    app.add_middleware(PlacesAccessLogMiddleware)

    @app.get("/autocomplete")
    async def autocomplete(q: str = Query(...)):
        return await google_places.autocomplete_legacy_response(q)

    @app.get("/details")
    async def details(place_id: str = Query(...), essentials: bool = False):
        return await google_places.details_legacy_response(
            place_id, essentials=essentials
        )

    @app.get("/warmup")
    async def warmup():
        return {"status": "ready"}

    async def inject_event(scope, receive, send):
        if scope["type"] == "http":
            scope = {**scope, "aws.event": _event(ip)}
        await app(scope, receive, send)

    return TestClient(inject_event)


class _Google:
    def __init__(self, *responses):
        self.responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    get = post


class PlacesAccessLogTest(unittest.TestCase):
    def test_daily_pseudonyms_and_invalid_configuration(self):
        scope = {"aws.event": _event(_IP)}
        with patch.dict(os.environ, {"PLACES_ACCESS_LOG_HMAC_KEY": _KEY}):
            first, status = _client_hash(scope, "2026-11-25")
            self.assertEqual(status, "ok")
            self.assertEqual(first, _client_hash(scope, "2026-11-25")[0])
            self.assertNotEqual(first, _client_hash(scope, "2026-11-26")[0])
            self.assertNotEqual(first, _client_hash(
                {"aws.event": _event("192.0.2.11")}, "2026-11-25"
            )[0])
            self.assertEqual(_client_hash({"headers": [
                (b"x-forwarded-for", _IP.encode())
            ]}, "2026-11-25"), (None, "source_unavailable"))
        with patch.dict(os.environ, {"PLACES_ACCESS_LOG_HMAC_KEY": ""}):
            self.assertEqual(_client_hash(scope, "2026-11-25"),
                             (None, "key_not_configured"))
        with patch.dict(os.environ, {"PLACES_ACCESS_LOG_HMAC_KEY": "bad"}):
            self.assertEqual(_client_hash(scope, "2026-11-25"),
                             (None, "invalid_key_configuration"))

    def test_logs_once_per_request_and_preserves_api_contract(self):
        google = _Google(
            httpx.Response(200, json={"suggestions": []}),
            httpx.Response(429, json={"error": {"message": "private-upstream"}}),
            httpx.Response(200, json={
                "location": {"latitude": 35.0, "longitude": 139.0},
            }),
            httpx.ConnectError("private-network-error"),
        )
        out = io.StringIO()
        with (
            patch.dict(os.environ, {
                "GOOGLE_MAPS_API_KEY": "private-key",
                "PLACES_ACCESS_LOG_HMAC_KEY": _KEY,
            }),
            patch.object(google_places.httpx, "AsyncClient", return_value=google),
            redirect_stdout(out),
            _app() as client,
        ):
            self.assertEqual(client.get("/autocomplete", params={
                "q": "private-query",
            }).json(), {"predictions": [], "status": "OK"})
            self.assertEqual(client.get("/details", params={
                "place_id": "private-place",
            }).status_code, 502)
            self.assertEqual(client.get("/details", params={
                "place_id": "private-place", "essentials": True,
            }).status_code, 200)
            self.assertEqual(client.get("/autocomplete", params={
                "q": "private-query",
            }).status_code, 502)
            self.assertEqual(client.get("/autocomplete").status_code, 422)
            self.assertEqual(client.get("/autocomplete", params={"q": "x"},
                                        headers={"X-App-City": "other"}).status_code, 409)
            self.assertEqual(client.get("/warmup").status_code, 200)

        logs = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(logs), 6)
        self.assertEqual([row["status"] for row in logs], [200, 502, 200, 502, 422, 409])
        self.assertEqual([row["upstream_attempts"] for row in logs], [1, 1, 1, 1, 0, 0])
        self.assertEqual([row["upstream_status"] for row in logs], [200, 429, 200, None, None, None])
        self.assertEqual([row["upstream_tier"] for row in logs],
                         ["autocomplete", "pro", "essentials", "autocomplete", None, None])
        self.assertEqual(len({row["client_hash"] for row in logs}), 1)
        self.assertTrue(all(row["client_hash_status"] == "ok" for row in logs))
        self.assertTrue(all(row["event"] == "places_access" for row in logs))
        for private in (_IP, _KEY, "private-key", "private-query", "private-place",
                        "private-upstream", "private-network-error"):
            self.assertNotIn(private, out.getvalue())

    def test_missing_hash_key_does_not_block_search(self):
        out = io.StringIO()
        with (
            patch.dict(os.environ, {
                "GOOGLE_MAPS_API_KEY": "test-key",
                "PLACES_ACCESS_LOG_HMAC_KEY": "",
            }),
            patch.object(google_places.httpx, "AsyncClient", return_value=_Google(
                httpx.Response(200, json={"suggestions": []}),
            )),
            redirect_stdout(out),
            _app() as client,
        ):
            self.assertEqual(client.get("/autocomplete", params={"q": "x"}).status_code, 200)
        row = json.loads(out.getvalue())
        self.assertIsNone(row["client_hash"])
        self.assertEqual(row["client_hash_status"], "key_not_configured")

    def test_concurrent_observations_are_isolated(self):
        from app.places_access_log import record_upstream_attempt, record_upstream_status

        async def run():
            async def downstream(scope, receive, send):
                endpoint = scope["path"]
                record_upstream_attempt("autocomplete" if endpoint == "/autocomplete" else "pro")
                await asyncio.sleep(0)
                record_upstream_status(200 if endpoint == "/autocomplete" else 429)
                await send({"type": "http.response.start", "status": 200 if endpoint == "/autocomplete" else 502})

            async def send(message):
                pass

            middleware = PlacesAccessLogMiddleware(downstream)
            await asyncio.gather(*[
                middleware({"type": "http", "path": path, "aws.event": _event(ip)}, None, send)
                for path, ip in (("/autocomplete", _IP), ("/details", "192.0.2.11"))
            ])

        out = io.StringIO()
        with patch.dict(os.environ, {"PLACES_ACCESS_LOG_HMAC_KEY": _KEY}), redirect_stdout(out):
            asyncio.run(run())
        logs = {row["endpoint"]: row for row in map(json.loads, out.getvalue().splitlines())}
        self.assertEqual(logs["autocomplete"]["upstream_status"], 200)
        self.assertEqual(logs["details"]["upstream_status"], 429)
        self.assertNotEqual(logs["autocomplete"]["client_hash"], logs["details"]["client_hash"])
