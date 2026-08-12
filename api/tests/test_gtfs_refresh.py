import csv
import hashlib
import io
import os
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone

from gtfs_refresh import (
    DownloadResult,
    GtfsDownloadError,
    GtfsRefreshError,
    GtfsValidationError,
    RefreshState,
    advance_api_gtfs_version,
    refresh_gtfs,
)


SOURCE_URL = "https://example.test/ToeiBus-GTFS.zip"


def _csv_text(header, row):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(header)
    writer.writerow(row)
    return output.getvalue()


def _gtfs_zip(extra_marker="v1", missing=None):
    missing = set(missing or [])
    files = {
        "agency.txt": _csv_text(
            ["agency_id", "agency_name", "agency_url", "agency_timezone"],
            ["toei", f"Toei {extra_marker}", "https://example.test", "Asia/Tokyo"],
        ),
        "routes.txt": _csv_text(
            ["route_id", "route_short_name", "route_type"],
            ["070", "上２３", "3"],
        ),
        "trips.txt": _csv_text(
            ["route_id", "service_id", "trip_id"],
            ["070", "61-160", f"trip-{extra_marker}"],
        ),
        "stop_times.txt": _csv_text(
            [
                "trip_id",
                "arrival_time",
                "departure_time",
                "stop_id",
                "stop_sequence",
            ],
            [f"trip-{extra_marker}", "10:00:00", "10:00:00", "stop-1", "1"],
        ),
        "stops.txt": _csv_text(
            ["stop_id", "stop_name", "stop_lat", "stop_lon"],
            ["stop-1", "平井七丁目", "35.0", "139.0"],
        ),
        "calendar.txt": _csv_text(
            [
                "service_id",
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
                "start_date",
                "end_date",
            ],
            ["61-160", "0", "0", "0", "0", "0", "1", "0", "20260101", "20261231"],
        ),
        "calendar_dates.txt": _csv_text(
            ["service_id", "date", "exception_type"],
            ["61-160", "20260812", "1"],
        ),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            if name not in missing:
                archive.writestr(name, content)
    return output.getvalue()


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _state(payload, etag='"old-etag"', last_modified="Mon, 10 Aug 2026 00:00:00 GMT"):
    digest = _sha(payload)
    return RefreshState(
        etag=etag,
        last_modified=last_modified,
        sha256=digest,
        updated_at="2026-08-10T00:00:00Z",
        object_key=f"versions/{digest}.zip",
        source_url=SOURCE_URL,
    )


class _FakeDownloader:
    def __init__(
        self,
        payload=b"",
        status_code=200,
        etag='"new-etag"',
        last_modified="Tue, 11 Aug 2026 00:00:00 GMT",
        error=None,
    ):
        self.payload = payload
        self.status_code = status_code
        self.etag = etag
        self.last_modified = last_modified
        self.error = error
        self.headers = None

    def download(self, url, headers, destination):
        self.headers = dict(headers)
        if self.error:
            raise self.error
        if self.status_code == 304:
            return DownloadResult(status_code=304)
        with open(destination, "wb") as file:
            file.write(self.payload)
        return DownloadResult(
            status_code=self.status_code,
            etag=self.etag,
            last_modified=self.last_modified,
            sha256=_sha(self.payload),
            size=len(self.payload),
        )


class _MemoryStore:
    def __init__(self, state=None, fail_version=False, fail_state=False):
        self.state = state
        self.fail_version = fail_version
        self.fail_state = fail_state
        self.versions = {}
        self.saved_states = []

    def load_state(self):
        return self.state

    def store_version(self, source_path, sha256):
        if self.fail_version:
            raise GtfsRefreshError("S3 version write failed")
        with open(source_path, "rb") as file:
            self.versions[sha256] = file.read()
        return f"versions/{sha256}.zip"

    def save_state(self, state):
        if self.fail_state:
            raise GtfsRefreshError("S3 state write failed")
        self.state = state
        self.saved_states.append(state)


class RefreshGtfsTest(unittest.TestCase):
    def refresh(self, downloader, store):
        return refresh_gtfs(
            downloader=downloader,
            store=store,
            request_url=SOURCE_URL + "?token=hidden",
            source_url=SOURCE_URL,
            now=datetime(2026, 8, 12, 0, 0, tzinfo=timezone.utc),
        )

    def test_initial_download_validates_uploads_and_switches_state(self):
        payload = _gtfs_zip()
        store = _MemoryStore()

        result = self.refresh(_FakeDownloader(payload), store)

        self.assertEqual(result.status, "updated")
        self.assertEqual(store.state.sha256, _sha(payload))
        self.assertEqual(store.state.updated_at, "2026-08-12T00:00:00Z")
        self.assertEqual(store.versions[_sha(payload)], payload)

    def test_existing_etag_is_sent_as_conditional_header(self):
        payload = _gtfs_zip()
        downloader = _FakeDownloader(payload)
        store = _MemoryStore(_state(payload, last_modified=None))

        self.refresh(downloader, store)

        self.assertEqual(downloader.headers, {"If-None-Match": '"old-etag"'})

    def test_existing_last_modified_is_sent_as_conditional_header(self):
        payload = _gtfs_zip()
        downloader = _FakeDownloader(payload)
        store = _MemoryStore(_state(payload, etag=None))

        self.refresh(downloader, store)

        self.assertEqual(
            downloader.headers,
            {"If-Modified-Since": "Mon, 10 Aug 2026 00:00:00 GMT"},
        )

    def test_http_304_does_not_write_s3(self):
        payload = _gtfs_zip()
        original = _state(payload)
        store = _MemoryStore(original)

        result = self.refresh(_FakeDownloader(status_code=304), store)

        self.assertEqual(result.reason, "http_304")
        self.assertIs(store.state, original)
        self.assertEqual(store.versions, {})
        self.assertEqual(store.saved_states, [])

    def test_http_200_with_same_sha_does_not_write_s3(self):
        payload = _gtfs_zip()
        original = _state(payload)
        store = _MemoryStore(original)

        result = self.refresh(_FakeDownloader(payload), store)

        self.assertEqual(result.reason, "same_sha256")
        self.assertIs(store.state, original)
        self.assertEqual(store.versions, {})

    def test_changed_zip_becomes_current(self):
        old_payload = _gtfs_zip("old")
        new_payload = _gtfs_zip("new")
        store = _MemoryStore(_state(old_payload))

        result = self.refresh(_FakeDownloader(new_payload), store)

        self.assertEqual(result.old_sha256, _sha(old_payload))
        self.assertEqual(result.new_sha256, _sha(new_payload))
        self.assertEqual(store.state.sha256, _sha(new_payload))

    def test_corrupt_zip_keeps_old_state(self):
        old_payload = _gtfs_zip("old")
        original = _state(old_payload)
        store = _MemoryStore(original)

        with self.assertRaises(GtfsValidationError):
            self.refresh(_FakeDownloader(b"not a zip"), store)

        self.assertIs(store.state, original)
        self.assertEqual(store.versions, {})

    def test_missing_required_file_keeps_old_state(self):
        old_payload = _gtfs_zip("old")
        original = _state(old_payload)
        store = _MemoryStore(original)

        with self.assertRaisesRegex(GtfsValidationError, "routes.txt"):
            self.refresh(
                _FakeDownloader(_gtfs_zip("broken", missing={"routes.txt"})),
                store,
            )

        self.assertIs(store.state, original)

    def test_calendar_may_be_omitted_when_calendar_dates_is_present(self):
        store = _MemoryStore()
        payload = _gtfs_zip("dates-only", missing={"calendar.txt"})

        result = self.refresh(_FakeDownloader(payload), store)

        self.assertEqual(result.status, "updated")

    def test_missing_both_service_calendar_files_is_rejected(self):
        store = _MemoryStore()
        payload = _gtfs_zip(
            "no-calendar",
            missing={"calendar.txt", "calendar_dates.txt"},
        )

        with self.assertRaisesRegex(
            GtfsValidationError,
            "calendar.txt or calendar_dates.txt",
        ):
            self.refresh(_FakeDownloader(payload), store)

        self.assertIsNone(store.state)

    def test_download_failure_keeps_old_state(self):
        payload = _gtfs_zip()
        original = _state(payload)
        store = _MemoryStore(original)

        with self.assertRaises(GtfsDownloadError):
            self.refresh(
                _FakeDownloader(error=GtfsDownloadError("network down")),
                store,
            )

        self.assertIs(store.state, original)

    def test_version_upload_failure_keeps_old_state(self):
        old_payload = _gtfs_zip("old")
        original = _state(old_payload)
        store = _MemoryStore(original, fail_version=True)

        with self.assertRaises(GtfsRefreshError):
            self.refresh(_FakeDownloader(_gtfs_zip("new")), store)

        self.assertIs(store.state, original)
        self.assertEqual(store.saved_states, [])

    def test_state_write_failure_keeps_old_state_authoritative(self):
        old_payload = _gtfs_zip("old")
        original = _state(old_payload)
        store = _MemoryStore(original, fail_state=True)

        with self.assertRaises(GtfsRefreshError):
            self.refresh(_FakeDownloader(_gtfs_zip("new")), store)

        self.assertIs(store.state, original)
        self.assertEqual(store.saved_states, [])
        self.assertEqual(len(store.versions), 1)


class _FakeLambdaClient:
    def __init__(self, variables):
        self.variables = dict(variables)
        self.updates = []

    def get_function_configuration(self, FunctionName):
        return {"Environment": {"Variables": dict(self.variables)}}

    def update_function_configuration(self, FunctionName, Environment):
        self.variables = dict(Environment["Variables"])
        self.updates.append((FunctionName, dict(self.variables)))


class AdvanceApiGtfsVersionTest(unittest.TestCase):
    def test_updates_only_the_data_version_and_preserves_existing_environment(self):
        client = _FakeLambdaClient({"S3_BUCKET_NAME": "toeigo", "OTHER": "keep"})

        changed = advance_api_gtfs_version(
            "toeigo-api",
            "a" * 64,
            lambda_client=client,
        )

        self.assertTrue(changed)
        self.assertEqual(client.variables["GTFS_DATA_VERSION"], "a" * 64)
        self.assertEqual(client.variables["OTHER"], "keep")
        self.assertEqual(len(client.updates), 1)

    def test_does_not_update_when_api_already_has_the_active_version(self):
        client = _FakeLambdaClient({"GTFS_DATA_VERSION": "a" * 64})

        changed = advance_api_gtfs_version(
            "toeigo-api",
            "a" * 64,
            lambda_client=client,
        )

        self.assertFalse(changed)
        self.assertEqual(client.updates, [])


if __name__ == "__main__":
    unittest.main()
