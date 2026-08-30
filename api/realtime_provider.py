from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from google.transit import gtfs_realtime_pb2


class RealtimeProvider(Protocol):
    async def vehicle_positions(
        self, *, force_refresh: bool = False
    ) -> tuple[dict[str, Any], ...]: ...

    async def trip_updates(self) -> tuple[dict[str, Any], ...]: ...

    async def alerts(self) -> tuple[dict[str, Any], ...]: ...


@dataclass(frozen=True, slots=True)
class GtfsRealtimeEndpoints:
    vehicle_positions: str | None = None
    trip_updates: str | None = None
    alerts: str | None = None

    def __post_init__(self) -> None:
        values = (
            self.vehicle_positions,
            self.trip_updates,
            self.alerts,
        )
        if all(value is None for value in values):
            raise ValueError("at least one GTFS-Realtime endpoint is required")
        for value in values:
            if value is not None and not value.startswith("https://"):
                raise ValueError("GTFS-Realtime endpoint must be absolute HTTPS")


def _translation_string(value) -> str | None:
    translations = getattr(value, "translation", ())
    if not translations:
        return None
    japanese = next(
        (item.text for item in translations if getattr(item, "language", "") == "ja"),
        None,
    )
    return japanese or translations[0].text


def _entity_ref(value) -> dict[str, Any]:
    return {
        "agency_id": value.agency_id or None,
        "route_id": value.route_id or None,
        "route_type": value.route_type if value.HasField("route_type") else None,
        "trip_id": (
            (value.trip.trip_id or None) if value.HasField("trip") else None
        ),
        "stop_id": value.stop_id or None,
    }


class GtfsRealtimeHttpProvider:
    """Strict GTFS-Realtime HTTP provider with no source fallback."""

    def __init__(
        self,
        endpoints: GtfsRealtimeEndpoints,
        *,
        consumer_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
        max_feed_age_seconds: float | None = None,
        max_future_skew_seconds: float = 60.0,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        if consumer_key == "":
            raise ValueError("consumer_key must be None or non-empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if max_feed_age_seconds is not None and max_feed_age_seconds <= 0:
            raise ValueError("max_feed_age_seconds must be > 0 when configured")
        if max_future_skew_seconds < 0:
            raise ValueError("max_future_skew_seconds must be >= 0")
        self.endpoints = endpoints
        self.consumer_key = consumer_key
        self._client = client
        self.timeout_seconds = timeout_seconds
        self.max_feed_age_seconds = max_feed_age_seconds
        self.max_future_skew_seconds = max_future_skew_seconds
        self._now_fn = now_fn or time.time

    @staticmethod
    def _required_endpoint(url: str | None, capability: str) -> str:
        if url is None:
            raise RuntimeError(
                f"GTFS-Realtime capability is not configured: {capability}"
            )
        return url

    def _validate_feed_timestamp(
        self,
        message: gtfs_realtime_pb2.FeedMessage,
        *,
        url: str,
    ) -> None:
        if self.max_feed_age_seconds is None:
            return
        if not message.header.HasField("timestamp") or message.header.timestamp <= 0:
            raise RuntimeError(
                f"GTFS-Realtime feed timestamp is missing: {url}"
            )
        now = self._now_fn()
        age_seconds = now - float(message.header.timestamp)
        if age_seconds > self.max_feed_age_seconds:
            raise RuntimeError(
                "GTFS-Realtime feed is stale: "
                f"url={url}, age_seconds={age_seconds:.1f}, "
                f"max_age_seconds={self.max_feed_age_seconds:.1f}"
            )
        if age_seconds < -self.max_future_skew_seconds:
            raise RuntimeError(
                "GTFS-Realtime feed timestamp is too far in the future: "
                f"url={url}, skew_seconds={-age_seconds:.1f}, "
                f"max_future_skew_seconds={self.max_future_skew_seconds:.1f}"
            )

    async def _fetch(self, url: str) -> gtfs_realtime_pb2.FeedMessage:
        params = (
            {"acl:consumerKey": self.consumer_key}
            if self.consumer_key is not None
            else None
        )
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            if not response.content:
                raise RuntimeError(f"GTFS-Realtime response is empty: {url}")
            message = gtfs_realtime_pb2.FeedMessage()
            try:
                message.ParseFromString(response.content)
            except Exception as error:
                raise RuntimeError(
                    f"GTFS-Realtime protobuf decode failed: {url}"
                ) from error
            self._validate_feed_timestamp(message, url=url)
            return message
        finally:
            if owns_client:
                await client.aclose()

    async def vehicle_positions(
        self, *, force_refresh: bool = False
    ) -> tuple[dict[str, Any], ...]:
        # This provider performs a fresh HTTP request on every call, so the flag
        # does not change its behavior. It exists to preserve the shared
        # interface used by Tokyo's cached provider.
        del force_refresh
        url = self._required_endpoint(
            self.endpoints.vehicle_positions,
            "vehicle_positions",
        )
        message = await self._fetch(url)
        rows: list[dict[str, Any]] = []
        for entity in message.entity:
            if not entity.HasField("vehicle"):
                continue
            vehicle = entity.vehicle
            if not vehicle.HasField("position"):
                raise RuntimeError(
                    f"VehiclePosition entity {entity.id!r} is missing position"
                )
            trip = vehicle.trip
            rows.append(
                {
                    "entity_id": entity.id,
                    "trip_id": trip.trip_id or None,
                    "route_id": trip.route_id or None,
                    "direction_id": (
                        trip.direction_id if trip.HasField("direction_id") else None
                    ),
                    "vehicle_id": vehicle.vehicle.id or None,
                    "vehicle_label": vehicle.vehicle.label or None,
                    "lat": vehicle.position.latitude,
                    "lon": vehicle.position.longitude,
                    "bearing": (
                        vehicle.position.bearing
                        if vehicle.position.HasField("bearing")
                        else None
                    ),
                    "speed": (
                        vehicle.position.speed
                        if vehicle.position.HasField("speed")
                        else None
                    ),
                    "stop_id": vehicle.stop_id or None,
                    "current_stop_sequence": (
                        vehicle.current_stop_sequence
                        if vehicle.HasField("current_stop_sequence")
                        else None
                    ),
                    "current_status": (
                        int(vehicle.current_status)
                        if vehicle.HasField("current_status")
                        else None
                    ),
                    "timestamp": vehicle.timestamp or None,
                    "feed_timestamp": message.header.timestamp or None,
                }
            )
        return tuple(rows)

    async def trip_updates(self) -> tuple[dict[str, Any], ...]:
        url = self._required_endpoint(
            self.endpoints.trip_updates,
            "trip_updates",
        )
        message = await self._fetch(url)
        rows: list[dict[str, Any]] = []
        for entity in message.entity:
            if not entity.HasField("trip_update"):
                continue
            update = entity.trip_update
            trip = update.trip
            stop_updates = []
            for stop in update.stop_time_update:
                stop_updates.append(
                    {
                        "stop_sequence": (
                            stop.stop_sequence if stop.HasField("stop_sequence") else None
                        ),
                        "stop_id": stop.stop_id or None,
                        "arrival_delay": (
                            stop.arrival.delay
                            if stop.HasField("arrival") and stop.arrival.HasField("delay")
                            else None
                        ),
                        "arrival_time": (
                            stop.arrival.time
                            if stop.HasField("arrival") and stop.arrival.HasField("time")
                            else None
                        ),
                        "departure_delay": (
                            stop.departure.delay
                            if stop.HasField("departure") and stop.departure.HasField("delay")
                            else None
                        ),
                        "departure_time": (
                            stop.departure.time
                            if stop.HasField("departure") and stop.departure.HasField("time")
                            else None
                        ),
                    }
                )
            rows.append(
                {
                    "entity_id": entity.id,
                    "trip_id": trip.trip_id or None,
                    "route_id": trip.route_id or None,
                    "direction_id": (
                        trip.direction_id if trip.HasField("direction_id") else None
                    ),
                    "vehicle_id": update.vehicle.id or None,
                    "timestamp": update.timestamp or None,
                    "feed_timestamp": message.header.timestamp or None,
                    "stop_time_updates": stop_updates,
                }
            )
        return tuple(rows)

    async def alerts(self) -> tuple[dict[str, Any], ...]:
        url = self._required_endpoint(
            self.endpoints.alerts,
            "alerts",
        )
        message = await self._fetch(url)
        rows: list[dict[str, Any]] = []
        for entity in message.entity:
            if not entity.HasField("alert"):
                continue
            alert = entity.alert
            rows.append(
                {
                    "entity_id": entity.id,
                    "header_text": _translation_string(alert.header_text),
                    "description_text": _translation_string(alert.description_text),
                    "url": _translation_string(alert.url),
                    "cause": int(alert.cause) if alert.HasField("cause") else None,
                    "effect": int(alert.effect) if alert.HasField("effect") else None,
                    "active_periods": [
                        {
                            "start": period.start if period.HasField("start") else None,
                            "end": period.end if period.HasField("end") else None,
                        }
                        for period in alert.active_period
                    ],
                    "informed_entities": [
                        _entity_ref(item) for item in alert.informed_entity
                    ],
                    "feed_timestamp": message.header.timestamp or None,
                }
            )
        return tuple(rows)
