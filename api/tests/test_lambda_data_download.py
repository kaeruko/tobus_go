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
