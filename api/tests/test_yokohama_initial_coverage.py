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
