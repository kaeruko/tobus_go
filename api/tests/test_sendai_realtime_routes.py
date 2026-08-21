import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.sendai_routes import register_sendai_routes


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


def _client(provider):
    app = FastAPI()
    app.state.loading_status = "ready"
    app.state.realtime_provider = provider
    register_sendai_routes(app)
    return TestClient(app)


class SendaiRealtimeRoutesTest(unittest.TestCase):
    def test_bus_location_requires_exact_route_and_trip(self):
        provider = _FakeProvider(
            positions=(
                {
                    "route_id": "R1",
                    "trip_id": "T1",
                    "vehicle_id": "BUS-1",
                    "lat": 38.26,
                    "lon": 140.88,
                    "stop_id": "S2",
                    "current_stop_sequence": 2,
                    "current_status": 2,
                    "timestamp": 100,
                    "feed_timestamp": 101,
                },
                {
                    "route_id": "R1",
                    "trip_id": "OTHER",
                    "vehicle_id": "BUS-2",
                    "lat": 38.27,
                    "lon": 140.89,
                },
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
        self.assertEqual(provider.vehicle_calls, [False])

    def test_bus_location_does_not_substitute_similar_trip(self):
        provider = _FakeProvider(
            positions=(
                {
                    "route_id": "R1",
                    "trip_id": "OTHER",
                    "vehicle_id": "BUS-2",
                    "lat": 38.27,
                    "lon": 140.89,
                },
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
                {"route_id": "R1", "trip_id": "T1", "vehicle_id": "BUS-1", "lat": 1.0, "lon": 2.0},
                {"route_id": "R1", "trip_id": "T1", "vehicle_id": "BUS-2", "lat": 1.1, "lon": 2.1},
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
        self.assertEqual(response.json()["detail"]["code"], "invalid_sendai_id")
        self.assertEqual(provider.vehicle_calls, [])


if __name__ == "__main__":
    unittest.main()
