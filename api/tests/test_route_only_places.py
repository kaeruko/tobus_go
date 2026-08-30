from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.route_only_places import register_route_only_places_routes


class _FakeAsyncClient:
    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)

    async def get(self, url: str, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)


def _response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://places.googleapis.com/"),
    )


def _client() -> TestClient:
    app = FastAPI()
    register_route_only_places_routes(app)
    return TestClient(app)


class RouteOnlyPlacesTest(unittest.TestCase):
    def test_autocomplete_uses_places_v1_and_preserves_flutter_contract(self) -> None:
        fake = _FakeAsyncClient(
            _response(
                200,
                {
                    "suggestions": [
                        {
                            "placePrediction": {
                                "placeId": "yokohama-station",
                                "text": {"text": "横浜駅, 神奈川県横浜市"},
                            }
                        }
                    ]
                },
            )
        )
        with (
            patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False),
            patch("app.route_only_places.httpx.AsyncClient", return_value=fake),
            _client() as client,
        ):
            response = client.get("/autocomplete", params={"q": "横浜駅"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "predictions": [
                    {
                        "place_id": "yokohama-station",
                        "description": "横浜駅, 神奈川県横浜市",
                    }
                ]
            },
        )
        self.assertEqual(len(fake.calls), 1)
        method, url, kwargs = fake.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://places.googleapis.com/v1/places:autocomplete")
        self.assertEqual(
            kwargs["json"],
            {
                "input": "横浜駅",
                "languageCode": "ja",
                "regionCode": "JP",
                "includedRegionCodes": ["JP"],
            },
        )
        self.assertEqual(kwargs["headers"]["X-Goog-Api-Key"], "test-key")
        self.assertEqual(
            kwargs["headers"]["X-Goog-FieldMask"],
            "suggestions.placePrediction.placeId,suggestions.placePrediction.text.text",
        )

    def test_details_uses_places_v1_and_preserves_flutter_contract(self) -> None:
        fake = _FakeAsyncClient(
            _response(
                200,
                {
                    "id": "yokohama-station",
                    "displayName": {"text": "横浜駅"},
                    "formattedAddress": "神奈川県横浜市西区高島2丁目",
                    "location": {
                        "latitude": 35.465981,
                        "longitude": 139.622142,
                    },
                },
            )
        )
        with (
            patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False),
            patch("app.route_only_places.httpx.AsyncClient", return_value=fake),
            _client() as client,
        ):
            response = client.get("/details", params={"place_id": "yokohama-station"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "result": {
                    "name": "横浜駅",
                    "formatted_address": "神奈川県横浜市西区高島2丁目",
                    "geometry": {
                        "location": {
                            "lat": 35.465981,
                            "lng": 139.622142,
                        }
                    },
                }
            },
        )
        self.assertEqual(len(fake.calls), 1)
        method, url, kwargs = fake.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(
            url,
            "https://places.googleapis.com/v1/places/yokohama-station",
        )
        self.assertEqual(
            kwargs["headers"]["X-Goog-FieldMask"],
            "id,displayName,formattedAddress,location",
        )
        self.assertEqual(
            kwargs["params"],
            {"languageCode": "ja", "regionCode": "JP"},
        )

    def test_missing_key_fails_instead_of_returning_empty_predictions(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_MAPS_API_KEY", None)
            with _client() as client:
                response = client.get("/autocomplete", params={"q": "横浜駅"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"]["code"],
            "google_maps_api_key_missing",
        )

    def test_google_error_is_propagated_as_diagnostic_502(self) -> None:
        fake = _FakeAsyncClient(
            _response(
                403,
                {
                    "error": {
                        "code": 403,
                        "status": "PERMISSION_DENIED",
                        "message": "Places API (New) is not enabled",
                    }
                },
            )
        )
        with (
            patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False),
            patch("app.route_only_places.httpx.AsyncClient", return_value=fake),
            _client() as client,
        ):
            response = client.get("/autocomplete", params={"q": "横浜駅"})

        self.assertEqual(response.status_code, 502)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "google_places_upstream_error")
        self.assertEqual(detail["upstream_status_code"], 403)
        self.assertEqual(
            detail["upstream"]["error"]["status"],
            "PERMISSION_DENIED",
        )


if __name__ == "__main__":
    unittest.main()
