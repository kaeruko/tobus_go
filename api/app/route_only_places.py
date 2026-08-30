from __future__ import annotations

import os

import httpx
from fastapi import Query


def register_route_only_places_routes(app) -> None:
    @app.get("/autocomplete")
    async def autocomplete(q: str = Query(...)):
        key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not key:
            return {"predictions": []}
        url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
        params = {
            "key": key,
            "input": q,
            "language": "ja",
            "components": "country:jp",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
        return response.json()

    @app.get("/details")
    async def details(place_id: str = Query(...)):
        key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not key:
            return {"result": {}}
        url = "https://maps.googleapis.com/maps/api/place/details/json"
        params = {
            "key": key,
            "place_id": place_id,
            "language": "ja",
            "fields": "geometry,name,formatted_address",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
        return response.json()
