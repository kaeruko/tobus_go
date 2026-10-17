"""Incremental reverse16: exact source, existing oracle, no new hub links."""
import contextlib
import copy
from datetime import date
import io
import unittest
from fastapi.testclient import TestClient
from app.sendai_practical_routes import create_sendai_practical_test_app
from sendai_operating_period import OperatingPeriodReview
from sendai_practical_bundle import build_reviewed_municipal_model, load_reviewed_subway
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_municipal_oracle import rows, runs
from tests.test_sendai_arai21_practical import load_bus
from tests.test_sendai_stage2 import replace_rows
from tests.test_sendai_stage4 import F, read
from scripts.check_sendai_expansion import raw_day_kinds, verify_model

class SendaiStage6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=read('municipal_bus_subset_20261006_stage6.json')
        cls.review=read('municipal_review_20261017_stage6.json')
        cls.previous=read('municipal_review_20261017_stage5.json')
        cls.matrix=read('municipal_fixed_cases_20261017_stage6.json')
        cls.period=OperatingPeriodReview.from_mapping(cls.review['operating_period'])
        cls.bus=load_bus(cls.source,cls.review)
        cls.subway,cls.raw_subway=load_reviewed_subway(F/'published_20230701.json',
            F/'practical_review_20261016.json',operating_period=cls.period)
        cls.network=cls.build(cls.review)
        cls.client=TestClient(create_sendai_practical_test_app(cls.network,environment='test',
            parameters=NetworkSearchParameters(**cls.matrix['parameters']),
            operating_period=cls.period,coverage_label=cls.review['coverage_label']))
        cls.kinds=raw_day_kinds(cls.review['operating_period'])

    @classmethod
    def tearDownClass(cls):cls.client.close()

    @classmethod
    def build(cls,review,bus=None):
        return build_reviewed_municipal_model(cls.subway,cls.bus if bus is None else bus,review,
            accept_experimental_bus_transfers=True)

    def test_seven_fixed_raw_oracles_and_api(self):
        self.assertEqual([c['expected_arrival_minute'] for c in self.matrix['cases']],
            [563,582,603,651,599,617,651])
        with contextlib.redirect_stdout(io.StringIO()):
            _,client=verify_model(self.bus,self.source['files'],self.raw_subway,self.subway,
                self.review,self.matrix,profile='stage6')
        client.close()

    def test_26_complete_buses_and_daily_service_counts(self):
        p=self.review['bus_patterns'][-1]
        self.assertEqual((p['route_id'],len(p['trip_ids']),len(p['stop_ids'])),
            ('sendai_bus:10022',26,25))
        self.assertEqual((p['stop_ids'][0],p['stop_ids'][10],p['stop_ids'][-1]),
            ('sendai_bus:5181_10','sendai_bus:4253_50','sendai_bus:5181_0'))
        self.assertEqual((p['stop_ids'][5],p['stop_ids'][19]),
            ('sendai_bus:4217_50','sendai_bus:4217_51'))
        self.assertEqual(len(rows(self.source['files']['stop_times.txt'])),8721)
        for day,count in ((date(2026,11,19),12),(date(2026,11,21),7),(date(2026,11,23),7)):
            active=[r for r in runs(self.source['files'],self.raw_subway,self.kinds,day,self.review)
                if r['day']==day and r['trip'] in p['trip_ids']]
            self.assertEqual(len(active),count)
            for rr in active:
                self.assertEqual(rr['stops'],tuple(p['stop_ids']))
                self.assertEqual((rr['pickup'][0],rr['dropoff'][0],rr['pickup'][-1],rr['dropoff'][-1]),
                    ('0','1','1','0'))

    def test_old_310_unchanged_and_no_reverse_link_invention(self):
        for key in ('operating_period','reviewed_days','bus_excluded_days','bus_feed_version',
                    'subway_feed_version','subway_transfer_margin_minutes'):
            self.assertEqual(self.review[key],self.previous[key])
        self.assertEqual(self.review['bus_patterns'][:-1],self.previous['bus_patterns'])
        self.assertEqual(self.review['bus_subway_transfers'],self.previous['bus_subway_transfers'])
        self.assertEqual(sum(t.startswith('sendai_bus:') for t in self.build(self.previous).free_scope.allowed_trip_ids),310)
        self.assertEqual(sum(t.startswith('sendai_bus:') for t in self.network.free_scope.allowed_trip_ids),336)
        self.assertFalse(any(x['from_stop_id']=='sendai_bus:5181_10' for x in self.review['bus_subway_transfers']))
        self.assertEqual(sum(x['to_stop_id']=='sendai_bus:5181_10' for x in self.review['bus_subway_transfers']),1)

    def test_distinct_15_vs_16_poles_and_whitelisted_trips(self):
        old=self.previous['bus_patterns'][-1];new=self.review['bus_patterns'][-1]
        self.assertEqual((old['route_id'],new['route_id']),('sendai_bus:10019','sendai_bus:10022'))
        self.assertEqual((old['stop_names'].count('若林体育館前'),new['stop_names'].count('若林体育館前')),(2,2))
        self.assertEqual(new['stop_names'].count('鶴巻'),1)
        self.assertNotEqual(old['stop_ids'],new['stop_ids'])
        self.assertFalse(set(old['trip_ids'])&set(new['trip_ids']))
        self.assertNotIn('sendai_bus:4253_50',old['stop_ids'])
        self.assertNotIn('sendai_bus:4253_10',new['stop_ids'])

    def test_trip_or_whole_stop_order_tampering_is_rejected(self):
        for change in ('trip','path'):
            review=copy.deepcopy(self.review);p=review['bus_patterns'][-1]
            if change=='trip':p['trip_ids'].pop()
            else:p['stop_ids'][6],p['stop_ids'][7]=p['stop_ids'][7],p['stop_ids'][6]
            with self.assertRaisesRegex(ValueError,'exact reviewed bus concrete-trip set mismatch'):
                self.build(review)

    def test_unreviewed_similar_route_does_not_get_free_scope(self):
        src=copy.deepcopy(self.source)
        rr=rows(src['files']['routes.txt']);r=next(r for r in rr if r['route_id']=='10022')
        rr.append({**r,'route_id':'99999'});replace_rows(src,'routes.txt',rr)
        tt=rows(src['files']['trips.txt']);t=next(x for x in tt if x['route_id']=='10022')
        fake='synthetic_unreviewed_reverse16'
        tt.append({**t,'route_id':'99999','trip_id':fake});replace_rows(src,'trips.txt',tt)
        times=rows(src['files']['stop_times.txt'])
        times.extend([{**x,'trip_id':fake} for x in times if x['trip_id']==t['trip_id']])
        replace_rows(src,'stop_times.txt',times)
        review={**self.review,'bus_feed_version':'synthetic_stage6_fixture'}
        self.assertNotIn('sendai_bus:'+fake,self.build(review,load_bus(src,review)).free_scope.allowed_trip_ids)

    def test_201_exact_poles_and_48_bounded_days(self):
        caps=self.client.get('/test/sendai/capabilities').json()
        old={s for p in self.previous['bus_patterns'] for s in p['stop_ids']}
        now={s['id'] for s in caps['stops'] if s['mode']=='bus'}
        self.assertEqual((len(now),len(now-old)),(201,15))
        self.assertTrue({'sendai_bus:4253_50','sendai_bus:4135_10','sendai_bus:4217_51'}<=now-old)
        self.assertEqual((len(caps['operating_dates']),caps['operating_dates'][-1]),(48,'2026-11-30'))
        c=self.matrix['cases'][0]
        for day,minute,code in (('2026-10-25',540,422),('2026-11-22',540,422),
                ('2026-12-01',540,422),('2026-11-30',540,200),('2026-11-30',1380,422)):
            with contextlib.redirect_stdout(io.StringIO()):
                response=self.client.post('/test/sendai/route',json=dict(origin_stop_id=c['origin'],
                    destination_stop_id=c['destination'],civil_date=day,departure_minute=minute,
                    fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True))
            self.assertEqual(response.status_code,code,(day,minute,response.text))
        self.assertFalse(caps['actual_connection_guaranteed'])
        self.assertFalse(caps['special_timetables_verified'])

if __name__=='__main__':unittest.main()
