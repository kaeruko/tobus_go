"""Long-route data and directed Nagamachi links on the existing common model."""
import contextlib
import copy
from datetime import date
import io
import unittest

from fastapi.testclient import TestClient
from app.sendai_practical_routes import create_sendai_practical_test_app
from sendai_operating_period import OperatingPeriodReview
from sendai_practical_bundle import build_reviewed_municipal_model, load_reviewed_subway
from sendai_practical_network import PracticalRide, PracticalTransfer, search_practical_subway
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_municipal_oracle import optimum, rows, runs, raw_services, validate
from tests.test_sendai_arai21_practical import load_bus
from tests.test_sendai_stage2 import replace_rows
from tests.test_sendai_stage4 import F, read
from scripts.check_sendai_expansion import raw_day_kinds, verify_model

NEW={'sendai_bus:10102','sendai_bus:10357','sendai_bus:10253'}


class SendaiStage8Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=read('municipal_bus_subset_20261006_stage8.json');cls.review=read('municipal_review_20261017_stage8.json')
        cls.previous=read('municipal_review_20261017_stage7.json');cls.matrix=read('municipal_fixed_cases_20261017_stage8.json')
        cls.period=OperatingPeriodReview.from_mapping(cls.review['operating_period']);cls.kinds=raw_day_kinds(cls.review['operating_period'])
        cls.bus=load_bus(cls.source,cls.review)
        cls.subway,cls.raw_subway=load_reviewed_subway(F/'published_20230701.json',F/'practical_review_20261016.json',operating_period=cls.period)
        cls.params=NetworkSearchParameters(**cls.matrix['parameters']);cls.network=cls.build(cls.review)
        cls.client=TestClient(create_sendai_practical_test_app(cls.network,environment='test',parameters=cls.params,
            operating_period=cls.period,coverage_label=cls.review['coverage_label']))

    @classmethod
    def tearDownClass(cls):cls.client.close()

    @classmethod
    def build(cls,review,bus=None):
        return build_reviewed_municipal_model(cls.subway,cls.bus if bus is None else bus,review,accept_experimental_bus_transfers=True)

    def search(self,c,network):
        with contextlib.redirect_stdout(io.StringIO()):
            return search_practical_subway(network,c['origin'],c['destination'],civil_date=date.fromisoformat(c['civil_date']),
                departure_minute=c['departure_minute'],parameters=self.params)

    def test_eighteen_fixed_raw_routes_complete_witnesses_and_api(self):
        self.assertEqual([c['expected_arrival_minute'] for c in self.matrix['cases']],
            [550,551,598,571,399,592,607,592,556,577,626,658,603,626,632,598,560,562])
        with contextlib.redirect_stdout(io.StringIO()):
            _,client=verify_model(self.bus,self.source['files'],self.raw_subway,self.subway,self.review,self.matrix,profile='stage8')
        client.close()
        for c in self.matrix['cases']:
            result=self.search(c,self.network)
            if 'bus' in c['modes']:
                self.assertTrue(any(isinstance(e,PracticalRide) and e.source.route_id in NEW for e in result[0].events),c['category'])
        c=self.matrix['cases'][4]
        self.assertIn('sendai_bus:30_1_13003970',[e.source.trip_id for e in self.search(c,self.network)[0].events if isinstance(e,PracticalRide)])

    def test_exact_five_patterns_full_services_and_short_source_branch(self):
        patterns=self.review['bus_patterns'][-5:]
        trips={'sendai_bus:'+t['trip_id']:t for t in rows(self.source['files']['trips.txt'])}
        services=[raw_services(self.source['files'],day) for day in (date(2026,11,19),date(2026,11,21),date(2026,11,23))]
        self.assertEqual([[sum(trips[tid]['service_id'] in active for tid in p['trip_ids']) for active in services] for p in patterns],
            [[3,0,0],[22,18,16],[19,16,15],[29,18,14],[29,19,15]])
        self.assertEqual(sorted((p['route_id'],len(p['stop_ids']),len(p['trip_ids'])) for p in patterns),
            [('sendai_bus:10102',15,61),('sendai_bus:10102',15,63),('sendai_bus:10253',15,50),('sendai_bus:10357',8,3),('sendai_bus:10357',15,56)])
        self.assertEqual((len(rows(self.source['files']['trips.txt'])),len(rows(self.source['files']['stop_times.txt']))),(752,16220))
        for p in patterns:
            exact={t['trip_id']:t for t in rows(self.source['files']['trips.txt']) if 'sendai_bus:'+t['trip_id'] in p['trip_ids']}
            self.assertEqual(len(exact),len(p['trip_ids']))
            for day in (date(2026,11,19),date(2026,11,21),date(2026,11,23)):
                active=raw_services(self.source['files'],day)
                self.assertTrue(any(t['service_id'] in active for t in exact.values()) or len(p['stop_ids'])==8)
        short=next(p for p in patterns if len(p['stop_ids'])==8)
        self.assertEqual((short['stop_ids'][0],short['stop_ids'][-1]),('sendai_bus:7265_10','sendai_bus:7051_0'))
        self.assertNotIn('sendai_bus:7111_10',short['stop_ids'])
        raw=runs(self.source['files'],self.raw_subway,self.kinds,date(2026,11,19),self.review)
        for rr in raw:
            if rr['day']!=date(2026,11,19) or not any(rr['trip'] in p['trip_ids'] for p in patterns):continue
            for pole in ('sendai_bus:6008_50','sendai_bus:6008_10','sendai_bus:7111_10','sendai_bus:7111_11'):
                if pole in rr['stops']:
                    i=rr['stops'].index(pole);self.assertEqual((rr['pickup'][i],rr['dropoff'][i]),('0','0'))

    def test_previous_519_period_and_all_old_directional_records_are_identical(self):
        self.assertEqual(self.review['bus_patterns'][:-5],self.previous['bus_patterns'])
        self.assertEqual(self.review['bus_subway_transfers'][:-8],self.previous['bus_subway_transfers'])
        for k in ('operating_period','reviewed_days','bus_excluded_days','bus_feed_version','subway_feed_version','subway_transfer_margin_minutes'):
            self.assertEqual(self.review[k],self.previous[k])
        self.assertEqual(sum(t.startswith('sendai_bus:') for t in self.build(self.previous).free_scope.allowed_trip_ids),519)
        self.assertEqual(sum(t.startswith('sendai_bus:') for t in self.network.free_scope.allowed_trip_ids),752)

    def test_each_hub_is_usable_independently_with_original_oracle(self):
        # These are two predeclared isolation conditions, not an automatic
        # fallback after a failed query. The main model retains both hubs.
        all_links=self.review['bus_subway_transfers'][-8:]
        self.assertEqual(len({(l['from_stop_id'],l['to_stop_id']) for l in all_links}),8)
        for station in ('長町','長町南'):
            review=copy.deepcopy(self.review)
            review['bus_subway_transfers']=self.previous['bus_subway_transfers']+[
                l for l in all_links if 'sendai_subway:namboku/'+station in (l['from_stop_id'],l['to_stop_id'])]
            self.assertEqual(len(review['bus_subway_transfers'])-len(self.previous['bus_subway_transfers']),4)
            network=self.build(review);day=date(2026,11,19)
            rr=runs(self.source['files'],self.raw_subway,self.kinds,day,review)
            witnessed=set()
            client=TestClient(create_sendai_practical_test_app(network,environment='test',parameters=self.params,operating_period=self.period,coverage_label=review['coverage_label']))
            self.addCleanup(client.close)
            for origin,dest in [('sendai_bus:7605_50','sendai_subway:namboku/泉中央'),('sendai_subway:namboku/泉中央','sendai_bus:7605_10'),
                    ('sendai_bus:7501_10','sendai_subway:namboku/泉中央'),('sendai_subway:namboku/泉中央','sendai_bus:7501_0')]:
                c=dict(origin=origin,destination=dest,civil_date=day.isoformat(),departure_minute=540)
                expected=optimum(rr,review,origin,dest,540,max_boardings=3,max_minutes=180);self.assertIsNotNone(expected)
                result=self.search(c,network);self.assertTrue(result)
                self.assertEqual(result[0].arrival_estimate.minute,expected)
                validate(result[0],rr,review,day,origin,dest,540)
                self.assertTrue(any(isinstance(e,PracticalTransfer) and 'sendai_subway:namboku/'+station in (e.from_stop_id,e.to_stop_id) for e in result[0].events))
                witnessed.update((e.from_stop_id,e.to_stop_id) for e in result[0].events if isinstance(e,PracticalTransfer))
                with contextlib.redirect_stdout(io.StringIO()):
                    response=client.post('/test/sendai/route',json=dict(origin_stop_id=origin,destination_stop_id=dest,civil_date=day.isoformat(),departure_minute=540,
                        fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True))
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['candidates'][0]['arrival']['minute'],dict(numerator=int(expected),denominator=1))
            self.assertTrue({(l['from_stop_id'],l['to_stop_id']) for l in review['bus_subway_transfers'][-4:]}<=witnessed)
        linked={s for l in all_links for s in (l['from_stop_id'],l['to_stop_id'])}
        self.assertFalse({'sendai_bus:6007_10','sendai_bus:6007_50','sendai_bus:7501_10','sendai_bus:7501_0','sendai_bus:7111_0','sendai_bus:7111_12'}&linked)
        self.assertTrue(all(l['time_basis']=='experimental_planning_assumption' and l['margin_minutes']==2 for l in all_links))

    def test_removing_both_new_hubs_disconnects_new_area(self):
        review=copy.deepcopy(self.review);del review['bus_subway_transfers'][-8:]
        network=self.build(review);rr=runs(self.source['files'],self.raw_subway,self.kinds,date(2026,11,19),review)
        for c in self.matrix['cases'][5:8]:
            self.assertFalse(self.search(c,network))
            self.assertIsNone(optimum(rr,review,c['origin'],c['destination'],540,max_boardings=3,max_minutes=180))

    def test_every_new_pattern_trip_set_and_stop_order_are_bound(self):
        for index in range(5):
            for field in ('trip_ids','stop_ids'):
                review=copy.deepcopy(self.review);p=review['bus_patterns'][-5+index]
                if field=='trip_ids':p[field].pop()
                else:p[field][2],p[field][3]=p[field][3],p[field][2]
                with self.assertRaisesRegex(ValueError,'exact reviewed bus concrete-trip set mismatch'):self.build(review)

    def test_same_number_and_complete_path_do_not_approve_other_route(self):
        source=copy.deepcopy(self.source)
        rr=rows(source['files']['routes.txt']);r=next(r for r in rr if r['route_id']=='10102');rr.append({**r,'route_id':'99999'});replace_rows(source,'routes.txt',rr)
        tt=rows(source['files']['trips.txt']);t=next(t for t in tt if t['route_id']=='10102');fake='synthetic_unreviewed_58'
        tt.append({**t,'route_id':'99999','trip_id':fake});replace_rows(source,'trips.txt',tt)
        times=rows(source['files']['stop_times.txt']);times.extend([{**r,'trip_id':fake} for r in times if r['trip_id']==t['trip_id']]);replace_rows(source,'stop_times.txt',times)
        review={**self.review,'bus_feed_version':'synthetic_unreviewed_58_v1'}
        self.assertNotIn('sendai_bus:'+fake,self.build(review,load_bus(source,review)).free_scope.allowed_trip_ids)

    def test_293_poles_finite_period_and_existing_exclusions(self):
        caps=self.client.get('/test/sendai/capabilities').json();current={s['id'] for s in caps['stops'] if s['mode']=='bus'};old={s for p in self.previous['bus_patterns'] for s in p['stop_ids']}
        self.assertEqual((len(current),len(current-old)),(293,48))
        self.assertEqual((len(caps['operating_dates']),caps['operating_dates'][-1]),(48,'2026-11-30'))
        c=self.matrix['cases'][0]
        for day,minute,code in [('2026-10-25',540,422),('2026-11-22',540,422),('2026-12-01',540,422),('2026-11-30',540,200),('2026-11-30',1380,422)]:
            with contextlib.redirect_stdout(io.StringIO()):
                response=self.client.post('/test/sendai/route',json=dict(origin_stop_id=c['origin'],destination_stop_id=c['destination'],civil_date=day,departure_minute=minute,
                    fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True))
            self.assertEqual(response.status_code,code,(day,minute,response.text))
        self.assertFalse(caps['actual_connection_guaranteed']);self.assertFalse(caps['special_timetables_verified'])


if __name__=='__main__':unittest.main()
