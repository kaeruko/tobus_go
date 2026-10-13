from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.route_endpoint import register_route_endpoint, require_yokohama_free_route_quotes
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

    def test_yokohama_final_free_route_contract_rejects_paid_or_unverified(self) -> None:
        policy = "yokohama_welfare_special_pass"
        good = {
            "policyId": policy, "settlementType": "free_pass",
            "status": "available", "payNowYen": 0, "effectiveFareYen": 0,
        }
        require_yokohama_free_route_quotes(
            {"candidates": [{"id": "verified", "fare": dict(good)}]}, policy,
        )
        for update in (
            {"payNowYen": 220, "effectiveFareYen": 220},
            {"payNowYen": None},
            {"payNowYen": False},
            {"status": "unavailable"},
            {"policyId": "yokohama_senior_special_pass"},
            {"settlementType": "normal"},
        ):
            with self.subTest(update=update):
                quote = good | update
                with self.assertRaisesRegex(RouteContractError, "unverified or paid"):
                    require_yokohama_free_route_quotes(
                        {"candidates": [{"id": "unsafe", "fare": quote}]}, policy,
                    )
        with self.assertRaisesRegex(RouteContractError, "missing verified"):
            require_yokohama_free_route_quotes(
                {"candidates": [{"id": "missing-fare"}]}, policy,
            )

    def test_yokohama_rejects_missing_normal_and_unknown_pass_without_search(self) -> None:
        for policy_id in (None, "normal", "invalid-id"):
            with self.subTest(policy_id=policy_id):
                engine = _RecordingEngine()
                body = _payload()
                if policy_id is not None:
                    body["fare_policy_id"] = policy_id
                resp = _client(engine, city_key="yokohama").post("/route", json=body)
                self.assertEqual(resp.status_code, 422)
                self.assertEqual(resp.json()["detail"]["code"], "invalid_route_input")
                self.assertEqual(engine.requests, [])

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
        response = _client(engine).post(
            "/route", json=_payload(fare_policy_id="yokohama_welfare_special_pass"),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "invalid_route_input")
        self.assertEqual(engine.requests, [])

    def test_fare_scope_id_is_not_coerced_from_a_number(self) -> None:
        engine = _RecordingEngine()
        response = _client(engine).post("/route", json=_payload(fare_policy_id=123))
        self.assertEqual(response.status_code, 422)
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
