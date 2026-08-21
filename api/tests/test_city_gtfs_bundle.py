from __future__ import annotations

import hashlib
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.services.city_gtfs_bundle import materialize_city_gtfs_bundle


class FakeS3:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls: list[tuple[str, str, str]] = []

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        self.calls.append((bucket, key, filename))
        Path(filename).write_bytes(self.payload)


def make_bundle(*, manifest: str = "nagoya_gtfs_manifest.json", unsafe: bool = False) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("stops.txt", "stop_id,stop_name,stop_lat,stop_lon\nS1,One,35,139\n")
        archive.writestr("routes.txt", "route_id,route_type\nR1,3\n")
        archive.writestr("trips.txt", "route_id,service_id,trip_id\nR1,WK,T1\n")
        archive.writestr(
            "stop_times.txt",
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,10:00:00,10:00:00,S1,1\n",
        )
        archive.writestr(
            "calendar.txt",
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "WK,1,1,1,1,1,0,0,20260101,20261231\n",
        )
        archive.writestr(manifest, "{}\n")
        if unsafe:
            archive.writestr("../escape.txt", "nope")
    return stream.getvalue()


class CityGtfsBundleTests(unittest.TestCase):
    def test_materializes_exact_configured_bundle(self) -> None:
        payload = make_bundle()
        sha256 = hashlib.sha256(payload).hexdigest()
        env = {
            "NAGOYA_GTFS_BUNDLE_S3_BUCKET": "nagoya-bucket",
            "NAGOYA_GTFS_BUNDLE_S3_KEY": "gtfs/nagoya/release.zip",
            "NAGOYA_GTFS_BUNDLE_SHA256": sha256,
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, env, clear=True
        ):
            target = Path(temp_dir) / "nagoya"
            s3 = FakeS3(payload)
            result = materialize_city_gtfs_bundle(
                city="nagoya",
                target_dir=target,
                manifest_filename="nagoya_gtfs_manifest.json",
                s3_client=s3,
            )

            self.assertEqual(result, target)
            self.assertTrue((target / "routes.txt").is_file())
            self.assertTrue((target / "nagoya_gtfs_manifest.json").is_file())
            self.assertEqual(len(s3.calls), 1)
            self.assertEqual(s3.calls[0][0:2], ("nagoya-bucket", "gtfs/nagoya/release.zip"))

    def test_sha_mismatch_does_not_publish_target(self) -> None:
        payload = make_bundle()
        env = {
            "NAGOYA_GTFS_BUNDLE_S3_BUCKET": "nagoya-bucket",
            "NAGOYA_GTFS_BUNDLE_S3_KEY": "gtfs/nagoya/release.zip",
            "NAGOYA_GTFS_BUNDLE_SHA256": "0" * 64,
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, env, clear=True
        ):
            target = Path(temp_dir) / "nagoya"
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                materialize_city_gtfs_bundle(
                    city="nagoya",
                    target_dir=target,
                    manifest_filename="nagoya_gtfs_manifest.json",
                    s3_client=FakeS3(payload),
                )
            self.assertFalse(target.exists())

    def test_unsafe_zip_path_does_not_publish_target(self) -> None:
        payload = make_bundle(unsafe=True)
        env = {
            "NAGOYA_GTFS_BUNDLE_S3_BUCKET": "nagoya-bucket",
            "NAGOYA_GTFS_BUNDLE_S3_KEY": "gtfs/nagoya/release.zip",
            "NAGOYA_GTFS_BUNDLE_SHA256": hashlib.sha256(payload).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, env, clear=True
        ):
            target = Path(temp_dir) / "nagoya"
            with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
                materialize_city_gtfs_bundle(
                    city="nagoya",
                    target_dir=target,
                    manifest_filename="nagoya_gtfs_manifest.json",
                    s3_client=FakeS3(payload),
                )
            self.assertFalse(target.exists())

    def test_sendai_uses_sendai_specific_configuration(self) -> None:
        payload = make_bundle(manifest="sendai_gtfs_manifest.json")
        env = {
            "SENDAI_GTFS_BUNDLE_S3_BUCKET": "sendai-bucket",
            "SENDAI_GTFS_BUNDLE_S3_KEY": "gtfs/sendai/release.zip",
            "SENDAI_GTFS_BUNDLE_SHA256": hashlib.sha256(payload).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, env, clear=True
        ):
            target = Path(temp_dir) / "sendai"
            s3 = FakeS3(payload)
            materialize_city_gtfs_bundle(
                city="sendai",
                target_dir=target,
                manifest_filename="sendai_gtfs_manifest.json",
                s3_client=s3,
            )
            self.assertEqual(s3.calls[0][0:2], ("sendai-bucket", "gtfs/sendai/release.zip"))

    def test_missing_configuration_fails_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {}, clear=True
        ):
            target = Path(temp_dir) / "nagoya"
            s3 = FakeS3(make_bundle())
            with self.assertRaisesRegex(RuntimeError, "NAGOYA_GTFS_BUNDLE_S3_BUCKET"):
                materialize_city_gtfs_bundle(
                    city="nagoya",
                    target_dir=target,
                    manifest_filename="nagoya_gtfs_manifest.json",
                    s3_client=s3,
                )
            self.assertEqual(s3.calls, [])

    def test_existing_target_is_never_reused_or_overwritten(self) -> None:
        payload = make_bundle()
        env = {
            "NAGOYA_GTFS_BUNDLE_S3_BUCKET": "nagoya-bucket",
            "NAGOYA_GTFS_BUNDLE_S3_KEY": "gtfs/nagoya/release.zip",
            "NAGOYA_GTFS_BUNDLE_SHA256": hashlib.sha256(payload).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, env, clear=True
        ):
            target = Path(temp_dir) / "nagoya"
            target.mkdir()
            marker = target / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            s3 = FakeS3(payload)
            with self.assertRaises(FileExistsError):
                materialize_city_gtfs_bundle(
                    city="nagoya",
                    target_dir=target,
                    manifest_filename="nagoya_gtfs_manifest.json",
                    s3_client=s3,
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertEqual(s3.calls, [])


if __name__ == "__main__":
    unittest.main()
