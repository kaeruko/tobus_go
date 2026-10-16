"""One bounded Arai 21 expansion, checked against retained raw source rows.

The three new queries were fixed from the raw timetable before model search.
The previous four queries and their expectations remain separate and unchanged.
"""
import contextlib
import copy
import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

from sendai_practical_bundle import build_reviewed_municipal_model, load_reviewed_subway
from sendai_operating_period import OperatingPeriodReview
from sendai_practical_network import PracticalRide, search_practical_subway
from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_municipal_oracle import optimum, rows, runs, validate


FIXTURE = Path(__file__).parent / 'fixtures' / 'sendai_subway'
ARAI_ROUTE = 'sendai_bus:10039'
PARAMETERS = NetworkSearchParameters(max_candidates=1, max_boardings=3, max_travel_minutes=180)
FIXED_CASES = (
    dict(category='21_only', civil_date='2026-10-16', departure_minute=420,
         origin='sendai_bus:5181_11', destination='sendai_bus:5099_0',
         expected_arrival_minute=442, required_trip='sendai_bus:20_1_12002380', modes=('bus',)),
    dict(category='21_rail', civil_date='2026-10-12', departure_minute=500,
         origin='sendai_bus:5099_10', destination='sendai_subway:tozai/仙台',
         expected_arrival_minute=547, required_trip='sendai_bus:20_3_32001450', modes=('bus', 'rail')),
    dict(category='rail_21', civil_date='2026-10-17', departure_minute=450,
         origin='sendai_subway:tozai/仙台', destination='sendai_bus:5099_0',
         expected_arrival_minute=491, required_trip='sendai_bus:20_2_22001340', modes=('rail', 'bus')),
)


def load_bus(source, review):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name, content in source['files'].items():
            (root / name).write_text(content, encoding='utf-8', newline='')
        return GtfsTransitAdapter.load(root, metadata=FeedMetadata(
            'sendai_bus', 'gtfs-jp', source['source_url'], review['bus_feed_version'],
            datetime(2026, 10, 16, tzinfo=timezone.utc)))


class SendaiArai21PracticalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((FIXTURE / 'municipal_bus_subset_20261006_stage1.json').read_text(encoding='utf-8'))
        cls.review = json.loads((FIXTURE / 'municipal_review_20261016_stage1.json').read_text(encoding='utf-8'))
        cls.bus = load_bus(cls.fixture, cls.review)
        cls.subway, cls.raw_subway = load_reviewed_subway(
            FIXTURE / 'published_20230701.json', FIXTURE / 'practical_review_20261016.json',
            operating_period=OperatingPeriodReview.from_mapping(cls.review['operating_period']))
        # Independently classify raw source days; never reuse the production
        # OperatingPeriodReview calendar output in the optimum calculation.
        period = cls.review['operating_period']
        first, last = (date.fromisoformat(period[k]) for k in ('coverage_start', 'coverage_end'))
        holidays = {date.fromisoformat(r['day']) for r in period['holiday_review']['holidays']}
        excluded = {date.fromisoformat(r['day']) for r in period['exclusions']}
        cls.days = {}
        for offset in range((last - first).days + 1):
            day = first + timedelta(days=offset)
            if day not in excluded:
                cls.days[day] = 'h' if day.weekday() >= 5 or day in holidays else 'w'
        cls.net = cls.build(cls.bus, cls.review)

    @classmethod
    def build(cls, bus, review):
        return build_reviewed_municipal_model(cls.subway, bus, review, accept_experimental_bus_transfers=True)

    def query(self, case, *, net=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return search_practical_subway(self.net if net is None else net, case['origin'], case['destination'],
                civil_date=date.fromisoformat(case['civil_date']), departure_minute=case['departure_minute'],
                parameters=PARAMETERS)

    def raw(self, day, *, source=None, review=None):
        return runs((self.fixture if source is None else source)['files'], self.raw_subway, self.days,
            day, self.review if review is None else review)

    def assert_raw_witness(self, case):
        day = date.fromisoformat(case['civil_date'])
        raw = self.raw(day)
        expected = optimum(raw, self.review, case['origin'], case['destination'], case['departure_minute'],
            max_boardings=3, max_minutes=180)
        self.assertEqual(expected, case['expected_arrival_minute'])
        result = self.query(case)
        self.assertTrue(result)
        self.assertEqual(result[0].arrival_estimate.day, day)
        self.assertEqual(result[0].arrival_estimate.minute, expected)
        validate(result[0], raw, self.review, day, case['origin'], case['destination'], case['departure_minute'])
        return result[0]

    def test_three_prefixed_queries_match_raw_optimum_and_complete_concrete_witness(self):
        for case in FIXED_CASES:
            with self.subTest(category=case['category']):
                result = self.assert_raw_witness(case)
                rides = [e.source for e in result.events if isinstance(e, PracticalRide)]
                self.assertEqual(tuple(r.mode for r in rides), case['modes'])
                bus_rides = [r for r in rides if r.mode == 'bus']
                self.assertEqual([r.trip_id for r in bus_rides], [case['required_trip']])
                self.assertEqual(self.bus.trips[bus_rides[0].trip_id].route_id, ARAI_ROUTE)
                self.assertEqual(len(bus_rides[0].stop_ids), 14)
                self.assertNotIn('sendai_bus:5127_10', bus_rides[0].stop_ids)

    def test_both_complete_patterns_same_route_and_each_service_kind_survive_raw_oracle(self):
        patterns = [p for p in self.review['bus_patterns'] if p['route_id'] == ARAI_ROUTE]
        self.assertEqual(len(patterns), 2)
        self.assertEqual(sorted(len(p['trip_ids']) for p in patterns), [3, 11])
        self.assertEqual({(p['stop_ids'][0], p['stop_ids'][-1]) for p in patterns}, {
            ('sendai_bus:5181_11', 'sendai_bus:5099_0'), ('sendai_bus:5099_10', 'sendai_bus:5181_0')})
        all_ids = {t for p in patterns for t in p['trip_ids']}
        self.assertEqual({r['route_id'] for r in rows(self.fixture['files']['routes.txt'])}, {'10033', '10255', '10039', '10038'})
        for day, marker, count in ((date(2026, 10, 16), '_1_', 6), (date(2026, 10, 17), '_2_', 4),
                                   (date(2026, 10, 18), '_3_', 4), (date(2026, 10, 12), '_3_', 4)):
            with self.subTest(day=day):
                rr = [r for r in self.raw(day) if r['day'] == day and r['trip'] in all_ids]
                self.assertEqual(len(rr), count)
                self.assertEqual({r['stops'] for r in rr}, {tuple(p['stop_ids']) for p in patterns})
                for run in rr:
                    self.assertIn(marker, run['trip'])
                    self.assertEqual(len(run['stops']), 14)
                    self.assertEqual((run['pickup'][0], run['dropoff'][0]), ('0', '1'))
                    self.assertEqual((run['pickup'][-1], run['dropoff'][-1]), ('1', '0'))

    def test_one_reviewed_direction_never_authorizes_other_direction_same_route(self):
        review = copy.deepcopy(self.review)
        outbound = next(p for p in review['bus_patterns'] if p['route_id'] == ARAI_ROUTE and p['stop_ids'][0] == 'sendai_bus:5181_11')
        review['bus_patterns'].remove(outbound)
        net = self.build(self.bus, review)
        self.assertTrue(set(outbound['trip_ids']).isdisjoint(net.free_scope.allowed_trip_ids))
        inbound = next(p for p in review['bus_patterns'] if p['route_id'] == ARAI_ROUTE)
        self.assertTrue(set(inbound['trip_ids']).issubset(net.free_scope.allowed_trip_ids))
        raw = self.raw(date(2026, 10, 16), review=review)
        self.assertTrue(set(outbound['trip_ids']).isdisjoint(r['trip'] for r in raw))

    def test_unreviewed_concrete_trip_or_changed_complete_path_fails_fast(self):
        for change in ('trip', 'path'):
            with self.subTest(change=change):
                review = copy.deepcopy(self.review)
                pattern = next(p for p in review['bus_patterns'] if p['route_id'] == ARAI_ROUTE)
                if change == 'trip':
                    pattern['trip_ids'].pop()
                else:
                    pattern['stop_ids'][5], pattern['stop_ids'][6] = pattern['stop_ids'][6], pattern['stop_ids'][5]
                with self.assertRaisesRegex(ValueError, 'exact reviewed bus concrete-trip set mismatch'):
                    self.build(self.bus, review)

    def test_same_short_name_and_identical_stops_do_not_authorize_another_route_id(self):
        # Synthetic impostor; both real route IDs 10038/10039 have explicit
        # independent complete-path reviews in the stage-one bundle.
        source = copy.deepcopy(self.fixture)
        route_rows = rows(source['files']['routes.txt'])
        template = next(r for r in route_rows if r['route_id'] == '10039')
        self.assertEqual(template['route_short_name'], '21')
        route_rows.append({**template, 'route_id': '99999'})
        trip_rows = rows(source['files']['trips.txt'])
        template = next(r for r in trip_rows if r['trip_id'] == '20_1_12002380')
        unreviewed = 'synthetic_unreviewed_number21'
        trip_rows.append({**template, 'route_id': '99999', 'trip_id': unreviewed})
        time_rows = rows(source['files']['stop_times.txt'])
        time_rows.extend([{**r, 'trip_id': unreviewed} for r in time_rows if r['trip_id'] == template['trip_id']])
        for name, records in (('routes.txt', route_rows), ('trips.txt', trip_rows), ('stop_times.txt', time_rows)):
            output = io.StringIO(newline='')
            writer = csv.DictWriter(output, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
            source['files'][name] = output.getvalue()
        review = {**self.review, 'bus_feed_version': 'synthetic-unreviewed-number21-v1'}
        bus = load_bus(source, review)
        self.assertIn('sendai_bus:99999', bus.routes)
        net = self.build(bus, review)
        self.assertNotIn('sendai_bus:' + unreviewed, net.free_scope.allowed_trip_ids)
        raw = self.raw(date(2026, 10, 16), source=source, review=review)
        self.assertNotIn('sendai_bus:' + unreviewed, {r['trip'] for r in raw})

    def test_pickup_and_dropoff_restrictions_cannot_produce_a_journey(self):
        # Synthetic negative mutation, retaining the same reviewed complete paths.
        case = dict(civil_date='2026-10-16', departure_minute=420,
                    origin='sendai_bus:5071_50', destination='sendai_bus:5081_50')
        self.assertTrue(self.query(case))
        for field, stop in (('pickup_type', '5071_50'), ('drop_off_type', '5081_50')):
            with self.subTest(field=field):
                source = copy.deepcopy(self.fixture)
                records = rows(source['files']['stop_times.txt'])
                for record in records:
                    if record['stop_id'] == stop:
                        record[field] = '1'
                output = io.StringIO(newline='')
                writer = csv.DictWriter(output, fieldnames=list(records[0]))
                writer.writeheader()
                writer.writerows(records)
                source['files']['stop_times.txt'] = output.getvalue()
                review = {**self.review, 'bus_feed_version': 'synthetic-arai21-restriction-v1'}
                bus = load_bus(source, review)
                raw = self.raw(date(2026, 10, 16), source=source, review=review)
                self.assertIsNone(optimum(raw, review, case['origin'], case['destination'], 420,
                    max_boardings=3, max_minutes=180))
                self.assertEqual(self.query(case, net=self.build(bus, review)), ())

    def test_previous_four_fixed_queries_on_new_bundle_keep_original_expectations(self):
        # This evaluates only the newly expanded model, not the old audit suite.
        previous = json.loads((FIXTURE / 'municipal_fixed_cases_20261016.json').read_text(encoding='utf-8'))
        self.assertEqual([c['expected_arrival_minute'] for c in previous['cases']], [711, 619, 734, 658])
        for case in previous['cases']:
            with self.subTest(category=case['category']):
                self.assert_raw_witness(case)


if __name__ == '__main__':
    unittest.main()
