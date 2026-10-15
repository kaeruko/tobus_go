"""Explicit ordered-run clocks retain seconds and preserve the default adapter."""
from dataclasses import replace
from datetime import date, datetime, timezone
from fractions import Fraction
import unittest

from transit_adapters.odpt import OdptCalendarRule, OdptTransitAdapter
from transit_dataset import FeedMetadata
from transit_network import NetworkCosts, build_transit_network

DAY = date(2026, 10, 15)
RULE = OdptCalendarRule((True,) * 7, DAY, DAY)


def build(objects, *, convention='ordered_run', rule=RULE):
    return OdptTransitAdapter.build(
        metadata=FeedMetadata('test', 'odpt', 'https://example.invalid', 'fixture',
                              datetime(2026, 10, 15, tzinfo=timezone.utc)),
        stations=[{'owl:sameAs': s, 'dc:title': s, 'geo:lat': 35., 'geo:long': 139.} for s in 'ABC'],
        railways=[{'owl:sameAs': 'rail', 'dc:title': 'Rail'}],
        train_timetables=[{'owl:sameAs': 'run', 'odpt:railway': 'rail', 'odpt:calendar': 'calendar',
                           'odpt:trainNumber': '1', 'odpt:trainTimetableObject': objects}],
        calendar_rules={'calendar': rule}, train_clock_convention=convention)


def stops(first='23:58:59', arrival='00:01:01', departure='00:02:02', last='00:05:03'):
    return [{'odpt:departureStation': 'A', 'odpt:departureTime': first},
            {'odpt:arrivalStation': 'B', 'odpt:departureStation': 'B',
             'odpt:arrivalTime': arrival, 'odpt:departureTime': departure},
            {'odpt:arrivalStation': 'A', 'odpt:arrivalTime': last}]


class OrderedTrainClocksTest(unittest.TestCase):
    def test_seconds_midnight_dwell_and_repeated_stop_remain_exact(self):
        dataset = build(stops())
        rows = dataset.stop_times
        self.assertEqual(rows[0].departure_service_seconds, 86339)
        self.assertEqual(rows[1].arrival_service_seconds, 86461)
        self.assertEqual(rows[1].departure_service_seconds, 86522)
        self.assertEqual(rows[2].arrival_service_seconds, 86703)
        self.assertIsNone(rows[0].arrival_service_seconds)
        self.assertIsNone(rows[-1].departure_service_seconds)
        snapshot = build_transit_network((dataset,), allowed_trip_ids=dataset.trips, costs=NetworkCosts(), walking_links=())
        scheduled = snapshot.rows_by_trip['test:run']
        self.assertEqual(scheduled[1].arrival_minute, Fraction(86461, 60))
        self.assertEqual([r.stop_id for r in scheduled], ['test:A', 'test:B', 'test:A'])

    def test_first_midnight_trip_stays_on_its_first_civil_date(self):
        rows = build(stops('00:00:01', '00:01:02', '00:02:03', '00:03:04')).stop_times
        self.assertEqual(rows[0].departure_service_seconds, 1)
        self.assertEqual(rows[-1].arrival_service_seconds, 184)

    def test_existing_24_plus_clocks_not_rewrapped_and_multiple_rollovers(self):
        rows = build(stops('47:59:59', '00:00:01', '00:00:02', '00:01:03')).stop_times
        self.assertEqual(rows[1].arrival_service_seconds, 172801)
        self.assertEqual(rows[-1].arrival_service_seconds, 172863)

    def test_equal_clocks_zero_duration_and_departure_rollover(self):
        rows = build(stops('23:59:59', '23:59:59', '00:00:01', '00:00:01')).stop_times
        self.assertEqual(rows[1].arrival_service_seconds, 86399)
        self.assertEqual(rows[1].departure_service_seconds, 86401)
        self.assertEqual(rows[2].arrival_service_seconds, 86401)

    def test_calendar_boundary_default_does_not_gain_ordered_rollover(self):
        default = build(stops(), convention='calendar_boundary')
        self.assertEqual(default.stop_times[1].arrival_service_seconds, 61)
        with self.assertRaisesRegex(ValueError, 'trip goes backwards'):
            build_transit_network((default,), allowed_trip_ids=default.trips, costs=NetworkCosts(), walking_links=())
        boundary = build(stops(), convention='calendar_boundary', rule=replace(RULE, service_day_start_second=10800))
        self.assertEqual(boundary.stop_times[1].arrival_service_seconds, 86461)

    def test_unknown_profile_boundary_conflict_and_missing_clock_fail(self):
        with self.assertRaisesRegex(ValueError, 'unsupported train clock convention'):
            build(stops(), convention='auto')
        with self.assertRaisesRegex(ValueError, 'conflict'):
            build(stops(), rule=replace(RULE, service_day_start_second=10800))
        for index, key in ((0, 'odpt:departureTime'), (1, 'odpt:arrivalTime'), (1, 'odpt:departureTime'), (2, 'odpt:arrivalTime')):
            objects = stops()
            del objects[index][key]
            with self.subTest(index=index, key=key), self.assertRaisesRegex(ValueError, 'missing ordered train clock'):
                build(objects)

    def test_invalid_clock_retains_original_cause(self):
        with self.assertRaisesRegex(ValueError, 'sequence=1') as error:
            build(stops(first='23:99:01'))
        self.assertIsInstance(error.exception.__cause__, ValueError)


if __name__ == '__main__':
    unittest.main()
