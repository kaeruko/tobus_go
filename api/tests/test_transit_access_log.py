import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.transit_access_log import TransitAccessLogMiddleware


class TransitAccessLogTest(unittest.TestCase):
    def test_usage_logs_and_privacy(self):
        app = FastAPI()
        app.add_middleware(TransitAccessLogMiddleware)

        @app.post("/route")
        async def route(payload: dict):
            return {"candidates": [], "meta": {}}

        @app.get("/bus/location")
        async def bus():
            raise HTTPException(404, "private-response")

        @app.get("/train/location")
        async def train():
            return {"ok": True}

        @app.get("/bus/next")
        async def timetable():
            return {"ok": True}

        @app.post("/train/resolve-route-identities")
        async def identity():
            raise RuntimeError("private-exception")

        @app.get("/route")
        @app.get("/warmup")
        @app.get("/autocomplete")
        async def ignored():
            return {"ok": True}

        async def inject_event(scope, receive, send):
            if scope["type"] == "http":
                scope = {**scope, "aws.event": {
                    "version": "2.0", "requestContext": {
                        "http": {"sourceIp": "192.0.2.10"},
                    },
                }}
            await app(scope, receive, send)

        out = io.StringIO()
        with patch.dict(os.environ, {"PLACES_ACCESS_LOG_HMAC_KEY": "ab" * 32}), redirect_stdout(out):
            with TestClient(inject_event, raise_server_exceptions=False) as client:
                self.assertEqual(client.post("/route", json={"address": "private-address"}).json(), {"candidates": [], "meta": {}})
                self.assertEqual(client.get("/bus/location", params={"trip_id": "private-trip"}).status_code, 404)
                self.assertEqual(client.get("/train/location").status_code, 200)
                self.assertEqual(client.get("/bus/next").status_code, 200)
                self.assertEqual(client.post("/train/resolve-route-identities").status_code, 500)
                self.assertEqual(client.post("/route").status_code, 422)
                for path in ("/route", "/warmup", "/autocomplete"):
                    self.assertEqual(client.get(path).status_code, 200)
                self.assertEqual(client.options("/bus/location").status_code, 405)

        rows = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([r["feature"] for r in rows], ["route_search", "realtime", "realtime", "timetable", "train_identity", "route_search"])
        self.assertEqual([r["status"] for r in rows], [200, 404, 200, 200, 500, 422])
        self.assertEqual(len({r["client_hash"] for r in rows}), 1)
        for row in rows:
            self.assertEqual(row["event"], "transit_access")
            self.assertEqual(row["client_hash_status"], "ok")
            self.assertGreaterEqual(row["duration_ms"], 0)
        for private in ("192.0.2.10", "ab" * 32, "private-address", "private-trip", "private-response", "private-exception"):
            self.assertNotIn(private, out.getvalue())

    def test_missing_hash_key_preserves_requests(self):
        app = FastAPI()
        app.add_middleware(TransitAccessLogMiddleware)

        @app.get("/train/location")
        async def train():
            return {"ok": True}

        out = io.StringIO()
        with patch.dict(os.environ, {"PLACES_ACCESS_LOG_HMAC_KEY": ""}), redirect_stdout(out):
            with TestClient(app) as client:
                self.assertEqual(client.get("/train/location").json(), {"ok": True})
        row = json.loads(out.getvalue())
        self.assertIsNone(row["client_hash"])
        self.assertEqual(row["client_hash_status"], "key_not_configured")
