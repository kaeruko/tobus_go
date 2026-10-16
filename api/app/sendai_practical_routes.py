"""Explicitly constructed test app. Never registered by public city startup."""
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from route_engine import RouteSearchLimitError
from sendai_practical_network import PracticalFreeNetwork, search_practical_subway
from sendai_practical_serializer import SCHEMA, serialize_practical_journey
from transit_timetable_choices import NetworkSearchParameters


class PracticalRouteRequest(BaseModel):
    origin_stop_id: str
    destination_stop_id: str
    civil_date: date
    departure_minute: int = Field(ge=0, lt=1440)
    # Explicit selection; normal settings are never converted to a free pass.
    fare_policy_id: Literal["sendai_fureai_pass"]
    accept_experimental_transfer_model: Literal[True]

    class Config:
        extra = "forbid"


def create_sendai_practical_test_app(network, *, environment, parameters):
    if environment != "test" or not isinstance(network, PracticalFreeNetwork):
        raise ValueError("explicit reviewed network and test environment required")
    if not isinstance(parameters, NetworkSearchParameters) or parameters.max_candidates != 1:
        raise ValueError("explicit shared v2 parameters with one earliest result required")
    app = FastAPI(title="仙台でGO 予定時刻モデル検証")
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(?:localhost|127\.0\.0\.1)(?::[0-9]+)?",
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.get("/test/sendai/capabilities")
    def capabilities():
        snapshot = network.free_scope.snapshot
        served = {row.stop_id for trip in network.free_scope.allowed_trip_ids for row in snapshot.rows_by_trip[trip]}
        modes = sorted({snapshot.routes[snapshot.trips[t].route_id].mode.value for t in snapshot.allowed_trip_ids})
        return {"schema": SCHEMA, "environment": "test", "city": "sendai",
            "fare_policy_ids": ["sendai_fureai_pass"], "supported_modes": modes,
            "unsupported": ["miyagi_kotsu", "unreviewed_municipal_segments", "realtime", "unreviewed_special_days"],
            "feed_versions": dict(snapshot.feed_versions),
            "feed_provenance": [{"feed_id": d.metadata.feed_id, "source_uri": d.metadata.source_uri,
                                 "version": d.metadata.version} for d in snapshot.datasets],
            "attribution": "仙台市・仙台市交通局 / 公共交通オープンデータセンター / CC BY 4.0。到着は予定時刻モデル。",
            "operating_dates": sorted(e.day.isoformat() for e in network.source.operating_days.entries if e.kind is not None
                       and ("bus" not in modes or e.day in network.bus_reviewed_days)),
            "stops": [{"id": key, "name": snapshot.stops[key].name,
                       "mode": "rail" if key.startswith("sendai_subway:") else "bus"} for key in sorted(served)],
            "transfer_time_measured": False, "actual_connection_guaranteed": False,
            "experimental_margin_formally_adopted": False,
            "parameters": {"max_candidates": parameters.max_candidates, "max_boardings": parameters.max_boardings,
                           "max_travel_minutes": parameters.max_travel_minutes}}

    @app.post("/test/sendai/route")
    def route(request: PracticalRouteRequest):
        try:
            journeys = search_practical_subway(network, request.origin_stop_id, request.destination_stop_id,
                civil_date=request.civil_date, departure_minute=request.departure_minute, parameters=parameters)
        except ValueError as error:
            raise HTTPException(422, detail={"code": "unsupported_review_scope", "message": str(error)}) from error
        except RouteSearchLimitError as error:
            # A partial result is never serialized as a completed search.
            raise HTTPException(503, detail={"code": "search_limit", "message": str(error)}) from error
        return {"schema": SCHEMA, "candidates": [serialize_practical_journey(j) for j in journeys]}
    return app
