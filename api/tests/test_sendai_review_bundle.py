"""Read-only/fail-closed tests for the separately approved Sendai source trio.

Synthetic records below establish byte and date boundaries only. They are
never accepted as independently reviewed operational Sendai transit data.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.sendai_review_bundle import (
    GTFS_MANIFEST, REVIEW_FILES, REVIEW_MANIFEST,
    create_review_manifest, validated_reviewed_paths,
)


class FakePeriod:
    query_start = date(2026, 10, 7)
    query_end = date(2026, 11, 30)

    def require_query_days(self, day, days, *, additional_reviewed_days):
        if day not in (date(2026, 10, 18), date(2026, 11, 30)):
            raise ValueError("query day is outside independent review")
        if days != (day,) or not additional_reviewed_days:
            raise ValueError("independent bus days are required")


class SendaiReviewedBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "gtfs"
        self.root.mkdir()
        self.source_sha = "a" * 64
        (self.root / GTFS_MANIFEST).write_text(
            json.dumps({"sha256": self.source_sha}), encoding="utf-8")
        for key, filename in REVIEW_FILES.items():
            obj = ({"bus_feed_version": f"sha256:{self.source_sha}",
                    "operating_period": {}} if key == "municipal" else {"test": key})
            (self.root / filename).write_text(
                json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def _manifest(self):
        with patch("sendai_operating_period.OperatingPeriodReview.from_mapping",
                   return_value=FakePeriod()):
            return create_review_manifest(self.root)

    def _verify(self):
        with patch("sendai_operating_period.OperatingPeriodReview.from_mapping",
                   return_value=FakePeriod()):
            return validated_reviewed_paths(self.root)

    def test_same_bundle_verifies_every_reviewed_json_byte(self):
        manifest = self._manifest()
        (self.root / REVIEW_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        paths = self._verify()
        self.assertEqual(paths["municipal"], self.root / REVIEW_FILES["municipal"])
        self.assertEqual(set(paths), set(REVIEW_FILES))
        self.assertEqual(manifest["query_end"], "2026-11-30")

    def test_no_manifest_refuses_to_load_unpinned_review(self):
        with self.assertRaises(FileNotFoundError):
            self._verify()

    def test_rejects_modified_review_and_missing_required_inputs(self):
        manifest = self._manifest()
        (self.root / REVIEW_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        (self.root / REVIEW_FILES["subway_published"]).write_text(
            '{"changed": true}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "binding mismatch"):
            self._verify()
        (self.root / REVIEW_FILES["subway_published"]).unlink()
        with self.assertRaisesRegex(ValueError, "missing or a symlink"):
            self._verify()

    def test_rejects_feed_sha_change_and_incompatible_review(self):
        manifest = self._manifest()
        (self.root / REVIEW_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        (self.root / GTFS_MANIFEST).write_text(
            json.dumps({"sha256": "b" * 64}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not match official GTFS"):
            self._verify()

    def test_rejects_manifest_extra_keys_and_invalid_hash(self):
        manifest = self._manifest()
        manifest["unauthorized_extension"] = True
        (self.root / REVIEW_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid Sendai reviewed bundle"):
            self._verify()
        manifest.pop("unauthorized_extension")
        manifest["files"]["subway_review"] = "garbage"
        (self.root / REVIEW_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self._verify()

    def test_preparer_pins_review_and_refuses_unreviewed_december(self):
        from scripts.prepare_sendai_reviewed_bundle import prepare

        # This test substitutes an intentionally synthetic dataset, model,
        # and calendar. The real CLI does not patch these validation steps.
        bus = SimpleNamespace(metadata=SimpleNamespace(version=f"sha256:{self.source_sha}"))
        network = SimpleNamespace(bus_reviewed_days=frozenset({date(2026, 10, 18)}))
        output = Path(self.temp.name) / "approved"
        municipal = self.root / REVIEW_FILES["municipal"]
        published = self.root / REVIEW_FILES["subway_published"]
        subway = self.root / REVIEW_FILES["subway_review"]

        with (
            patch("scripts.prepare_sendai_reviewed_bundle.load_sendai_dataset",
                  return_value=bus) as load,
            patch("scripts.prepare_sendai_reviewed_bundle.load_reviewed_subway",
                  return_value=(object(), None)) as subway_load,
            patch("scripts.prepare_sendai_reviewed_bundle.build_reviewed_municipal_model",
                  return_value=network) as build,
            patch("sendai_operating_period.OperatingPeriodReview.from_mapping",
                  return_value=FakePeriod()),
        ):
            kwargs = {
                "gtfs_dir": self.root, "municipal": municipal, "published": published,
                "subway_review": subway, "output": output,
                "expected_service_date": "2026-10-18",
                "target_query_date": "2026-10-18",
            }
            manifest = prepare(**kwargs)
            self.assertTrue((output / REVIEW_MANIFEST).is_file())
            self.assertEqual(manifest["bus_source_sha256"], self.source_sha)
            self.assertEqual(validated_reviewed_paths(output)["municipal"],
                             output / REVIEW_FILES["municipal"])
            load.assert_called_once_with(self.root, expected_service_date="2026-10-18")
            subway_load.assert_called_once()
            build.assert_called_once()
            with self.assertRaises(FileExistsError):
                prepare(**kwargs)
            kwargs["output"] = Path(self.temp.name) / "december"
            kwargs["target_query_date"] = "2026-12-01"
            with self.assertRaisesRegex(ValueError, "outside independent review"):
                prepare(**kwargs)
            self.assertFalse(kwargs["output"].exists())


if __name__ == "__main__":
    unittest.main()
