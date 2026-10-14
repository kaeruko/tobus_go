"""Offline synthetic GTFS tests; no ODPT API or live feed used."""
import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from yokohama_subway import (
    MANIFEST, RESOURCE_ID, SOURCE_URL, VERSION, load_yokohama_subway_dataset,
)

DAY = "2026-10-14"


def _refresh_manifest(root):
    value = {
        "source_url": SOURCE_URL,
        "resource_id": RESOURCE_ID,
        "feed_version": VERSION,
        "fetched_at": "2026-10-14T00:00:00+09:00",
        "valid_from": "2025-12-26",
        "valid_until": "2026-12-31",
        "validated_service_date": DAY,
        "files_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.glob("*.txt")
        },
    }
    (root / MANIFEST).write_text(json.dumps(value), encoding="utf-8")


def _fixture(root):
    inputs = {
        "agency.txt": "agency_name,agency_timezone\n横浜市交通局,Asia/Tokyo\n",
        "feed_info.txt": "feed_version,feed_start_date,feed_end_date\n20251226,20251226,20261231\n",
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "A,横浜,35.4660,139.6225\nB,桜木町,35.4500,139.6300\n"
        ),
        "routes.txt": "route_id,route_short_name,route_long_name,route_type\nBLUE,ブルー,地下鉄,1\n",
        "trips.txt": "route_id,service_id,trip_id,trip_headsign\nBLUE,ALL,T1,桜木町\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,09:55:00,09:55:00,A,1\nT1,10:10:00,10:10:00,B,2\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "ALL,1,1,1,1,1,1,1,20251226,20261231\n"
        ),
    }
    for name, data in inputs.items():
        (root / name).write_text(data, encoding="utf-8")
    _refresh_manifest(root)


class SubwayPreflightTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        _fixture(self.root)

    def test_namespace_and_read_only(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        dataset = load_yokohama_subway_dataset(
            self.root, expected_service_date=DAY,
        )
        self.assertEqual(dataset.metadata.feed_id, "yokohama_subway")
        self.assertEqual(list(dataset.routes), ["yokohama_subway:BLUE"])
        self.assertEqual(list(dataset.trips), ["yokohama_subway:T1"])
        self.assertIn(
            "yokohama_subway:ALL", dataset.active_service_ids(date(2026, 10, 14)),
        )
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_tampered_content_is_rejected(self):
        with (self.root / "trips.txt").open("a", encoding="utf-8") as handle:
            handle.write("BLUE,ALL,T2,横浜\n")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            load_yokohama_subway_dataset(self.root, expected_service_date=DAY)

    def test_manifest_mismatch_rejected(self):
        p = self.root / MANIFEST
        value = json.loads(p.read_text(encoding="utf-8"))
        value["feed_version"] = "20251101"
        p.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "feed_version mismatch"):
            load_yokohama_subway_dataset(self.root, expected_service_date=DAY)

    def test_bus_route_is_rejected(self):
        p = self.root / "routes.txt"
        p.write_text(p.read_text(encoding="utf-8").replace(",1\n", ",3\n"))
        _refresh_manifest(self.root)
        with self.assertRaisesRegex(ValueError, "non-rail"):
            load_yokohama_subway_dataset(self.root, expected_service_date=DAY)

    def test_date_outside_validity_and_wrong_review_date(self):
        with self.assertRaisesRegex(ValueError, "outside catalog"):
            load_yokohama_subway_dataset(
                self.root, expected_service_date="2027-01-01",
            )
        with self.assertRaisesRegex(ValueError, "validated_service_date mismatch"):
            load_yokohama_subway_dataset(
                self.root, expected_service_date="2026-10-15",
            )

    def test_no_active_service_rejected(self):
        p = self.root / "calendar.txt"
        p.write_text(p.read_text(encoding="utf-8").replace(
            "ALL,1,1,1,1,1,1,1,", "ALL,0,0,0,0,0,0,0,"
        ))
        _refresh_manifest(self.root)
        with self.assertRaisesRegex(ValueError, "no active trips"):
            load_yokohama_subway_dataset(self.root, expected_service_date=DAY)

    def test_manifest_required(self):
        (self.root / MANIFEST).unlink()
        with self.assertRaises(FileNotFoundError):
            load_yokohama_subway_dataset(self.root, expected_service_date=DAY)


if __name__ == "__main__":
    unittest.main()
