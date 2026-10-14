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
from audit_yokohama_transfer_candidates import (
    audit_transfer_candidates, read_bus_pole_source_fields,
)


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
        self.assertEqual(
            [r["route_id"] for r in candidate["active_reviewed_bus_routes"]],
            ["yokohama_bus:BUS"],
        )
        self.assertEqual(
            candidate["active_reviewed_bus_routes"][0]["route_short_name"],
            "008系統",
        )
        self.assertEqual(
            candidate["active_reviewed_bus_routes"][0]["trip_headsigns"], [],
        )
        self.assertEqual(
            [r["route_id"] for r in candidate["active_unapproved_subway_routes"]],
            ["yokohama_subway:BLUE"],
        )
        self.assertNotIn(
            "yokohama_bus:X",
            str(candidate["active_reviewed_bus_routes"]),
        )
        self.assertFalse(candidate["walkable_route_verified"])
        self.assertFalse(candidate["pass_fare_verified"])
        self.assertIsNone(candidate["official_transfer_evidence_url"])

    def test_route_hints_do_not_change_candidate_count_or_approve_subway(self):
        result = self._report()
        candidate = result["candidates"][0]
        self.assertEqual(result["candidate_pair_count"], 1)
        self.assertEqual(result["shown_pair_count"], 1)
        self.assertEqual(candidate["status"], "UNVERIFIED_GEOMETRIC_HINT")
        self.assertFalse(candidate["pass_fare_verified"])
        self.assertTrue(candidate["active_unapproved_subway_routes"])
        self.assertIsNone(candidate["official_transfer_evidence_url"])

    def test_pole_focus_preserves_raw_candidates_and_does_not_change_approval(self):
        all_pairs = self._report()
        focused = self._report(focus_bus_stop_ids=("yokohama_bus:B",))
        self.assertEqual(focused["focus_bus_stop_ids"], ["yokohama_bus:B"])
        self.assertEqual(focused["candidate_pair_count"], all_pairs["candidate_pair_count"])
        self.assertEqual(focused["focus_matching_pair_count"], 1)
        self.assertEqual(focused["shown_pair_count"], 1)
        self.assertEqual(focused["candidates"][0]["bus_stop_id"], "yokohama_bus:B")
        self.assertEqual(focused["candidates"][0]["status"], "UNVERIFIED_GEOMETRIC_HINT")
        self.assertFalse(focused["candidates"][0]["walkable_route_verified"])
        self.assertFalse(focused["candidates"][0]["pass_fare_verified"])
        self.assertIsNone(focused["candidates"][0]["official_transfer_evidence_url"])
        self.assertEqual(focused["candidates"][0]["bus_gtfs_lat"], self.bus.dataset.stops["yokohama_bus:B"].lat)
        self.assertEqual(focused["candidates"][0]["subway_gtfs_lon"], self.rail.dataset.stops["yokohama_subway:S"].lon)

    def test_two_poles_same_station_remain_candidates_without_official_list_ranking(self):
        # Synthetic stand O is moved alongside stand B only to verify that
        # two distinct bus pole IDs survive; no official-nearby-list flag.
        base = self.bus.dataset.stops["yokohama_bus:O"]
        b = self.bus.dataset.stops["yokohama_bus:B"]
        bus_dataset = replace(
            self.bus.dataset,
            stops={
                **self.bus.dataset.stops,
                "yokohama_bus:O": replace(
                    base, lat=b.lat + 0.00003, lon=b.lon,
                ),
            },
        )
        coverage = replace(self.bus, dataset=bus_dataset)
        report = audit_transfer_candidates(
            coverage, self.rail.dataset,
            service_date=DAY, radius_m=300,
            focus_bus_stop_ids=("yokohama_bus:O", "yokohama_bus:B"),
        )
        self.assertEqual(report["candidate_pair_count"], 2)
        self.assertEqual(report["focus_matching_pair_count"], 2)
        self.assertEqual(report["shown_pair_count"], 2)
        self.assertEqual(
            {c["bus_stop_id"] for c in report["candidates"]},
            {"yokohama_bus:O", "yokohama_bus:B"},
        )
        self.assertTrue(all(
            c["status"] == "UNVERIFIED_GEOMETRIC_HINT"
            and not c["walkable_route_verified"]
            and not c["pass_fare_verified"]
            and c["official_transfer_evidence_url"] is None
            for c in report["candidates"]
        ))

    def test_unknown_duplicate_or_invalid_focus_fails_closed(self):
        for ids in (
            ("yokohama_bus:INVALID",),
            ("yokohama_bus:B", "yokohama_bus:B"),
            ("yokohama_subway:S",),
            ("other:B",),
            ("yokohama_bus:B", "x"),
        ):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, "focus"):
                self._report(focus_bus_stop_ids=ids)

    def test_raw_pole_metadata_is_not_automatically_official_bay_mapping(self):
        original = self.bus_root / "stops.txt"
        raw = original.read_text(encoding="utf-8")
        raw = raw.replace(
            "stop_id,stop_name,stop_lat,stop_lon",
            "stop_id,stop_name,stop_lat,stop_lon,stop_code,platform_code",
        ).replace(
            "O,横浜駅前,35.4700,139.6200",
            "O,横浜駅前,35.4700,139.6200,,",
        ).replace(
            "B,桜木町,35.4650,139.6250",
            "B,桜木町,35.4650,139.6250,ABC,8",
        )
        original.write_text(raw, encoding="utf-8")
        found = read_bus_pole_source_fields(
            self.bus_root, {"yokohama_bus:B"}
        )
        self.assertEqual(found["yokohama_bus:B"]["stop_code"], "ABC")
        self.assertEqual(found["yokohama_bus:B"]["platform_code"], "8")
        self.assertFalse(found["yokohama_bus:B"]["official_bay_number_verified"])
        with self.assertRaisesRegex(ValueError, "missing requested"):
            read_bus_pole_source_fields(
                self.bus_root, {"yokohama_bus:MISSING"}
            )

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
