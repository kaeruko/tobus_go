from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.app_factory import create_app
from yokohama_transit import (
    YOKOHAMA_BUS_APPROVED_FEED_VERSION,
    YOKOHAMA_BUS_APPROVED_REVISION,
    YOKOHAMA_BUS_APPROVED_VALID_FROM,
    YOKOHAMA_BUS_APPROVED_VALID_UNTIL,
    YOKOHAMA_BUS_FEED_ID,
    YOKOHAMA_BUS_MANIFEST_FILENAME,
    YOKOHAMA_BUS_RESOURCE_ID,
    YOKOHAMA_BUS_STATIC_URL,
)


SERVICE_DATE = "2026-08-29"


def _write_feed(root: Path, *, manifest_service_date: str = SERVICE_DATE) -> None:
    files = {
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "A,横浜駅前,35.4660,139.6225\n"
            "B,桜木町駅前,35.4500,139.6300\n"
        ),
        "routes.txt": (
            "route_id,route_short_name,route_long_name,route_type\n"
            "R1,8,横浜駅前から桜木町駅前,3\n"
        ),
        "trips.txt": (
            "route_id,service_id,trip_id,trip_headsign,direction_id\n"
            "R1,ALL,T1,桜木町駅前,0\n"
        ),
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,10:00:00,10:00:00,A,1\n"
            "T1,10:15:00,10:15:00,B,2\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "ALL,1,1,1,1,1,1,1,20260727,20270726\n"
        ),
        "calendar_dates.txt": "service_id,date,exception_type\n",
        "feed_info.txt": (
            "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version\n"
            "横浜市交通局,https://www.city.yokohama.lg.jp/kotsu/,ja,20260727,20270726,"
            f"{YOKOHAMA_BUS_APPROVED_FEED_VERSION}\n"
        ),
    }
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    (root / YOKOHAMA_BUS_MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "source_url": YOKOHAMA_BUS_STATIC_URL,
                "resource_id": YOKOHAMA_BUS_RESOURCE_ID,
                "revision": YOKOHAMA_BUS_APPROVED_REVISION,
                "feed_version": YOKOHAMA_BUS_APPROVED_FEED_VERSION,
                "validated_service_date": manifest_service_date,
                "fetched_at": "2026-08-29T00:00:00+00:00",
                "sha256": "d" * 64,
                "valid_from": YOKOHAMA_BUS_APPROVED_VALID_FROM,
                "valid_until": YOKOHAMA_BUS_APPROVED_VALID_UNTIL,
                "calendar_coverage_from": YOKOHAMA_BUS_APPROVED_VALID_FROM,
                "calendar_coverage_until": YOKOHAMA_BUS_APPROVED_VALID_UNTIL,
            }
        ),
        encoding="utf-8",
    )


def _environment(root: Path) -> dict[str, str]:
    return {
        "APP_CITY": "yokohama",
        "YOKOHAMA_BUS_GTFS_DIR": str(root),
        "YOKOHAMA_BUS_GTFS_EXPECTED_SERVICE_DATE": SERVICE_DATE,
    }


class YokohamaBackendTest(unittest.TestCase):
    def test_startup_loads_only_yokohama_static_bus_gtfs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root)
            with patch.dict(os.environ, _environment(root), clear=False), patch(
                "httpx.AsyncClient",
                side_effect=AssertionError("Yokohama startup attempted HTTP"),
            ):
                os.environ.pop("ODPT_API_TOKEN", None)
                app = create_app("local")
                for handler in app.router.on_startup:
                    asyncio.run(handler())

            self.assertEqual(app.state.loading_status, "ready")
            self.assertEqual(app.state.city_key, "yokohama")
            self.assertEqual(
                app.state.transit_dataset.metadata.feed_id,
                YOKOHAMA_BUS_FEED_ID,
            )
            self.assertIsNone(app.state.realtime_provider)
            self.assertFalse(app.state.realtime_bus_supported)
            self.assertFalse(hasattr(app.state, "G"))
            self.assertFalse(hasattr(app.state, "TM"))

            paths = {route.path for route in app.routes}
            self.assertIn("/route", paths)
            self.assertIn("/autocomplete", paths)
            self.assertIn("/details", paths)
            self.assertNotIn("/bus/location", paths)
            self.assertNotIn("/realtime/trip-updates", paths)
            self.assertNotIn("/realtime/alerts", paths)
            self.assertNotIn("/explore/reachable", paths)
            self.assertNotIn("/train/resolve-route-identities", paths)

    def test_health_reports_loaded_feed_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root)
            with patch.dict(os.environ, _environment(root), clear=False):
                with TestClient(create_app("local")) as client:
                    response = client.get(
                        "/healthz",
                        headers={"X-App-City": "yokohama"},
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "status": "ready",
                "city": "yokohama",
                "feed_id": YOKOHAMA_BUS_FEED_ID,
                "feed_version": YOKOHAMA_BUS_APPROVED_FEED_VERSION,
                "realtime": False,
            },
        )

    def test_route_uses_yokohama_route_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root)
            with patch.dict(os.environ, _environment(root), clear=False):
                with TestClient(create_app("local")) as client:
                    response = client.post(
                        "/route",
                        headers={"X-App-City": "yokohama"},
                        json={
                            "alat": 35.4660,
                            "alon": 139.6225,
                            "blat": 35.4500,
                            "blon": 139.6300,
                            "pref": "shortTime",
                            "start_time": "09:55",
                            "target_date_str": SERVICE_DATE,
                        },
                    )

        self.assertEqual(response.status_code, 200)
        candidates = response.json()["candidates"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["arrival_time"], "10:15")
        self.assertEqual(candidates[0]["lines"], ["8"])
        ride = next(step for step in candidates[0]["steps"] if step["kind"] == "bus")
        self.assertEqual(ride["route_id"], "yokohama_bus:R1")
        self.assertEqual(ride["trip_id"], "yokohama_bus:T1")

    def test_route_only_places_boundary_is_available_without_a_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root)
            with patch.dict(os.environ, _environment(root), clear=False):
                os.environ.pop("GOOGLE_MAPS_API_KEY", None)
                with TestClient(create_app("local")) as client:
                    autocomplete = client.get(
                        "/autocomplete",
                        params={"q": "横浜駅"},
                        headers={"X-App-City": "yokohama"},
                    )
                    details = client.get(
                        "/details",
                        params={"place_id": "test-place"},
                        headers={"X-App-City": "yokohama"},
                    )

        self.assertEqual(autocomplete.status_code, 200)
        self.assertEqual(autocomplete.json(), {"predictions": []})
        self.assertEqual(details.status_code, 200)
        self.assertEqual(details.json(), {"result": {}})

    def test_missing_gtfs_dir_fails_startup(self) -> None:
        with patch.dict(
            os.environ,
            {
                "APP_CITY": "yokohama",
                "YOKOHAMA_BUS_GTFS_EXPECTED_SERVICE_DATE": SERVICE_DATE,
            },
            clear=False,
        ):
            os.environ.pop("YOKOHAMA_BUS_GTFS_DIR", None)
            app = create_app("local")
            with self.assertRaisesRegex(
                RuntimeError,
                "YOKOHAMA_BUS_GTFS_DIR is required",
            ):
                with TestClient(app):
                    pass

    def test_missing_expected_service_date_fails_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "APP_CITY": "yokohama",
                    "YOKOHAMA_BUS_GTFS_DIR": directory,
                },
                clear=False,
            ):
                os.environ.pop("YOKOHAMA_BUS_GTFS_EXPECTED_SERVICE_DATE", None)
                app = create_app("local")
                with self.assertRaisesRegex(
                    RuntimeError,
                    "YOKOHAMA_BUS_GTFS_EXPECTED_SERVICE_DATE is required",
                ):
                    with TestClient(app):
                        pass

    def test_manifest_service_date_mismatch_fails_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root, manifest_service_date="2026-08-30")
            with patch.dict(os.environ, _environment(root), clear=False):
                app = create_app("local")
                with self.assertRaisesRegex(
                    RuntimeError,
                    "expected service date mismatch",
                ):
                    with TestClient(app):
                        pass

    def test_missing_manifest_fails_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, _environment(root), clear=False):
                app = create_app("local")
                with self.assertRaises(FileNotFoundError):
                    with TestClient(app):
                        pass

    def test_tokyo_client_is_rejected_by_yokohama_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root)
            with patch.dict(os.environ, _environment(root), clear=False):
                with TestClient(create_app("local")) as client:
                    response = client.get(
                        "/healthz",
                        headers={"X-App-City": "tokyo"},
                    )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "city_mismatch")
        self.assertIn("backend='yokohama'", response.json()["detail"]["message"])


if __name__ == "__main__":
    unittest.main()
