"""Bounded route-10030 expansion on the unchanged stage-one transfer model.

Only the expanded bundle is searched; previous audit suites are not invoked.
Expected arrivals are fixed from retained raw rows before model search.
"""
import contextlib
import copy
import csv
from datetime import date
import io
import json
from pathlib import Path
import sys
import unittest

from fastapi.testclient import TestClient
from app.sendai_practical_routes import create_sendai_practical_test_app
from sendai_operating_period import OperatingPeriodReview
from sendai_practical_bundle import build_reviewed_municipal_model, load_reviewed_subway
from sendai_practical_network import PracticalRide, search_practical_subway
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_municipal_oracle import optimum, rows, runs, validate
from tests.test_sendai_arai21_practical import load_bus

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.check_sendai_expansion import raw_day_kinds

FIXTURE = Path(__file__).parent / 'fixtures/sendai_subway'
ROUTE = 'sendai_bus:10030'


def read_fixture(name):
    return json.loads((FIXTURE / name).read_text(encoding='utf-8'))


def replace_rows(source, name, records):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=list(records[0]))
    writer.writeheader()
    writer.writerows(records)
    source['files'][name] = output.getvalue()


class SendaiStage2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = read_fixture('municipal_bus_subset_20261006_stage2.json')
        cls.review = read_fixture('municipal_review_20261016_stage2.json')
        cls.previous_review = read_fixture('municipal_review_20261016_stage1.json')
        cls.matrix = read_fixture('municipal_fixed_cases_20261016_stage2.json')
        cls.previous_matrix = read_fixture('municipal_fixed_cases_20261016_stage1.json')
        cls.period = OperatingPeriodReview.from_mapping(cls.review['operating_period'])
        cls.parameters = NetworkSearchParameters(**cls.matrix['parameters'])
        cls.bus = load_bus(cls.source, cls.review)
        cls.subway, cls.raw_subway = load_reviewed_subway(
            FIXTURE / 'published_20230701.json', FIXTURE / 'practical_review_20261016.json',
            operating_period=cls.period)
        cls.network = cls.build(cls.bus, cls.review)
        cls.client = cls.app(cls.network, cls.review)
        cls.kinds = raw_day_kinds(cls.review['operating_period'])
        cls.raw_cache = {}

    @classmethod
    def build(cls, bus, review):
        return build_reviewed_municipal_model(cls.subway, bus, review,
            accept_experimental_bus_transfers=True)

    @classmethod
    def app(cls, network, review):
        return TestClient(create_sendai_practical_test_app(network, environment='test',
            parameters=cls.parameters, operating_period=cls.period,
            coverage_label=review['coverage_label']))

    def raw(self, day):
        if day not in self.raw_cache:
            self.raw_cache[day] = runs(self.source['files'], self.raw_subway,
                self.kinds, day, self.review)
        return self.raw_cache[day]

    def assert_case(self, case, *, check_api=False):
        day = date.fromisoformat(case['civil_date'])
        raw = self.raw(day)
        expected = optimum(raw, self.review, case['origin'], case['destination'],
            case['departure_minute'], max_boardings=3, max_minutes=180)
        self.assertEqual(expected, case['expected_arrival_minute'])
        with contextlib.redirect_stdout(io.StringIO()):
            results = search_practical_subway(self.network, case['origin'], case['destination'],
                civil_date=day, departure_minute=case['departure_minute'], parameters=self.parameters)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual((result.arrival_estimate.day, result.arrival_estimate.minute), (day, expected))
        validate(result, raw, self.review, day, case['origin'], case['destination'], case['departure_minute'])
        rides = [event.source for event in result.events if isinstance(event, PracticalRide)]
        self.assertEqual([ride.mode for ride in rides], case['modes'])
        self.assertIn(case['required_route_id'],
            {self.bus.trips[ride.trip_id].route_id for ride in rides if ride.mode == 'bus'})
        if check_api:
            with contextlib.redirect_stdout(io.StringIO()):
                response = self.client.post('/test/sendai/route', json={
                    'origin_stop_id': case['origin'], 'destination_stop_id': case['destination'],
                    'civil_date': case['civil_date'], 'departure_minute': case['departure_minute'],
                    'fare_policy_id': 'sendai_fureai_pass', 'accept_experimental_transfer_model': True})
            self.assertEqual(response.status_code, 200, response.text)
            candidate = response.json()['candidates'][0]
            self.assertEqual(candidate['arrival']['date'], case['civil_date'])
            self.assertEqual(candidate['arrival']['minute'], {'numerator': int(expected), 'denominator': 1})
            wire_rides = [event for event in candidate['events'] if event['kind'] == 'ride']
            self.assertEqual([event['trip_id'] for event in wire_rides], [ride.trip_id for ride in rides])
            self.assertEqual([event['stop_ids'] for event in wire_rides], [list(ride.stop_ids) for ride in rides])
            self.assertEqual(candidate['fare']['additional_payment_yen'], 0)
            self.assertIsNone(candidate['fare']['normal_fare_yen'])
            self.assertFalse(candidate['actual_connection_guaranteed'])

    def test_six_new_fixed_queries_match_independent_raw_optimum_and_api_witness(self):
        self.assertEqual([case['expected_arrival_minute'] for case in self.matrix['cases']],
            [589, 616, 597, 643, 609, 623])
        for case in self.matrix['cases']:
            with self.subTest(category=case['category']):
                self.assert_case(case, check_api=True)

    def test_previous_seven_queries_keep_fixed_expectations_on_expanded_bundle(self):
        self.assertEqual([case['expected_arrival_minute'] for case in self.previous_matrix['cases']],
            [442, 547, 491, 570, 600, 576, 627])
        for case in self.previous_matrix['cases']:
            with self.subTest(category=case['category']):
                self.assert_case(case)

    def test_two_complete_patterns_and_119_trips_preserve_all_service_categories(self):
        patterns = [p for p in self.review['bus_patterns'] if p['route_id'] == ROUTE]
        self.assertEqual(len(patterns), 2)
        self.assertEqual(sorted(len(p['trip_ids']) for p in patterns), [58, 61])
        self.assertEqual({(p['stop_ids'][0], p['stop_ids'][-1]) for p in patterns}, {
            ('sendai_bus:1294_10', 'sendai_bus:1085_0'),
            ('sendai_bus:1085_12', 'sendai_bus:1294_0')})
        trip_ids = {trip for p in patterns for trip in p['trip_ids']}
        self.assertEqual(len(trip_ids), 119)
        self.assertEqual(trip_ids, {trip.id for trip in self.bus.trips.values() if trip.route_id == ROUTE})
        self.assertTrue(trip_ids.issubset(self.network.free_scope.allowed_trip_ids))
        seen = set()
        for day, marker, count in ((date(2026, 10, 19), '_1_', 54),
                (date(2026, 10, 17), '_2_', 35), (date(2026, 10, 18), '_3_', 30),
                (date(2026, 10, 12), '_3_', 30)):
            with self.subTest(day=day):
                active = [r for r in self.raw(day) if r['day'] == day and r['trip'] in trip_ids]
                self.assertEqual(len(active), count)
                self.assertEqual({r['stops'] for r in active}, {tuple(p['stop_ids']) for p in patterns})
                for run in active:
                    seen.add(run['trip'])
                    self.assertIn(marker, run['trip'])
                    self.assertEqual(len(run['stops']), 26)
                    self.assertEqual((run['pickup'][0], run['dropoff'][0]), ('0', '1'))
                    self.assertEqual((run['pickup'][-1], run['dropoff'][-1]), ('1', '0'))
                    self.assertEqual(set(zip(run['pickup'][1:-1], run['dropoff'][1:-1])), {('0', '0')})
        self.assertEqual(seen, trip_ids)

    def test_removing_one_direction_does_not_authorize_it_through_shared_route(self):
        review = copy.deepcopy(self.review)
        removed = next(p for p in review['bus_patterns']
            if p['route_id'] == ROUTE and p['stop_ids'][0] == 'sendai_bus:1085_12')
        review['bus_patterns'].remove(removed)
        network = self.build(self.bus, review)
        self.assertTrue(set(removed['trip_ids']).isdisjoint(network.free_scope.allowed_trip_ids))
        retained = next(p for p in review['bus_patterns'] if p['route_id'] == ROUTE)
        self.assertTrue(set(retained['trip_ids']).issubset(network.free_scope.allowed_trip_ids))

    def test_changed_concrete_trip_set_or_complete_path_fails_fast(self):
        for change in ('trip', 'path'):
            with self.subTest(change=change):
                review = copy.deepcopy(self.review)
                pattern = next(p for p in review['bus_patterns'] if p['route_id'] == ROUTE)
                if change == 'trip':
                    pattern['trip_ids'].pop()
                else:
                    pattern['stop_ids'][5], pattern['stop_ids'][6] = pattern['stop_ids'][6], pattern['stop_ids'][5]
                with self.assertRaisesRegex(ValueError, 'exact reviewed bus concrete-trip set mismatch'):
                    self.build(self.bus, review)

    def test_same_number20_and_identical_path_do_not_authorize_another_route(self):
        source = copy.deepcopy(self.source)
        route_rows = rows(source['files']['routes.txt'])
        template = next(r for r in route_rows if r['route_id'] == '10030')
        self.assertEqual(template['route_short_name'], '20')
        route_rows.append({**template, 'route_id': '99999'})
        trip_rows = rows(source['files']['trips.txt'])
        trip = next(r for r in trip_rows if r['route_id'] == '10030')
        unreviewed = 'synthetic_unreviewed_number20'
        trip_rows.append({**trip, 'route_id': '99999', 'trip_id': unreviewed})
        time_rows = rows(source['files']['stop_times.txt'])
        time_rows.extend([{**r, 'trip_id': unreviewed} for r in time_rows if r['trip_id'] == trip['trip_id']])
        for name, records in (('routes.txt', route_rows), ('trips.txt', trip_rows), ('stop_times.txt', time_rows)):
            replace_rows(source, name, records)
        review = {**self.review, 'bus_feed_version': 'synthetic-unreviewed-number20-v1'}
        bus = load_bus(source, review)
        self.assertIn('sendai_bus:99999', bus.routes)
        network = self.build(bus, review)
        self.assertNotIn('sendai_bus:' + unreviewed, network.free_scope.allowed_trip_ids)
        raw = runs(source['files'], self.raw_subway, self.kinds, date(2026, 10, 19), review)
        self.assertNotIn('sendai_bus:' + unreviewed, {r['trip'] for r in raw})

    def test_stage2_capabilities_add_only_reviewed_stops_with_unchanged_dates_and_transfers(self):
        for key in ('operating_period', 'reviewed_days', 'bus_excluded_days',
                'bus_subway_transfers', 'subway_transfer_margin_minutes'):
            self.assertEqual(self.review[key], self.previous_review[key], key)
        self.assertEqual(self.matrix['parameters'], self.previous_matrix['parameters'])
        self.assertEqual(self.matrix['parameters'],
            {'max_candidates': 1, 'max_boardings': 3, 'max_travel_minutes': 180})
        previous_network = self.build(self.bus, self.previous_review)
        previous = self.app(previous_network, self.previous_review).get('/test/sendai/capabilities').json()
        current = self.client.get('/test/sendai/capabilities').json()
        old_stops = {r['id'] for r in previous['stops']}
        new_stops = {r['id'] for r in current['stops']}
        added_patterns = [p for p in self.review['bus_patterns'] if p['route_id'] == ROUTE]
        added_stops = {stop for p in added_patterns for stop in p['stop_ids']}
        self.assertEqual(new_stops - old_stops, added_stops - old_stops)
        self.assertTrue(old_stops.issubset(new_stops))
        self.assertTrue({'sendai_bus:1294_10', 'sendai_bus:1294_0'}.issubset(new_stops - old_stops))
        self.assertTrue({t for p in added_patterns for t in p['trip_ids']}.isdisjoint(
            previous_network.free_scope.allowed_trip_ids))
        self.assertEqual(current['operating_dates'], previous['operating_dates'])
        self.assertEqual(len(current['operating_dates']), 19)
        self.assertNotIn('2026-10-25', current['operating_dates'])
        self.assertEqual(current['coverage_label'], self.review['coverage_label'])
        self.assertFalse(current['special_timetables_verified'])


if __name__ == '__main__':
    unittest.main()
