"""Incremental Arai 15 evidence; existing engine, adapter, oracle and API."""
import contextlib
import copy
from datetime import date
import io
import unittest

from fastapi.testclient import TestClient
from app.sendai_practical_routes import create_sendai_practical_test_app
from sendai_operating_period import OperatingPeriodReview
from sendai_practical_bundle import build_reviewed_municipal_model, load_reviewed_subway
from sendai_practical_network import search_practical_subway
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_municipal_oracle import optimum, rows, runs
from tests.test_sendai_arai21_practical import load_bus
from tests.test_sendai_stage2 import replace_rows
from tests.test_sendai_stage4 import F, read
from scripts.check_sendai_expansion import raw_day_kinds, verify_model


class SendaiStage5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=read('municipal_bus_subset_20261006_stage5.json')
        cls.review=read('municipal_review_20261017_stage5.json')
        cls.previous=read('municipal_review_20261017_stage4.json')
        cls.matrix=read('municipal_fixed_cases_20261017_stage5.json')
        cls.period=OperatingPeriodReview.from_mapping(cls.review['operating_period'])
        cls.bus=load_bus(cls.source,cls.review)
        cls.subway,cls.raw_subway=load_reviewed_subway(F/'published_20230701.json',F/'practical_review_20261016.json',operating_period=cls.period)
        cls.network=cls.build(cls.bus,cls.review)
        cls.params=NetworkSearchParameters(**cls.matrix['parameters'])
        cls.client=TestClient(create_sendai_practical_test_app(cls.network,environment='test',parameters=cls.params,
            operating_period=cls.period,coverage_label=cls.review['coverage_label']))

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    @classmethod
    def build(cls,bus,review):
        return build_reviewed_municipal_model(cls.subway,bus,review,accept_experimental_bus_transfers=True)

    def test_six_preselected_raw_routes_and_full_witnesses_match_api(self):
        self.assertEqual([c['expected_arrival_minute'] for c in self.matrix['cases']],[595,579,595,668,579,595])
        with contextlib.redirect_stdout(io.StringIO()):
            _,client=verify_model(self.bus,self.source['files'],self.raw_subway,self.subway,self.review,self.matrix,profile='stage5')
        client.close()

    def test_complete_loop_and_daily_concrete_services(self):
        p=self.review['bus_patterns'][-1]
        self.assertEqual((p['route_id'],len(p['trip_ids']),len(p['stop_ids'])),('sendai_bus:10019',29,25))
        self.assertEqual((p['stop_ids'][0],p['stop_ids'][-1]),('sendai_bus:5181_10','sendai_bus:5181_0'))
        self.assertEqual([s for n,s in zip(p['stop_names'],p['stop_ids']) if n=='若林体育館前'],
            ['sendai_bus:4217_11','sendai_bus:4217_10'])
        kinds=raw_day_kinds(self.review['operating_period'])
        for day,count in [(date(2026,11,19),13),(date(2026,11,21),8),(date(2026,11,23),8),(date(2026,11,29),8)]:
            rr=[r for r in runs(self.source['files'],self.raw_subway,kinds,day,self.review)
                if r['day']==day and r['trip'] in p['trip_ids']]
            self.assertEqual(len(rr),count)
            for r in rr:
                self.assertEqual((r['pickup'][0],r['dropoff'][0],r['pickup'][-1],r['dropoff'][-1]),('0','1','1','0'))

    def test_previous_patterns_links_and_finite_period_are_unchanged(self):
        for key in ('operating_period','reviewed_days','bus_excluded_days','bus_feed_version','subway_feed_version','subway_transfer_margin_minutes'):
            self.assertEqual(self.review[key],self.previous[key],key)
        self.assertEqual(self.review['bus_patterns'][:-1],self.previous['bus_patterns'])
        self.assertEqual(self.review['bus_subway_transfers'][:-1],self.previous['bus_subway_transfers'])
        old=self.build(self.bus,self.previous)
        self.assertEqual(sum(t.startswith('sendai_bus:') for t in old.free_scope.allowed_trip_ids),281)
        self.assertEqual(sum(t.startswith('sendai_bus:') for t in self.network.free_scope.allowed_trip_ids),310)

    def test_new_bay_direction_is_required_not_mirrored(self):
        link=self.review['bus_subway_transfers'][-1]
        self.assertEqual((link['from_stop_id'],link['to_stop_id'],link['subway_entrance']),
            ('sendai_subway:tozai/荒井','sendai_bus:5181_10','中央1出入口'))
        self.assertEqual((link['standard_minutes'],link['margin_minutes'],link['time_basis']),
            (5,2,'experimental_planning_assumption'))
        self.assertFalse(any(l['from_stop_id']=='sendai_bus:5181_10' for l in self.review['bus_subway_transfers']))
        review=copy.deepcopy(self.review);review['bus_subway_transfers'].pop()
        case=self.matrix['cases'][2];day=date.fromisoformat(case['civil_date'])
        with contextlib.redirect_stdout(io.StringIO()):
            result=search_practical_subway(self.build(self.bus,review),case['origin'],case['destination'],
                civil_date=day,departure_minute=case['departure_minute'],parameters=self.params)
        # The old bay2 bus can reach a shared concrete pole, then wait for a
        # later 15. Do not mistake this legitimate three-boarding route for
        # an implicit bay1 connection or disable the existing transfer engine.
        self.assertTrue(result)
        self.assertEqual(result[0].arrival_estimate.minute,714)
        self.assertGreater(result[0].arrival_estimate.minute,case['expected_arrival_minute'])
        rr=runs(self.source['files'],self.raw_subway,raw_day_kinds(review['operating_period']),day,review)
        self.assertEqual(optimum(rr,review,case['origin'],case['destination'],case['departure_minute'],max_boardings=3,max_minutes=180),714)

    def test_exact_trip_or_full_path_mutation_rejected(self):
        for change in ('trip','path'):
            review=copy.deepcopy(self.review);p=review['bus_patterns'][-1]
            if change=='trip':p['trip_ids'].pop()
            else:p['stop_ids'][5],p['stop_ids'][19]=p['stop_ids'][19],p['stop_ids'][5]
            with self.assertRaisesRegex(ValueError,'exact reviewed bus concrete-trip set mismatch'):
                self.build(self.bus,review)

    def test_same_number_path_does_not_allow_unknown_route(self):
        source=copy.deepcopy(self.source)
        rr=rows(source['files']['routes.txt']);template=next(r for r in rr if r['route_id']=='10019')
        rr.append({**template,'route_id':'99999'});replace_rows(source,'routes.txt',rr)
        tt=rows(source['files']['trips.txt']);trip=next(t for t in tt if t['route_id']=='10019')
        fake='synthetic_unreviewed_15';tt.append({**trip,'route_id':'99999','trip_id':fake});replace_rows(source,'trips.txt',tt)
        times=rows(source['files']['stop_times.txt']);times.extend([{**r,'trip_id':fake} for r in times if r['trip_id']==trip['trip_id']])
        replace_rows(source,'stop_times.txt',times)
        review={**self.review,'bus_feed_version':'synthetic_unreviewed_15_v1'}
        self.assertNotIn('sendai_bus:'+fake,self.build(load_bus(source,review),review).free_scope.allowed_trip_ids)

    def test_capabilities_and_date_boundaries_with_new_stops(self):
        caps=self.client.get('/test/sendai/capabilities').json()
        current={s['id'] for s in caps['stops'] if s['mode']=='bus'}
        old={s for p in self.previous['bus_patterns'] for s in p['stop_ids']}
        p=self.review['bus_patterns'][-1]
        self.assertEqual(current-old,set(p['stop_ids'])-old)
        self.assertEqual((len(current),len(current-old)),(186,14))
        self.assertTrue({'sendai_bus:5181_10','sendai_bus:4253_10','sendai_bus:4135_50'}<=current-old)
        self.assertEqual((len(caps['operating_dates']),caps['operating_dates'][-1]),(48,'2026-11-30'))
        case=self.matrix['cases'][0]
        for day,minute,status in [('2026-10-25',540,422),('2026-11-22',540,422),('2026-12-01',540,422),('2026-11-30',540,200),('2026-11-30',1380,422)]:
            with contextlib.redirect_stdout(io.StringIO()):
                response=self.client.post('/test/sendai/route',json=dict(origin_stop_id=case['origin'],destination_stop_id=case['destination'],
                    civil_date=day,departure_minute=minute,fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True))
            self.assertEqual(response.status_code,status,(day,minute,response.text))


if __name__=='__main__':unittest.main()
