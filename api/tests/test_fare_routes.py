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

if __name__ == "__main__":
    unittest.main()
