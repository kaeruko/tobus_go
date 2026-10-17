"""Sendai hub data extension: exact reviewed links and complete bus runs."""
import contextlib
import copy
from datetime import date
import io
import unittest

from fastapi.testclient import TestClient
from app.sendai_practical_routes import create_sendai_practical_test_app
from sendai_operating_period import OperatingPeriodReview
from sendai_practical_bundle import build_reviewed_municipal_model, load_reviewed_subway
from sendai_practical_network import PracticalTransfer, search_practical_subway
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_municipal_oracle import optimum, rows, runs
from tests.test_sendai_arai21_practical import load_bus
from tests.test_sendai_stage2 import replace_rows
from tests.test_sendai_stage4 import F, read
from scripts.check_sendai_expansion import raw_day_kinds, verify_model

NEW={'sendai_bus:10065','sendai_bus:10219'}


class SendaiStage7Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=read('municipal_bus_subset_20261006_stage7.json')
        cls.review=read('municipal_review_20261017_stage7.json')
        cls.previous=read('municipal_review_20261017_stage6.json')
        cls.matrix=read('municipal_fixed_cases_20261017_stage7.json')
        cls.period=OperatingPeriodReview.from_mapping(cls.review['operating_period'])
        cls.bus=load_bus(cls.source,cls.review)
        cls.subway,cls.raw_subway=load_reviewed_subway(F/'published_20230701.json',F/'practical_review_20261016.json',operating_period=cls.period)
        cls.params=NetworkSearchParameters(**cls.matrix['parameters'])
        cls.network=cls.build(cls.review)
        cls.client=TestClient(create_sendai_practical_test_app(cls.network,environment='test',parameters=cls.params,
            operating_period=cls.period,coverage_label=cls.review['coverage_label']))
        cls.kinds=raw_day_kinds(cls.review['operating_period'])

    @classmethod
    def tearDownClass(cls):cls.client.close()

    @classmethod
    def build(cls,review,bus=None):
        return build_reviewed_municipal_model(cls.subway,cls.bus if bus is None else bus,review,accept_experimental_bus_transfers=True)

    def search(self,case,network):
        with contextlib.redirect_stdout(io.StringIO()):
            return search_practical_subway(network,case['origin'],case['destination'],civil_date=date.fromisoformat(case['civil_date']),
                departure_minute=case['departure_minute'],parameters=self.params)

    def test_fourteen_new_fixed_routes_match_existing_raw_oracle_and_api(self):
        self.assertEqual([c['expected_arrival_minute'] for c in self.matrix['cases']],
            [565,563,600,595,595,595,584,606,584,606,657,582,584,595])
        with contextlib.redirect_stdout(io.StringIO()):
            _,client=verify_model(self.bus,self.source['files'],self.raw_subway,self.subway,self.review,self.matrix,profile='stage7')
        client.close()

    def test_exact_patterns_services_and_original_through_stop_rules(self):
        patterns=self.review['bus_patterns'][-2:]
        self.assertEqual([(p['route_id'],len(p['trip_ids']),len(p['stop_ids'])) for p in patterns],
            [('sendai_bus:10065',92,21),('sendai_bus:10219',91,23)])
        self.assertEqual((len(rows(self.source['files']['trips.txt'])),len(rows(self.source['files']['stop_times.txt']))),(519,12746))
        for day,counts in [(date(2026,11,19),(32,31)),(date(2026,11,21),(30,31)),(date(2026,11,23),(30,29))]:
            rr=runs(self.source['files'],self.raw_subway,self.kinds,day,self.review)
            for p,count in zip(patterns,counts):
                active=[r for r in rr if r['day']==day and r['trip'] in p['trip_ids']]
                self.assertEqual(len(active),count)
                for r in active:
                    self.assertEqual(r['stops'],tuple(p['stop_ids']))
                    i=r['stops'].index('sendai_bus:50_850' if p['route_id'].endswith('10065') else 'sendai_bus:50_210')
                    self.assertEqual((r['pickup'][i],r['dropoff'][i]),('0','0'))
        self.assertNotEqual(patterns[0]['stop_ids'],list(reversed(patterns[1]['stop_ids'])))

    def test_old_336_trips_period_and_every_existing_link_are_unchanged(self):
        self.assertEqual(self.review['bus_patterns'][:-2],self.previous['bus_patterns'])
        self.assertEqual(self.review['bus_subway_transfers'][:-8],self.previous['bus_subway_transfers'])
        for k in ('operating_period','reviewed_days','bus_excluded_days','bus_feed_version','subway_feed_version','subway_transfer_margin_minutes'):
            self.assertEqual(self.review[k],self.previous[k])
        self.assertEqual(sum(t.startswith('sendai_bus:') for t in self.build(self.previous).free_scope.allowed_trip_ids),336)
        self.assertEqual(sum(t.startswith('sendai_bus:') for t in self.network.free_scope.allowed_trip_ids),519)

    def test_eight_directional_links_have_actual_witnesses_and_no_name_matching(self):
        links=self.review['bus_subway_transfers'][-8:]
        expected={(l['from_stop_id'],l['to_stop_id']) for l in links}
        self.assertEqual(len(expected),8)
        witnessed=set()
        for c in self.matrix['cases'][2:10]:
            result=self.search(c,self.network)
            self.assertTrue(result,c['category'])
            witnessed.update((e.from_stop_id,e.to_stop_id) for e in result[0].events if isinstance(e,PracticalTransfer))
        self.assertTrue(expected<=witnessed,(expected-witnessed))
        for l in links:
            self.assertEqual((l['margin_minutes'],l['time_basis']),(2,'experimental_planning_assumption'))
            self.assertEqual(l['subway_entrance'],'南4出入口' if '50_850' in (l['from_stop_id']+l['to_stop_id']) else '北2出入口')
            self.assertNotIn('中央2',l['path_description']);self.assertNotIn('北5',l['path_description'])
        linked={s for l in links for s in (l['from_stop_id'],l['to_stop_id'])}
        self.assertNotIn('sendai_bus:50_0',linked)
        self.assertNotIn('sendai_bus:50_52',linked)

    def test_removing_only_sendai_links_disconnects_new_area_in_both_oracles(self):
        review=copy.deepcopy(self.review);del review['bus_subway_transfers'][-8:]
        network=self.build(review)
        day=date(2026,11,19);rr=runs(self.source['files'],self.raw_subway,self.kinds,day,review)
        for c in self.matrix['cases'][2:6]:
            self.assertFalse(self.search(c,network),c['category'])
            self.assertIsNone(optimum(rr,review,c['origin'],c['destination'],540,max_boardings=3,max_minutes=180))

    def test_concrete_trip_set_or_full_pattern_tampering_is_rejected(self):
        for rid in NEW:
            for field in ('trip_ids','stop_ids'):
                review=copy.deepcopy(self.review);p=next(p for p in review['bus_patterns'] if p['route_id']==rid)
                if field=='trip_ids':p[field].pop()
                else:p[field][8],p[field][9]=p[field][9],p[field][8]
                with self.assertRaisesRegex(ValueError,'exact reviewed bus concrete-trip set mismatch'):self.build(review)

    def test_same_number_full_path_does_not_allow_unreviewed_route(self):
        source=copy.deepcopy(self.source)
        rr=rows(source['files']['routes.txt']);template=next(r for r in rr if r['route_id']=='10065')
        rr.append({**template,'route_id':'99999'});replace_rows(source,'routes.txt',rr)
        tt=rows(source['files']['trips.txt']);trip=next(t for t in tt if t['route_id']=='10065');fake='synthetic_unreviewed_308'
        tt.append({**trip,'route_id':'99999','trip_id':fake});replace_rows(source,'trips.txt',tt)
        times=rows(source['files']['stop_times.txt']);times.extend([{**r,'trip_id':fake} for r in times if r['trip_id']==trip['trip_id']])
        replace_rows(source,'stop_times.txt',times)
        review={**self.review,'bus_feed_version':'synthetic_unreviewed_308_v1'}
        self.assertNotIn('sendai_bus:'+fake,self.build(review,load_bus(source,review)).free_scope.allowed_trip_ids)

    def test_245_poles_and_existing_date_and_fare_boundaries(self):
        caps=self.client.get('/test/sendai/capabilities').json()
        current={s['id'] for s in caps['stops'] if s['mode']=='bus'};old={s for p in self.previous['bus_patterns'] for s in p['stop_ids']}
        self.assertEqual((len(current),len(current-old)),(245,44))
        self.assertEqual((len(caps['operating_dates']),caps['operating_dates'][-1]),(48,'2026-11-30'))
        c=self.matrix['cases'][0]
        for day,minute,code in [('2026-10-25',540,422),('2026-11-22',540,422),('2026-12-01',540,422),('2026-11-30',540,200),('2026-11-30',1380,422)]:
            with contextlib.redirect_stdout(io.StringIO()):
                response=self.client.post('/test/sendai/route',json=dict(origin_stop_id=c['origin'],destination_stop_id=c['destination'],civil_date=day,
                    departure_minute=minute,fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True))
            self.assertEqual(response.status_code,code,(day,minute,response.text))
        self.assertFalse(caps['actual_connection_guaranteed'])
        self.assertFalse(caps['special_timetables_verified'])


if __name__=='__main__':unittest.main()
