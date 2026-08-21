from __future__ import annotations

from copy import deepcopy

from fastapi import HTTPException
from pydantic import BaseModel

from fare_policy import decorate_route_result_with_fare, fare_policy_api_options


class FareApplyRequest(BaseModel):
    policy_id: str
    candidates: list[dict]


def register_fare_routes(app) -> None:
    @app.get("/fare/policies")
    async def fare_policies():
        city_key = getattr(app.state, "city_key", None)
        if not isinstance(city_key, str) or not city_key:
            raise HTTPException(500, "Backend city is not initialized")
        try:
            return {
                "city": city_key,
                "policies": fare_policy_api_options(city_key),
            }
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error

    @app.post("/fare/apply")
    async def fare_apply(req: FareApplyRequest):
        city_key = getattr(app.state, "city_key", None)
        if not isinstance(city_key, str) or not city_key:
            raise HTTPException(500, "Backend city is not initialized")

        # Do not mutate the route-search result object owned by another layer.
        # Fare policy is a post-processing boundary by design.
        result = {"candidates": deepcopy(req.candidates)}
        try:
            decorate_route_result_with_fare(
                city_key=city_key,
                result=result,
                policy_id=req.policy_id,
            )
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error
        return result
