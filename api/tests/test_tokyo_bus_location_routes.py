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


class _MovedVehicleProvider:
    async def vehicle_positions(self, *, force_refresh=False):
        del force_refresh
        return (
            {
                "vehicle_id": "BUS-1",
                "lat": 35.68,
                "lon": 139.76,
                "trip_id": "trip-2",
                "trip_stop_ids": ["stop-3", "stop-4"],
                "before_first_stop": False,
                "from_stop_sequence": 8,
                "observed_stop_sequence": 9,
                "current_status": "IN_TRANSIT_TO",
                "feed_timestamp": 1_700_000_100,
                "vehicle_timestamp": 1_700_000_101,
                "raw_stop_id": "stop-4",
                "raw_stop_name": "別便の停留所",
                "odpt:busroute": "route-1",
                "odpt:fromBusstopPole": "stop-3",
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

    def test_debug_404_reports_where_the_requested_vehicle_went(self):
        app = FastAPI()
        app.state.TM = SimpleNamespace(
            latest_bus_positions_fetched_at=1_700_000_102
        )
        app.state.realtime_provider = _MovedVehicleProvider()
        register_routes(app)

        response = TestClient(app).get(
            "/bus/location",
            params={
                "route_id": "route-1",
                "trip_id": "trip-1",
                "vehicle_id": "BUS-1",
                "debug": "true",
            },
        )

        self.assertEqual(response.status_code, 404)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "bus_trip_not_found")
        diagnostic = detail["diagnostic"]
        self.assertEqual(diagnostic["route_match_count"], 1)
        self.assertEqual(diagnostic["route_trip_match_count"], 0)
        self.assertEqual(diagnostic["requested_trip_matches"], [])
        self.assertEqual(
            diagnostic["requested_vehicle_matches"],
            [
                {
                    "vehicle_id": "BUS-1",
                    "route_id": "route-1",
                    "trip_id": "trip-2",
                    "raw_stop_id": "stop-4",
                    "raw_stop_name": "別便の停留所",
                    "from_stop_id": "stop-3",
                    "from_stop_sequence": 8,
                    "observed_stop_sequence": 9,
                    "current_status": "IN_TRANSIT_TO",
                    "feed_timestamp": 1_700_000_100,
                    "vehicle_timestamp": 1_700_000_101,
                }
            ],
        )

    def test_non_debug_404_does_not_expose_match_diagnostic(self):
        app = FastAPI()
        app.state.TM = SimpleNamespace(
            latest_bus_positions_fetched_at=1_700_000_102
        )
        app.state.realtime_provider = _MovedVehicleProvider()
        register_routes(app)

        response = TestClient(app).get(
            "/bus/location",
            params={
                "route_id": "route-1",
                "trip_id": "trip-1",
                "vehicle_id": "BUS-1",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("diagnostic", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
