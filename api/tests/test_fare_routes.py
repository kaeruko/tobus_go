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

    def test_nagoya_normal_fare_is_210_per_city_bus_ride(self):
        result = {
            "candidates": [
                {
                    "id": "n1",
                    "steps": [
                        {"kind": "walk"},
                        {"kind": "bus", "route_id": "nagoya_bus:R1"},
                        {"kind": "wait"},
                        {"kind": "bus", "route_id": "nagoya_bus:R2"},
                    ],
                }
            ]
        }

        decorate_route_result_with_fare(
            city_key="nagoya",
            result=result,
            policy_id="normal",
        )

        candidate = result["candidates"][0]
        self.assertEqual(candidate["fare"]["normalFareYen"], 420)
        self.assertEqual(candidate["fare"]["payNowYen"], 420)
        ride_steps = [
            step for step in candidate["steps"] if step["kind"] == "bus"
        ]
        self.assertEqual([step["fare_yen"] for step in ride_steps], [210, 210])

    def test_nagoya_free_pass_changes_only_fare_quote_not_route(self):
        candidate = {
            "id": "same-route",
            "steps": [{"kind": "bus", "route_id": "nagoya_bus:R1"}],
        }
        normal_result = {"candidates": [candidate.copy() | {"steps": [dict(candidate["steps"][0])] }]}
        pass_result = {"candidates": [candidate.copy() | {"steps": [dict(candidate["steps"][0])] }]}

        decorate_route_result_with_fare(
            city_key="nagoya",
            result=normal_result,
            policy_id="normal",
        )
        decorate_route_result_with_fare(
            city_key="nagoya",
            result=pass_result,
            policy_id="nagoya_welfare_special_pass",
        )

        self.assertEqual(
            normal_result["candidates"][0]["id"],
            pass_result["candidates"][0]["id"],
        )
        self.assertEqual(normal_result["candidates"][0]["fare"]["payNowYen"], 210)
        self.assertEqual(pass_result["candidates"][0]["fare"]["payNowYen"], 0)
        self.assertEqual(
            pass_result["candidates"][0]["fare"]["settlementType"],
            "free_pass",
        )

    def test_fare_apply_endpoint_rejects_other_city_policy(self):
        client = self._client("nagoya")
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
        client = self._client("nagoya")
        response = client.get("/fare/policies")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["city"], "nagoya")
        ids = [item["policyId"] for item in payload["policies"]]
        self.assertEqual(ids, ["normal", "nagoya_welfare_special_pass"])
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

    def test_yokohama_normal_policy_is_available_without_inventing_fare(self):
        client = self._client("yokohama")

        policies = client.get("/fare/policies")
        self.assertEqual(policies.status_code, 200)
        self.assertEqual(
            [item["policyId"] for item in policies.json()["policies"]],
            ["normal"],
        )

        response = client.post(
            "/fare/apply",
            json={
                "policy_id": "normal",
                "candidates": [
                    {
                        "id": "y1",
                        "steps": [
                            {"kind": "walk"},
                            {"kind": "bus", "route_id": "yokohama_bus:R1"},
                        ],
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        quote = response.json()["candidates"][0]["fare"]
        self.assertEqual(quote["policyId"], "normal")
        self.assertEqual(quote["status"], "unavailable")
        self.assertIsNone(quote["normalFareYen"])
        self.assertIsNone(quote["payNowYen"])
        self.assertEqual(
            quote["unavailableReason"],
            "normal_fare_not_calculable_from_current_route_data",
        )


if __name__ == "__main__":
    unittest.main()
