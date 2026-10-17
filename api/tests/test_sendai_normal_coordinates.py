"""Normal /route -> reviewed concrete journey; retained source oracle only.

No bulk audit replay. Five new boundary cases compare the actual normal API
journey with independent original-row optima and full concrete witnesses.
"""
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.route_endpoint import register_route_endpoint
from app.route_only_routes import SharedNetworkApiRouteRequest
from gtfs_route_backend import GtfsRouteEngine
from route_engine import GeoPoint
from sendai_coordinate_routes import SendaiCoordinateScope
from sendai_coordinate_access import nagamachi_minami_access
from sendai_practical_bundle import build_reviewed_municipal_model, load_reviewed_subway
from sendai_practical_network import PracticalRide, search_practical_subway
from sendai_practical_serializer import serialize_practical_journey
from sendai_operating_period import OperatingPeriodReview
from tests.sendai_bulk_fixture import F, load_source, read
from tests.test_sendai_arai21_practical import load_bus
from tests.sendai_municipal_oracle import runs, optimum, validate
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.check_sendai_expansion import raw_day_kinds


def make_client(adapter):
    app = FastAPI()
    app.state.loading_status = "ready"
    app.state.city_key = "sendai"
    app.state.route_engine = adapter
    register_route_endpoint(app, warmup_message="loading", request_model=SharedNetworkApiRouteRequest)
    return TestClient(app)


def body(case):
    return dict(alat=case['origin'][0], alon=case['origin'][1],
        blat=case['destination'][0], blon=case['destination'][1],
        target_date_str=case['civil_date'], start_time='09:00', pref='time',
        bus_only=case['bus_only'], fare_policy_id='sendai_fureai_pass',
        accept_experimental_transfer_model=True)


class SendaiNormalCoordinateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_source()
        cls.review = read('municipal_review_20261017_bulk.json')
        cls.bus = load_bus(cls.source, cls.review)
        cls.period = OperatingPeriodReview.from_mapping(cls.review['operating_period'])
        cls.subway, cls.raw_subway = load_reviewed_subway(F/'published_20230701.json',
            F/'practical_review_20261016.json', operating_period=cls.period)
        cls.network = build_reviewed_municipal_model(cls.subway, cls.bus, cls.review,
            accept_experimental_bus_transfers=True)
        cls.normal = GtfsRouteEngine(cls.bus)
        cls.adapter = SendaiCoordinateScope(cls.normal,cls.network,cls.period,
            environment='development', access_reviews=nagamachi_minami_access(cls.network))
        cls.cases = read('normal_coordinate_cases_20261017.json')['cases']
        cls.walk_parity = read('normal_coordinate_parity_20261017.json')['cases']

    def test_normal_api_five_actual_journeys_match_raw_oracle_and_stop_contract(self):
        day = date(2026,11,19)
        raw = runs(self.source['files'],self.raw_subway,{day:raw_day_kinds(self.review['operating_period'])[day]},day,self.review)
        for case in self.cases:
            with self.subTest(case=case['name']):
                expected_raw = [r for r in raw if r['mode']=='bus'] if case['bus_only'] else raw
                start = 540 + case['origin_access_minutes']
                expected = optimum(expected_raw,self.review,case['origin_stop_id'],case['destination_stop_id'],
                    start,max_boardings=3,max_minutes=180-case['origin_access_minutes']-case['destination_access_minutes'])
                self.assertEqual(expected+case['destination_access_minutes'],case['arrival_minute'])
                observed = []
                def trace(*args,**kwargs):
                    result=search_practical_subway(*args,**kwargs);observed.extend(result);return result
                with patch('sendai_coordinate_routes.search_practical_subway', side_effect=trace):
                    response = make_client(self.adapter).post('/route',json=body(case))
                self.assertEqual(response.status_code,200,response.text)
                payload=response.json();self.assertTrue(payload['meta']['development_only'])
                candidate=payload['candidates'][0]
                # Captured on the unchanged a028dbf8 main before extraction.
                # Freeze every serialized walking field, including unknown
                # physical distance, unmeasured time, margins and source IDs.
                # Whole-journey input_version and derived IDs already vary
                # between interpreter processes; the raw oracle below remains
                # the independent authority for the complete concrete route.
                self.assertEqual([s for s in candidate['steps'] if s['kind']=='walk'],
                    self.walk_parity[case['name']]['walks'])
                self.assertEqual(candidate['arrival_time'],f"{case['arrival_minute']//60:02d}:{case['arrival_minute']%60:02d}")
                self.assertEqual(candidate['planning_journey'],serialize_practical_journey(observed[0]))
                validate(observed[0],expected_raw,self.review,day,case['origin_stop_id'],case['destination_stop_id'],start)
                rides=[e for e in observed[0].events if isinstance(e,PracticalRide)]
                if case['bus_only']:
                    self.assertTrue(rides)
                    self.assertTrue(all(e.source.mode=='bus' for e in rides))
                else:
                    self.assertEqual([e.source.mode for e in rides],case['expected_modes'])
                quote=candidate['fare'];self.assertEqual(quote['payNowYen'],0);self.assertIsNone(quote['normalFareYen'])
                self.assertEqual(quote['policyId'],'sendai_fureai_pass')
                serialized=[s for s in candidate['steps'] if s['kind'] in ('bus','rail')]
                for step,event in zip(serialized,rides):
                    self.assertEqual((step['trip_id'],step['route_id'],step['departureStopId'],step['arrivalPoleId']),
                        (event.source.trip_id,event.source.route_id,event.source.from_stop_id,event.source.to_stop_id))
                    self.assertEqual([p['id'] for p in step['stops']],list(event.source.stop_ids))
                if case['origin_access_minutes']:
                    self.assertEqual(candidate['steps'][0]['kind'],'walk')
                    self.assertEqual(candidate['steps'][0]['minutes'],1)
                    self.assertFalse(candidate['steps'][0]['planning_details']['walking_time_measured'])

    def test_pass_default_normal_and_consent_are_independent(self):
        client=make_client(self.adapter);base=body(self.cases[0])
        without_policy={k:v for k,v in base.items() if k!='fare_policy_id'}
        with patch.object(self.normal,'search',wraps=self.normal.search) as normal:
            response=client.post('/route',json=without_policy)
            # This unchanged legacy coordinate batch reaches its existing
            # safety guard for this exact OD. Preserve the observed diagnostic;
            # never turn a normal-fare failure into a successful free search.
            self.assertEqual(response.status_code,503,response.text);normal.assert_called_once()
            self.assertEqual(response.json()['detail']['code'],'route_search_limit')
            self.assertIn('max_visited',response.json()['detail']['diagnostic'])
        for change in ({'accept_experimental_transfer_model':False},
                       {'accept_experimental_transfer_model':'true'},
                       {'fare_policy_id':'sendai_keiro_pass'},{'fare_policy_id':'tokyo_toei_transport_pass'}):
            response=client.post('/route',json={**base,**change})
            self.assertEqual(response.status_code,422,response.text)

    def test_unreviewed_coordinates_other_poles_and_outside_scope_fail_closed(self):
        base=body(self.cases[0]);client=make_client(self.adapter)
        # A few metres near the known pole do not authorize any sidewalk.
        for lat,lon in [(base['alat']+.00005,base['alon']),
                        (38.224693,140.876349),  # bay 7 is a separate coordinate, not the reviewed bay-2 footprint
                        (38.2319,140.8893),     # hospital entrance access is not reviewed
                        (38.2907,140.9997)]:   # unreviewed external area
            if (lat,lon)==(38.224693,140.876349):
                # Its exact pole is a valid independent input, never an alias.
                endpoint=self.adapter.endpoint(GeoPoint(lat,lon),'origin')
                self.assertEqual(endpoint['stop_id'],'sendai_bus:7111_11')
                continue
            response=client.post('/route',json={**base,'alat':lat,'alon':lon})
            self.assertEqual(response.status_code,422,response.text)
            self.assertIn('unreviewed_coordinate_access',response.text)
        for stop in ('sendai_bus:3253_10','sendai_bus:3255_50'):
            s=self.network.free_scope.snapshot.stops[stop]
            response=client.post('/route',json={**base,'alat':s.lat,'alon':s.lon})
            self.assertEqual(response.status_code,422,response.text)

    def test_finite_dates_and_last_day_preserved(self):
        client=make_client(self.adapter);base=body(self.cases[0])
        good=client.post('/route',json={**base,'target_date_str':'2026-11-30'})
        self.assertEqual(good.status_code,200,good.text)
        self.assertEqual(good.json()['candidates'][0]['arrival_time'],'09:38')
        for value in ('2026-10-25','2026-11-22','2026-12-01','2026-10-11'):
            result=client.post('/route',json={**base,'target_date_str':value})
            self.assertEqual(result.status_code,422,result.text)

    def test_reviewed_surface_is_directional_and_cannot_bridge_curbs(self):
        point=GeoPoint(38.22439,140.87613)
        for role in ('origin','destination'):
            value=self.adapter.endpoint(point,role)
            self.assertEqual(value['stop_id'],'sendai_bus:7111_10')
            self.assertEqual(value['basis'],'reviewed_surface_planning_assumption')
        with self.assertRaisesRegex(ValueError,'unreviewed_coordinate_access'):
            self.adapter.endpoint(GeoPoint(38.22464,140.87613),'origin')
        with self.assertRaises(ValueError):
            SendaiCoordinateScope(self.normal,self.network,self.period,environment='production')

    def test_unchanged_normal_backend_is_constructed_once_on_explicit_demand(self):
        from unittest.mock import Mock
        factory=Mock(return_value=self.normal)
        adapter=SendaiCoordinateScope(None,self.network,self.period,environment='development',normal_backend_factory=factory)
        adapter.for_fare_policy('sendai_fureai_pass')
        factory.assert_not_called()
        self.assertIs(adapter.normal_backend,self.normal)
        self.assertIs(adapter.normal_backend,self.normal)
        factory.assert_called_once_with()


if __name__=='__main__':unittest.main()
