import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import register_routes


class _FakeProvider:
    async def vehicle_positions(self, *, force_refresh=False):
        del force_refresh
        return (
            {
                "vehicle_id": "BUS-1",
                "lat": 35.68,
                "lon": 139.76,
                "trip_id": "trip-1",
                "trip_stop_ids": ["stop-1", "stop-2"],
                "before_first_stop": True,
                "from_stop_sequence": None,
                "observed_stop_sequence": 1,
                "current_status": "IN_TRANSIT_TO",
                "feed_timestamp": 1_700_000_000,
                "vehicle_timestamp": 1_700_000_001,
                "raw_stop_id": "stop-1",
                "raw_stop_name": "始発",
                "odpt:busroute": "route-1",
                "odpt:fromBusstopPole": None,
            },
        )


class TokyoBusLocationRoutesTest(unittest.TestCase):
    def test_before_first_stop_is_preserved_at_http_contract(self):
        app = FastAPI()
        app.state.TM = SimpleNamespace(latest_bus_positions_fetched_at=1_700_000_002)
        app.state.realtime_provider = _FakeProvider()
        register_routes(app)

        response = TestClient(app).get(
            "/bus/location",
            params={"route_id": "route-1", "trip_id": "trip-1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["before_first_stop"])
        self.assertIsNone(response.json()["odpt:fromBusstopPole"])
        self.assertIsNone(response.json()["from_stop_sequence"])


if __name__ == "__main__":
    unittest.main()
