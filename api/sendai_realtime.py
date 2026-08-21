from __future__ import annotations

import httpx

from realtime_provider import GtfsRealtimeEndpoints, GtfsRealtimeHttpProvider

SENDAI_VEHICLE_POSITION_URL = (
    "https://api-public.odpt.org/api/v4/gtfs/realtime/"
    "odpt_SendaiMunicipal_bus_realtime_information_vehicle"
)
SENDAI_TRIP_UPDATES_URL = (
    "https://api-public.odpt.org/api/v4/gtfs/realtime/"
    "odpt_SendaiMunicipal_bus_realtime_information_trip_update"
)
SENDAI_ALERT_URL = (
    "https://api-public.odpt.org/api/v4/gtfs/realtime/"
    "odpt_SendaiMunicipal_bus_realtime_information_alert"
)

SENDAI_REALTIME_ENDPOINTS = GtfsRealtimeEndpoints(
    vehicle_positions=SENDAI_VEHICLE_POSITION_URL,
    trip_updates=SENDAI_TRIP_UPDATES_URL,
    alerts=SENDAI_ALERT_URL,
)


def create_sendai_realtime_provider(
    *,
    client: httpx.AsyncClient | None = None,
) -> GtfsRealtimeHttpProvider:
    # Use exactly the documented public endpoints. There is deliberately no
    # automatic fallback to the consumer-key endpoints.
    return GtfsRealtimeHttpProvider(
        SENDAI_REALTIME_ENDPOINTS,
        consumer_key=None,
        client=client,
    )
