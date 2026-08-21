import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.app_factory import create_app
from nagoya_transit import (
    NAGOYA_DATASET_ID,
    NAGOYA_MANIFEST_FILENAME,
    NAGOYA_RESOURCE_ID,
)


def _write_feed(root: Path):
    files = {
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "A,名古屋駅,35.1709,136.8815\n"
            "B,栄,35.1706,136.9066\n"
        ),
        "routes.txt": (
            "route_id,route_short_name,route_long_name,route_type\n"
            "R1,幹1,名古屋駅から栄,3\n"
        ),
        "trips.txt": (
            "route_id,service_id,trip_id,trip_headsign,direction_id\n"
            "R1,WK,T1,栄,0\n"
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
    (root / NAGOYA_MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "dataset_id": NAGOYA_DATASET_ID,
                "resource_id": NAGOYA_RESOURCE_ID,
                "revision": "2026-03-28",
                "source_url": "https://data.bodik.jp/nagoya.zip",
                "fetched_at": "2026-08-21T00:00:00+00:00",
                "sha256": "b" * 64,
            }
        ),
        encoding="utf-8",
    )


class NagoyaAppFactoryTest(unittest.TestCase):
    def test_nagoya_startup_performs_no_http_or_odpt_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root)
            env = {
                "APP_CITY": "nagoya",
                "NAGOYA_GTFS_DIR": str(root),
                "NAGOYA_GTFS_EXPECTED_REVISION": "2026-03-28",
                # A token is intentionally present. Nagoya must still not use it.
                "ODPT_API_TOKEN": "must-not-be-used",
            }
            with patch.dict(os.environ, env, clear=False), patch(
                "httpx.AsyncClient",
                side_effect=AssertionError("Nagoya startup attempted HTTP"),
            ):
                app = create_app("local")
                for handler in app.router.on_startup:
                    asyncio.run(handler())

            self.assertEqual(app.state.loading_status, "ready")
            self.assertEqual(app.state.city_key, "nagoya")
            self.assertFalse(hasattr(app.state, "realtime_provider"))
            paths = {route.path for route in app.routes}
            self.assertIn("/route", paths)
            self.assertIn("/bus/location", paths)
            self.assertNotIn("/explore/reachable", paths)
            self.assertNotIn("/train/resolve-route-identities", paths)

    def test_backend_city_key_is_exact(self):
        with patch.dict(os.environ, {"APP_CITY": " nagoya"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "Unsupported APP_CITY"):
                create_app("local")


if __name__ == "__main__":
    unittest.main()
