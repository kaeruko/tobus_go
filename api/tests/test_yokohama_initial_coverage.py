from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.app_factory import create_app
from test_yokohama_backend import SERVICE_DATE, _environment, _write_feed
from yokohama_fare_coverage import YokohamaFareCoverage
from yokohama_transit import load_yokohama_bus_dataset

import sys
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_yokohama_initial_pass_coverage import proposed_coverage


def _realistic_named_fixture(root: Path) -> None:
    _write_feed(root)
    (root / "routes.txt").write_text(
        "route_id,route_short_name,route_long_name,route_type\n"
        "008,008系統,,3\n"
        "089,,89系統　ぶらり野毛山動物園BUS,3\n"
        "200,,ベイサイドブルー,3\n"
        "271,,観光スポット周遊バス「あかいくつ」,3\n"
        "280,,ぶらり三溪園BUS,3\n",
        encoding="utf-8",
    )
    (root / "trips.txt").write_text(
        "route_id,service_id,trip_id,trip_headsign,direction_id,jp_trip_desc,jp_trip_desc_symbol\n"
        "008,ALL,T8,桜木町駅前,0,,\n"
        "089,ALL,T89,桜木町駅前,0,,\n"
        "200,ALL,T200,桜木町駅前,0,,\n"
        "271,ALL,T271,桜木町駅前,0,,\n"
        "280,ALL,T280,桜木町駅前,0,,\n",
        encoding="utf-8",
    )
    (root / "stop_times.txt").write_text(
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T8,09:57:00,09:57:00,A,1\nT8,10:02:00,10:02:00,B,2\n"
        "T89,10:00:00,10:00:00,A,1\nT89,10:15:00,10:15:00,B,2\n"
        "T200,10:30:00,10:30:00,A,1\nT200,10:45:00,10:45:00,B,2\n"
        "T271,09:58:00,09:58:00,A,1\nT271,10:03:00,10:03:00,B,2\n"
        "T280,11:30:00,11:30:00,A,1\nT280,11:45:00,11:45:00,B,2\n",
        encoding="utf-8",
    )


class YokohamaPartialCoverageTest(unittest.TestCase):
    def test_proposal_produces_only_three_safe_ordinary_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _realistic_named_fixture(root)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            proposed, report = proposed_coverage(
                root, service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            after = {p.name: p.read_bytes() for p in root.iterdir()}
            self.assertEqual(before, after)
            self.assertEqual(report["route_count"], 5)
            kinds = proposed["routes"]
            self.assertEqual(kinds["yokohama_bus:089"], "local")
            self.assertEqual(kinds["yokohama_bus:200"], "local")
            self.assertEqual(kinds["yokohama_bus:280"], "local")
            self.assertEqual(kinds["yokohama_bus:271"], "sightseeing")
            self.assertEqual(kinds["yokohama_bus:008"], "unreviewed")

            path = root / "reviewed_partial.json"
            path.write_text(json.dumps(proposed), encoding="utf-8")
            dataset = load_yokohama_bus_dataset(
                root, expected_service_date=SERVICE_DATE,
            )
            covered = YokohamaFareCoverage.load(path, dataset=dataset)
            filtered = covered.municipal_free_coverage()
            self.assertEqual(set(filtered.dataset.routes), {
                "yokohama_bus:089", "yokohama_bus:200", "yokohama_bus:280",
            })

    def test_both_passes_ignore_faster_unreviewed_and_akai_kutsu_services(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _realistic_named_fixture(root)
            proposed, _ = proposed_coverage(
                root, service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            (root / "coverage.json").write_text(
                json.dumps(proposed), encoding="utf-8",
            )
            env = _environment(root)
            env["YOKOHAMA_REALTIME_MODE"] = "disabled"
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("ODPT_API_TOKEN", None)
                with TestClient(create_app("local")) as client:
                    for policy in (
                        "yokohama_welfare_special_pass",
                        "yokohama_senior_special_pass",
                    ):
                        with self.subTest(policy=policy):
                            response = client.post(
                                "/route", headers={"X-App-City": "yokohama"},
                                json={
                                    "alat": 35.4660, "alon": 139.6225,
                                    "blat": 35.4500, "blon": 139.6300,
                                    "pref": "shortTime", "start_time": "09:55",
                                    "target_date_str": SERVICE_DATE,
                                    "fare_policy_id": policy,
                                },
                            )
                            self.assertEqual(response.status_code, 200, response.text)
                            candidates = response.json()["candidates"]
                            self.assertEqual(len(candidates), 1)
                            ride = next(s for s in candidates[0]["steps"] if s["kind"] == "bus")
                            self.assertEqual(ride["route_id"], "yokohama_bus:089")
                            self.assertEqual(ride["trip_id"], "yokohama_bus:T89")
                            self.assertEqual(candidates[0]["fare"]["payNowYen"], 0)

    def test_smoke_can_verify_200_and_weekend_280_separately(self):
        from smoke_yokohama_real_gtfs import run_smoke

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _realistic_named_fixture(root)
            # The real 280 sightseeing route operates on weekends and
            # holidays, not an ordinary Friday. Model the same constraint.
            trips_path = root / "trips.txt"
            trips_path.write_text(
                trips_path.read_text(encoding="utf-8").replace(
                    "280,ALL,T280,", "280,WEEKEND,T280,"
                ),
                encoding="utf-8",
            )
            calendar_path = root / "calendar.txt"
            calendar_path.write_text(
                calendar_path.read_text(encoding="utf-8")
                + "WEEKEND,0,0,0,0,0,1,1,20260727,20270726\n",
                encoding="utf-8",
            )
            proposal, _ = proposed_coverage(
                root, service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            coverage_path = root / "coverage.json"
            coverage_path.write_text(
                json.dumps(proposal), encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "no active trips"):
                run_smoke(
                    gtfs_dir=root, coverage=coverage_path,
                    manifest_service_date=SERVICE_DATE,
                    ride_date="2026-09-04", route_id="280",
                )
            for route_id, ride_date, departure, arrival in (
                ("200", "2026-09-04", "10:30", "10:45"),
                ("280", "2026-09-05", "11:30", "11:45"),
            ):
                with self.subTest(route_id=route_id):
                    report = run_smoke(
                        gtfs_dir=root, coverage=coverage_path,
                        manifest_service_date=SERVICE_DATE,
                        ride_date=ride_date, route_id=route_id,
                    )
                    self.assertEqual(report["tested_route_id"], route_id)
                    self.assertEqual(report["ride_date"], ride_date)
                    self.assertEqual(
                        report["probe"]["route_id"], f"yokohama_bus:{route_id}",
                    )
                    self.assertEqual(report["probe"]["source_departure"], departure)
                    self.assertEqual(report["probe"]["source_arrival"], arrival)
                    self.assertEqual(len(report["results"]), 2)
                    for result in report["results"]:
                        self.assertEqual(result["result"], "PASS")
                        self.assertIn(f"yokohama_bus:{route_id}", result["route_ids"])
                        self.assertEqual(result["bus_departure"], departure)
                        self.assertEqual(result["arrival_at_requested_destination"], arrival)
                        self.assertEqual(result["additional_payment_yen"], 0)

    def test_loop_route_visits_same_stop_twice_but_selects_earliest_arrival(self):
        from smoke_yokohama_real_gtfs import run_smoke

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _realistic_named_fixture(root)
            # A -> B -> C -> B, with the same GTFS stop ID for both
            # occurrences of B. The source probe chooses the final B;
            # the route engine should alight at the first B.
            stops = root / "stops.txt"
            stops.write_text(
                stops.read_text(encoding="utf-8")
                + "C,循環中継点,35.4400,139.6450\n",
                encoding="utf-8",
            )
            times = root / "stop_times.txt"
            times.write_text(
                times.read_text(encoding="utf-8").replace(
                    "T200,10:45:00,10:45:00,B,2",
                    "T200,10:45:00,10:45:00,B,2\n"
                    "T200,11:00:00,11:00:00,C,3\n"
                    "T200,11:15:00,11:15:00,B,4",
                ),
                encoding="utf-8",
            )
            proposed, _ = proposed_coverage(
                root, service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            (root / "coverage.json").write_text(
                json.dumps(proposed), encoding="utf-8",
            )
            report = run_smoke(
                gtfs_dir=root, coverage=root / "coverage.json",
                manifest_service_date=SERVICE_DATE,
                ride_date=SERVICE_DATE, route_id="200",
            )
            self.assertEqual(report["probe"]["source_arrival"], "11:15")
            self.assertEqual(
                [x["arrival_time"] for x in report["probe"]["source_destination_visits"]],
                ["10:45", "11:15"],
            )
            self.assertTrue(report["probe"]["revisits_same_destination_stop"])
            for result in report["results"]:
                self.assertEqual(result["route_ids"], ["yokohama_bus:200"])
                self.assertEqual(result["bus_arrival_at_alighting_stop"], "10:45")
                self.assertEqual(result["arrival_at_requested_destination"], "10:45")
                self.assertEqual(result["final_walk_meters"], 0)
                self.assertEqual(result["additional_payment_yen"], 0)

    def test_real_feed_smoke_reports_early_alighting_and_final_walk(self):
        from smoke_yokohama_real_gtfs import run_smoke

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _realistic_named_fixture(root)
            # Extend 089 with a stop reached earlier than the requested
            # destination. Walking 100m from C should beat staying to B.
            stops_path = root / "stops.txt"
            stops_path.write_text(
                stops_path.read_text(encoding="utf-8")
                + "C,一本松手前,35.4500,139.6289\n",
                encoding="utf-8",
            )
            times_path = root / "stop_times.txt"
            times_path.write_text(
                times_path.read_text(encoding="utf-8").replace(
                    "T89,10:15:00,10:15:00,B,2",
                    "T89,10:11:00,10:11:00,C,2\n"
                    "T89,10:15:00,10:15:00,B,3",
                ),
                encoding="utf-8",
            )
            proposed, _ = proposed_coverage(
                root, service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            (root / "coverage.json").write_text(
                json.dumps(proposed), encoding="utf-8",
            )
            report = run_smoke(
                gtfs_dir=root,
                coverage=root / "coverage.json",
                manifest_service_date=SERVICE_DATE,
                ride_date=SERVICE_DATE,
            )
            self.assertEqual(report["probe"]["source_arrival"], "10:15")
            for result in report["results"]:
                self.assertEqual(result["bus_arrival_at_alighting_stop"], "10:11")
                self.assertEqual(result["alighting_stop"], "一本松手前")
                self.assertGreater(result["final_walk_meters"], 0)
                self.assertEqual(result["arrival_at_requested_destination"], "10:13")
                self.assertEqual(result["additional_payment_yen"], 0)

    def test_v2_api_ignores_faster_same_route_unreviewed_trip_for_both_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _realistic_named_fixture(root)
            trips_path = root / "trips.txt"
            trips_path.write_text(
                trips_path.read_text(encoding="utf-8")
                + "089,ALL,T89FAST,桜木町駅前,0,,\n",
                encoding="utf-8",
            )
            times_path = root / "stop_times.txt"
            times_path.write_text(
                times_path.read_text(encoding="utf-8")
                + "T89FAST,09:58:00,09:58:00,A,1\n"
                + "T89FAST,10:03:00,10:03:00,B,2\n",
                encoding="utf-8",
            )
            proposal, _ = proposed_coverage(
                root, service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            proposal["schema_version"] = 2
            proposal["reviewed_free_trips"] = {
                "yokohama_bus:T89": (
                    "https://www.city.yokohama.lg.jp/kotsu/bus/"
                ),
            }
            (root / "coverage.json").write_text(
                json.dumps(proposal), encoding="utf-8",
            )
            env = _environment(root)
            env["YOKOHAMA_REALTIME_MODE"] = "disabled"
            with patch.dict(os.environ, env, clear=False):
                with TestClient(create_app("local")) as client:
                    for policy in (
                        "yokohama_welfare_special_pass",
                        "yokohama_senior_special_pass",
                    ):
                        with self.subTest(policy=policy):
                            response = client.post(
                                "/route", headers={"X-App-City": "yokohama"},
                                json={
                                    "alat": 35.4660, "alon": 139.6225,
                                    "blat": 35.4500, "blon": 139.6300,
                                    "pref": "shortTime", "start_time": "09:55",
                                    "target_date_str": SERVICE_DATE,
                                    "fare_policy_id": policy,
                                },
                            )
                            self.assertEqual(response.status_code, 200, response.text)
                            candidates = response.json()["candidates"]
                            self.assertEqual(len(candidates), 1)
                            ride = next(
                                step for step in candidates[0]["steps"]
                                if step["kind"] == "bus"
                            )
                            self.assertEqual(ride["route_id"], "yokohama_bus:089")
                            self.assertEqual(ride["trip_id"], "yokohama_bus:T89")
                            self.assertEqual(ride["departure_time"], "10:00")
                            self.assertEqual(ride["arrival_time"], "10:15")
                            self.assertEqual(candidates[0]["fare"]["payNowYen"], 0)

    def test_real_feed_inspector_is_read_only_and_does_not_approve_trips(self):
        from inspect_yokohama_trip_evidence import inspect_route

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _realistic_named_fixture(root)
            proposal, _ = proposed_coverage(
                root, service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            coverage_path = root / "coverage.json"
            coverage_path.write_text(json.dumps(proposal), encoding="utf-8")
            original = {p.name: p.read_bytes() for p in root.iterdir()}
            result = inspect_route(
                gtfs_dir=root, coverage_path=coverage_path,
                manifest_service_date=SERVICE_DATE,
                ride_date=SERVICE_DATE, route_id="008",
            )
            self.assertEqual(
                {p.name: p.read_bytes() for p in root.iterdir()}, original
            )
            self.assertEqual(result["route_review_classification"], "unreviewed")
            self.assertEqual(result["coverage_schema"], 1)
            self.assertEqual(result["scheduled_trips_on_day"], 1)
            self.assertEqual(result["late_clock_review_flags_on_day"], 0)
            sample = result["daytime_and_other_nonflagged_samples"][0]
            self.assertEqual(sample["trip_id"], "yokohama_bus:T8")
            self.assertEqual(sample["from_stop"], "横浜駅前")
            self.assertEqual(sample["departure"], "09:57")
            self.assertFalse(sample["v2_explicitly_reviewed"])
            self.assertEqual(result["late_clock_samples"], [])
            with self.assertRaisesRegex(ValueError, "unknown route"):
                inspect_route(
                    gtfs_dir=root, coverage_path=coverage_path,
                    manifest_service_date=SERVICE_DATE,
                    ride_date=SERVICE_DATE, route_id="999",
                )
            with self.assertRaisesRegex(ValueError, "ASCII digits"):
                inspect_route(
                    gtfs_dir=root, coverage_path=coverage_path,
                    manifest_service_date=SERVICE_DATE,
                    ride_date=SERVICE_DATE, route_id="8",
                )
            with self.assertRaisesRegex(ValueError, "limit"):
                inspect_route(
                    gtfs_dir=root, coverage_path=coverage_path,
                    manifest_service_date=SERVICE_DATE,
                    ride_date=SERVICE_DATE, route_id="008", limit=0,
                )

    def test_route_008_proposal_keeps_original_coverage_and_searches_both_passes(self):
        from propose_yokohama_route_008_coverage import propose

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _realistic_named_fixture(root)
            original, _ = proposed_coverage(
                root, service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            source_path = root / "coverage.json"
            source_path.write_text(json.dumps(original), encoding="utf-8")
            originals = {p.name: p.read_bytes() for p in root.iterdir()}

            proposed, report = propose(
                gtfs_dir=root, coverage_path=source_path,
                service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            self.assertEqual(
                {p.name: p.read_bytes() for p in root.iterdir()}, originals,
                "proposal must be a read-only operation",
            )
            self.assertEqual(report["route_added"], "yokohama_bus:008")
            self.assertEqual(proposed["schema_version"], 1)
            self.assertEqual(proposed["routes"]["yokohama_bus:008"], "local")
            self.assertEqual(proposed["routes"]["yokohama_bus:271"], "sightseeing")
            self.assertEqual(
                {r for r, kind in proposed["routes"].items() if kind == "local"},
                {"yokohama_bus:008", "yokohama_bus:089",
                 "yokohama_bus:200", "yokohama_bus:280"},
            )
            new_path = root / "four_route_dev.json"
            new_path.write_text(json.dumps(proposed), encoding="utf-8")
            env = _environment(root)
            env["YOKOHAMA_REALTIME_MODE"] = "disabled"
            env["YOKOHAMA_FARE_COVERAGE_PATH"] = str(new_path)
            with patch.dict(os.environ, env, clear=False):
                with TestClient(create_app("local")) as client:
                    for policy_id in (
                        "yokohama_welfare_special_pass",
                        "yokohama_senior_special_pass",
                    ):
                        with self.subTest(policy=policy_id):
                            response = client.post(
                                "/route", headers={"X-App-City": "yokohama"},
                                json={
                                    "alat": 35.4660, "alon": 139.6225,
                                    "blat": 35.4500, "blon": 139.6300,
                                    "pref": "shortTime", "start_time": "09:55",
                                    "target_date_str": SERVICE_DATE,
                                    "fare_policy_id": policy_id,
                                },
                            )
                            self.assertEqual(response.status_code, 200, response.text)
                            candidates = response.json()["candidates"]
                            self.assertEqual(len(candidates), 1)
                            ride = next(
                                step for step in candidates[0]["steps"]
                                if step["kind"] == "bus"
                            )
                            self.assertEqual(ride["route_id"], "yokohama_bus:008")
                            self.assertEqual(ride["trip_id"], "yokohama_bus:T8")
                            self.assertEqual(ride["departure_time"], "09:57")
                            self.assertEqual(ride["arrival_time"], "10:02")
                            self.assertEqual(candidates[0]["fare"]["payNowYen"], 0)

    def test_route_008_proposal_refuses_modified_route_identifiers(self):
        from propose_yokohama_route_008_coverage import propose

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _realistic_named_fixture(root)
            original, _ = proposed_coverage(
                root, service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            original_path = root / "coverage.json"
            original_path.write_text(json.dumps(original), encoding="utf-8")
            before = root / "routes.txt"
            before.write_text(
                before.read_text(encoding="utf-8").replace("008系統", "別系統"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "name/identity changed"):
                propose(
                    gtfs_dir=root, coverage_path=original_path,
                    service_date=SERVICE_DATE, reviewed_on="2026-10-14",
                )

    def test_008_real_gtfs_smoke_requires_four_route_proposal_and_preserves_original(self):
        from propose_yokohama_route_008_coverage import propose
        from smoke_yokohama_real_gtfs import run_smoke

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _realistic_named_fixture(root)
            # A daytime 008 trip with 15-minute travel; the original
            # synthetic 008 was 5 minutes and cannot be a smoke probe.
            times = root / "stop_times.txt"
            times.write_text(
                times.read_text(encoding="utf-8").replace(
                    "T8,10:02:00,10:02:00,B,2",
                    "T8,10:12:00,10:12:00,B,2",
                ),
                encoding="utf-8",
            )
            original, _ = proposed_coverage(
                root, service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            base_path = root / "coverage.json"
            base_path.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "route 008 requires"):
                run_smoke(
                    gtfs_dir=root, coverage=base_path,
                    manifest_service_date=SERVICE_DATE,
                    ride_date=SERVICE_DATE, route_id="008",
                )

            extended, _ = propose(
                gtfs_dir=root, coverage_path=base_path,
                service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            proposed_path = root / "coverage_dev_008.json"
            proposed_path.write_text(json.dumps(extended), encoding="utf-8")
            prior = {p.name: p.read_bytes() for p in root.iterdir()}
            result = run_smoke(
                gtfs_dir=root, coverage=proposed_path,
                manifest_service_date=SERVICE_DATE,
                ride_date=SERVICE_DATE, route_id="008",
            )
            self.assertEqual(
                prior, {p.name: p.read_bytes() for p in root.iterdir()},
                "smoke must not modify GTFS or either coverage file",
            )
            self.assertEqual(result["tested_route_id"], "008")
            self.assertEqual(result["probe"]["route_id"], "yokohama_bus:008")
            self.assertEqual(result["probe"]["source_departure"], "09:57")
            self.assertEqual(result["probe"]["source_arrival"], "10:12")
            self.assertEqual(len(result["development_coverage_routes"]), 4)
            self.assertEqual(len(result["results"]), 2)
            for policy in result["results"]:
                self.assertEqual(policy["route_ids"], ["yokohama_bus:008"])
                self.assertEqual(policy["bus_departure"], "09:57")
                self.assertEqual(policy["arrival_at_requested_destination"], "10:12")
                self.assertEqual(policy["additional_payment_yen"], 0)
                self.assertEqual(policy["result"], "PASS")

    def test_all_route_catalog_prioritizes_exceptions_without_approving_them(self):
        from review_yokohama_bus_route_catalog import review_catalog

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _realistic_named_fixture(root)
            routes = root / "routes.txt"
            routes.write_text(
                routes.read_text(encoding="utf-8")
                + "091,,【急行】91系統,3\n",
                encoding="utf-8",
            )
            trips = root / "trips.txt"
            trips.write_text(
                trips.read_text(encoding="utf-8")
                + "091,ALL,T91,直行便,0,,\n",
                encoding="utf-8",
            )
            times = root / "stop_times.txt"
            times.write_text(
                times.read_text(encoding="utf-8")
                + "T91,08:30:00,08:30:00,A,1\n"
                "T91,08:50:00,08:50:00,B,2\n",
                encoding="utf-8",
            )
            proposal, _ = proposed_coverage(
                root, service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            source = root / "coverage.json"
            source.write_text(json.dumps(proposal), encoding="utf-8")
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            result = review_catalog(
                gtfs_dir=root, coverage_path=source,
                manifest_service_date=SERVICE_DATE,
                ride_dates=[SERVICE_DATE, "2026-10-15"],
            )
            self.assertEqual(
                before, {p.name: p.read_bytes() for p in root.iterdir()}
            )
            self.assertEqual(result["route_count"], 6)
            self.assertEqual(
                result["review_queue_counts"],
                {
                    "enabled_in_development_coverage": 3,
                    "excluded_in_current_coverage": 1,
                    "exception_terms_need_manual_review": 1,
                    "nonstandard_name_need_manual_review": 0,
                    "ordinary_name_candidate_not_approved": 1,
                },
            )
            flagged = result["groups"]["exception_terms_need_manual_review"][0]
            self.assertEqual(flagged["route_id"], "091")
            self.assertEqual(flagged["exception_terms"], ["直行"])
            self.assertEqual(flagged["other_unusual_terms"], ["急行"])
            self.assertEqual(flagged["current_coverage_kind"], "unreviewed")
            self.assertEqual(
                result["groups"]["ordinary_name_candidate_not_approved"][0]["route_id"],
                "008",
            )
            self.assertEqual(
                result["groups"]["excluded_in_current_coverage"][0]["route_id"],
                "271",
            )
            self.assertEqual(result["file_action"], "READ ONLY: no files created or modified")

    def test_all_route_catalog_uses_four_route_dev_coverage_without_mutating_baseline(self):
        from propose_yokohama_route_008_coverage import propose
        from review_yokohama_bus_route_catalog import review_catalog

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _realistic_named_fixture(root)
            baseline, _ = proposed_coverage(
                root, service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            source = root / "coverage.json"
            source.write_text(json.dumps(baseline), encoding="utf-8")
            four, _ = propose(
                gtfs_dir=root, coverage_path=source,
                service_date=SERVICE_DATE, reviewed_on="2026-10-14",
            )
            extended = root / "coverage_dev_008.json"
            extended.write_text(json.dumps(four), encoding="utf-8")
            original_bytes = source.read_bytes()
            result = review_catalog(
                gtfs_dir=root, coverage_path=extended,
                manifest_service_date=SERVICE_DATE, ride_dates=[SERVICE_DATE],
            )
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(result["reviewable_unapproved_routes"], 0)
            self.assertEqual(result["review_queue_counts"]["enabled_in_development_coverage"], 4)
            self.assertEqual(result["review_queue_counts"]["excluded_in_current_coverage"], 1)
            self.assertEqual(
                {x["route_id"] for x in result["groups"]["enabled_in_development_coverage"]},
                {"008", "089", "200", "280"},
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                review_catalog(
                    gtfs_dir=root, coverage_path=extended,
                    manifest_service_date=SERVICE_DATE,
                    ride_dates=[SERVICE_DATE, SERVICE_DATE],
                )
            with self.assertRaisesRegex(ValueError, "at least one"):
                review_catalog(
                    gtfs_dir=root, coverage_path=extended,
                    manifest_service_date=SERVICE_DATE, ride_dates=[],
                )

    def test_known_route_rename_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _realistic_named_fixture(root)
            path = root / "routes.txt"
            path.write_text(
                path.read_text(encoding="utf-8").replace("ベイサイドブルー", "新しい別路線"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "changed name"):
                proposed_coverage(
                    root, service_date=SERVICE_DATE, reviewed_on="2026-10-14",
                )


if __name__ == "__main__":
    unittest.main()
