import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fare_routes import register_fare_routes
from fare_policy import decorate_route_result_with_fare


class FareRoutesTest(unittest.TestCase):
    def _client(self, city_key: str) -> TestClient:
        app = FastAPI()
        app.state.city_key = city_key
        register_fare_routes(app)
        return TestClient(app)

    def test_fare_apply_endpoint_rejects_other_city_policy(self):
        client = self._client("sendai")
        response = client.post(
            "/fare/apply",
            json={
                "policy_id": "tokyo_toei_transport_pass",
                "candidates": [
                    {
                        "id": "n1",
                        "steps": [{"kind": "bus"}],
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("unsupported fare policy", response.json()["detail"])

    def test_policy_endpoint_is_city_scoped(self):
        client = self._client("sendai")
        response = client.get("/fare/policies")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["city"], "sendai")
        ids = [item["policyId"] for item in payload["policies"]]
        self.assertEqual(ids, ["normal"])
        self.assertNotIn("tokyo_toei_transport_pass", ids)

    def test_public_apply_rejects_reviewed_sendai_passes(self):
        for city in ("sendai", "tokyo"):
            client = self._client(city)
            for policy_id in ("sendai_fureai_pass", "sendai_keiro_pass"):
                with self.subTest(city=city, policy_id=policy_id):
                    response = client.post("/fare/apply", json={
                        "policy_id": policy_id,
                        "candidates": [{"id": "bus", "steps": [{"kind": "bus"}]}],
                    })
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertIn("unsupported fare policy", response.json()["detail"])

    def test_tokyo_normal_fare_remains_unavailable_without_exact_step_fares(self):
        result = {
            "candidates": [
                {
                    "id": "t1",
                    "steps": [
                        {"kind": "rail", "route_id": "toei_rail:Asakusa"},
                    ],
                }
            ]
        }
        decorate_route_result_with_fare(
            city_key="tokyo",
            result=result,
            policy_id="normal",
        )
        quote = result["candidates"][0]["fare"]
        self.assertEqual(quote["status"], "unavailable")
        self.assertIsNone(quote["normalFareYen"])
        self.assertIsNone(quote["payNowYen"])

    def test_tokyo_toei_pass_rejects_tokyo_metro_segment(self):
        client = self._client("tokyo")
        response = client.post(
            "/fare/apply",
            json={
                "policy_id": "tokyo_toei_transport_pass",
                "candidates": [{
                    "id": "metro",
                    "steps": [{
                        "kind": "rail",
                        "operator_id": "tokyo_metro",
                        "route_id": "tokyo_metro:1",
                    }],
                }],
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("cannot be applied to Tokyo Metro", response.json()["detail"])

    def test_tokyo_toei_pass_keeps_legacy_toei_candidate_compatible(self):
        client = self._client("tokyo")
        response = client.post(
            "/fare/apply",
            json={
                "policy_id": "tokyo_toei_transport_pass",
                "candidates": [{
                    "id": "toei",
                    "steps": [{"kind": "rail", "route_id": "toei_rail:Asakusa"}],
                }],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["candidates"][0]["fare"]["payNowYen"], 0)

if __name__ == "__main__":
    unittest.main()
