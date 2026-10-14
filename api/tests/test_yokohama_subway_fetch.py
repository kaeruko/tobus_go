"""Mocked ODPT ZIP download tests; never contact real ODPT or store secrets."""
from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import httpx

from test_yokohama_subway import _fixture
from yokohama_subway import (
    SOURCE_URL, fetch_yokohama_subway_gtfs, load_yokohama_subway_dataset,
)

DAY = "2026-10-14"
KEY = "super-secret-test-key"


def _archive(root: Path, *, prefix: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(root.glob("*.txt")):
            archive.writestr(prefix + p.name, p.read_bytes())
    return buffer.getvalue()


def _client(data: bytes, *, status: int = 200):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, content=data)

    return httpx.Client(transport=httpx.MockTransport(respond)), requests


class SubwayDownloadTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / "input"
        self.source.mkdir()
        _fixture(self.source)
        self.archive = _archive(self.source)

    def _fetch(self, client, *, target_name="output", **kw):
        return fetch_yokohama_subway_gtfs(
            self.root / target_name,
            expected_service_date=DAY,
            consumer_key=KEY,
            client=client,
            **kw,
        )

    def test_download_validated_atomically_without_logging_key(self):
        client, requests = _client(self.archive)
        with client:
            report = self._fetch(client)
        self.assertEqual(report["route_count"], 1)
        self.assertEqual(report["trip_count"], 1)
        self.assertEqual(report["feed_id"], "yokohama_subway")
        self.assertNotIn(KEY, repr(report))
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.host, "api.odpt.org")
        self.assertEqual(requests[0].url.params["date"], "current")
        self.assertEqual(requests[0].url.params["acl:consumerKey"], KEY)
        self.assertTrue((self.root / "output" / "yokohama_subway_gtfs_manifest.json").exists())
        dataset = load_yokohama_subway_dataset(
            self.root / "output", expected_service_date=DAY,
        )
        self.assertEqual(dataset.metadata.source_uri, SOURCE_URL)
        self.assertFalse(list(self.root.glob(".yokohama_subway_*")))

    def test_nested_gtfs_path_can_be_unpacked_by_basename(self):
        client, _ = _client(_archive(self.source, prefix="gtfs/"))
        with client:
            self._fetch(client)
        self.assertTrue((self.root / "output" / "trips.txt").exists())

    def test_unauthorized_is_sanitized_and_does_not_create_target(self):
        client, _ = _client(b'{"error":"key secret"}', status=401)
        with client, self.assertRaisesRegex(RuntimeError, "HTTP 401") as captured:
            self._fetch(client)
        self.assertNotIn(KEY, str(captured.exception))
        self.assertNotIn("secret", str(captured.exception))
        self.assertFalse((self.root / "output").exists())

    def test_redirection_is_not_followed_with_api_key(self):
        client, requests = _client(b"", status=302)
        with client, self.assertRaisesRegex(RuntimeError, "HTTP 302"):
            self._fetch(client)
        self.assertEqual(len(requests), 1)
        self.assertFalse((self.root / "output").exists())

    def test_corrupted_zip_and_nonmatching_feed_fail_without_partial_output(self):
        client, _ = _client(b"not zip data")
        with client, self.assertRaisesRegex(ValueError, "invalid ZIP archive"):
            self._fetch(client)
        self.assertFalse((self.root / "output").exists())
        feed_info = self.source / "feed_info.txt"
        feed_info.write_text(feed_info.read_text().replace("20251226", "20251101"))
        client2, _ = _client(_archive(self.source))
        with client2, self.assertRaisesRegex(ValueError, "feed_info version mismatch"):
            self._fetch(client2)
        self.assertFalse((self.root / "output").exists())

    def test_zip_traversal_duplicate_or_unexpected_file_rejected(self):
        for malicious_name in ("../trips.txt", "A/../../trips.txt", "evil.bin"):
            with self.subTest(member=malicious_name):
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as archive:
                    archive.writestr(malicious_name, b"ignore")
                client, _ = _client(buffer.getvalue())
                with client, self.assertRaisesRegex(ValueError, "unsafe path|non-GTFS"):
                    self._fetch(client)
                self.assertFalse((self.root / "output").exists())

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("A/trips.txt", b"one")
            archive.writestr("B/trips.txt", b"two")
        client, _ = _client(buffer.getvalue())
        with client, self.assertRaisesRegex(ValueError, "duplicate text basename"):
            self._fetch(client)

    def test_refuses_overwrite_invalid_key_or_parent(self):
        (self.root / "output").mkdir()
        client, requests = _client(self.archive)
        with client, self.assertRaises(FileExistsError):
            self._fetch(client)
        self.assertFalse(requests)
        with self.assertRaisesRegex(ValueError, "consumer key"):
            fetch_yokohama_subway_gtfs(
                self.root / "new", expected_service_date=DAY,
                consumer_key="",
            )
        with self.assertRaises(FileNotFoundError):
            fetch_yokohama_subway_gtfs(
                self.root / "missing_parent" / "new",
                expected_service_date=DAY,
                consumer_key=KEY,
            )


if __name__ == "__main__":
    unittest.main()
