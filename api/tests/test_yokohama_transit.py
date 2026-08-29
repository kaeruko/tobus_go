import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata
from yokohama_transit import (
    YOKOHAMA_BUS_APPROVED_FEED_VERSION,
    YOKOHAMA_BUS_APPROVED_REVISION,
    YOKOHAMA_BUS_APPROVED_VALID_FROM,
    YOKOHAMA_BUS_APPROVED_VALID_UNTIL,
    YOKOHAMA_BUS_FEED_ID,
    YOKOHAMA_BUS_MANIFEST_FILENAME,
    YOKOHAMA_BUS_RESOURCE_ID,
    YOKOHAMA_BUS_STATIC_URL,
    YokohamaBusRouteBackend,
    fetch_yokohama_bus_gtfs,
    load_yokohama_bus_dataset,
)

SERVICE_DATE = "2026-08-29"


def _files(*, stop_b_lat: str = "35.4650", stop_b_lon: str = "139.6220", feed_version: str = YOKOHAMA_BUS_APPROVED_FEED_VERSION):
    return {
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "A,横浜駅前,35.4660,139.6225\n"
            f"B,桜木町駅前,{stop_b_lat},{stop_b_lon}\n"
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
            f"{feed_version}\n"
        ),
    }


def _write_feed(root: Path, **kwargs):
    for name, content in _files(**kwargs).items():
        (root / name).write_text(content, encoding="utf-8")


def _write_manifest(root: Path, *, service_date: str = SERVICE_DATE):
    (root / YOKOHAMA_BUS_MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "source_url": YOKOHAMA_BUS_STATIC_URL,
                "resource_id": YOKOHAMA_BUS_RESOURCE_ID,
                "revision": YOKOHAMA_BUS_APPROVED_REVISION,
                "feed_version": YOKOHAMA_BUS_APPROVED_FEED_VERSION,
                "validated_service_date": service_date,
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


def _zip_bytes(**kwargs):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in _files(**kwargs).items():
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


class YokohamaBusStaticGtfsTest(unittest.TestCase):
    def test_existing_gtfs_adapter_loads_yokohama_bus_without_city_transform(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root)
            dataset = GtfsTransitAdapter.load(
                root,
                metadata=FeedMetadata(
                    feed_id=YOKOHAMA_BUS_FEED_ID,
                    source_type="gtfs-jp",
                    source_uri=YOKOHAMA_BUS_STATIC_URL,
                    version=YOKOHAMA_BUS_APPROVED_FEED_VERSION,
                    fetched_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
                ),
            )

            self.assertIn("yokohama_bus:A", dataset.stops)
            self.assertIn("yokohama_bus:R1", dataset.routes)
            self.assertIn("yokohama_bus:T1", dataset.trips)
            backend = YokohamaBusRouteBackend(dataset, walk_radius_m=100)
            result = backend.search(
                alat=35.4660,
                alon=139.6225,
                blat=35.4650,
                blon=139.6220,
                pref="time",
                start_time="09:55",
                date_str=SERVICE_DATE,
            )
            self.assertEqual(result["candidates"][0]["arrival_time"], "10:15")

    def test_fetch_records_explicit_approved_resource_and_sha256(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bus" / "20260727"
            client = _FakeClient(_zip_bytes())
            manifest = fetch_yokohama_bus_gtfs(
                target,
                expected_service_date=SERVICE_DATE,
                consumer_key="test-token",
                client=client,
            )

            self.assertEqual(manifest.resource_id, YOKOHAMA_BUS_RESOURCE_ID)
            self.assertEqual(manifest.revision, YOKOHAMA_BUS_APPROVED_REVISION)
            self.assertEqual(manifest.feed_version, YOKOHAMA_BUS_APPROVED_FEED_VERSION)
            self.assertEqual(manifest.valid_from, YOKOHAMA_BUS_APPROVED_VALID_FROM)
            self.assertEqual(manifest.valid_until, YOKOHAMA_BUS_APPROVED_VALID_UNTIL)
            self.assertEqual(len(manifest.sha256), 64)
            self.assertTrue((target / "stops.txt").is_file())
            self.assertTrue((target / YOKOHAMA_BUS_MANIFEST_FILENAME).is_file())
            self.assertEqual(
                client.calls,
                [
                    (
                        YOKOHAMA_BUS_STATIC_URL,
                        {
                            "date": "current",
                            "acl:consumerKey": "test-token",
                        },
                    )
                ],
            )

    def test_current_endpoint_changing_revision_fails_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bus" / "changed"
            client = _FakeClient(_zip_bytes(feed_version="v3.0_20260901"))
            with self.assertRaisesRegex(RuntimeError, "resource changed"):
                fetch_yokohama_bus_gtfs(
                    target,
                    expected_service_date=SERVICE_DATE,
                    consumer_key="test-token",
                    client=client,
                )
            self.assertFalse(target.exists())

    def test_zero_zero_stop_coordinates_fail_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bus" / "zero"
            client = _FakeClient(_zip_bytes(stop_b_lat="0", stop_b_lon="0"))
            with self.assertRaisesRegex(ValueError, "must not be 0,0"):
                fetch_yokohama_bus_gtfs(
                    target,
                    expected_service_date=SERVICE_DATE,
                    consumer_key="test-token",
                    client=client,
                )
            self.assertFalse(target.exists())

    def test_non_finite_stop_coordinates_fail_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bus" / "nan"
            client = _FakeClient(_zip_bytes(stop_b_lat="NaN"))
            with self.assertRaisesRegex(ValueError, "non-finite coordinates"):
                fetch_yokohama_bus_gtfs(
                    target,
                    expected_service_date=SERVICE_DATE,
                    consumer_key="test-token",
                    client=client,
                )
            self.assertFalse(target.exists())

    def test_out_of_range_stop_coordinates_fail_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bus" / "range"
            client = _FakeClient(_zip_bytes(stop_b_lat="91"))
            with self.assertRaisesRegex(ValueError, "latitude is out of range"):
                fetch_yokohama_bus_gtfs(
                    target,
                    expected_service_date=SERVICE_DATE,
                    consumer_key="test-token",
                    client=client,
                )
            self.assertFalse(target.exists())

    def test_installed_service_date_mismatch_fails_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_feed(root)
            _write_manifest(root)
            with self.assertRaisesRegex(RuntimeError, "expected service date mismatch"):
                load_yokohama_bus_dataset(
                    root,
                    expected_service_date="2026-08-30",
                )

    def test_service_date_outside_approved_resource_fails_before_download(self):
        client = _FakeClient(_zip_bytes())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bus" / "stale"
            with self.assertRaisesRegex(RuntimeError, "outside the approved GTFS resource"):
                fetch_yokohama_bus_gtfs(
                    target,
                    expected_service_date="2027-07-27",
                    consumer_key="test-token",
                    client=client,
                )
            self.assertEqual(client.calls, [])
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
