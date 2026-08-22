import os
from urllib.parse import quote

import httpx
from fastapi import HTTPException

PLACES_AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
PLACES_DETAILS_URL = "https://places.googleapis.com/v1/places"
PLACES_DETAILS_FIELD_MASK = "id,displayName,formattedAddress,location"


def _api_key() -> str:
    key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        raise HTTPException(500, "GOOGLE_MAPS_API_KEY is missing")
    return key


def _upstream_json(response: httpx.Response, operation: str) -> dict:
    if response.status_code < 200 or response.status_code >= 300:
        raise HTTPException(
            502,
            f"Places API (New) {operation} upstream error {response.status_code}",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            502,
            f"Places API (New) {operation} returned invalid JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            502,
            f"Places API (New) {operation} returned a non-object JSON response",
        )
    return payload


async def autocomplete_legacy_response(query: str) -> dict:
    query = query.strip()
    if not query:
        raise HTTPException(400, "q must not be empty")

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _api_key(),
    }
    body = {
        "input": query,
        "languageCode": "ja",
        "includedRegionCodes": ["jp"],
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                PLACES_AUTOCOMPLETE_URL,
                headers=headers,
                json=body,
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            502,
            f"Places API (New) autocomplete request failed: {type(exc).__name__}",
        ) from exc

    payload = _upstream_json(response, "autocomplete")
    suggestions = payload.get("suggestions", [])
    if not isinstance(suggestions, list):
        raise HTTPException(
            502,
            "Places API (New) autocomplete response has invalid suggestions",
        )

    predictions = []
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            raise HTTPException(
                502,
                "Places API (New) autocomplete response contains an invalid suggestion",
            )
        prediction = suggestion.get("placePrediction")
        if prediction is None:
            continue
        if not isinstance(prediction, dict):
            raise HTTPException(
                502,
                "Places API (New) autocomplete response has invalid placePrediction",
            )

        place_id = prediction.get("placeId")
        text = prediction.get("text")
        description = text.get("text") if isinstance(text, dict) else None
        if not isinstance(place_id, str) or not place_id:
            raise HTTPException(
                502,
                "Places API (New) autocomplete placePrediction is missing placeId",
            )
        if not isinstance(description, str) or not description:
            raise HTTPException(
                502,
                "Places API (New) autocomplete placePrediction is missing text.text",
            )

        predictions.append(
            {
                "place_id": place_id,
                "description": description,
            }
        )

    return {"predictions": predictions, "status": "OK"}


async def details_legacy_response(place_id: str) -> dict:
    place_id = place_id.strip()
    if not place_id:
        raise HTTPException(400, "place_id must not be empty")

    encoded_place_id = quote(place_id, safe="")
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _api_key(),
        "X-Goog-FieldMask": PLACES_DETAILS_FIELD_MASK,
    }
    params = {"languageCode": "ja", "regionCode": "JP"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{PLACES_DETAILS_URL}/{encoded_place_id}",
                headers=headers,
                params=params,
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            502,
            f"Places API (New) details request failed: {type(exc).__name__}",
        ) from exc

    payload = _upstream_json(response, "details")

    display_name = payload.get("displayName")
    name = display_name.get("text") if isinstance(display_name, dict) else None
    location = payload.get("location")
    latitude = location.get("latitude") if isinstance(location, dict) else None
    longitude = location.get("longitude") if isinstance(location, dict) else None
    formatted_address = payload.get("formattedAddress")

    if not isinstance(name, str) or not name:
        raise HTTPException(
            502,
            "Places API (New) details response is missing displayName.text",
        )
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        raise HTTPException(
            502,
            "Places API (New) details response is missing numeric location",
        )
    if formatted_address is not None and not isinstance(formatted_address, str):
        raise HTTPException(
            502,
            "Places API (New) details response has invalid formattedAddress",
        )

    result = {
        "name": name,
        "geometry": {
            "location": {
                "lat": float(latitude),
                "lng": float(longitude),
            }
        },
    }
    if formatted_address:
        result["formatted_address"] = formatted_address

    return {"result": result, "status": "OK"}
