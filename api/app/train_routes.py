from fastapi import HTTPException, Query

from app.services.train_realtime import (
    TrainRealtimeError,
    build_location_response,
    get_realtime_vehicles,
    get_static_gtfs,
    resolve_train_vehicle,
)


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
