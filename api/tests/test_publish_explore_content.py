import argparse
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "publish_explore_content",
    Path(__file__).resolve().parents[2] / "scripts" / "publish_explore_content.py",
)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def remote_image(content: bytes, *, etag: str | None = None) -> dict:
    return {
        "Size": len(content),
        "ETag": etag or f'"{hashlib.md5(content, usedforsecurity=False).hexdigest()}"',
    }


class PublishExploreContentTest(unittest.TestCase):
    def _arguments(self, *, dry_run: bool = False) -> argparse.Namespace:
        return argparse.Namespace(
            city="tokyo", region="us-west-2", lambda_function="toeigo-api",
            bucket="test-bucket", dry_run=dry_run, progress_json=True,
        )

    def _payload(self, *filenames: str) -> dict:
        return {"spots": [{"images": [{"file": name} for name in filenames]}]}

    def test_aws_is_noninteractive_and_has_connection_and_process_limits(self):
        result = subprocess.CompletedProcess([], 0, stdout="bucket\n", stderr="")
        with patch.object(publisher.shutil, "which", return_value="aws.exe"), \
                patch.object(publisher.subprocess, "run", return_value=result) as run:
            self.assertEqual(publisher.run_aws(["lambda", "get-function-configuration"]), "bucket")
        arguments, kwargs = run.call_args
        command = arguments[0]
        self.assertIn("--no-cli-pager", command)
        self.assertIn("--no-cli-auto-prompt", command)
        self.assertEqual(command[command.index("--cli-connect-timeout") + 1], "10")
        self.assertEqual(command[command.index("--cli-read-timeout") + 1], "30")
        self.assertEqual(kwargs["timeout"], publisher.AWS_COMMAND_TIMEOUT_SECONDS)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["env"]["AWS_PAGER"], "")
        self.assertEqual(kwargs["env"]["AWS_CLI_AUTO_PROMPT"], "off")
        self.assertEqual(kwargs["env"]["AWS_MAX_ATTEMPTS"], "2")

    def test_aws_timeout_reports_command_and_deadline(self):
        with patch.object(publisher.shutil, "which", return_value="aws.exe"), \
                patch.object(publisher.subprocess, "run", side_effect=subprocess.TimeoutExpired("aws", 90)):
            with self.assertRaisesRegex(RuntimeError, "timed out after 90 seconds: aws.exe s3 cp"):
                publisher.run_aws(["s3", "cp", "photo.jpg", "s3://bucket/photo.jpg"])

    def test_aws_failure_keeps_service_error(self):
        result = subprocess.CompletedProcess([], 1, stdout="", stderr="AccessDenied\n")
        with patch.object(publisher.shutil, "which", return_value="aws.exe"), \
                patch.object(publisher.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "AccessDenied"):
                publisher.run_aws(["s3api", "list-objects-v2"])

    def test_s3_listing_uses_one_paginated_cli_call_and_image_prefix(self):
        output = json.dumps({"Contents": [
            {"Key": "content/explore/tokyo/images/one.jpg", **remote_image(b"one")},
            {"Key": "other/image.jpg", **remote_image(b"other")},
        ]})
        with patch.object(publisher, "run_aws", return_value=output) as run:
            listing = publisher.list_remote_images(
                bucket="bucket", prefix="content/explore/tokyo", region="us-west-2",
            )
        self.assertEqual(set(listing), {"one.jpg"})
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["s3api", "list-objects-v2"])
        self.assertEqual(command[command.index("--prefix") + 1], "content/explore/tokyo/images/")
        self.assertNotIn("--no-paginate", command)

    def test_empty_bucket_and_invalid_listing(self):
        with patch.object(publisher, "run_aws", return_value="{}"):
            self.assertEqual(publisher.list_remote_images(bucket="b", prefix="p", region="r"), {})
        for output in ("not json", '[]', '{"Contents": {}}', '{"Contents": [null]}'):
            with self.subTest(output=output), patch.object(publisher, "run_aws", return_value=output):
                with self.assertRaisesRegex(RuntimeError, "invalid S3 image listing"):
                    publisher.list_remote_images(bucket="b", prefix="p", region="r")

    def test_same_size_edits_missing_and_multipart_objects_are_uploaded(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "image.jpg"
            source.write_bytes(b"new")
            self.assertTrue(publisher.image_is_unchanged(source, remote_image(b"new")))
            self.assertFalse(publisher.image_is_unchanged(source, remote_image(b"old")))
            self.assertFalse(publisher.image_is_unchanged(source, remote_image(b"new", etag='"abcd-2"')))
            self.assertFalse(publisher.image_is_unchanged(source, {"Size": 3}))
            self.assertFalse(publisher.image_is_unchanged(source, None))
            self.assertFalse(publisher.image_is_unchanged(source, remote_image(b"longer")))

    def test_bare_md5_etag_keeps_matching_image_but_not_same_size_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "image.jpg"
            source.write_bytes(b"new")
            matching = hashlib.md5(b"new", usedforsecurity=False).hexdigest()
            changed = hashlib.md5(b"old", usedforsecurity=False).hexdigest()
            for etag, expected in (
                (matching, True), (matching.upper(), True), (changed, False),
                ('"' + matching, False), (matching + '"', False),
            ):
                with self.subTest(etag=etag):
                    self.assertEqual(publisher.image_is_unchanged(
                        source, {"Size": 3, "ETag": etag}), expected)

    def test_listing_rejects_ambiguous_keys_and_malformed_metadata(self):
        entry = {"Key": "p/images/one.jpg", **remote_image(b"one")}
        malformed = [
            [dict(entry, Key="p/images/")],
            [dict(entry, Key="p/images/nested/one.jpg")],
            [dict(entry, Key="p/images/nested\\one.jpg")],
            [entry, dict(entry)],
            [{key: value for key, value in entry.items() if key != "Size"}],
            *[[dict(entry, Size=size)] for size in (-1, "3", 3.0, True)],
            *[[dict(entry, ETag=etag)] for etag in (None, 123)],
        ]
        for contents in malformed:
            with self.subTest(contents=contents), \
                    patch.object(publisher, "run_aws", return_value=json.dumps({"Contents": contents})):
                with self.assertRaisesRegex(RuntimeError, "invalid S3 image listing"):
                    publisher.list_remote_images(bucket="b", prefix="p/", region="r")
        # Missing/composite ETags are conservative upload decisions, not an
        # invalid listing. Metadata still identifies one unambiguous object.
        for etag in (None, '"multipart-2"'):
            item = {"Key": "p/images/one.jpg", "Size": 3}
            if etag is not None:
                item["ETag"] = etag
            with self.subTest(valid_listing=item), \
                    patch.object(publisher, "run_aws", return_value=json.dumps({"Contents": [item]})) as aws:
                self.assertEqual(publisher.list_remote_images(bucket="b", prefix="p/", region="r"),
                                 {"one.jpg": item})
                command = aws.call_args.args[0]
                self.assertEqual(command[command.index("--prefix") + 1], "p/images/")

    def test_delta_uploads_changed_photo_once_then_manifest_with_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            images = Path(directory)
            (images / "same.jpg").write_bytes(b"same")
            (images / "edited.jpg").write_bytes(b"new")
            payload = self._payload("same.jpg", "edited.jpg", "edited.jpg")
            with patch.object(publisher, "parse_args", return_value=self._arguments()), \
                    patch.object(publisher, "source_paths", return_value=(images / "spots.csv", images)), \
                    patch.object(publisher, "compile_csv", return_value=payload), \
                    patch.object(publisher, "list_remote_images", return_value={
                        "same.jpg": remote_image(b"same"), "edited.jpg": remote_image(b"old"),
                    }) as listing, patch.object(publisher, "upload_file") as upload, redirect_stdout(StringIO()) as output:
                self.assertEqual(publisher.main(), 0)
            listing.assert_called_once()
            calls = [call.kwargs for call in upload.call_args_list]
            self.assertEqual([call["source"].name for call in calls], ["edited.jpg", "spots.json"])
            self.assertEqual(calls[0]["content_type"], "image/jpeg")
            self.assertEqual(calls[0]["cache_control"], "public,max-age=86400")
            self.assertEqual(calls[1]["content_type"], "application/json; charset=utf-8")
            self.assertEqual(calls[1]["cache_control"], "no-cache")
            events = [json.loads(line[len(publisher.PROGRESS_PREFIX):])
                      for line in output.getvalue().splitlines()
                      if line.startswith(publisher.PROGRESS_PREFIX)]
            self.assertEqual(events[0]["stage"], "validate")
            self.assertEqual(events[-1], {"stage": "complete", "current": 1, "total": 1, "skipped": 1})
            self.assertEqual(sum(event["stage"] == "complete" for event in events), 1)
            uploading = [event for event in events if event["stage"] == "images" and "filename" in event]
            self.assertEqual([event["current"] for event in uploading], [0, 1])
            self.assertTrue(all(event["total"] == 1 for event in uploading))

    def test_unchanged_images_still_publish_edited_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            images = Path(directory)
            (images / "same.jpg").write_bytes(b"same")
            with patch.object(publisher, "parse_args", return_value=self._arguments()), \
                    patch.object(publisher, "source_paths", return_value=(images / "spots.csv", images)), \
                    patch.object(publisher, "compile_csv", return_value=self._payload("same.jpg")), \
                    patch.object(publisher, "list_remote_images", return_value={"same.jpg": remote_image(b"same")}), \
                    patch.object(publisher, "upload_file") as upload, redirect_stdout(StringIO()):
                publisher.main()
            upload.assert_called_once()
            self.assertEqual(upload.call_args.kwargs["source"].name, "spots.json")

    def test_dry_run_compares_images_without_uploading(self):
        with tempfile.TemporaryDirectory() as directory:
            images = Path(directory)
            (images / "new.jpg").write_bytes(b"new")
            with patch.object(publisher, "parse_args", return_value=self._arguments(dry_run=True)), \
                    patch.object(publisher, "source_paths", return_value=(images / "spots.csv", images)), \
                    patch.object(publisher, "compile_csv", return_value=self._payload("new.jpg")), \
                    patch.object(publisher, "list_remote_images", return_value={}) as listing, \
                    patch.object(publisher, "upload_file") as upload, redirect_stdout(StringIO()):
                self.assertEqual(publisher.main(), 0)
            listing.assert_called_once()
            upload.assert_not_called()

    def test_local_validation_failure_prevents_all_aws_calls(self):
        with patch.object(publisher, "parse_args", return_value=self._arguments()), \
                patch.object(publisher, "compile_csv", side_effect=publisher.ExploreContentError("bad CSV")), \
                patch.object(publisher, "run_aws") as aws, \
                patch.object(publisher, "upload_file") as upload, redirect_stdout(StringIO()):
            with self.assertRaisesRegex(publisher.ExploreContentError, "bad CSV"):
                publisher.main()
        aws.assert_not_called()
        upload.assert_not_called()

    def test_failed_image_never_publishes_manifest_or_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            images = Path(directory)
            (images / "one.jpg").write_bytes(b"one")
            (images / "two.jpg").write_bytes(b"two")
            with patch.object(publisher, "parse_args", return_value=self._arguments()), \
                    patch.object(publisher, "source_paths", return_value=(images / "spots.csv", images)), \
                    patch.object(publisher, "compile_csv", return_value=self._payload("one.jpg", "two.jpg")), \
                    patch.object(publisher, "list_remote_images", return_value={}), \
                    patch.object(publisher, "upload_file", side_effect=[None, RuntimeError("upload failed")]) as upload, \
                    redirect_stdout(StringIO()) as output:
                with self.assertRaisesRegex(RuntimeError, "upload failed"):
                    publisher.main()
            self.assertEqual([call.kwargs["source"].name for call in upload.call_args_list], ["one.jpg", "two.jpg"])
            self.assertNotIn('"stage": "complete"', output.getvalue())
            self.assertNotIn('"stage": "manifest"', output.getvalue())

    def test_progress_protocol_flushes_each_event(self):
        with patch("builtins.print") as report:
            publisher.emit_progress(True, "images", current=2, total=3, filename="photo.jpg", skipped=4)
        report.assert_called_once()
        self.assertTrue(report.call_args.kwargs["flush"])
        line = report.call_args.args[0]
        self.assertTrue(line.startswith(publisher.PROGRESS_PREFIX))
        self.assertEqual(json.loads(line[len(publisher.PROGRESS_PREFIX):]), {
            "stage": "images", "current": 2, "total": 3, "filename": "photo.jpg", "skipped": 4,
        })


if __name__ == "__main__":
    unittest.main()
