import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.app_factory import create_app


class YokohamaBackendFoundationTest(unittest.TestCase):
    def _create_client(self) -> TestClient:
        with patch.dict(os.environ, {"APP_CITY": "yokohama"}, clear=False):
            app = create_app("test")
        return TestClient(app)

    def test_health_identifies_yokohama_and_reports_not_configured(self):
        with self._create_client() as client:
            response = client.get("/healthz", headers={"X-App-City": "yokohama"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["city"], "yokohama")
        self.assertFalse(response.json()["ok"])
        self.assertEqual(response.json()["status"], "not_configured")
        self.assertEqual(response.json()["feeds"], [])

    def test_route_does_not_fall_back_to_another_city(self):
        with self._create_client() as client:
            response = client.post("/route", headers={"X-App-City": "yokohama"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"]["code"],
            "yokohama_transit_not_configured",
        )

    def test_tokyo_client_is_rejected_by_yokohama_backend(self):
        with self._create_client() as client:
            response = client.get("/healthz", headers={"X-App-City": "tokyo"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "city_mismatch")
        self.assertIn("backend='yokohama'", response.json()["detail"]["message"])


if __name__ == "__main__":
    unittest.main()
