"""Focused facility coordinates versus independently frozen raw-row optima."""
from datetime import date
import math
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from tests import test_sendai_normal_coordinates as normal
from tests.sendai_bulk_fixture import read
from tests.sendai_municipal_oracle import runs,arrivals,validate,few_transfer_arrivals
from scripts.check_sendai_expansion import raw_day_kinds
from sendai_practical_network import search_practical_subway
import sendai_practical_network as practical


class SendaiGeneralRealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Match the development server: do not eagerly build a second, unused
        # normal-fare graph before timing bounded free-pass searches.
        f=SimpleNamespace();f.source=normal.load_source();f.review=read('municipal_review_20261017_bulk.json')
        f.bus=normal.load_bus(f.source,f.review)
        f.period=normal.OperatingPeriodReview.from_mapping(f.review['operating_period'])
        f.subway,f.raw_subway=normal.load_reviewed_subway(normal.F/'published_20230701.json',
            normal.F/'practical_review_20261016.json',operating_period=f.period)
        f.network=normal.build_reviewed_municipal_model(f.subway,f.bus,f.review,
            accept_experimental_bus_transfers=True)
        f.adapter=normal.SendaiCoordinateScope(None,f.network,f.period,environment='development',
            access_reviews=normal.nagamachi_minami_access(f.network),
            normal_backend_factory=lambda:normal.GtfsRouteEngine(f.bus))
        cls.fixture=f
        cls.cases=read('general_coordinate_cases_20261018.json')['cases']
        cls.few=read('general_few_transfers_20261018.json')
        cls.day=date(2026,11,19)
        cls.raw=runs(cls.fixture.source['files'],cls.fixture.raw_subway,
            {cls.day:raw_day_kinds(cls.fixture.review['operating_period'])[cls.day]},cls.day,cls.fixture.review)

    def checked_http(self,case,mode,expected,origin_id,destination_id):
        from sendai_practical_serializer import serialize_practical_journey
        observed=[]
        def trace(*args,**kwargs):
            result=search_practical_subway(*args,**kwargs);observed.extend(result);return result
        with patch('sendai_coordinate_routes.search_practical_subway',side_effect=trace):
            response=normal.make_client(self.fixture.adapter).post('/route',json={**normal.body(case),'pref':mode})
        self.assertEqual(response.status_code,200,response.text)
        data=response.json();candidate=data['candidates'][0]
        self.assertEqual(candidate['arrival_time'],f'{expected//60:02d}:{expected%60:02d}')
        self.assertGreaterEqual(candidate['boards'],1)
        self.assertEqual(candidate['access']['origin']['stop_id'],origin_id)
        self.assertEqual(candidate['access']['destination']['stop_id'],destination_id)
        matched=[j for j in observed if serialize_practical_journey(j)==candidate['planning_journey']]
        self.assertEqual(len(matched),1)
        journey=matched[0]
        validate(journey,self.raw,self.fixture.review,self.day,origin_id,destination_id,
                 540+candidate['access']['origin']['minutes'])
        self.assertEqual(candidate['total_time'],expected-540)
        self.assertEqual(sum(s['minutes'] for s in candidate['steps']),candidate['total_time'])
        diagnostic=data['meta']['coordinate_access']
        self.assertTrue(diagnostic['comparison_complete'])
        self.assertEqual(diagnostic['completed_pairs'],diagnostic['total_pairs'])
        self.assertEqual(diagnostic['network_builds'],1)
        self.assertEqual(diagnostic['minimum_transit_boardings'],1)
        return candidate,journey,diagnostic

    def test_few_transfers_facilities_match_independent_raw_cost_objectives_and_witnesses(self):
        for case,frozen in zip(self.cases,self.few['facility_cases'],strict=True):
            with self.subTest(case=case['name']):
                self.assertEqual(case['name'],frozen['name'])
                objectives=[]
                for i,(_,origin,ow,_) in enumerate(case['origin_candidates']):
                    times=few_transfer_arrivals(self.raw,self.fixture.review,origin,540+ow,
                        max_boardings=3,max_minutes=180-ow,
                        destination_walk_minutes={sid:dw for _,sid,dw,_ in case['destination_candidates']})
                    for j,(_,destination,dw,_) in enumerate(case['destination_candidates']):
                        if destination in times:
                            count,cost,clock,_=times[destination]
                            objectives.append((count,cost,clock+dw,clock,i,j))
                self.assertEqual(min(objectives),(frozen['boardings'],frozen['planning_cost_tenths'],
                    frozen['arrival_minute'],frozen['transit_arrival'],frozen['origin_rank'],frozen['destination_rank']))
                candidate,journey,diagnostic=self.checked_http(case,'fewTransfers',frozen['arrival_minute'],
                    frozen['origin'],frozen['destination'])
                self.assertEqual(candidate['boards'],frozen['boardings'])
                self.assertAlmostEqual(journey.planning_cost,frozen['planning_cost_tenths']/10)
                self.assertEqual(diagnostic['total_pairs'],len(case['origin_candidates'])*len(case['destination_candidates']))
                if case['name']=='ward_offices':
                    self.assertGreater(frozen['arrival_minute'],case['arrival_minute'])
                    self.assertEqual([s['trip_id'] for s in candidate['steps'] if s['kind']=='bus'],
                                     ['sendai_bus:20_1_12003910'])

    def test_walk_only_and_exact_same_pole_do_not_hide_valid_transit(self):
        from transit_timetable_choices import NetworkSearchParameters
        for frozen in self.few['zero_ride_regressions']:
            case={**frozen,'civil_date':'2026-11-19','bus_only':False}
            origin,destination=frozen['origin_stop_id'],frozen['destination_stop_id']
            earliest=arrivals(self.raw,self.fixture.review,origin,540,max_boardings=3,max_minutes=180)
            few=few_transfer_arrivals(self.raw,self.fixture.review,origin,540,max_boardings=3,max_minutes=180)
            self.assertEqual(earliest[destination],frozen['earliest'])
            self.assertEqual(few[destination][:3],(frozen['few']['boardings'],
                frozen['few']['planning_cost_tenths'],frozen['few']['arrival_minute']))
            for mode,expected in (('time',frozen['earliest']),('fewTransfers',frozen['few']['arrival_minute'])):
                with self.subTest(destination=destination,mode=mode):
                    candidate,journey,_=self.checked_http(case,mode,expected,origin,destination)
                    self.assertEqual(candidate['boards'],2)
                    if mode=='fewTransfers':
                        self.assertAlmostEqual(journey.planning_cost,frozen['few']['planning_cost_tenths']/10)
            # There is a 16-minute zero-ride connection, but no actual ride
            # arriving within this window. No quote error and no fake route.
            self.assertNotIn(destination,arrivals(self.raw,self.fixture.review,origin,540,
                max_boardings=3,max_minutes=16))
            for mode in ('time','fewTransfers'):
                self.assertEqual(search_practical_subway(self.fixture.network,origin,destination,
                    civil_date=self.day,departure_minute=540,mode=mode,
                    parameters=NetworkSearchParameters(max_candidates=1,max_boardings=3,max_travel_minutes=16)),())

    def test_three_facility_queries_raw_optimum_specific_run_witness_and_single_materialization(self):
        for case in self.cases:
            with self.subTest(case=case['name']):
                # Original rows and predeclared coordinate assumptions, with
                # no access adapter or timetable/core implementation involved.
                pairs=[]
                for _,origin,ow,_ in case['origin_candidates']:
                    times=arrivals(self.raw,self.fixture.review,origin,540+ow,max_boardings=3,max_minutes=180-ow)
                    for _,destination,dw,_ in case['destination_candidates']:
                        if destination in times and times[destination]+dw<=720:
                            pairs.append((origin,destination,ow,dw,times[destination]))
                self.assertEqual(min(p[-1]+p[-2] for p in pairs),case['arrival_minute'])
                observed=[]
                def trace(*args,**kwargs):
                    result=search_practical_subway(*args,**kwargs);observed.extend(result);return result
                with patch('sendai_coordinate_routes.search_practical_subway',side_effect=trace), \
                     patch.object(practical,'build_transit_network',wraps=practical.build_transit_network) as builds, \
                     patch.object(practical,'_latest_source_minute',wraps=practical._latest_source_minute) as source_scans, \
                     patch.object(practical,'_practical_input_version',wraps=practical._practical_input_version) as versions:
                    response=normal.make_client(self.fixture.adapter).post('/route',json=normal.body(case))
                self.assertEqual(response.status_code,200,response.text)
                data=response.json();candidate=data['candidates'][0]
                expected=f"{case['arrival_minute']//60:02d}:{case['arrival_minute']%60:02d}"
                self.assertEqual(candidate['arrival_time'],expected)
                self.assertEqual(builds.call_count,1)
                self.assertEqual(source_scans.call_count,1)
                self.assertEqual(versions.call_count,1)
                diagnostic=data['meta']['coordinate_access']
                self.assertTrue(diagnostic['comparison_complete'])
                self.assertFalse(diagnostic['all_geographic_candidates_compared'])
                self.assertEqual(diagnostic['completed_pairs'],len(case['origin_candidates'])*len(case['destination_candidates']))
                preparations={'ward_offices':6,'tai_to_izumi':6,'kasu_to_tai':1}
                self.assertEqual(diagnostic['timetable_preparations'],preparations[case['name']])
                origin,dest=(candidate['access'][role] for role in ('origin','destination'))
                # Match the exact original-run wire, not only its final clock.
                from sendai_practical_serializer import serialize_practical_journey
                matched=[j for j in observed if serialize_practical_journey(j)==candidate['planning_journey']]
                self.assertEqual(len(matched),1)
                validate(matched[0],self.raw,self.fixture.review,self.day,origin['stop_id'],dest['stop_id'],540+origin['minutes'])
                self.assertEqual(candidate['total_time'],case['arrival_minute']-540)
                self.assertEqual(sum(s['minutes'] for s in candidate['steps']),candidate['total_time'])
                self.assertEqual(candidate['walking_distance_meters'],sum(s['meters'] for s in candidate['steps'] if s['kind']=='walk'))
                for value in (origin,dest):
                    if value['basis']=='haversine_80m_per_minute_estimate':
                        self.assertEqual(value['minutes'],math.ceil(value['geometric_distance_meters']/80))
                        self.assertFalse(value['connection_guaranteed']);self.assertIsNone(value['physical_walk_meters'])
                # The nearest boarding pole is NOT the winner for Taihaku:
                # raw 7111_51 arrives 11:26, the selected 7111_10 at 09:46.
                if case['name']=='tai_to_izumi':
                    self.assertNotEqual(origin['stop_id'],case['origin_candidates'][0][1])

    def test_unsupported_day_and_no_candidate_keep_fail_closed_contract(self):
        client=normal.make_client(self.fixture.adapter);base=normal.body(self.cases[1])
        for day in ('2026-10-25','2026-11-22','2026-12-01'):
            response=client.post('/route',json={**base,'target_date_str':day})
            self.assertEqual(response.status_code,422,response.text)
        for change in ({'alat':0,'alon':0},{'blat':0,'blon':0}):
            response=client.post('/route',json={**base,**change})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['candidates'],[])
        response=client.post('/route',json={**base,'target_date_str':'2026-11-30','start_time':'23:59'})
        self.assertEqual(response.status_code,422,response.text)

    def test_same_condition_choices_reuse_preserves_every_full_practical_wire(self):
        from transit_timetable_choices import NetworkSearchParameters
        from sendai_practical_serializer import serialize_practical_journey
        case=self.cases[0];origin=case['origin_candidates'][0]
        materializations={};metadata={};profiles=[]
        for choices in (None,{}):
            complete=[]
            for _,destination,walk,_ in case['destination_candidates']:
                values=search_practical_subway(self.fixture.network,origin[1],destination,
                    civil_date=self.day,departure_minute=540+origin[2],
                    parameters=NetworkSearchParameters(max_candidates=1,max_boardings=3,
                        max_travel_minutes=180-origin[2]-walk),
                    _request_materializations=materializations,_request_metadata=metadata,_request_choices=choices)
                complete.append([serialize_practical_journey(v) for v in values])
            profiles.append(complete)
        self.assertEqual(profiles[0],profiles[1])
        self.assertEqual(choices['preparations'],1)
        self.assertEqual(choices['reuse_hits'],5)
        # The lookup provider still holds later departures from the broad
        # window. The unchanged core must reject them under a shorter query.
        short=search_practical_subway(self.fixture.network,origin[1],case['destination_candidates'][0][1],
            civil_date=self.day,departure_minute=540+origin[2],
            parameters=NetworkSearchParameters(max_candidates=1,max_boardings=3,max_travel_minutes=1),
            _request_materializations=materializations,_request_metadata=metadata,_request_choices=choices)
        expected=arrivals(self.raw,self.fixture.review,origin[1],540+origin[2],max_boardings=3,max_minutes=1)
        self.assertNotIn(case['destination_candidates'][0][1],expected)
        self.assertEqual(short,())
        self.assertEqual(choices['preparations'],1)


if __name__=='__main__':unittest.main()
