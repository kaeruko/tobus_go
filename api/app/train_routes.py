from fastapi import HTTPException, Query
from pydantic import BaseModel

from app.services.train_realtime import (
    StaticTrainGtfs,
    TrainRealtimeError,
    build_location_response,
    get_realtime_vehicles,
    get_static_gtfs,
    resolve_train_vehicle,
)
from app.services.train_route_identity import (
    TrainRouteIdentityError,
    enrich_route_result_train_trip_ids,
)
from app.services.train_service_calendar import get_active_train_trip_ids
from toei_engine import determine_day_type


class TrainRouteIdentityRequest(BaseModel):
    candidates: list[dict]
    target_date_str: str | None = None


def register_train_routes(app) -> None:
    @app.get("/train/location")
    async def train_location(
        trip_id: str | None = Query(None),
        from_name: str | None = Query(None),
        to_name: str | None = Query(None),
        arrival_time: str | None = Query(None),
        force_refresh: bool = Query(False),
    ):
        try:
            vehicles, fetched_at = await get_realtime_vehicles(
                force_refresh=force_refresh,
            )
            static_gtfs = await get_static_gtfs()
            resolved = resolve_train_vehicle(
                vehicles,
                static_gtfs,
                trip_id=trip_id,
                from_name=from_name,
                to_name=to_name,
                arrival_time=arrival_time,
            )
            return build_location_response(
                resolved,
                realtime_fetched_at=fetched_at,
            )
        except TrainRealtimeError as error:
            raise HTTPException(
                error.status_code,
                detail={"code": error.code, "message": error.message},
            ) from error

    @app.post("/train/resolve-route-identities")
    async def resolve_route_identities(req: TrainRouteIdentityRequest):
        timetable_manager = getattr(app.state, "TM", None)
        if timetable_manager is None:
            raise HTTPException(
                503,
                detail={
                    "code": "train_timetable_manager_unavailable",
                    "message": "Train timetable manager is not initialized",
                },
            )

        try:
            static_gtfs = await get_static_gtfs()
            active_trip_ids = await get_active_train_trip_ids(req.target_date_str)
            active_static_gtfs = StaticTrainGtfs(
                trips={
                    trip_id: trip
                    for trip_id, trip in static_gtfs.trips.items()
                    if trip_id in active_trip_ids
                }
            )
            if not active_static_gtfs.trips:
                raise TrainRealtimeError(
                    "train_static_service_date_no_matching_trips",
                    "Static train GTFS has no trips active for the requested service date",
                    502,
                )

            enriched = enrich_route_result_train_trip_ids(
                {"candidates": req.candidates, "meta": {}},
                timetable_manager=timetable_manager,
                day_type=determine_day_type(req.target_date_str),
                static_gtfs=active_static_gtfs,
            )
        except TrainRealtimeError as error:
            raise HTTPException(
                error.status_code,
                detail={"code": error.code, "message": error.message},
            ) from error
        except TrainRouteIdentityError as error:
            raise HTTPException(
                409,
                detail={"code": error.code, "message": error.message},
            ) from error

        meta = enriched.get("meta") or {}
        return {
            "candidates": enriched.get("candidates", []),
            "rejections": meta.get("train_identity_rejected_candidates", []),
        }
