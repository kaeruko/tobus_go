import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.app_factory import create_app
from sendai_transit import SENDAI_MANIFEST_FILENAME, SENDAI_STATIC_URL


SERVICE_DATE = "2026-08-21"


def _write_feed(root: Path):
    files = {
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "A,仙台駅前,38.2600,140.8820\n"
            "B,交通局大学病院前,38.2710,140.8610\n"
        ),
        "routes.txt": (
            "route_id,route_short_name,route_long_name,route_type\n"
            "R1,10,仙台駅前から交通局大学病院前,3\n"
        ),
        "trips.txt": (
            "route_id,service_id,trip_id,trip_headsign,direction_id\n"
            "R1,WK,T1,交通局大学病院前,0\n"
        ),
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,10:00:00,10:00:00,A,1\n"
            "T1,10:20:00,10:20:00,B,2\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "WK,1,1,1,1,1,1,1,20260101,20261231\n"
        ),
    }
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    (root / SENDAI_MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "source_url": SENDAI_STATIC_URL,
                "validated_service_date": SERVICE_DATE,
                "fetched_at": "2026-08-21T00:00:00+00:00",
                "sha256": "d" * 64,
                "valid_from": "2026-01-01",
                "valid_until": "2026-12-31",
            }
        ),
        encoding="utf-8",
    )


class SendaiAppFactoryTest(unittest.TestCase):
    def test_sendai_startup_uses_sendai_gtfs_without_tokyo_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root)
            env = {
                "APP_CITY": "sendai",
                "SENDAI_GTFS_DIR": str(root),
                "SENDAI_GTFS_EXPECTED_SERVICE_DATE": SERVICE_DATE,
            }
            with patch.dict(os.environ, env, clear=False), patch(
                "httpx.AsyncClient",
                side_effect=AssertionError("Sendai startup attempted HTTP"),
            ):
                os.environ.pop("ODPT_API_TOKEN", None)
                app = create_app("local")
                for handler in app.router.on_startup:
                    asyncio.run(handler())

            self.assertEqual(app.state.loading_status, "ready")
            self.assertEqual(app.state.city_key, "sendai")
            self.assertEqual(app.state.transit_dataset.metadata.feed_id, "sendai_bus")
            self.assertTrue(app.state.realtime_bus_supported)
            self.assertTrue(hasattr(app.state, "realtime_provider"))
            self.assertFalse(hasattr(app.state, "G"))
            self.assertFalse(hasattr(app.state, "TM"))

            paths = {route.path for route in app.routes}
            self.assertIn("/route", paths)
            self.assertIn("/autocomplete", paths)
            self.assertIn("/details", paths)
            self.assertIn("/bus/location", paths)
            self.assertIn("/realtime/trip-updates", paths)
            self.assertIn("/realtime/alerts", paths)
            self.assertNotIn("/explore/reachable", paths)
            self.assertNotIn("/train/resolve-route-identities", paths)

    def test_sendai_requires_explicit_service_date(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root)
            env = {
                "APP_CITY": "sendai",
                "SENDAI_GTFS_DIR": str(root),
            }
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("SENDAI_GTFS_EXPECTED_SERVICE_DATE", None)
                app = create_app("local")
                with self.assertRaisesRegex(
                    RuntimeError,
                    "SENDAI_GTFS_EXPECTED_SERVICE_DATE is required",
                ):
                    for handler in app.router.on_startup:
                        asyncio.run(handler())


if __name__ == "__main__":
    unittest.main()
