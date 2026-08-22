import inspect
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app.services import google_places


class _FakeAsyncClient:
    def __init__(self, response=None, request_error=None):
        self.response = response
        self.request_error = request_error
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if self.request_error is not None:
            raise self.request_error
        return self.response

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if self.request_error is not None:
            raise self.request_error
        return self.response


class GooglePlacesNewTests(unittest.IsolatedAsyncioTestCase):
    async def test_autocomplete_calls_new_api_and_preserves_flutter_contract(self):
        response = httpx.Response(
            200,
            json={
                "suggestions": [
                    {
                        "placePrediction": {
                            "placeId": "place-tokyo-station",
                            "text": {"text": "東京駅, 東京都"},
                        }
                    }
                ]
            },
        )
        fake_client = _FakeAsyncClient(response=response)

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-backend-key"}, clear=False):
            with patch.object(google_places.httpx, "AsyncClient", return_value=fake_client) as client_cls:
                result = await google_places.autocomplete_legacy_response(" 東京駅 ")

        client_cls.assert_called_once_with(timeout=10.0)
        self.assertEqual(
            result,
            {
                "predictions": [
                    {
                        "place_id": "place-tokyo-station",
                        "description": "東京駅, 東京都",
                    }
                ],
                "status": "OK",
            },
        )
        self.assertEqual(len(fake_client.calls), 1)
        method, url, kwargs = fake_client.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://places.googleapis.com/v1/places:autocomplete")
        self.assertEqual(
            kwargs["json"],
            {
                "input": "東京駅",
                "languageCode": "ja",
                "includedRegionCodes": ["jp"],
            },
        )
        self.assertEqual(kwargs["headers"]["X-Goog-Api-Key"], "test-backend-key")

    async def test_details_calls_new_api_with_field_mask_and_preserves_flutter_contract(self):
        response = httpx.Response(
            200,
            json={
                "id": "place-tokyo-station",
                "displayName": {"text": "東京駅"},
                "formattedAddress": "東京都千代田区丸の内１丁目",
                "location": {
                    "latitude": 35.681236,
                    "longitude": 139.767125,
                },
            },
        )
        fake_client = _FakeAsyncClient(response=response)

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-backend-key"}, clear=False):
            with patch.object(google_places.httpx, "AsyncClient", return_value=fake_client) as client_cls:
                result = await google_places.details_legacy_response("place-tokyo-station")

        client_cls.assert_called_once_with(timeout=10.0)
        self.assertEqual(
            result,
            {
                "result": {
                    "name": "東京駅",
                    "geometry": {
                        "location": {
                            "lat": 35.681236,
                            "lng": 139.767125,
                        }
                    },
                    "formatted_address": "東京都千代田区丸の内１丁目",
                },
                "status": "OK",
            },
        )
        self.assertEqual(len(fake_client.calls), 1)
        method, url, kwargs = fake_client.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(
            url,
            "https://places.googleapis.com/v1/places/place-tokyo-station",
        )
        self.assertEqual(kwargs["params"], {"languageCode": "ja", "regionCode": "JP"})
        self.assertEqual(
            kwargs["headers"]["X-Goog-FieldMask"],
            "id,displayName,formattedAddress,location",
        )

    async def test_missing_api_key_fails_instead_of_returning_empty_results(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPException) as caught:
                await google_places.autocomplete_legacy_response("東京駅")

        self.assertEqual(caught.exception.status_code, 500)
        self.assertEqual(caught.exception.detail, "GOOGLE_MAPS_API_KEY is missing")

    async def test_upstream_error_fails_without_legacy_fallback(self):
        response = httpx.Response(403, json={"error": {"message": "forbidden"}})
        fake_client = _FakeAsyncClient(response=response)

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-backend-key"}, clear=False):
            with patch.object(google_places.httpx, "AsyncClient", return_value=fake_client):
                with self.assertRaises(HTTPException) as caught:
                    await google_places.autocomplete_legacy_response("東京駅")

        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(len(fake_client.calls), 1)
        self.assertEqual(
            fake_client.calls[0][1],
            "https://places.googleapis.com/v1/places:autocomplete",
        )

    async def test_request_error_does_not_expose_api_key(self):
        request = httpx.Request("POST", "https://places.googleapis.com/v1/places:autocomplete")
        fake_client = _FakeAsyncClient(
            request_error=httpx.ConnectError("connection failed", request=request)
        )

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-backend-key"}, clear=False):
            with patch.object(google_places.httpx, "AsyncClient", return_value=fake_client):
                with self.assertRaises(HTTPException) as caught:
                    await google_places.autocomplete_legacy_response("東京駅")

        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("ConnectError", caught.exception.detail)
        self.assertNotIn("test-backend-key", caught.exception.detail)

    def test_legacy_places_endpoints_are_not_present(self):
        source = inspect.getsource(google_places)
        self.assertNotIn("maps.googleapis.com/maps/api/place", source)


if __name__ == "__main__":
    unittest.main()
