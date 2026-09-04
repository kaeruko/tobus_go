from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.route_endpoint import register_route_endpoint
from route_engine import (
    RouteContractError,
    RoutePreference,
    RouteSearchLimitError,
    RouteSearchResult,
)


class _RecordingEngine:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result or RouteSearchResult(candidates=[])
        self.error = error
        self.requests = []

    def search(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def _client(engine: _RecordingEngine, *, raise_server_exceptions: bool = True):
    app = FastAPI()
    app.state.loading_status = "ready"
    app.state.route_engine = engine
    register_route_endpoint(app, warmup_message="warming up")
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _payload(**overrides):
    value = {
        "alat": 35.0,
        "alon": 139.0,
        "blat": 35.1,
        "blon": 139.1,
        "pref": "shortTime",
        "start_time": "09:55",
        "target_date_str": "2026-09-04",
    }
    value.update(overrides)
    return value


class SharedRouteEndpointTest(unittest.TestCase):
    def test_api_alias_is_normalized_before_engine_call(self) -> None:
        engine = _RecordingEngine()
        response = _client(engine).post("/route", json=_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"candidates": [], "meta": {}})
        self.assertEqual(engine.requests[0].preference, RoutePreference.FASTEST)

    def test_unknown_preference_is_422_without_fallback(self) -> None:
        engine = _RecordingEngine()
        response = _client(engine).post(
            "/route",
            json=_payload(pref="unknown"),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"]["code"],
            "unsupported_route_preference",
        )
        self.assertEqual(engine.requests, [])

    def test_search_safety_limit_is_503_with_diagnostic(self) -> None:
        engine = _RecordingEngine(error=RouteSearchLimitError("visited=100"))
        response = _client(engine).post("/route", json=_payload())
        self.assertEqual(response.status_code, 503)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "route_search_limit")
        self.assertEqual(detail["diagnostic"], "visited=100")

    def test_contract_failure_is_500(self) -> None:
        engine = _RecordingEngine(error=RouteContractError("broken candidate"))
        response = _client(engine).post("/route", json=_payload())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"]["code"],
            "route_contract_violation",
        )

    def test_unclassified_runtime_error_is_not_rewritten_as_422(self) -> None:
        engine = _RecordingEngine(error=RuntimeError("internal failure"))
        response = _client(
            engine,
            raise_server_exceptions=False,
        ).post("/route", json=_payload())
        self.assertEqual(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
