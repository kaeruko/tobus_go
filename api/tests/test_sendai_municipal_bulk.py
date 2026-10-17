"""Operator-wide review compilation on retained raw GTFS and common SearchCore."""
import contextlib
import copy
from datetime import date
import io
import unittest

from fastapi.testclient import TestClient
from app.sendai_practical_routes import create_sendai_practical_test_app
from sendai_operating_period import OperatingPeriodReview
from sendai_practical_bundle import build_reviewed_municipal_model,load_reviewed_subway
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_bulk_fixture import F,read,load_source
from tests.test_sendai_arai21_practical import load_bus
from tests.test_sendai_stage2 import replace_rows
from tests.sendai_municipal_oracle import rows
from scripts.review_sendai_municipal_bulk import compile_review,inventory
from scripts.check_sendai_municipal_bulk import verify_all_rows,fixed_routes


class SendaiMunicipalBulkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=load_source();cls.review=read('municipal_review_20261017_bulk.json')
        cls.scope=read('municipal_bulk_scope_20261017.json');cls.previous=read('municipal_review_20261017_stage8.json')
        cls.matrix=read('municipal_fixed_cases_20261017_bulk.json');cls.bus=load_bus(cls.source,cls.review)
        cls.period=OperatingPeriodReview.from_mapping(cls.review['operating_period'])
        cls.subway,cls.raw=load_reviewed_subway(F/'published_20230701.json',F/'practical_review_20261016.json',operating_period=cls.period)

    def test_full_inventory_compile_and_all_approved_original_occurrences(self):
        review,report=compile_review(self.source,self.previous,self.scope)
        self.assertEqual(review,self.review);self.assertEqual(report,read('municipal_bulk_inventory_20261017.json'))
        self.assertEqual((report['routes'],report['patterns'],report['trips']),(339,471,8231))
        self.assertEqual(report['approved'],dict(routes=336,patterns=467,trips=8142,stops=2127))
        self.assertEqual(report['new_trips'],7390)
        result=verify_all_rows(self.bus,self.source,self.review)
        self.assertEqual(result['approved_trips'],8142)
        self.assertEqual(result['reviewed_dates'],len(self.previous['reviewed_days']))

    def test_all_decisions_complete_unique_and_source_bound(self):
        for mutation in ('missing','duplicate','unknown','inventory'):
            scope=copy.deepcopy(self.scope)
            if mutation=='missing':scope['groups'][0]['pattern_ids'].pop()
            if mutation=='duplicate':scope['groups'][1]['pattern_ids'].append(scope['groups'][0]['pattern_ids'][0])
            if mutation=='unknown':scope['groups'][0]['pattern_ids'][0]='0'*64
            if mutation=='inventory':scope['inventory']['trips']-=1
            with self.assertRaises(ValueError):compile_review(self.source,self.previous,scope)
        # An exact route with the same public number never inherits another
        # path's review. Source order/calendar/pickup changes need fresh review.
        for name,field,value in [('trips.txt','service_id','changed_service'),('stop_times.txt','pickup_type','1'),('stop_times.txt','stop_sequence','999')]:
            source={**self.source,'files':dict(self.source['files'])};rr=rows(source['files'][name]);rr[0][field]=value;replace_rows(source,name,rr)
            with self.assertRaisesRegex(ValueError,'inventory review differs'):compile_review(source,self.previous,self.scope)

    def test_outside_and_same_number_routes_are_not_conflated(self):
        approved={p['route_id'] for p in self.review['bus_patterns']}
        self.assertIn('sendai_bus:10160',approved)  # 85 in Akiu, distinct from the outside-city 85
        self.assertFalse({'sendai_bus:10036','sendai_bus:10214','sendai_bus:10161'}&approved)
        pp,totals=inventory(self.source);outside=[p for p in pp if p['route_id'] in {'sendai_bus:10036','sendai_bus:10214','sendai_bus:10161'}]
        self.assertEqual((len(outside),sum(len(p['trip_ids']) for p in outside)),(4,89))
        external={'sendai_bus:3253_10','sendai_bus:3253_50','sendai_bus:3255_10','sendai_bus:3255_50'}
        self.assertTrue(all(external.intersection(p['stop_ids']) for p in outside))
        self.assertFalse(external&{s for p in self.review['bus_patterns'] for s in p['stop_ids']})

    def test_previous_patterns_links_and_finite_period_are_unchanged(self):
        self.assertEqual(self.review['bus_patterns'][:20],self.previous['bus_patterns'])
        for key in ('bus_subway_transfers','operating_period','bus_excluded_days','reviewed_days','subway_transfer_margin_minutes','subway_feed_version'):
            self.assertEqual(self.review[key],self.previous[key])
        self.assertEqual(len(self.review['bus_subway_transfers']),22)
        old=build_reviewed_municipal_model(self.subway,self.bus,self.previous,accept_experimental_bus_transfers=True)
        self.assertEqual(sum(t.startswith('sendai_bus:') for t in old.free_scope.allowed_trip_ids),752)

    def test_fixed_raw_optima_full_witnesses_and_asgi_including_no_route(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            net,reports=fixed_routes(self.bus,self.source,self.subway,self.raw,self.review,self.matrix)
        self.assertEqual(len(reports),11)
        modes=[r.get('modes') for r in reports if r.get('modes')]
        self.assertIn(['bus'],modes);self.assertIn(['bus','rail'],modes);self.assertIn(['rail','bus'],modes)
        self.assertTrue(any(len(m)>=3 for m in modes))
        self.assertEqual(next(r for r in reports if r['category']=='rail_new_bus')['status'],'confirmed_no_route')

    def test_capabilities_scope_dates_and_entitlement_remain_explicit(self):
        net=build_reviewed_municipal_model(self.subway,self.bus,self.review,accept_experimental_bus_transfers=True)
        with TestClient(create_sendai_practical_test_app(net,environment='test',parameters=NetworkSearchParameters(max_candidates=1,max_boardings=3,max_travel_minutes=180),operating_period=self.period,coverage_label=self.review['coverage_label'])) as client:
            caps=client.get('/test/sendai/capabilities').json()
            poles={s['id'] for s in caps['stops'] if s['mode']=='bus'}
            self.assertEqual(len(poles),2127);self.assertFalse({'sendai_bus:3253_10','sendai_bus:3255_10'}&poles)
            self.assertEqual(len(caps['operating_dates']),48)
            self.assertFalse({'2026-10-25','2026-11-22','2026-12-01'}&set(caps['operating_dates']))
            self.assertFalse(caps['actual_connection_guaranteed'])
            base=dict(origin_stop_id='sendai_bus:2005_50',destination_stop_id='sendai_bus:2041_0',civil_date='2026-11-19',departure_minute=540,fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True)
            for change in ({'civil_date':'2026-12-01'},{'civil_date':'2026-10-25'},{'civil_date':'2026-11-22'},{'fare_policy_id':'sendai_keiro_pass'},{'accept_experimental_transfer_model':False}):
                response=client.post('/test/sendai/route',json={**base,**change});self.assertEqual(response.status_code,422,response.text)


if __name__=='__main__':unittest.main()
