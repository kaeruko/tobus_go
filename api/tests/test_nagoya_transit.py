import asyncio
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.nagoya_runtime import setup_nagoya_on_startup
from nagoya_transit import (
    NAGOYA_DATASET_ID,
    NAGOYA_MANIFEST_FILENAME,
    NAGOYA_RESOURCE_ID,
    NagoyaRouteBackend,
    fetch_nagoya_gtfs,
    load_nagoya_dataset,
    resolve_nagoya_resource,
)


REVISION = "2026-03-28"
SOURCE_URL = "https://data.bodik.jp/dataset/nagoya/resource/file.zip"


def _gtfs_files():
    return {
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "A,名古屋駅,35.170900,136.881500\n"
            "B,伏見,35.169000,136.897000\n"
            "C,栄,35.170600,136.906600\n"
        ),
        "routes.txt": (
            "route_id,route_short_name,route_long_name,route_type\n"
            "R1,幹1,名古屋駅から伏見,3\n"
            "R2,幹2,伏見から栄,3\n"
            "R3,直通,名古屋駅から栄,3\n"
        ),
        "trips.txt": (
            "route_id,service_id,trip_id,trip_headsign,direction_id\n"
            "R1,WK,T1,伏見,0\n"
            "R2,WK,T2,栄,0\n"
            "R3,WK,T3,栄,0\n"
        ),
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,10:00:00,10:00:00,A,1\n"
            "T1,10:10:00,10:10:00,B,2\n"
            "T2,10:15:00,10:15:00,B,1\n"
            "T2,10:25:00,10:25:00,C,2\n"
            "T3,10:05:00,10:05:00,A,1\n"
            "T3,10:40:00,10:40:00,C,2\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "WK,1,1,1,1,1,1,1,20260101,20261231\n"
        ),
        "calendar_dates.txt": "service_id,date,exception_type\n",
    }


def _zip_bytes():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in _gtfs_files().items():
            archive.writestr(name, content)
    return output.getvalue()


def _package_payload(revision_name="2026年3月28日改正"):
    return {
        "success": True,
        "result": {
            "id": NAGOYA_DATASET_ID,
            "resources": [
                {
                    "id": NAGOYA_RESOURCE_ID,
                    "package_id": NAGOYA_DATASET_ID,
                    "state": "active",
                    "format": "ZIP",
                    "mimetype": "application/zip",
                    "name": f"市バスGTFS-JPデータ {revision_name}",
                    "url": SOURCE_URL,
                }
            ],
        },
    }


class _FakeResponse:
    def __init__(self, *, payload=None, content=b""):
        self._payload = payload
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        if len(self.urls) == 1:
            return _FakeResponse(payload=_package_payload())
        if url == SOURCE_URL:
            return _FakeResponse(content=_zip_bytes())
        raise AssertionError(f"unexpected URL: {url}")


def _write_installed_feed(root: Path, revision=REVISION):
    for name, content in _gtfs_files().items():
        (root / name).write_text(content, encoding="utf-8")
    manifest = {
        "dataset_id": NAGOYA_DATASET_ID,
        "resource_id": NAGOYA_RESOURCE_ID,
        "revision": revision,
        "source_url": SOURCE_URL,
        "fetched_at": "2026-08-21T00:00:00+00:00",
        "sha256": "a" * 64,
    }
    (root / NAGOYA_MANIFEST_FILENAME).write_text(
        json.dumps(manifest), encoding="utf-8"
    )


class NagoyaGtfsSourceTest(unittest.TestCase):
    def test_resolves_only_the_configured_revision(self):
        resource = resolve_nagoya_resource(
            _package_payload(), expected_revision=REVISION
        )
        self.assertEqual(resource["resource_id"], NAGOYA_RESOURCE_ID)
        self.assertEqual(resource["revision"], REVISION)

        with self.assertRaisesRegex(RuntimeError, "revision mismatch"):
            resolve_nagoya_resource(
                _package_payload(), expected_revision="2026-07-01"
            )

    def test_fetch_writes_validated_versioned_feed_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / REVISION
            client = _FakeClient()
            manifest = fetch_nagoya_gtfs(
                target,
                expected_revision=REVISION,
                client=client,
            )

            self.assertEqual(manifest.revision, REVISION)
            self.assertTrue((target / "stops.txt").is_file())
            self.assertTrue((target / NAGOYA_MANIFEST_FILENAME).is_file())
            self.assertEqual(client.urls[1], SOURCE_URL)

    def test_installed_manifest_revision_mismatch_fails_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_installed_feed(root, revision=REVISION)

            with self.assertRaisesRegex(RuntimeError, "manifest revision mismatch"):
                load_nagoya_dataset(root, expected_revision="2026-07-01")


class NagoyaRouteBackendTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        _write_installed_feed(root)
        self.dataset = load_nagoya_dataset(root, expected_revision=REVISION)
        self.backend = NagoyaRouteBackend(self.dataset, walk_radius_m=100)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _search(self, pref):
        return self.backend.search(
            alat=35.170900,
            alon=136.881500,
            blat=35.170600,
            blon=136.906600,
            pref=pref,
            start_time="09:55",
            date_str="2026-08-21",
        )

    def test_fastest_route_can_transfer_using_only_nagoya_gtfs(self):
        result = self._search("time")
        candidate = result["candidates"][0]

        self.assertEqual(candidate["rides"], 2)
        self.assertEqual(candidate["transfers"], 1)
        self.assertEqual(candidate["arrival_time"], "10:25")
        self.assertEqual(
            [step["title"] for step in candidate["steps"] if step["kind"] == "bus"],
            ["幹1", "幹2"],
        )
        self.assertTrue(
            all(
                step["route_id"].startswith("nagoya_bus:")
                for step in candidate["steps"]
                if step["kind"] == "bus"
            )
        )

    def test_fewest_transfers_prefers_direct_trip(self):
        result = self._search("fewTransfers")
        candidate = result["candidates"][0]

        self.assertEqual(candidate["rides"], 1)
        self.assertEqual(candidate["transfers"], 0)
        self.assertEqual(candidate["arrival_time"], "10:40")
        bus_steps = [step for step in candidate["steps"] if step["kind"] == "bus"]
        self.assertEqual(bus_steps[0]["title"], "直通")

    def test_legacy_cost_value_matches_visible_few_transfer_default(self):
        result = self._search("cost")
        self.assertEqual(result["candidates"][0]["transfers"], 0)

    def test_initial_walk_cannot_cross_the_service_day_boundary(self):
        with self.assertRaisesRegex(RuntimeError, "service-day boundary"):
            self.backend.search(
                alat=35.170200,
                alon=136.881500,
                blat=35.170600,
                blon=136.906600,
                pref="time",
                start_time="23:59",
                date_str="2026-08-21",
            )

    def test_nagoya_runtime_requires_no_odpt_token_or_toei_graph(self):
        app = SimpleNamespace(state=SimpleNamespace())
        root = Path(self.temp_dir.name)
        env = {
            "NAGOYA_GTFS_DIR": str(root),
            "NAGOYA_GTFS_EXPECTED_REVISION": REVISION,
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("ODPT_API_TOKEN", None)
            asyncio.run(setup_nagoya_on_startup(app, "local"))

        self.assertEqual(app.state.loading_status, "ready")
        self.assertEqual(app.state.city_key, "nagoya")
        self.assertFalse(app.state.realtime_bus_supported)
        self.assertFalse(hasattr(app.state, "G"))
        self.assertFalse(hasattr(app.state, "TM"))


if __name__ == "__main__":
    unittest.main()
