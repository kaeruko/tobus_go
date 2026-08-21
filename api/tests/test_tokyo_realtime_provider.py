import asyncio
import unittest
from types import SimpleNamespace

from app.services.tokyo_realtime_provider import TokyoRealtimeProvider


class TokyoRealtimeProviderTest(unittest.TestCase):
    def test_preserves_existing_cache_age_and_force_refresh_semantics(self):
        tm = SimpleNamespace(
            latest_bus_positions=[{"vehicle_id": "A"}],
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

        self.assertEqual(normal, ({"vehicle_id": "A"},))
        self.assertEqual(forced, ({"vehicle_id": "A"},))
        self.assertEqual(calls, [45, 0])

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
