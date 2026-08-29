from __future__ import annotations


async def setup_yokohama_on_startup(app, mode: str) -> None:
    # This foundation intentionally has no transit dataset attached yet.
    # Keep the Yokohama backend alive for health/isolation checks, but never
    # substitute Tokyo/ODPT data while the Yokohama GTFS feeds are unconfigured.
    del mode
    app.state.city_key = "yokohama"
    app.state.loading_status = "not_configured"
    app.state.transit_dataset = None
    app.state.route_backend = None
    app.state.realtime_provider = None
    app.state.realtime_bus_supported = False
