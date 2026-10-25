from __future__ import annotations

import datetime as dt
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.test_tokyo_metro_gtfs import _fixture
from tokyo_metro_release_inputs import sha256, validate_release_inputs


class TokyoMetroReleaseInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.gtfs, self.stations, self.railways = _fixture(self.root)
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(
            json.dumps(
                {"schema": "tokyo_metro_reviewed_transfer/v1", "transfers": []}
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def archive(self, *, omitted: str | None = None) -> Path:
        target = self.root / "feed.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self.gtfs.iterdir()):
                if path.name != omitted:
                    archive.write(path, path.name)
        return target

    def validate(self, archive: Path, **overrides):
        values = {
            "archive_path": archive,
            "stations_path": self.stations,
            "railways_path": self.railways,
            "transfer_manifest_path": self.manifest,
            "expected_archive_sha256": sha256(archive),
            "expected_station_sha256": sha256(self.stations),
            "expected_railway_sha256": sha256(self.railways),
            "expected_transfer_manifest_sha256": sha256(self.manifest),
            "expected_version": "test-v1",
            "expected_valid_from": dt.date(2026, 9, 19),
            "expected_valid_until": dt.date(2027, 3, 12),
            "service_date": dt.date(2026, 10, 23),
        }
        values.update(overrides)
        return validate_release_inputs(**values)

    def test_accepts_exact_pinned_archive_and_masters(self):
        result = self.validate(self.archive())
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["feed_version"], "test-v1")
        self.assertEqual((result["routes"], result["stops"], result["trips"]), (2, 4, 4))

    def test_rejects_invalid_zip_even_when_its_hash_is_pinned(self):
        archive = self.root / "invalid.zip"
        archive.write_bytes(b"not a zip")
        with self.assertRaisesRegex(ValueError, "not a valid ZIP"):
            self.validate(archive)

    def test_rejects_missing_required_file(self):
        archive = self.archive(omitted="routes.txt")
        with self.assertRaisesRegex(ValueError, "missing: routes.txt"):
            self.validate(archive)

    def test_rejects_archive_hash_mismatch(self):
        archive = self.archive()
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.validate(archive, expected_archive_sha256="0" * 64)

    def test_rejects_transfer_manifest_hash_mismatch(self):
        with self.assertRaisesRegex(ValueError, "transfer-manifest SHA-256 mismatch"):
            self.validate(
                self.archive(),
                expected_transfer_manifest_sha256="0" * 64,
            )

    def test_requires_counterpart_path_and_hash_together(self):
        with self.assertRaisesRegex(ValueError, "must be supplied together"):
            self.validate(
                self.archive(),
                expected_counterpart_stations_sha256="0" * 64,
            )

    def test_rejects_counterpart_hash_mismatch(self):
        counterpart = self.root / "counterpart.json"
        counterpart.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "counterpart-stations SHA-256 mismatch"):
            self.validate(
                self.archive(),
                counterpart_stations_path=counterpart,
                expected_counterpart_stations_sha256="0" * 64,
            )

    def test_rejects_station_id_mapping_mismatch(self):
        stations = json.loads(self.stations.read_text(encoding="utf-8"))
        stations[0]["odpt:stationCode"] = "UNKNOWN"
        self.stations.write_text(json.dumps(stations), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no matching official ODPT station code"):
            self.validate(self.archive())

    def test_rejects_different_feed_edition(self):
        with self.assertRaisesRegex(ValueError, "edition mismatch"):
            self.validate(self.archive(), expected_version="another-version")

    def test_rejects_service_date_outside_effective_period(self):
        with self.assertRaisesRegex(ValueError, "outside the feed period"):
            self.validate(self.archive(), service_date=dt.date(2027, 3, 13))

    def test_requires_base_hash_before_loading_pickle(self):
        base = self.root / "base.pkl"
        base.write_bytes(b"not a trusted pickle")
        with self.assertRaisesRegex(
            ValueError, "expected base app-data SHA-256 is required"
        ):
            self.validate(self.archive(), base_app_data_path=base)

    def test_rejects_base_hash_mismatch_before_loading_pickle(self):
        base = self.root / "base.pkl"
        base.write_bytes(b"not a trusted pickle")
        with self.assertRaisesRegex(ValueError, "base app-data SHA-256 mismatch"):
            self.validate(
                self.archive(),
                base_app_data_path=base,
                expected_base_app_data_sha256="0" * 64,
            )

    def test_failed_validation_does_not_modify_an_existing_active_artifact(self):
        active = self.root / "active-app-data.pkl"
        active.write_bytes(b"previous accepted artifact")
        before = hashlib.sha256(active.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "edition mismatch"):
            self.validate(self.archive(), expected_version="unapproved")
        self.assertEqual(hashlib.sha256(active.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
