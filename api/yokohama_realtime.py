from __future__ import annotations

import os

import httpx

from realtime_provider import GtfsRealtimeEndpoints, GtfsRealtimeHttpProvider


YOKOHAMA_BUS_VEHICLE_POSITION_URL = (
    "https://api.odpt.org/api/v4/gtfs/realtime/YokohamaMunicipalBus_vehicle"
)
YOKOHAMA_BUS_REALTIME_ENDPOINTS = GtfsRealtimeEndpoints(
    vehicle_positions=YOKOHAMA_BUS_VEHICLE_POSITION_URL,
)


def _positive_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a number") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be > 0")
    return value


def create_yokohama_bus_realtime_provider(
    *,
    client: httpx.AsyncClient | None = None,
) -> GtfsRealtimeHttpProvider:
    consumer_key = os.getenv("ODPT_API_TOKEN", "").strip()
    if not consumer_key:
        raise RuntimeError("ODPT_API_TOKEN is required for Yokohama bus realtime")

    max_feed_age_seconds = _positive_float_env(
        "YOKOHAMA_BUS_REALTIME_MAX_AGE_SECONDS",
        180.0,
    )
    return GtfsRealtimeHttpProvider(
        YOKOHAMA_BUS_REALTIME_ENDPOINTS,
        consumer_key=consumer_key,
        client=client,
        max_feed_age_seconds=max_feed_age_seconds,
    )
