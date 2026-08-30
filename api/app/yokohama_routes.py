from __future__ import annotations

from app.gtfs_bus_realtime_routes import register_gtfs_bus_vehicle_location_route
from app.route_only_places import register_route_only_places_routes
from app.route_only_routes import register_route_only_core_routes
from yokohama_transit import YOKOHAMA_BUS_FEED_ID


def register_yokohama_routes(app) -> None:
    register_route_only_core_routes(
        app,
        city_key="yokohama",
        city_display_name="Yokohama",
        warmup_data_label="Yokohama bus GTFS data",
        realtime_health={
            "vehicle_positions": True,
            "trip_updates": False,
            "alerts": False,
        },
    )
    register_gtfs_bus_vehicle_location_route(
        app,
        feed_id=YOKOHAMA_BUS_FEED_ID,
    )
    register_route_only_places_routes(app)
