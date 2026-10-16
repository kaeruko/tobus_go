import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.app_factory import create_app, install_city_isolation
from unittest.mock import patch


class CityIsolationTest(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        install_city_isolation(app, "sendai")

        @app.get("/probe")
        async def probe():
            return {"city": "sendai"}

        self.client = TestClient(app)

    def test_matching_city_is_accepted(self):
        response = self.client.get("/probe", headers={"X-App-City": "sendai"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"city": "sendai"})

    def test_different_city_is_rejected_before_route_data_is_returned(self):
        response = self.client.get("/probe", headers={"X-App-City": "tokyo"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "city_mismatch")
        self.assertIn("client='tokyo'", response.json()["detail"]["message"])
        self.assertIn("backend='sendai'", response.json()["detail"]["message"])

    def test_header_value_is_exact_and_not_normalized(self):
        response = self.client.get("/probe", headers={"X-App-City": " Sendai"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "city_mismatch")

    def test_legacy_client_without_header_remains_compatible(self):
        response = self.client.get("/probe")
        self.assertEqual(response.status_code, 200)

    def test_retired_cities_fail_before_runtime_import_or_startup(self):
        for city in ("nagoya", "yokohama"):
            with self.subTest(city=city), patch.dict("os.environ", {"APP_CITY": city}):
                with self.assertRaisesRegex(RuntimeError, "Expected one of: tokyo, sendai"):
                    create_app("local")
                with self.assertRaises(ValueError):
                    install_city_isolation(FastAPI(), city)

    def test_unsupported_backend_city_fails_during_registration(self):
        with self.assertRaises(ValueError):
            install_city_isolation(FastAPI(), "sapporo")


if __name__ == "__main__":
    unittest.main()
