"""New finite-period helper regressions; synthetic reviews, no existing gates."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime
import json
import unittest

from sendai_operating_period import NORMAL_RULE, HolidayPeriodReview, OperatingPeriodReview
from transit_adapters.sendai_subway import Evidence
from transit_adapters.sendai_subway_practical import DayClassification, FiniteOperatingDays


def review():
    # Deliberately synthetic evidence; these tests certify no live timetable.
    return OperatingPeriodReview(
        date(2026, 10, 11), date(2026, 11, 4), date(2026, 10, 12), date(2026, 11, 3),
        date(2026, 10, 16),
        (Evidence("https://www.city.sendai.jp/synthetic-normal-timetable", "a" * 64),),
        (Evidence("https://www.kotsu.city.sendai.jp/synthetic-notices", "b" * 64),),
        HolidayPeriodReview(date(2026, 10, 1), date(2026, 11, 30),
            "https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html", "c" * 64,
            ((date(2026, 10, 12), "Sports Day"), (date(2026, 11, 3), "Culture Day"),
             (date(2026, 11, 23), "Labour Thanksgiving Day"))),
        (), "Synthetic normal timetable only; special services and later changes are not verified.")


class OperatingPeriodTests(unittest.TestCase):
    def test_bounded_normal_weekday_weekend_and_official_holidays(self):
        table = review().operating_days()
        self.assertIsInstance(table, FiniteOperatingDays)
        self.assertEqual(len(table.entries), 25)
        for d, expected in ((date(2026, 10, 12), "h"), (date(2026, 10, 19), "w"),
                            (date(2026, 10, 24), "h"), (date(2026, 11, 3), "h")):
            self.assertEqual(table.kind_on(d), expected)
        with self.assertRaisesRegex(ValueError, "not in finite reviewed table"):
            table.kind_on(date(2026, 11, 5))

    def test_holiday_source_coverage_cannot_be_silently_extended(self):
        r = review()
        with self.assertRaisesRegex(ValueError, "holiday evidence"):
            replace(r, coverage_end=date(2026, 12, 1))
        with self.assertRaisesRegex(ValueError, "coverage"):
            replace(r.holiday_review, start=date(2026, 12, 1))

    def test_explicit_exclusion_wins_over_holiday_or_weekend(self):
        for day in (date(2026, 10, 12), date(2026, 10, 25)):
            r = replace(review(), exclusions=(DayClassification(day, None, "special timetable unreviewed"),))
            with self.assertRaisesRegex(ValueError, "special timetable unreviewed"):
                r.operating_days().kind_on(day)

    def test_no_implicit_bus_calendar_or_date_classification(self):
        r = review()
        day = date(2026, 10, 19)
        self.assertEqual(r.operating_days().kind_on(day), "w")
        with self.assertRaisesRegex(ValueError, "independent bus/transfer"):
            r.require_query_days(day, (day,), additional_reviewed_days=(frozenset(),))
        self.assertEqual(r.advertised_dates(service_day_offsets=(0,),
                                           additional_reviewed_days=(frozenset(),)), ())

    def test_query_window_excludes_internal_boundary_days(self):
        r = review()
        dates = r.advertised_dates(service_day_offsets=(-1, 0, 1))
        self.assertEqual(dates[0], r.query_start)
        self.assertEqual(dates[-1], r.query_end)
        self.assertNotIn(r.coverage_start, dates)
        self.assertNotIn(r.coverage_end, dates)
        with self.assertRaisesRegex(ValueError, "advertised"):
            r.require_query_days(r.coverage_start, (r.coverage_start,))

    def test_envelope_does_not_advertise_missing_previous_or_next_day(self):
        r = review()
        r = replace(r, query_start=r.coverage_start, query_end=r.coverage_end)
        dates = r.advertised_dates(service_day_offsets=(-1, 0, 1))
        self.assertNotIn(r.coverage_start, dates)
        self.assertNotIn(r.coverage_end, dates)
        wider = r.advertised_dates(service_day_offsets=(-1, 0, 1, 2))
        self.assertNotIn(date(2026, 11, 3), wider)

    def test_excluded_dependency_blocks_query_not_just_its_own_date(self):
        r = replace(review(), exclusions=(DayClassification(date(2026, 10, 25), None, "unreviewed special day"),))
        dates = r.advertised_dates(service_day_offsets=(-1, 0, 1))
        for n in (24, 25, 26):
            self.assertNotIn(date(2026, 10, n), dates)
        with self.assertRaisesRegex(ValueError, "excluded operating day"):
            r.require_query_days(date(2026, 10, 24), (date(2026, 10, 24), date(2026, 10, 25)))
        # An exact query dependency with no next-day use remains allowed.
        self.assertEqual(r.require_query_days(date(2026, 10, 24), (date(2026, 10, 24),)),
                         (date(2026, 10, 24),))

    def test_independent_bus_and_transfer_sets_intersect_without_reclassifying_subway(self):
        r = review()
        all_days = frozenset(e.day for e in r.operating_days().entries)
        missing = date(2026, 10, 25)
        bus = all_days - {missing}
        dates = r.advertised_dates(service_day_offsets=(-1, 0, 1),
                                   additional_reviewed_days=(bus, all_days))
        self.assertEqual(r.operating_days().kind_on(missing), "h")
        self.assertNotIn(date(2026, 10, 24), dates)
        with self.assertRaisesRegex(ValueError, "2026-10-25"):
            r.require_query_days(date(2026, 10, 26), (missing, date(2026, 10, 26)),
                                 additional_reviewed_days=(bus, all_days))

    def test_exact_dependency_outside_coverage_stops_not_partial_success(self):
        r = review()
        with self.assertRaisesRegex(ValueError, "unsupported operating day"):
            r.require_query_days(date(2026, 11, 3),
                                 (date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)))

    def test_json_roundtrip_retains_sources_bounds_assumption_and_false_guarantee(self):
        r = review()
        raw = json.loads(json.dumps(r.to_mapping()))
        self.assertEqual(raw["normal_timetable_rule"], NORMAL_RULE)
        self.assertIs(raw["special_timetables_verified"], False)
        self.assertEqual(OperatingPeriodReview.from_mapping(raw), r)
        table = r.operating_days()
        self.assertEqual(table.evidence, r.normal_timetable_sources + r.change_notice_sources)
        self.assertEqual(table.holiday_source_sha256, "c" * 64)
        self.assertEqual(table.reviewed_at, date(2026, 10, 16))
        raw["normal_timetable_sources"][0]["sha256"] = "d" * 64
        self.assertEqual(r.normal_timetable_sources[0].sha256, "a" * 64)

    def test_wrong_schema_feed_rule_claim_or_unrecognized_field_rejected(self):
        changes = ({"schema_version": True}, {"schema_version": 2}, {"feed_id": "sendai_bus"},
                   {"normal_timetable_rule": "gtfs_weekday_flags"},
                   {"special_timetables_verified": True}, {"normal_timetable_only": False},
                   {"fallback": "weekday"})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                OperatingPeriodReview.from_mapping({**review().to_mapping(), **change})

    def test_missing_evidence_or_assumption_rejected(self):
        for change in ({"normal_timetable_sources": ()}, {"change_notice_sources": ()},
                       {"assumption_note": " "}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(review(), **change)

    def test_invalid_holiday_origin_hash_duplicate_and_coverage_rejected(self):
        h = review().holiday_review
        for change in ({"source_uri": "https://example.com/calendar"},
                       {"source_uri": "https://www8.cao.go.jp:443/calendar"},
                       {"source_sha256": "A" * 64}, {"holidays": h.holidays + (h.holidays[0],)},
                       {"holidays": ((date(2027, 1, 1), "outside"),)},
                       {"holidays": ((date(2026, 10, 12), ""),)}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(h, **change)

    def test_wrong_date_types_inverted_bounds_and_duplicate_exclusions_rejected(self):
        e = DayClassification(date(2026, 10, 25), None, "excluded")
        for change in ({"coverage_start": datetime(2026, 10, 11)},
                       {"query_end": date(2026, 10, 1)}, {"exclusions": (e, e)},
                       {"exclusions": (DayClassification(date(2026, 10, 25), "h", "override"),)}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(review(), **change)

    def test_invalid_dependencies_offsets_or_implicit_mutable_sets_rejected(self):
        r = review()
        day = date(2026, 10, 19)
        for dependencies in ((), (day, day), (date(2026, 10, 20),), [day]):
            with self.subTest(dependencies=dependencies), self.assertRaises(ValueError):
                r.require_query_days(day, dependencies)
        for offsets in ((), (1,), (0, 0), (False,), [0]):
            with self.subTest(offsets=offsets), self.assertRaises(ValueError):
                r.advertised_dates(service_day_offsets=offsets)
        for extra in ([frozenset({day})], ({day},), (frozenset({"2026-10-19"}),)):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                r.require_query_days(day, (day,), additional_reviewed_days=extra)

    def test_noncanonical_dates_unknown_nested_fields_and_missing_lists_rejected(self):
        for field, value in (("query_start", "20261012"), ("reviewed_at", None),
                             ("exclusions", None), ("normal_timetable_sources", {})):
            raw = review().to_mapping()
            raw[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                OperatingPeriodReview.from_mapping(raw)
        raw = deepcopy(review().to_mapping())
        raw["holiday_review"]["unreviewed_default"] = "h"
        with self.assertRaises(ValueError):
            OperatingPeriodReview.from_mapping(raw)


if __name__ == "__main__":
    unittest.main()
