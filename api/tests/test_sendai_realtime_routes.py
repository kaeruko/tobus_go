import unittest
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.sendai_routes import register_sendai_routes
from sendai_transit import SENDAI_FEED_ID
from transit_dataset import (
    FeedMetadata,
    TransitDataset,
    TransitMode,
    TransitRoute,
    TransitStop,
    TransitStopTime,
    TransitTrip,
)


class _FakeProvider:
    def __init__(self, positions=(), trip_updates=(), alerts=(), error=None):
        self.positions = tuple(positions)
        self.updates = tuple(trip_updates)
        self.alert_rows = tuple(alerts)
        self.error = error
        self.vehicle_calls = []

    async def vehicle_positions(self, *, force_refresh=False):
        self.vehicle_calls.append(force_refresh)
        if self.error is not None:
            raise self.error
        return self.positions

    async def trip_updates(self):
        if self.error is not None:
            raise self.error
        return self.updates

    async def alerts(self):
        if self.error is not None:
            raise self.error
        return self.alert_rows


def _dataset() -> TransitDataset:
    route_id = f"{SENDAI_FEED_ID}:R1"
    trip_id = f"{SENDAI_FEED_ID}:T1"
    stop_1 = f"{SENDAI_FEED_ID}:S1"
    stop_2 = f"{SENDAI_FEED_ID}:S2"
    return TransitDataset(
        metadata=FeedMetadata(
            feed_id=SENDAI_FEED_ID,
            source_type="gtfs",
            source_uri="https://example.invalid/sendai.zip",
            version="test",
            fetched_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        ),
        stops={
            stop_1: TransitStop(
                id=stop_1,
                source_id="S1",
                name="仙台駅前",
                lat=38.260,
                lon=140.880,
            ),
            stop_2: TransitStop(
                id=stop_2,
                source_id="S2",
                name="市役所前",
                lat=38.270,
                lon=140.890,
            ),
        },
        routes={
            route_id: TransitRoute(
                id=route_id,
                source_id="R1",
                short_name="1",
                long_name="仙台駅前～市役所前",
                mode=TransitMode.BUS,
            ),
        },
        trips={
            trip_id: TransitTrip(
                id=trip_id,
                source_id="T1",
                route_id=route_id,
                service_id=f"{SENDAI_FEED_ID}:ALL",
                headsign="市役所前",
            ),
        },
        stop_times=(
            TransitStopTime(
                trip_id=trip_id,
                stop_id=stop_1,
                sequence=1,
                arrival_minute=600,
                departure_minute=600,
            ),
            TransitStopTime(
                trip_id=trip_id,
                stop_id=stop_2,
                sequence=2,
                arrival_minute=610,
                departure_minute=610,
            ),
        ),
        calendars={},
    )


def _position(*, vehicle_id="BUS-1", trip_id="T1", stop_id="S2", sequence=2):
    return {
        "route_id": "R1",
        "trip_id": trip_id,
        "vehicle_id": vehicle_id,
        "lat": 38.26,
        "lon": 140.88,
        "stop_id": stop_id,
        "current_stop_sequence": sequence,
        "current_status": 2,
        "timestamp": 100,
        "feed_timestamp": 101,
    }


def _client(provider):
    app = FastAPI()
    app.state.loading_status = "ready"
    app.state.realtime_provider = provider
    app.state.transit_dataset = _dataset()
    register_sendai_routes(app)
    return TestClient(app)


class SendaiRealtimeRoutesTest(unittest.TestCase):
    def test_bus_location_requires_exact_route_and_trip_and_enriches_static_progress(self):
        provider = _FakeProvider(
            positions=(
                _position(),
                _position(vehicle_id="BUS-2", trip_id="OTHER"),
            )
        )
        response = _client(provider).get(
            "/bus/location",
            params={
                "route_id": "sendai_bus:R1",
                "trip_id": "sendai_bus:T1",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["vehicle_id"], "BUS-1")
        self.assertEqual(body["route_id"], "sendai_bus:R1")
        self.assertEqual(body["trip_id"], "sendai_bus:T1")
        self.assertEqual(body["raw_trip_id"], "T1")
        self.assertEqual(body["odpt:fromBusstopPole"], "sendai_bus:S1")
        self.assertEqual(body["raw_stop_name"], "市役所前")
        self.assertFalse(body["before_first_stop"])
        self.assertEqual(provider.vehicle_calls, [False])

    def test_bus_location_preserves_vehicle_approaching_first_stop(self):
        provider = _FakeProvider(
            positions=(
                _position(stop_id="S1", sequence=1),
            )
        )
        response = _client(provider).get(
            "/bus/location",
            params={
                "route_id": "sendai_bus:R1",
                "trip_id": "sendai_bus:T1",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["before_first_stop"])
        self.assertIsNone(body["odpt:fromBusstopPole"])
        self.assertIsNone(body["from_stop_sequence"])
        self.assertEqual(body["raw_stop_name"], "仙台駅前")

    def test_bus_location_does_not_substitute_similar_trip(self):
        provider = _FakeProvider(
            positions=(
                _position(vehicle_id="BUS-2", trip_id="OTHER"),
            )
        )
        response = _client(provider).get(
            "/bus/location",
            params={
                "route_id": "sendai_bus:R1",
                "trip_id": "sendai_bus:T1",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "bus_realtime_not_found")

    def test_bus_location_rejects_ambiguous_exact_matches(self):
        provider = _FakeProvider(
            positions=(
                _position(vehicle_id="BUS-1"),
                _position(vehicle_id="BUS-2"),
            )
        )
        client = _client(provider)
        response = client.get(
            "/bus/location",
            params={
                "route_id": "sendai_bus:R1",
                "trip_id": "sendai_bus:T1",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "bus_realtime_ambiguous")

        selected = client.get(
            "/bus/location",
            params={
                "route_id": "sendai_bus:R1",
                "trip_id": "sendai_bus:T1",
                "vehicle_id": "BUS-2",
            },
        )
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.json()["vehicle_id"], "BUS-2")

    def test_realtime_failure_is_503_and_has_no_route_fallback(self):
        provider = _FakeProvider(error=RuntimeError("upstream protobuf decode failed"))
        response = _client(provider).get(
            "/bus/location",
            params={
                "route_id": "sendai_bus:R1",
                "trip_id": "sendai_bus:T1",
            },
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "realtime_fetch_failed")
        self.assertIn("protobuf decode failed", response.json()["detail"]["message"])

    def test_rejects_non_sendai_namespaced_ids(self):
        provider = _FakeProvider()
        response = _client(provider).get(
            "/bus/location",
            params={"route_id": "tokyo:R1", "trip_id": "sendai_bus:T1"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "invalid_feed_id")
        self.assertEqual(provider.vehicle_calls, [])


if __name__ == "__main__":
    unittest.main()
