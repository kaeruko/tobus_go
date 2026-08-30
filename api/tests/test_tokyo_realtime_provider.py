import asyncio
import unittest
from types import SimpleNamespace

from app.services.tokyo_realtime_provider import TokyoRealtimeProvider


def _vehicle_row(**overrides):
    row = {
        "vehicle_id": "A",
        "trip_id": "trip-a",
        "route_id": "route-a",
        "odpt:busroute": "route-a",
        "lat": 35.68,
        "lon": 139.76,
        "raw_stop_id": "stop-4",
        "raw_stop_name": "Stop 4",
        "observed_stop_sequence": 4,
        "from_stop_sequence": 3,
        "current_status": "IN_TRANSIT_TO",
        "vehicle_timestamp": 1_700_000_010,
        "feed_timestamp": 1_700_000_000,
        "odpt:fromBusstopPole": "stop-3",
        "next_stop": "Stop 4",
        "next_stop_id": "stop-4",
    }
    row.update(overrides)
    return row


class TokyoRealtimeProviderTest(unittest.TestCase):
    def test_preserves_existing_cache_age_and_force_refresh_semantics(self):
        tm = SimpleNamespace(
            latest_bus_positions=[_vehicle_row()],
            latest_bus_positions_error=None,
        )
        calls = []

        async def refresh(manager, max_age_seconds):
            self.assertIs(manager, tm)
            calls.append(max_age_seconds)
            return True

        provider = TokyoRealtimeProvider(tm, refresh)
        normal = asyncio.run(provider.vehicle_positions())
        forced = asyncio.run(provider.vehicle_positions(force_refresh=True))

        self.assertEqual(normal[0]["vehicle_id"], "A")
        self.assertEqual(normal[0]["route_id"], "route-a")
        self.assertEqual(normal[0]["current_stop_sequence"], 4)
        self.assertEqual(normal[0]["from_stop_sequence"], 3)
        self.assertFalse(normal[0]["before_first_stop"])
        self.assertEqual(forced, normal)
        self.assertEqual(calls, [45, 0])

    def test_before_first_stop_does_not_fabricate_departed_stop(self):
        tm = SimpleNamespace(
            latest_bus_positions=[
                _vehicle_row(
                    raw_stop_id="stop-1",
                    raw_stop_name="始発",
                    observed_stop_sequence=1,
                    from_stop_sequence=1,
                    **{
                        "odpt:fromBusstopPole": "stop-1",
                    },
                )
            ],
            latest_bus_positions_error=None,
        )

        async def refresh(manager, max_age_seconds):
            del manager, max_age_seconds
            return True

        provider = TokyoRealtimeProvider(tm, refresh)
        row = asyncio.run(provider.vehicle_positions())[0]

        self.assertTrue(row["before_first_stop"])
        self.assertIsNone(row["from_stop_sequence"])
        self.assertIsNone(row["odpt:fromBusstopPole"])
        self.assertEqual(row["next_stop"], "始発")
        self.assertEqual(row["next_stop_id"], "stop-1")

    def test_refresh_failure_surfaces_runtime_error(self):
        tm = SimpleNamespace(
            latest_bus_positions=[],
            latest_bus_positions_error="GTFS-RT HTTP 503",
        )

        async def refresh(manager, max_age_seconds):
            del manager, max_age_seconds
            return False

        provider = TokyoRealtimeProvider(tm, refresh)
        with self.assertRaisesRegex(RuntimeError, "GTFS-RT HTTP 503"):
            asyncio.run(provider.vehicle_positions())

    def test_malformed_progress_fails_explicitly(self):
        tm = SimpleNamespace(
            latest_bus_positions=[_vehicle_row(observed_stop_sequence=0)],
            latest_bus_positions_error=None,
        )

        async def refresh(manager, max_age_seconds):
            del manager, max_age_seconds
            return True

        provider = TokyoRealtimeProvider(tm, refresh)
        with self.assertRaisesRegex(RuntimeError, "current_stop_sequence"):
            asyncio.run(provider.vehicle_positions())

    def test_unsupported_tokyo_realtime_capabilities_fail_explicitly(self):
        tm = SimpleNamespace(latest_bus_positions=[])

        async def refresh(manager, max_age_seconds):
            del manager, max_age_seconds
            return True

        provider = TokyoRealtimeProvider(tm, refresh)
        with self.assertRaisesRegex(NotImplementedError, "TripUpdates"):
            asyncio.run(provider.trip_updates())
        with self.assertRaisesRegex(NotImplementedError, "Alert"):
            asyncio.run(provider.alerts())


if __name__ == "__main__":
    unittest.main()
