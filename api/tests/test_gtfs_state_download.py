import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gtfs_state import (
    CompiledGtfsStateError,
    download_compiled_lambda_assets,
)


class _FakeS3:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.calls = []

    def get_object(self, Bucket, Key):
        self.calls.append(("get", Bucket, Key))
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def download_file(self, bucket, key, destination):
        self.calls.append(("download", bucket, key))
        if key not in self.objects:
            raise KeyError(key)
        with open(destination, "wb") as file:
            file.write(self.objects[key])


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class CompiledGtfsDownloadTest(unittest.TestCase):
    def test_downloads_prebuilt_and_versioned_compiled_state(self):
        prebuilt = b"prebuilt"
        compiled = b"compiled-state"
        source_sha = "a" * 64
        state = {
            "sha256": source_sha,
            "object_key": "gtfs/toei/versions/source.zip",
            "compiled_state_key": "gtfs/toei/compiled/source.pkl.gz",
            "compiled_state_sha256": _sha(compiled),
            "compiled_state_schema_version": 1,
            "compiled_state_record_counts": {"trips": 1},
        }
        fake_s3 = _FakeS3(
            {
                "gtfs/toei/state.json": json.dumps(state).encode("utf-8"),
                "deploy/app_data.pkl": prebuilt,
                state["compiled_state_key"]: compiled,
            }
        )

        with tempfile.TemporaryDirectory() as data_dir:
            with (
                patch.dict(
                    os.environ,
                    {
                        "S3_BUCKET_NAME": "bucket",
                        "S3_PREBUILT_KEY": "deploy/app_data.pkl",
                        "S3_GTFS_STATE_KEY": "gtfs/toei/state.json",
                    },
                    clear=False,
                ),
                patch("boto3.client", return_value=fake_s3),
            ):
                assets = download_compiled_lambda_assets(data_dir)

            self.assertEqual(assets.source_sha256, source_sha)
            with open(assets.prebuilt_path, "rb") as file:
                self.assertEqual(file.read(), prebuilt)
            with open(assets.compiled_state_path, "rb") as file:
                self.assertEqual(file.read(), compiled)

        self.assertEqual(
            fake_s3.calls,
            [
                ("get", "bucket", "gtfs/toei/state.json"),
                ("download", "bucket", "deploy/app_data.pkl"),
                (
                    "download",
                    "bucket",
                    "gtfs/toei/compiled/source.pkl.gz",
                ),
            ],
        )

    def test_missing_compiled_pointer_fails_without_raw_zip_fallback(self):
        state = {
            "sha256": "a" * 64,
            "object_key": "gtfs/toei/versions/source.zip",
        }
        fake_s3 = _FakeS3(
            {"gtfs/toei/state.json": json.dumps(state).encode("utf-8")}
        )

        with tempfile.TemporaryDirectory() as data_dir:
            with (
                patch.dict(
                    os.environ,
                    {
                        "S3_BUCKET_NAME": "bucket",
                        "S3_GTFS_STATE_KEY": "gtfs/toei/state.json",
                    },
                    clear=False,
                ),
                patch("boto3.client", return_value=fake_s3),
            ):
                with self.assertRaisesRegex(
                    CompiledGtfsStateError,
                    "missing compiled_state_key",
                ):
                    download_compiled_lambda_assets(data_dir)

        self.assertEqual(
            fake_s3.calls,
            [("get", "bucket", "gtfs/toei/state.json")],
        )

    def test_compiled_checksum_mismatch_is_fatal(self):
        compiled = b"corrupted"
        state = {
            "sha256": "a" * 64,
            "object_key": "gtfs/toei/versions/source.zip",
            "compiled_state_key": "gtfs/toei/compiled/source.pkl.gz",
            "compiled_state_sha256": "b" * 64,
            "compiled_state_schema_version": 1,
            "compiled_state_record_counts": {"trips": 1},
        }
        fake_s3 = _FakeS3(
            {
                "gtfs/toei/state.json": json.dumps(state).encode("utf-8"),
                "app_data.pkl": b"prebuilt",
                state["compiled_state_key"]: compiled,
            }
        )

        with tempfile.TemporaryDirectory() as data_dir:
            with (
                patch.dict(
                    os.environ,
                    {
                        "S3_BUCKET_NAME": "bucket",
                        "S3_PREBUILT_KEY": "app_data.pkl",
                        "S3_GTFS_STATE_KEY": "gtfs/toei/state.json",
                    },
                    clear=False,
                ),
                patch("boto3.client", return_value=fake_s3),
            ):
                with self.assertRaisesRegex(
                    CompiledGtfsStateError,
                    "checksum mismatch",
                ):
                    download_compiled_lambda_assets(data_dir)


if __name__ == "__main__":
    unittest.main()
