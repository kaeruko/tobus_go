"""Focused facility coordinates versus independently frozen raw-row optima."""
from datetime import date
import math
from unittest.mock import patch
import unittest

from tests import test_sendai_normal_coordinates as normal
from tests.sendai_bulk_fixture import read
from tests.sendai_municipal_oracle import runs,arrivals,validate
from scripts.check_sendai_expansion import raw_day_kinds
from sendai_practical_network import search_practical_subway
import sendai_practical_network as practical


class SendaiGeneralRealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        normal.SendaiNormalCoordinateTests.setUpClass()
        cls.fixture=normal.SendaiNormalCoordinateTests
        cls.cases=read('general_coordinate_cases_20261018.json')['cases']
        cls.day=date(2026,11,19)
        cls.raw=runs(cls.fixture.source['files'],cls.fixture.raw_subway,
            {cls.day:raw_day_kinds(cls.fixture.review['operating_period'])[cls.day]},cls.day,cls.fixture.review)

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
