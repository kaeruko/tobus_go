"""Pure synthetic same-date bus/subway geometric triage regression tests."""
from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from test_yokohama_municipal_transfer import DAY, _feed
from audit_yokohama_transfer_candidates import audit_transfer_candidates


class CandidateTriageTests(unittest.TestCase):
    def setUp(self):
        self.bus_temp = tempfile.TemporaryDirectory()
        self.rail_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.bus_temp.cleanup)
        self.addCleanup(self.rail_temp.cleanup)
        self.bus_root = Path(self.bus_temp.name)
        self.rail_root = Path(self.rail_temp.name)
        self.bus = _feed(self.bus_root, rail=False)
        self.rail = _feed(self.rail_root, rail=True)

    def _report(self, **kwargs):
        return audit_transfer_candidates(
            self.bus, self.rail.dataset, service_date=DAY, **kwargs,
        )

    def test_read_only_one_nearby_pair_but_no_automatic_approval(self):
        before = {
            ("bus", p.name): p.read_bytes() for p in self.bus_root.iterdir()
        } | {
            ("rail", p.name): p.read_bytes() for p in self.rail_root.iterdir()
        }
        result = self._report()
        after = {
            ("bus", p.name): p.read_bytes() for p in self.bus_root.iterdir()
        } | {
            ("rail", p.name): p.read_bytes() for p in self.rail_root.iterdir()
        }
        self.assertEqual(before, after)
        self.assertEqual(result["file_action"], "NONE")
        self.assertEqual(result["candidate_pair_count"], 1)
        self.assertEqual(result["active_reviewed_bus_stop_count"], 2)
        self.assertEqual(result["active_subway_stop_count_not_yet_fare_approved"], 2)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["bus_stop_id"], "yokohama_bus:B")
        self.assertEqual(candidate["subway_stop_id"], "yokohama_subway:S")
        self.assertLess(candidate["straight_line_distance_m"], 20)
        self.assertFalse(candidate["walkable_route_verified"])
        self.assertFalse(candidate["pass_fare_verified"])
        self.assertIsNone(candidate["official_transfer_evidence_url"])

    def test_radius_changes_proximity_not_fare_certification(self):
        self.assertEqual(self._report(radius_m=1)["candidate_pair_count"], 0)
        self.assertEqual(self._report(radius_m=600)["candidate_pair_count"], 1)

    def test_fail_closed_on_missing_bus_coverage(self):
        limited = replace(
            self.bus,
            route_service_kinds={
                "yokohama_bus:BUS": "unreviewed",
                "yokohama_bus:X": "sightseeing",
            },
        )
        with self.assertRaisesRegex(ValueError, "no reviewed municipal bus"):
            audit_transfer_candidates(limited, self.rail.dataset, service_date=DAY)

    def test_bad_feed_identity_and_date_are_rejected(self):
        wrong = replace(self.bus, operator_id="unrelated_operator")
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            audit_transfer_candidates(wrong, self.rail.dataset, service_date=DAY)
        with self.assertRaisesRegex(ValueError, "active scheduled stops"):
            audit_transfer_candidates(
                self.bus, self.rail.dataset, service_date="2027-01-01"
            )
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            audit_transfer_candidates(
                self.bus, self.rail.dataset, service_date="2026-1-1"
            )

    def test_invalid_radius_and_limit_rejected(self):
        for radius in (0, -1, 601, True):
            with self.subTest(radius=radius), self.assertRaisesRegex(
                ValueError, "radius_m"
            ):
                self._report(radius_m=radius)
        for limit in (0, -1, 101, True):
            with self.subTest(limit=limit), self.assertRaisesRegex(
                ValueError, "limit"
            ):
                self._report(limit=limit)


if __name__ == "__main__":
    unittest.main()
