"""Incremental real routes at existing hubs; reuse the raw oracle and API gate."""
import contextlib
import copy
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
from sendai_practical_network import search_practical_subway
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_municipal_oracle import optimum, rows, runs
from tests.test_sendai_arai21_practical import load_bus
from tests.test_sendai_stage2 import replace_rows

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.check_sendai_expansion import raw_day_kinds, verify_model

F=Path(__file__).parent/'fixtures/sendai_subway'
NEW={'sendai_bus:10061','sendai_bus:10254'}


def read(name):
    return json.loads((F/name).read_text(encoding='utf-8'))


class SendaiStage4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=read('municipal_bus_subset_20261006_stage4.json')
        cls.review=read('municipal_review_20261017_stage4.json')
        cls.previous=read('municipal_review_20261017_stage3.json')
        cls.matrix=read('municipal_fixed_cases_20261017_stage4.json')
        cls.period=OperatingPeriodReview.from_mapping(cls.review['operating_period'])
        cls.kinds=raw_day_kinds(cls.review['operating_period'])
        cls.bus=load_bus(cls.source,cls.review)
        cls.subway,cls.raw_subway=load_reviewed_subway(F/'published_20230701.json',F/'practical_review_20261016.json',operating_period=cls.period)
        cls.network=cls.build(cls.bus,cls.review)
        cls.params=NetworkSearchParameters(**cls.matrix['parameters'])
        cls.client=TestClient(create_sendai_practical_test_app(cls.network,environment='test',parameters=cls.params,
            operating_period=cls.period,coverage_label=cls.review['coverage_label']))
        cls.raw_cache={}

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    @classmethod
    def build(cls,bus,review):
        return build_reviewed_municipal_model(cls.subway,bus,review,accept_experimental_bus_transfers=True)

    def raw(self,day):
        if day not in self.raw_cache:
            self.raw_cache[day]=runs(self.source['files'],self.raw_subway,self.kinds,day,self.review)
        return self.raw_cache[day]

    def search(self,case,network=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return search_practical_subway(self.network if network is None else network,case['origin'],case['destination'],
                civil_date=date.fromisoformat(case['civil_date']),departure_minute=case['departure_minute'],parameters=self.params)

    def request(self,day,minute=540):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.client.post('/test/sendai/route',json=dict(origin_stop_id='sendai_bus:8035_10',
                destination_stop_id='sendai_bus:1085_0',civil_date=day,departure_minute=minute,
                fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True))

    def test_eight_fixed_new_routes_use_existing_raw_oracle_and_api_gate(self):
        self.assertEqual([c['expected_arrival_minute'] for c in self.matrix['cases']],
            [589,616,566,596,619,674,574,595])
        with contextlib.redirect_stdout(io.StringIO()):
            _,client=verify_model(self.bus,self.source['files'],self.raw_subway,self.subway,self.review,self.matrix,profile='stage4')
        client.close()

    def test_exact_patterns_daily_services_and_repeated_place_occurrences_survive(self):
        patterns=[p for p in self.review['bus_patterns'] if p['route_id'] in NEW]
        self.assertEqual(sorted((len(p['stop_ids']),len(p['trip_ids'])) for p in patterns),[(25,37),(33,3),(43,44)])
        self.assertEqual({r['route_id'] for r in rows(self.source['files']['routes.txt'])},
            {'10030','10033','10038','10039','10255','10061','10254'})
        expected={'sendai_bus:10061':(21,12,11,11),'sendai_bus:10254':(15,13,12,12)}
        days=(date(2026,11,19),date(2026,11,21),date(2026,11,23),date(2026,11,29))
        seen=set()
        for index,day in enumerate(days):
            raw=[r for r in self.raw(day) if r['day']==day]
            for rid,counts in expected.items():
                allowed={t for p in patterns if p['route_id']==rid for t in p['trip_ids']}
                active=[r for r in raw if r['trip'] in allowed]
                self.assertEqual(len(active),counts[index],(day,rid))
                for r in active:
                    seen.add(r['trip'])
                    self.assertEqual((r['pickup'][0],r['dropoff'][0]),('0','1'))
                    self.assertEqual((r['pickup'][-1],r['dropoff'][-1]),('1','0'))
        self.assertEqual(len(seen),84)
        loop=next(p for p in patterns if p['route_id']=='sendai_bus:10061')
        self.assertEqual((loop['stop_ids'][0],loop['stop_ids'][-1]),('sendai_bus:1085_11','sendai_bus:1085_0'))
        self.assertEqual(loop['stop_names'].count('吉成一丁目'),2)
        self.assertLess(loop['stop_ids'].index('sendai_bus:8023_51'),loop['stop_ids'].index('sendai_bus:8023_52'))
        long=next(p for p in patterns if len(p['stop_ids'])==33)
        self.assertEqual(long['stop_names'].count('上屋倉'),2)
        self.assertLess(long['stop_ids'].index('sendai_bus:4069_51'),long['stop_ids'].index('sendai_bus:4069_10'))

    def test_addition_preserves_previous_reviews_period_and_directional_links(self):
        for key in ('operating_period','reviewed_days','bus_excluded_days','bus_feed_version',
                'subway_feed_version','subway_transfer_margin_minutes'):
            self.assertEqual(self.review[key],self.previous[key],key)
        self.assertEqual(self.review['bus_patterns'][:-3],self.previous['bus_patterns'])
        self.assertEqual(self.review['bus_subway_transfers'][:-1],self.previous['bus_subway_transfers'])
        link=self.review['bus_subway_transfers'][-1]
        self.assertEqual((link['from_stop_id'],link['to_stop_id']),('sendai_subway:namboku/泉中央','sendai_bus:1085_11'))
        self.assertEqual((link['standard_minutes'],link['margin_minutes']),(8,2))
        self.assertEqual(link['time_basis'],'experimental_planning_assumption')
        self.assertFalse(any(l['from_stop_id']=='sendai_bus:1085_11' for l in self.review['bus_subway_transfers']))
        old=self.build(self.bus,self.previous)
        self.assertEqual(sum(t.startswith('sendai_bus:') for t in old.free_scope.allowed_trip_ids),197)
        self.assertEqual(sum(t.startswith('sendai_bus:') for t in self.network.free_scope.allowed_trip_ids),281)

    def test_capabilities_add_73_concrete_poles_and_keep_finite_date_rejections(self):
        caps=self.client.get('/test/sendai/capabilities').json()
        current={s['id'] for s in caps['stops'] if s['mode']=='bus'}
        old={s for p in self.previous['bus_patterns'] for s in p['stop_ids']}
        self.assertEqual((len(current),len(current-old)),(172,73))
        self.assertTrue({'sendai_bus:1085_11','sendai_bus:8035_10','sendai_bus:3025_50','sendai_bus:4055_11'}<=current-old)
        self.assertEqual((len(caps['operating_dates']),caps['operating_dates'][-1]),(48,'2026-11-30'))
        for day in ('2026-10-25','2026-11-22','2026-12-01'):
            self.assertNotIn(day,caps['operating_dates'])
            self.assertEqual(self.request(day).status_code,422)
        self.assertEqual(self.request('2026-11-30').status_code,200)
        self.assertEqual(self.request('2026-11-30',1380).status_code,422)

    def test_new_bay_is_required_and_not_implicitly_mirrored(self):
        review=copy.deepcopy(self.review)
        review['bus_subway_transfers'].pop()
        network=self.build(self.bus,review)
        case=self.matrix['cases'][2]
        self.assertFalse(self.search(case,network))
        self.assertIsNone(optimum(self.raw(date(2026,11,19)),review,case['origin'],case['destination'],
            case['departure_minute'],max_boardings=3,max_minutes=180))

    def test_changed_trip_set_or_complete_pattern_fails_fast(self):
        for rid in NEW:
            for change in ('trip','path'):
                with self.subTest(route=rid,change=change):
                    review=copy.deepcopy(self.review)
                    p=next(p for p in review['bus_patterns'] if p['route_id']==rid)
                    if change=='trip':p['trip_ids'].pop()
                    else:p['stop_ids'][4],p['stop_ids'][5]=p['stop_ids'][5],p['stop_ids'][4]
                    with self.assertRaisesRegex(ValueError,'exact reviewed bus concrete-trip set mismatch'):
                        self.build(self.bus,review)

    def test_same_number_and_same_full_path_do_not_approve_another_route(self):
        source=copy.deepcopy(self.source)
        routes=rows(source['files']['routes.txt'])
        template=next(r for r in routes if r['route_id']=='10061')
        routes.append({**template,'route_id':'99999'})
        trips=rows(source['files']['trips.txt'])
        template=next(t for t in trips if t['route_id']=='10061')
        fake='synthetic_unreviewed_30'
        trips.append({**template,'route_id':'99999','trip_id':fake})
        times=rows(source['files']['stop_times.txt'])
        times.extend([{**r,'trip_id':fake} for r in times if r['trip_id']==template['trip_id']])
        for name,rr in (('routes.txt',routes),('trips.txt',trips),('stop_times.txt',times)):replace_rows(source,name,rr)
        review={**self.review,'bus_feed_version':'synthetic_unreviewed_30_v1'}
        bus=load_bus(source,review)
        network=self.build(bus,review)
        self.assertNotIn('sendai_bus:'+fake,network.free_scope.allowed_trip_ids)

    def test_r18_does_not_create_an_unreviewed_reverse_18(self):
        case=dict(civil_date='2026-11-19',departure_minute=540,
            origin='sendai_subway:tozai/荒井',destination='sendai_bus:4055_11')
        self.assertFalse(self.search(case))
        self.assertIsNone(optimum(self.raw(date(2026,11,19)),self.review,case['origin'],case['destination'],540,
            max_boardings=3,max_minutes=180))


if __name__=='__main__':unittest.main()
