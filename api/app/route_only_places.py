from __future__ import annotations

import math
import os
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException, Query


_AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
_DETAILS_BASE_URL = "https://places.googleapis.com/v1/places"
_AUTOCOMPLETE_FIELD_MASK = (
    "suggestions.placePrediction.placeId,"
    "suggestions.placePrediction.text.text"
)
_DETAILS_FIELD_MASK = "id,displayName,formattedAddress,location"


def _require_api_key() -> str:
    key = os.getenv("GOOGLE_MAPS_API_KEY")
    if key is None or key == "":
        raise HTTPException(
            status_code=500,
            detail={
                "code": "google_maps_api_key_missing",
                "message": "GOOGLE_MAPS_API_KEY is required for Places lookup",
            },
        )
    return key


def _google_headers(key: str, field_mask: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": field_mask,
    }


def _decode_google_response(response: httpx.Response, *, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "google_places_invalid_response",
                "operation": operation,
                "upstream_status_code": response.status_code,
                "upstream_body": response.text,
            },
        ) from error

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "google_places_invalid_response",
                "operation": operation,
                "upstream_status_code": response.status_code,
                "upstream_body": payload,
            },
        )

    if response.is_error or "error" in payload:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "google_places_upstream_error",
                "operation": operation,
                "upstream_status_code": response.status_code,
                "upstream": payload,
            },
        )

    return payload


async def _request_autocomplete(q: str) -> dict[str, Any]:
    key = _require_api_key()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                _AUTOCOMPLETE_URL,
                headers=_google_headers(key, _AUTOCOMPLETE_FIELD_MASK),
                json={
                    "input": q,
                    "languageCode": "ja",
                    "regionCode": "JP",
                    "includedRegionCodes": ["jp"],
                },
            )
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "google_places_request_failed",
                "operation": "autocomplete",
                "message": str(error),
            },
        ) from error

    return _decode_google_response(response, operation="autocomplete")


async def _request_details(place_id: str) -> dict[str, Any]:
    key = _require_api_key()
    encoded_place_id = quote(place_id, safe="")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{_DETAILS_BASE_URL}/{encoded_place_id}",
                headers=_google_headers(key, _DETAILS_FIELD_MASK),
                params={
                    "languageCode": "ja",
                    "regionCode": "JP",
                },
            )
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "google_places_request_failed",
                "operation": "details",
                "message": str(error),
            },
        ) from error

    return _decode_google_response(response, operation="details")


def _legacy_autocomplete_payload(payload: dict[str, Any]) -> dict[str, Any]:
    suggestions = payload.get("suggestions", [])
    if not isinstance(suggestions, list):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "google_places_invalid_response",
                "operation": "autocomplete",
                "message": "suggestions must be a list",
            },
        )

    predictions: list[dict[str, str]] = []
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "google_places_invalid_response",
                    "operation": "autocomplete",
                    "message": "suggestion must be an object",
                },
            )
        prediction = suggestion.get("placePrediction")
        if not isinstance(prediction, dict):
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "google_places_invalid_response",
                    "operation": "autocomplete",
                    "message": "suggestion is missing placePrediction",
                },
            )
        place_id = prediction.get("placeId")
        text = prediction.get("text")
        description = text.get("text") if isinstance(text, dict) else None
        if not isinstance(place_id, str) or place_id == "":
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "google_places_invalid_response",
                    "operation": "autocomplete",
                    "message": "placePrediction.placeId is missing",
                },
            )
        if not isinstance(description, str) or description == "":
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "google_places_invalid_response",
                    "operation": "autocomplete",
                    "message": "placePrediction.text.text is missing",
                },
            )
        predictions.append(
            {
                "place_id": place_id,
                "description": description,
            }
        )

    return {"predictions": predictions}


def _legacy_details_payload(payload: dict[str, Any]) -> dict[str, Any]:
    display_name = payload.get("displayName")
    name = display_name.get("text") if isinstance(display_name, dict) else None
    if not isinstance(name, str) or name == "":
        raise HTTPException(
            status_code=502,
            detail={
                "code": "google_places_invalid_response",
                "operation": "details",
                "message": "displayName.text is missing",
            },
        )

    result: dict[str, Any] = {"name": name}
    formatted_address = payload.get("formattedAddress")
    if isinstance(formatted_address, str):
        result["formatted_address"] = formatted_address

    location = payload.get("location")
    if location is not None:
        if not isinstance(location, dict):
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "google_places_invalid_response",
                    "operation": "details",
                    "message": "location must be an object",
                },
            )
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        if (
            isinstance(latitude, bool)
            or isinstance(longitude, bool)
            or not isinstance(latitude, (int, float))
            or not isinstance(longitude, (int, float))
            or not math.isfinite(float(latitude))
            or not math.isfinite(float(longitude))
        ):
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "google_places_invalid_response",
                    "operation": "details",
                    "message": "location latitude/longitude are invalid",
                },
            )
        result["geometry"] = {
            "location": {
                "lat": float(latitude),
                "lng": float(longitude),
            }
        }

    return {"result": result}


def register_route_only_places_routes(app) -> None:
    @app.get("/autocomplete")
    async def autocomplete(q: str = Query(...)):
        payload = await _request_autocomplete(q)
        return _legacy_autocomplete_payload(payload)

    @app.get("/details")
    async def details(place_id: str = Query(...)):
        payload = await _request_details(place_id)
        return _legacy_details_payload(payload)
