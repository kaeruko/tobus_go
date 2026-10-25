import json
import unittest
from datetime import date
from pathlib import Path

import jpholiday


ROOT = Path(__file__).resolve().parents[2]
CORPUS = (
    ROOT
    / "api"
    / "benchmarks"
    / "tokyo_metro_release_2026_10_25"
    / "corpus.json"
)


class TokyoMetroReleaseCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = CORPUS.read_text(encoding="utf-8")
        cls.corpus = json.loads(cls.raw)

    def test_fixed_matrix_covers_all_scopes_modes_limits_and_transfer_modes(self):
        expected_scopes = {
            frozenset(("toei_bus",)),
            frozenset(("toei_subway",)),
            frozenset(("tokyo_metro",)),
            frozenset(("toei_bus", "toei_subway")),
            frozenset(("toei_bus", "tokyo_metro")),
            frozenset(("toei_subway", "tokyo_metro")),
            frozenset(("toei_bus", "toei_subway", "tokyo_metro")),
        }
        self.assertEqual(
            {frozenset(case["scope"]) for case in self.corpus["matrix_cases"]},
            expected_scopes,
        )
        contract = self.corpus["fixed_contract"]
        self.assertEqual(contract["modes"], ["time", "fewTransfers"])
        self.assertEqual(contract["candidate_limits"], [1, 2, 3, 4, 5])
        self.assertEqual(contract["estimated_transfer_modes"], [False, True])

    def test_supplemental_coverage_is_fixed(self):
        tags = {
            tag
            for case in self.corpus["supplemental_cases"]
            for tag in case["tags"]
        }
        self.assertTrue(
            {
                "weekend",
                "public_holiday",
                "last_train",
                "date_crossing",
                "reviewed_transfer",
                "direction_forward",
                "direction_reverse",
                "multi_line",
                "estimated_transfer",
                "unreachable_without_estimated_transfers",
                "walking_access_probe",
            }.issubset(tags)
        )
        synthetic = {
            cover
            for row in self.corpus["synthetic_contract_tests"]
            for cover in row["covers"]
        }
        self.assertTrue(
            {
                "transfer_feasibility",
                "missed_train_rejected",
                "direction_exception",
                "closed_time_window",
                "walking_resource_limit",
            }.issubset(synthetic)
        )

    def test_limits_and_feed_are_not_relaxed(self):
        contract = self.corpus["fixed_contract"]
        self.assertEqual(contract["time_limit_seconds"], 15)
        self.assertEqual(contract["pop_limit"], 100000)
        self.assertEqual(contract["max_travel_minutes"], 240)
        self.assertEqual(self.corpus["feed"]["version"], "20261008")
        self.assertEqual(len(self.corpus["feed"]["archive_sha256"]), 64)

    def test_public_holiday_is_a_real_holiday_not_a_weekend_label(self):
        holiday_cases = [
            case
            for case in self.corpus["supplemental_cases"]
            if "public_holiday" in case["tags"]
        ]
        self.assertEqual(len(holiday_cases), 1)
        case = holiday_cases[0]
        service_date = date.fromisoformat(case["date"])
        expectation = case["calendar_expectation"]

        self.assertEqual(service_date, date(2026, 10, 12))
        self.assertEqual(service_date.weekday(), 0)  # Monday, not a weekend.
        self.assertTrue(jpholiday.is_holiday(service_date))
        self.assertEqual(jpholiday.is_holiday_name(service_date), "スポーツの日")
        self.assertEqual(expectation["official_name_en"], "Sports Day")
        self.assertTrue(expectation["official_holiday"])
        self.assertEqual(expectation["civil_day_type"], "holiday")
        self.assertEqual(expectation["gtfs_removed_service_ids"], ["0"])
        self.assertEqual(expectation["gtfs_added_service_ids"], ["1"])

    def test_corpus_contains_no_secret_or_authenticated_source_data(self):
        lowered = self.raw.lower()
        for forbidden in (
            "api_key",
            "apikey",
            "consumerkey",
            "authorization:",
            "bearer ",
        ):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
