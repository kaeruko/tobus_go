"""Synthetic route/agency inventory audit, without external requests or writes."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audit_yokohama_subway_routes import audit_subway_routes
from test_yokohama_subway import DAY, _fixture
from yokohama_subway import load_yokohama_subway_dataset


class SubwayRouteIdentityAuditTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        _fixture(self.root)
        self.dataset = load_yokohama_subway_dataset(
            self.root, expected_service_date=DAY
        )

    def test_immutable_source_read_only_and_no_automatic_fare_approval(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        result = audit_subway_routes(
            self.dataset, self.root, service_date=DAY
        )
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        self.assertEqual(result["operation"], "READ ONLY; ZERO FARE APPROVAL")
        self.assertEqual(result["file_action"], "NONE")
        self.assertEqual(result["source_route_record_count"], 1)
        self.assertEqual(result["distinct_source_route_names"], 1)
        self.assertEqual(result["active_route_record_count"], 1)
        item = result["routes"][0]
        self.assertEqual(item["route_id"], "yokohama_subway:BLUE")
        self.assertEqual(item["source_agency_name"], "横浜市交通局")
        self.assertEqual(item["agency_mapping"], "GTFS_SINGLE_AGENCY_ONLY")
        self.assertEqual(item["active_service_day_trips"], 1)
        self.assertEqual(item["active_boardable_station_count"], 2)
        self.assertEqual(item["pass_coverage_status"], "UNREVIEWED_GTFS_ROUTE_ID")

    def test_future_date_is_no_active_trips_not_fare_approved(self):
        result = audit_subway_routes(
            self.dataset, self.root, service_date="2027-04-14"
        )
        self.assertEqual(result["active_route_record_count"], 0)
        self.assertEqual(result["routes"][0]["active_boardable_station_count"], 0)
        self.assertEqual(result["routes"][0]["pass_coverage_status"], "UNREVIEWED_GTFS_ROUTE_ID")

    def test_invalid_feed_identity_and_service_date_rejected(self):
        from dataclasses import replace
        with self.assertRaisesRegex(ValueError, "identity"):
            audit_subway_routes(
                replace(
                    self.dataset,
                    metadata=replace(self.dataset.metadata, feed_id="foreign"),
                ),
                self.root, service_date=DAY,
            )
        for bad in ("2026-1-4", "invalid"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "service_date"):
                audit_subway_routes(
                    self.dataset, self.root, service_date=bad
                )

    def test_ambiguous_agency_does_not_prove_operator(self):
        agency = self.root / "agency.txt"
        agency.write_text(
            "agency_id,agency_name,agency_timezone\n"
            "A,横浜市交通局,Asia/Tokyo\n"
            "B,他社,Asia/Tokyo\n",
            encoding="utf-8",
        )
        report = audit_subway_routes(
            self.dataset, self.root, service_date=DAY
        )
        self.assertIsNone(report["routes"][0]["source_agency_name"])
        self.assertEqual(
            report["routes"][0]["agency_mapping"],
            "UNRESOLVED_MULTIPLE_AGENCIES",
        )

    def test_unknown_explicit_agency_fails_closed(self):
        agency = self.root / "agency.txt"
        agency.write_text(
            "agency_id,agency_name,agency_timezone\n"
            "A,横浜市交通局,Asia/Tokyo\n",
            encoding="utf-8",
        )
        routes = self.root / "routes.txt"
        routes.write_text(
            "route_id,route_short_name,route_long_name,route_type,agency_id\n"
            "BLUE,ブルー,地下鉄,1,unknown\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "unlisted source agency_id"):
            audit_subway_routes(
                self.dataset, self.root, service_date=DAY
            )


if __name__ == "__main__":
    unittest.main()
