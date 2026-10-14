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

    def test_download_counts_non_timepoint_omissions_without_estimating(self):
        p = self.source / "stop_times.txt"
        p.write_text(
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence,timepoint\n"
            "T1,09:55:00,09:55:00,A,1,1\n"
            "T1,,,A,2,\n"
            "T1,10:10:00,10:10:00,B,3,1\n",
            encoding="utf-8",
        )
        client, _ = _client(_archive(self.source))
        with client:
            report = self._fetch(client)
        self.assertEqual(report["source_stop_time_rows"], 3)
        self.assertEqual(report["searchable_stop_time_rows"], 2)
        self.assertEqual(report["excluded_untimed_intermediate_rows"], 1)
        self.assertEqual(report["excluded_untimed_rows_missing_timepoint"], 1)
        self.assertTrue((self.root / "output" / "stop_times.txt").exists())
        self.assertIn(
            "T1,,,A,2,",
            (self.root / "output" / "stop_times.txt").read_text(encoding="utf-8"),
        )

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

    def test_client_cannot_override_no_redirect_policy(self):
        seen = []

        def on_request(req: httpx.Request) -> httpx.Response:
            seen.append(req.url.host)
            if req.url.host == "api.odpt.org":
                return httpx.Response(
                    302, headers={"Location": "https://evil.example/capture"},
                )
            return httpx.Response(200, content=b"should never get here")

        with httpx.Client(
            transport=httpx.MockTransport(on_request),
            follow_redirects=True,
        ) as client, self.assertRaisesRegex(ValueError, "redirect host not approved"):
            self._fetch(client)
        self.assertEqual(seen, ["api.odpt.org"])
        self.assertFalse((self.root / "output").exists())

    def test_allowlisted_https_cdn_redirect_strips_odpt_credentials(self):
        requests = []

        def respond(req: httpx.Request) -> httpx.Response:
            requests.append(req)
            if req.url.host == "api.odpt.org":
                return httpx.Response(
                    302,
                    headers={"Location": "https://storage.googleapis.com/"
                                         "yokohama-odpt/test.zip?signature=public"},
                )
            return httpx.Response(200, content=self.archive)

        with httpx.Client(
            transport=httpx.MockTransport(respond),
            follow_redirects=True,
            headers={"Authorization": f"Bearer {KEY}"},
            params={"inherited": KEY},
        ) as client:
            report = self._fetch(client)
        self.assertEqual(report["trip_count"], 1)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1].url.host, "storage.googleapis.com")
        self.assertNotIn(KEY, str(requests[1].url))
        self.assertNotIn("acl:consumerKey", str(requests[1].url))
        self.assertNotIn("authorization", {x.lower() for x in requests[1].headers})
        self.assertNotIn("inherited", str(requests[1].url))
        self.assertFalse(list(self.root.glob(".yokohama_subway_*")))

    def test_s3_redirect_with_absolute_url_and_no_location_secret(self):
        requests = []

        def respond(req: httpx.Request) -> httpx.Response:
            requests.append(req)
            if len(requests) == 1:
                return httpx.Response(
                    302, headers={"Location":
                        "https://odpt-feed.s3.ap-northeast-1.amazonaws.com/train.zip"},
                )
            return httpx.Response(200, content=self.archive)

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            self._fetch(client)
        self.assertEqual(len(requests), 2)

    def test_odpt_azure_blob_redirect_succeeds_without_forwarding_credentials(self):
        requests = []
        azure_location = (
            "https://dataodpt.blob.core.windows.net/yokohama/Train.zip"
            "?sv=2026-01-01&sig=synthetic-signed-access"
        )

        def respond(req: httpx.Request) -> httpx.Response:
            requests.append(req)
            if len(requests) == 1:
                return httpx.Response(302, headers={"Location": azure_location})
            return httpx.Response(200, content=self.archive)

        with httpx.Client(
            transport=httpx.MockTransport(respond),
            follow_redirects=True,
            headers={"Authorization": f"Bearer {KEY}", "Cookie": f"session={KEY}"},
            params={"client_default": KEY},
        ) as client:
            result = self._fetch(client)
        self.assertEqual(result["feed_id"], "yokohama_subway")
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1].url.host, "dataodpt.blob.core.windows.net")
        self.assertEqual(str(requests[1].url), azure_location)
        self.assertNotIn(KEY, str(requests[1].url))
        self.assertNotIn(KEY, str(requests[1].headers))
        self.assertNotIn("authorization", {x.lower() for x in requests[1].headers})
        self.assertNotIn("cookie", {x.lower() for x in requests[1].headers})
        self.assertNotIn("client_default", requests[1].url.params)
        self.assertNotIn("acl:consumerKey", requests[1].url.params)
        self.assertFalse(list(self.root.glob(".yokohama_subway_*")))

    def test_azure_host_allowlist_is_exact_not_wildcard(self):
        malicious = (
            "https://dataodpt.blob.core.windows.net.evil.example/Train.zip",
            "https://notdataodpt.blob.core.windows.net/Train.zip",
            "https://dataodpt-blob.core.windows.net/Train.zip",
            "http://dataodpt.blob.core.windows.net/Train.zip",
            "https://dataodpt.blob.core.windows.net:444/Train.zip",
            "https://dataodpt.blob.core.windows.net/Train.zip?acl%3AconsumerKey=" + KEY,
        )
        for location in malicious:
            with self.subTest(location="redacted"):
                requests = []
                def respond(req: httpx.Request) -> httpx.Response:
                    requests.append(req)
                    return httpx.Response(302, headers={"Location": location})
                with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                    with self.assertRaisesRegex(ValueError, "redirect"):
                        self._fetch(client)
                self.assertEqual(len(requests), 1)
                self.assertFalse((self.root / "output").exists())

    def test_redirect_cannot_leak_key_or_change_to_http_or_untrusted_host(self):
        for location in (
            "https://evil.example/train.zip",
            "http://storage.googleapis.com/unsafe.zip",
            "https://storage.googleapis.com/train.zip?acl%3AconsumerKey=" + KEY,
            "https://storage.googleapis.com/train.zip?key=" + KEY,
            "https://storage.googleapis.com:8443/train.zip",
        ):
            with self.subTest(redirect="redacted"):
                count = []
                def respond(req):
                    count.append(req)
                    return httpx.Response(302, headers={"Location": location})
                with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                    with self.assertRaisesRegex(ValueError, "redirect"):
                        self._fetch(client)
                self.assertEqual(len(count), 1)
                self.assertFalse((self.root / "output").exists())

    def test_redirect_loop_fails_without_partial_output(self):
        responses = []
        def respond(req):
            responses.append(req)
            return httpx.Response(
                302, headers={"Location": "https://storage.googleapis.com/loop.zip"}
            )
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaisesRegex(RuntimeError, "safe redirect limit"):
                self._fetch(client)
        self.assertEqual(len(responses), 4)
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
