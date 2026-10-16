"""November-only finite service coverage, unchanged SearchCore v2 and raw oracles."""
import contextlib
from datetime import date
import io
import json
import sys
from pathlib import Path
import unittest

from fastapi.testclient import TestClient
from app.sendai_practical_routes import create_sendai_practical_test_app
from sendai_operating_period import OperatingPeriodReview
from sendai_practical_bundle import build_reviewed_municipal_model, load_reviewed_subway
from sendai_practical_network import PracticalRide, search_practical_subway
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_municipal_oracle import optimum, raw_services, runs, validate
from tests.test_sendai_arai21_practical import load_bus
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.check_sendai_expansion import raw_day_kinds

ROOT = Path(__file__).parent / "fixtures" / "sendai_subway"


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


class NovemberStage3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = read("municipal_bus_subset_20261006_stage2.json")
        cls.review = read("municipal_review_20261017_stage3.json")
        cls.previous = read("municipal_review_20261016_stage2.json")
        cls.matrix = read("municipal_fixed_cases_20261017_stage3.json")
        cls.period = OperatingPeriodReview.from_mapping(cls.review["operating_period"])
        cls.kinds = raw_day_kinds(cls.review["operating_period"])
        cls.bus = load_bus(cls.source, cls.review)
        cls.subway, cls.raw_subway = load_reviewed_subway(
            ROOT / "published_20230701.json", ROOT / "practical_review_20261016.json",
            operating_period=cls.period)
        cls.network = build_reviewed_municipal_model(
            cls.subway, cls.bus, cls.review, accept_experimental_bus_transfers=True)
        cls.params = NetworkSearchParameters(**cls.matrix["parameters"])
        cls.client = TestClient(create_sendai_practical_test_app(
            cls.network, environment="test", parameters=cls.params,
            operating_period=cls.period, coverage_label=cls.review["coverage_label"]))

    def request(self, day, origin="sendai_bus:1294_10", destination="sendai_bus:1085_0", minute=540):
        return self.client.post("/test/sendai/route", json=dict(
            origin_stop_id=origin, destination_stop_id=destination, civil_date=day,
            departure_minute=minute, fare_policy_id="sendai_fureai_pass",
            accept_experimental_transfer_model=True))

    def test_finite_dates_holidays_exclusions_and_boundary(self):
        caps = self.client.get("/test/sendai/capabilities").json()
        days = caps["operating_dates"]
        self.assertEqual((len(days), days[0], days[-1]), (48, "2026-10-12", "2026-11-30"))
        for day in ("2026-10-25", "2026-11-22", "2026-12-01"):
            self.assertNotIn(day, days)
            self.assertEqual(self.request(day).status_code, 422)
        for day in ("2026-11-03", "2026-11-23"):
            self.assertEqual(self.period.operating_days().kind_on(date.fromisoformat(day)), "h")
            services = raw_services(self.source["files"], date.fromisoformat(day))
            self.assertIn("O_20_3", services)
            self.assertNotIn("O_20_1", services)
        self.assertEqual(self.period.operating_days().kind_on(date(2026, 11, 21)), "h")
        self.assertEqual(self.period.operating_days().kind_on(date(2026, 11, 19)), "w")
        self.assertEqual(self.request("2026-11-30").status_code, 200)
        # At the GTFS endpoint the next service day has not been approved.
        self.assertEqual(self.request("2026-11-30", minute=1380).status_code, 422)
        self.assertFalse(caps["actual_connection_guaranteed"])
        self.assertFalse(caps["special_timetables_verified"])

    def test_seven_november_oracles_and_api_witnesses(self):
        self.assertEqual(len(self.matrix["cases"]), 7)
        for case in self.matrix["cases"]:
            with self.subTest(case=case["category"]):
                day = date.fromisoformat(case["civil_date"])
                raw = runs(self.source["files"], self.raw_subway, self.kinds, day, self.review)
                expected = optimum(raw, self.review, case["origin"], case["destination"],
                    case["departure_minute"], max_boardings=3, max_minutes=180)
                self.assertIsNotNone(expected)
                if case["expected_arrival_minute"] is not None:
                    self.assertEqual(expected, case["expected_arrival_minute"])
                with contextlib.redirect_stdout(io.StringIO()):
                    result = search_practical_subway(self.network, case["origin"], case["destination"],
                        civil_date=day, departure_minute=case["departure_minute"], parameters=self.params)
                self.assertEqual(len(result), 1)
                journey = result[0]
                self.assertEqual(journey.arrival_estimate.minute, expected)
                validate(journey, raw, self.review, day, case["origin"], case["destination"], case["departure_minute"])
                rides = [e.source for e in journey.events if isinstance(e, PracticalRide)]
                self.assertEqual([r.mode for r in rides], case["modes"])
                if "required_route_id" in case:
                    self.assertIn(case["required_route_id"],
                        {self.bus.trips[r.trip_id].route_id for r in rides if r.mode == "bus"})
                with contextlib.redirect_stdout(io.StringIO()):
                    response = self.request(case["civil_date"], case["origin"], case["destination"],
                        case["departure_minute"])
                self.assertEqual(response.status_code, 200, response.text)
                wire = response.json()["candidates"][0]
                self.assertEqual(wire["arrival"]["minute"],
                    {"numerator": int(expected), "denominator": 1})
                self.assertEqual(wire["fare"]["additional_payment_yen"], 0)
                self.assertIsNone(wire["fare"]["normal_fare_yen"])
                self.assertFalse(wire["actual_connection_guaranteed"])

    def test_review_only_extends_days_not_scope_or_shared_search(self):
        self.assertEqual(self.review["bus_patterns"], self.previous["bus_patterns"])
        self.assertEqual(self.review["bus_subway_transfers"], self.previous["bus_subway_transfers"])
        self.assertEqual(self.review["bus_excluded_days"], self.previous["bus_excluded_days"])
        self.assertEqual(self.review["bus_feed_version"], self.previous["bus_feed_version"])
        self.assertEqual(self.review["subway_transfer_margin_minutes"], self.previous["subway_transfer_margin_minutes"])
        self.assertEqual(sum(t.startswith("sendai_bus:") for t in self.network.free_scope.allowed_trip_ids), 197)


if __name__ == "__main__":
    unittest.main()
