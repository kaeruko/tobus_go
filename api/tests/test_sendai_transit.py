import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from gtfs_route_backend import GtfsRouteBackend
from sendai_transit import (
    SENDAI_FEED_ID,
    SENDAI_MANIFEST_FILENAME,
    SENDAI_STATIC_URL,
    SendaiRouteBackend,
    fetch_sendai_gtfs,
    load_sendai_dataset,
)
from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata


SERVICE_DATE = "2026-08-21"


def _files():
    return {
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "A,仙台駅前,38.2600,140.8820\n"
            "B,青葉通一番町,38.2600,140.8720\n"
            "C,交通局大学病院前,38.2710,140.8610\n"
        ),
        "routes.txt": (
            "route_id,route_short_name,route_long_name,route_type\n"
            "R1,10,仙台駅前から青葉通一番町,3\n"
            "R2,20,青葉通一番町から交通局大学病院前,3\n"
            "R3,30,仙台駅前から交通局大学病院前,3\n"
        ),
        "trips.txt": (
            "route_id,service_id,trip_id,trip_headsign,direction_id\n"
            "R1,WK,T1,青葉通一番町,0\n"
            "R2,WK,T2,交通局大学病院前,0\n"
            "R3,WK,T3,交通局大学病院前,0\n"
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


def _write_feed(root: Path):
    for name, content in _files().items():
        (root / name).write_text(content, encoding="utf-8")


def _write_manifest(root: Path, *, service_date: str = SERVICE_DATE):
    (root / SENDAI_MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "source_url": SENDAI_STATIC_URL,
                "validated_service_date": service_date,
                "fetched_at": "2026-08-21T00:00:00+00:00",
                "sha256": "c" * 64,
                "valid_from": "2026-01-01",
                "valid_until": "2026-12-31",
            }
        ),
        encoding="utf-8",
    )


def _zip_bytes():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in _files().items():
            archive.writestr(name, content)
    return output.getvalue()


class _FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class _FakeClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        return _FakeResponse(self.content)


class SendaiStaticGtfsTest(unittest.TestCase):
    def test_existing_gtfs_adapter_loads_sendai_without_city_transform(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root)
            dataset = GtfsTransitAdapter.load(
                root,
                metadata=FeedMetadata(
                    feed_id=SENDAI_FEED_ID,
                    source_type="gtfs-jp",
                    source_uri=SENDAI_STATIC_URL,
                    version=f"service-date:{SERVICE_DATE}",
                    fetched_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
                ),
            )

            self.assertIn("sendai_bus:A", dataset.stops)
            self.assertIn("sendai_bus:R1", dataset.routes)
            self.assertIn("sendai_bus:T1", dataset.trips)
            backend = GtfsRouteBackend(dataset, walk_radius_m=100)
            result = backend.search(
                alat=38.2600,
                alon=140.8820,
                blat=38.2710,
                blon=140.8610,
                pref="time",
                start_time="09:55",
                date_str=SERVICE_DATE,
            )
            self.assertEqual(result["candidates"][0]["arrival_time"], "10:25")

    def test_sendai_backend_uses_shared_engine_for_fewest_transfers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root)
            _write_manifest(root)
            dataset = load_sendai_dataset(
                root,
                expected_service_date=SERVICE_DATE,
            )
            backend = SendaiRouteBackend(dataset, walk_radius_m=100)
            result = backend.search(
                alat=38.2600,
                alon=140.8820,
                blat=38.2710,
                blon=140.8610,
                pref="fewTransfers",
                start_time="09:55",
                date_str=SERVICE_DATE,
            )

            candidate = result["candidates"][0]
            self.assertEqual(candidate["rides"], 1)
            self.assertEqual(candidate["transfers"], 0)
            self.assertEqual(candidate["arrival_time"], "10:40")
            bus_steps = [step for step in candidate["steps"] if step["kind"] == "bus"]
            self.assertEqual(bus_steps[0]["route_id"], "sendai_bus:R3")
            self.assertEqual(bus_steps[0]["trip_id"], "sendai_bus:T3")

    def test_installed_service_date_mismatch_fails_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root)
            _write_manifest(root)
            with self.assertRaisesRegex(RuntimeError, "expected service date mismatch"):
                load_sendai_dataset(
                    root,
                    expected_service_date="2026-08-22",
                )

    def test_fetch_uses_only_configured_odpt_static_url_and_validates_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sendai"
            client = _FakeClient(_zip_bytes())
            manifest = fetch_sendai_gtfs(
                target,
                expected_service_date=SERVICE_DATE,
                consumer_key="test-token",
                client=client,
            )

            self.assertEqual(manifest.validated_service_date, SERVICE_DATE)
            self.assertTrue((target / "stops.txt").is_file())
            self.assertTrue((target / SENDAI_MANIFEST_FILENAME).is_file())
            self.assertEqual(
                client.calls,
                [(SENDAI_STATIC_URL, {"acl:consumerKey": "test-token"})],
            )


if __name__ == "__main__":
    unittest.main()
