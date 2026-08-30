from __future__ import annotations

from app.route_only_places import register_route_only_places_routes
from app.route_only_routes import (
    register_route_only_core_routes,
    register_unsupported_bus_realtime_routes,
)


def register_nagoya_routes(app) -> None:
    register_route_only_core_routes(
        app,
        city_key="nagoya",
        city_display_name="Nagoya",
        realtime_health=False,
    )
    register_unsupported_bus_realtime_routes(
        app,
        message="Nagoya backend does not expose an official open realtime feed",
    )
    register_route_only_places_routes(app)
