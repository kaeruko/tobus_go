from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.route_endpoint import register_route_endpoint
from route_engine import (
    RouteCandidate,
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


def _client(
    engine: _RecordingEngine, *, raise_server_exceptions: bool = True,
    city_key: str | None = None,
):
    app = FastAPI()
    if city_key is not None:
        app.state.city_key = city_key
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

    def test_bus_only_flag_is_forwarded_to_engine(self) -> None:
        engine = _RecordingEngine()
        response = _client(engine).post(
            "/route",
            json=_payload(bus_only=True),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(engine.requests[0].bus_only)

    def test_bus_only_defaults_to_false(self) -> None:
        engine = _RecordingEngine()
        response = _client(engine).post("/route", json=_payload())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(engine.requests[0].bus_only)

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

    def test_unavailable_fare_scope_does_not_run_normal_search(self) -> None:
        engine = _RecordingEngine()
        for policy_id in ("unsupported_fixture_pass", "sendai_fureai_pass", "sendai_keiro_pass"):
            with self.subTest(policy_id=policy_id):
                response = _client(engine, city_key="sendai").post(
                    "/route", json=_payload(fare_policy_id=policy_id),
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"]["code"], "invalid_route_input")
        self.assertEqual(engine.requests, [])

    def test_fare_scope_id_is_not_coerced_from_a_number(self) -> None:
        engine = _RecordingEngine()
        response = _client(engine).post("/route", json=_payload(fare_policy_id=123))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(engine.requests, [])

    def test_reviewed_quote_mismatch_fails_without_public_repricing(self) -> None:
        for policy_id, quoted_policy, status in (
            ("sendai_fureai_pass", "sendai_fureai_pass", "unavailable"),
            ("sendai_keiro_pass", "sendai_keiro_pass", "available"),
            ("sendai_keiro_pass", "sendai_fureai_pass", "unavailable"),
        ):
            with self.subTest(policy_id=policy_id, quoted_policy=quoted_policy, status=status):
                candidate = RouteCandidate.from_mapping({
                    "id": "fixture", "lines": ["bus"], "boards": 1, "transfers": 0,
                    "total_time": 1, "walking_distance_meters": 0, "walking_segment_count": 0,
                    "steps": [{"kind": "bus", "title": "bus", "from_": "A", "to": "B", "minutes": 1}],
                    "points": [], "arrival_time": "09:56",
                    "fare": {"policyId": quoted_policy, "status": status},
                })
                engine = _RecordingEngine(RouteSearchResult(candidates=[candidate]))
                engine.for_fare_policy = lambda selected: engine
                engine.verified_quote_policy_statuses = {
                    "sendai_fureai_pass": "available", "sendai_keiro_pass": "unavailable",
                }
                response = _client(engine, city_key="sendai").post(
                    "/route", json=_payload(fare_policy_id=policy_id),
                )
                self.assertEqual(response.status_code, 500, response.text)
                self.assertEqual(response.json()["detail"]["code"], "route_contract_violation")
                self.assertEqual(len(engine.requests), 1)

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
