import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from app.runtime import _download_lambda_data, setup_on_startup


class _FakeS3:
    def __init__(self, objects):
        self.objects = objects
        self.calls = []

    def download_file(self, bucket, key, destination):
        self.calls.append((bucket, key))
        shutil.copyfile(self.objects[key], destination)

    def get_object(self, Bucket, Key):
        self.calls.append((Bucket, Key))
        with open(self.objects[Key], "rb") as file:
            return {"Body": io.BytesIO(file.read())}


class LambdaDataDownloadTest(unittest.TestCase):
    def test_downloads_prebuilt_and_gtfs_once(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as data_dir:
            prebuilt_source = os.path.join(source_dir, "app_data.pkl")
            with open(prebuilt_source, "wb") as file:
                file.write(b"prebuilt")

            gtfs_source = os.path.join(source_dir, "ToeiBus-GTFS.zip")
            with zipfile.ZipFile(gtfs_source, "w") as archive:
                archive.writestr("ToeiBus-GTFS/routes.txt", "route_id\n")

            fake_s3 = _FakeS3(
                {
                    "deploy/app_data.pkl": prebuilt_source,
                    "deploy/ToeiBus-GTFS.zip": gtfs_source,
                }
            )

            with (
                patch.dict(
                    os.environ,
                    {
                        "S3_BUCKET_NAME": "test-bucket",
                        "S3_PREBUILT_KEY": "deploy/app_data.pkl",
                        "S3_GTFS_KEY": "deploy/ToeiBus-GTFS.zip",
                    },
                ),
                patch("boto3.client", return_value=fake_s3),
            ):
                first_path = _download_lambda_data(data_dir)
                second_path = _download_lambda_data(data_dir)

            self.assertEqual(first_path, os.path.join(data_dir, "app_data.pkl"))
            self.assertEqual(second_path, first_path)
            self.assertTrue(
                os.path.exists(os.path.join(data_dir, "ToeiBus-GTFS", "routes.txt"))
            )
            self.assertEqual(
                fake_s3.calls,
                [
                    ("test-bucket", "deploy/app_data.pkl"),
                    ("test-bucket", "deploy/ToeiBus-GTFS.zip"),
                ],
            )

    def test_resolves_atomic_gtfs_state_and_accepts_source_zip_layout(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as data_dir:
            prebuilt_source = os.path.join(source_dir, "app_data.pkl")
            with open(prebuilt_source, "wb") as file:
                file.write(b"prebuilt")

            gtfs_source = os.path.join(source_dir, "source.zip")
            with zipfile.ZipFile(gtfs_source, "w") as archive:
                archive.writestr("routes.txt", "route_id,route_type\n070,3\n")
            with open(gtfs_source, "rb") as file:
                gtfs_sha256 = hashlib.sha256(file.read()).hexdigest()

            state_source = os.path.join(source_dir, "state.json")
            with open(state_source, "w", encoding="utf-8") as file:
                json.dump(
                    {
                        "sha256": gtfs_sha256,
                        "object_key": "gtfs/toei/versions/current.zip",
                    },
                    file,
                )

            fake_s3 = _FakeS3(
                {
                    "deploy/app_data.pkl": prebuilt_source,
                    "gtfs/toei/state.json": state_source,
                    "gtfs/toei/versions/current.zip": gtfs_source,
                }
            )

            with (
                patch.dict(
                    os.environ,
                    {
                        "S3_BUCKET_NAME": "test-bucket",
                        "S3_PREBUILT_KEY": "deploy/app_data.pkl",
                        "S3_GTFS_STATE_KEY": "gtfs/toei/state.json",
                    },
                ),
                patch("boto3.client", return_value=fake_s3),
            ):
                path = _download_lambda_data(data_dir)

            self.assertEqual(path, os.path.join(data_dir, "app_data.pkl"))
            self.assertTrue(
                os.path.exists(os.path.join(data_dir, "ToeiBus-GTFS", "routes.txt"))
            )
            self.assertEqual(
                fake_s3.calls,
                [
                    ("test-bucket", "gtfs/toei/state.json"),
                    ("test-bucket", "deploy/app_data.pkl"),
                    ("test-bucket", "gtfs/toei/versions/current.zip"),
                ],
            )


class LambdaStartupReuseTest(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_initialized_runtime(self):
        app = SimpleNamespace(
            state=SimpleNamespace(
                loading_status="ready",
                G=object(),
                TM=object(),
            )
        )

        with patch("app.runtime._download_lambda_data") as download:
            await setup_on_startup(app, "lambda")

        download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
