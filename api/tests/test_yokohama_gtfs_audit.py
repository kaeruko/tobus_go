from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from audit_yokohama_bus_gtfs import audit, _minutes


def _fixture(root: Path) -> None:
    files = {
        "yokohama_bus_gtfs_manifest.json": json.dumps({
            "feed_version": "v3.0_20260727",
            "revision": "20260727",
            "validated_service_date": "2026-09-04",
            "source_url": "https://api.odpt.org/api/v4/files/odpt/YokohamaMunicipal/Bus.zip?date=current",
        }),
        "feed_info.txt": "feed_version\nv3.0_20260727\n",
        "routes.txt": (
            "route_id,route_short_name,route_long_name,route_type\n"
            "008,008系統,,3\n"
            "089,,89系統　ぶらり野毛山動物園BUS,3\n"
            "091,,【急行】91系統,3\n"
            "271,,観光スポット周遊バス「あかいくつ」,3\n"
        ),
        "trips.txt": (
            "trip_id,route_id,jp_trip_desc,jp_trip_desc_symbol\n"
            "T8,008,,\nT89,089,,\nT91,091,,\nT271,271,,\n"
        ),
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time\n"
            "T8,23:10:00,23:10:00\n"
            "T89,12:00:00,12:00:00\n"
            "T91,12:10:00,12:10:00\n"
            "T271,24:10:00,24:10:00\n"
        ),
    }
    for name, data in files.items():
        (root / name).write_text(data, encoding="utf-8")


class YokohamaGtfsAuditTest(unittest.TestCase):
    def test_report_is_read_only_and_only_describes_policy_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _fixture(root)
            before = {x.name: x.read_bytes() for x in root.iterdir()}
            result = audit(root)
            after = {x.name: x.read_bytes() for x in root.iterdir()}
            self.assertEqual(before, after)
            self.assertEqual(result["route_count"], 4)
            self.assertEqual(result["trip_count"], 4)
            self.assertEqual(result["late_clock_trip_count"], 2)
            self.assertFalse(any(result["fare_files_present"].values()))
            self.assertEqual(result["trip_descriptions_populated"], 0)
            by_id = {row["route_id"]: row for row in result["special_and_late_routes"]}
            self.assertEqual(by_id["089"]["review"], "listed_eligible")
            self.assertEqual(by_id["271"]["review"], "listed_excluded")
            self.assertEqual(by_id["091"]["review"], "manual_route_review_required")
            self.assertEqual(by_id["008"]["review"], "ordinary_name_only_not_fare_verified")
            self.assertEqual(by_id["271"]["late_clock_trips"], 1)
            self.assertIn("NOT proof", result["warning"])

    def test_known_exception_cannot_silently_become_a_different_route(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _fixture(root)
            path = root / "routes.txt"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    '観光スポット周遊バス「あかいくつ」', "別路線"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "changed name"):
                audit(root)

    def test_unknown_trip_and_mismatched_feed_fail_fast(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _fixture(root)
            path = root / "stop_times.txt"
            path.write_text(
                path.read_text(encoding="utf-8") + "UNKNOWN,10:00:00,10:00:00\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unknown trip"):
                audit(root)
            _fixture(root)
            feed_info = root / "feed_info.txt"
            feed_info.write_text("feed_version\nchanged\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "version does not match"):
                audit(root)

    def test_service_day_clock_accepts_24_plus_but_rejects_invalid_minutes(self) -> None:
        self.assertEqual(_minutes("24:10:00"), 1450)
        with self.assertRaises(ValueError):
            _minutes("25:99:00")


if __name__ == "__main__":
    unittest.main()
