import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from unittest.mock import patch

from gtfs_refresh import DownloadResult, GtfsRefreshError, S3GtfsStore
from gtfs_refresh_compiled import refresh_gtfs_with_compiled_state
from gtfs_state import CompiledGtfsStateError


SOURCE_URL = "https://example.test/ToeiBus-GTFS.zip"
STATE_KEY = "gtfs/toei/state.json"
VERSION_PREFIX = "gtfs/toei/versions"


class _NotFound(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "404"}}
        super().__init__("not found")


class _FakeS3:
    def __init__(self):
        self.objects = {}
        self.metadata = {}
        self.put_order = []

    @staticmethod
    def _bytes(body):
        if isinstance(body, bytes):
            return body
        return body.read()

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _NotFound()
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _NotFound()
        return {"Metadata": dict(self.metadata.get(Key, {}))}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Key] = self._bytes(Body)
        self.metadata[Key] = dict(kwargs.get("Metadata", {}))
        self.put_order.append(Key)
        return {}

    def download_file(self, bucket, key, destination):
        if key not in self.objects:
            raise _NotFound()
        with open(destination, "wb") as file:
            file.write(self.objects[key])


class _FakeDownloader:
    def __init__(self, payload=b"", status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.calls = 0
        self.headers = None

    def download(self, url, headers, destination):
        self.calls += 1
        self.headers = dict(headers)
        if self.status_code == 304:
            return DownloadResult(status_code=304)
        with open(destination, "wb") as file:
            file.write(self.payload)
        return DownloadResult(
            status_code=self.status_code,
            etag='"etag"',
            last_modified="Tue, 01 Sep 2026 00:00:00 GMT",
            sha256=hashlib.sha256(self.payload).hexdigest(),
            size=len(self.payload),
        )


def _gtfs_zip(marker="v1"):
    files = {
        "agency.txt": (
            "agency_id,agency_name,agency_url,agency_timezone\n"
            "toei,Toei,https://example.test,Asia/Tokyo\n"
        ),
        "routes.txt": (
            "route_id,route_short_name,route_type\n"
            "R1,上23,3\n"
        ),
        "trips.txt": (
            "route_id,service_id,trip_id\n"
            f"R1,S1,T-{marker}\n"
        ),
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            f"T-{marker},10:00:00,10:00:00,A,1\n"
            f"T-{marker},10:20:00,10:20:00,B,2\n"
        ),
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "A,平井七丁目,35.7000,139.8500\n"
            "B,浅草雷門,35.7100,139.8600\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "S1,1,1,1,1,1,0,0,20260101,20261231\n"
        ),
        "calendar_dates.txt": (
            "service_id,date,exception_type\n"
            "S1,20260921,1\n"
        ),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def _store(fake_s3):
    return S3GtfsStore(
        bucket_name="bucket",
        state_key=STATE_KEY,
        version_prefix=VERSION_PREFIX,
        s3_client=fake_s3,
    )


def _raw_state(payload, object_key):
    return {
        "etag": '"old"',
        "last_modified": "Mon, 31 Aug 2026 00:00:00 GMT",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "updated_at": "2026-08-31T00:00:00Z",
        "object_key": object_key,
        "source_url": SOURCE_URL,
    }


class CompiledRefreshTest(unittest.TestCase):
    def test_initial_refresh_publishes_compiled_artifact_before_state_switch(self):
        payload = _gtfs_zip()
        fake_s3 = _FakeS3()
        result = refresh_gtfs_with_compiled_state(
            downloader=_FakeDownloader(payload),
            store=_store(fake_s3),
            request_url=SOURCE_URL,
            source_url=SOURCE_URL,
            now=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(result.status, "updated")
        state = json.loads(fake_s3.objects[STATE_KEY])
        self.assertEqual(state["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(state["compiled_state_schema_version"], 1)
        self.assertIn(state["compiled_state_key"], fake_s3.objects)
        self.assertEqual(
            fake_s3.metadata[state["compiled_state_key"]]["sha256"],
            state["compiled_state_sha256"],
        )
        self.assertLess(
            fake_s3.put_order.index(state["compiled_state_key"]),
            fake_s3.put_order.index(STATE_KEY),
        )

    def test_compilation_failure_never_switches_authoritative_state(self):
        payload = _gtfs_zip()
        fake_s3 = _FakeS3()
        with patch(
            "gtfs_refresh_compiled.build_compiled_state_from_zip",
            side_effect=CompiledGtfsStateError("compile failed"),
        ):
            with self.assertRaisesRegex(CompiledGtfsStateError, "compile failed"):
                refresh_gtfs_with_compiled_state(
                    downloader=_FakeDownloader(payload),
                    store=_store(fake_s3),
                    request_url=SOURCE_URL,
                    source_url=SOURCE_URL,
                )

        self.assertNotIn(STATE_KEY, fake_s3.objects)
        self.assertTrue(
            any(key.startswith(VERSION_PREFIX + "/") for key in fake_s3.objects)
        )

    def test_existing_raw_state_is_backfilled_without_redownloading_odpt(self):
        payload = _gtfs_zip()
        digest = hashlib.sha256(payload).hexdigest()
        object_key = f"{VERSION_PREFIX}/{digest}.zip"
        fake_s3 = _FakeS3()
        fake_s3.objects[object_key] = payload
        fake_s3.objects[STATE_KEY] = (
            json.dumps(_raw_state(payload, object_key)) + "\n"
        ).encode("utf-8")
        downloader = _FakeDownloader(status_code=500)

        result = refresh_gtfs_with_compiled_state(
            downloader=downloader,
            store=_store(fake_s3),
            request_url=SOURCE_URL,
            source_url=SOURCE_URL,
        )

        self.assertEqual(result.reason, "compiled_state_backfill")
        self.assertEqual(downloader.calls, 0)
        state = json.loads(fake_s3.objects[STATE_KEY])
        self.assertEqual(state["sha256"], digest)
        self.assertIn(state["compiled_state_key"], fake_s3.objects)

    def test_304_with_compiled_pointer_keeps_state_unchanged(self):
        payload = _gtfs_zip()
        fake_s3 = _FakeS3()
        first = refresh_gtfs_with_compiled_state(
            downloader=_FakeDownloader(payload),
            store=_store(fake_s3),
            request_url=SOURCE_URL,
            source_url=SOURCE_URL,
        )
        self.assertEqual(first.status, "updated")
        before = fake_s3.objects[STATE_KEY]
        before_puts = list(fake_s3.put_order)
        downloader = _FakeDownloader(status_code=304)

        second = refresh_gtfs_with_compiled_state(
            downloader=downloader,
            store=_store(fake_s3),
            request_url=SOURCE_URL,
            source_url=SOURCE_URL,
        )

        self.assertEqual(second.reason, "http_304")
        self.assertEqual(fake_s3.objects[STATE_KEY], before)
        self.assertEqual(fake_s3.put_order, before_puts)
        self.assertEqual(downloader.calls, 1)


if __name__ == "__main__":
    unittest.main()
