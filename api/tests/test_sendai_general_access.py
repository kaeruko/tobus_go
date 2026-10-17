"""Connection-layer negative contracts fixed before the general-access change.

Synthetic schedules isolate endpoint selection; the real-data tests separately
check the unchanged shared search and its original-row witness.
"""
from datetime import date, datetime
from fractions import Fraction
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo
import unittest
from walking_access import ReviewedPoleAccess

from route_engine import GeoPoint, RouteInputError, RoutePreference, RouteSearchLimitError, RouteSearchRequest
from sendai_coordinate_routes import SendaiCoordinateScope
from sendai_practical_network import CivilMinute, PracticalRide


def adapter():
    stops = {key: NS(id=key, name='同名標柱', lat=38+i*.001, lon=140)
             for i,key in enumerate(('sendai_bus:a','sendai_bus:b','sendai_bus:c','sendai_bus:d'))}
    rows = [NS(stop_id=key, pickup_type=1 if key.endswith('c') else 0,
               drop_off_type=1 if key.endswith('d') else 0) for key in stops]
    snapshot=NS(stops=stops, rows_by_trip={'sendai_bus:t':tuple(NS(source=r,stop_id=r.stop_id) for r in rows)},
                feed_versions={'sendai_bus':'synthetic'}, costs=NS())
    network=NS(free_scope=NS(snapshot=snapshot,allowed_trip_ids={'sendai_bus:t'}),bus_reviewed_days=frozenset())
    return SendaiCoordinateScope(Mock(),network,Mock(),environment='development')


def endpoint(key,minutes=0):
    return dict(stop_id='sendai_bus:'+key,minutes=minutes,meters=80*minutes,basis='synthetic')


def journey(arrival,boards=1,cost=10):
    clock=CivilMinute(date(2026,11,19),Fraction(arrival))
    return NS(arrival_estimate=clock,planning_cost=cost,
              events=tuple(PracticalRide(NS(),clock,clock) for _ in range(boards)))


def request(**kw):
    return RouteSearchRequest(origin=GeoPoint(38.01,140),destination=GeoPoint(38.02,140),
        departure_at=kw.pop('departure_at',datetime(2026,11,19,9,tzinfo=ZoneInfo('Asia/Tokyo'))),
        preference=kw.pop('preference',RoutePreference.FASTEST),
        accept_experimental_transfer_model=True,**kw)


class GeneralAccessContracts(unittest.TestCase):
    def test_shared_distance_order_specific_ids_and_role_permissions(self):
        a=adapter(); point=GeoPoint(38.0016,140)
        origins,info=a.endpoint_candidates(point,'origin')
        destinations,_=a.endpoint_candidates(point,'destination')
        self.assertEqual([e['stop_id'] for e in origins],['sendai_bus:b','sendai_bus:d','sendai_bus:a'])
        self.assertNotIn('sendai_bus:c',[e['stop_id'] for e in origins])
        self.assertNotIn('sendai_bus:d',[e['stop_id'] for e in destinations])
        self.assertEqual(info['radius_m'],600)
        for e in (*origins,*destinations):
            self.assertEqual(e['basis'],'haversine_80m_per_minute_estimate')
            self.assertFalse(e['connection_guaranteed'])
            self.assertFalse(e['walking_time_measured'])
            self.assertIsNone(e['physical_walk_meters'])

    def test_rounding_and_inclusive_radius_use_shared_functions(self):
        a=adapter();stop=a.bus_stops['sendai_bus:a'];point=GeoPoint(38.01,140)
        for distance,minutes,meters in ((0,0,0),(80,1,80),(80.001,2,80),(600,8,600)):
            with self.subTest(distance=distance),patch('sendai_coordinate_routes.nearby_stops',return_value=[(stop,distance)]):
                result,_=a.endpoint_candidates(point,'origin')
                self.assertEqual((result[0]['minutes'],result[0]['meters']),(minutes,meters))
        result,_=a.endpoint_candidates(GeoPoint(39,140),'origin')
        self.assertEqual(result,())

    def test_no_role_candidate_does_not_search_or_invent_reverse_connection(self):
        a=adapter();a.boarding_stops.clear()
        with patch('sendai_coordinate_routes.search_practical_subway') as search:
            result=a.for_fare_policy('sendai_fureai_pass').search(request())
        self.assertEqual(result.candidates,[]);search.assert_not_called()
        self.assertFalse(result.meta['destination_reachable'])
        a=adapter();a.alighting_stops.clear()
        values,_=a.endpoint_candidates(GeoPoint(38.0016,140),'destination')
        self.assertEqual(values,())

    def test_explicit_position_and_review_precede_general_and_ambiguity_still_raises(self):
        a=adapter();point=GeoPoint(38,140)
        values,scope=a.endpoint_candidates(point,'origin')
        self.assertEqual(scope['scope'],'explicit')
        self.assertEqual(values,(a.endpoint(point,'origin'),))
        a.access_reviews=(ReviewedPoleAccess('origin','sendai_bus:a','synthetic',
            ((38.00005,139.9999),(38.00005,140.0001),(38.00015,140.0001),(38.00015,139.9999)),
            'separately reviewed direction',NS(uri='https://example.test/map',sha256='a'*64),
            minutes=1,meters=8,label='reviewed waiting pavement'),)
        point=GeoPoint(38.0001,140)
        values,scope=a.endpoint_candidates(point,'origin')
        self.assertEqual(values,(a.access_reviews[0].endpoint(),))
        reverse,scope=a.endpoint_candidates(point,'destination')
        self.assertEqual(scope['scope'],'geometric_estimate')
        self.assertTrue(all(v['basis']=='haversine_80m_per_minute_estimate' for v in reverse))
        a.bus_stops['sendai_bus:b'].lat=38
        with self.assertRaisesRegex(RouteInputError,'unreviewed_coordinate_access'):
            a.endpoint_candidates(GeoPoint(38,140),'origin')

    def test_candidate_cap_reports_every_omitted_pole_and_no_geographic_optimum(self):
        a=adapter()
        for i in range(8):
            sid=f'sendai_bus:extra-{i}'
            a.bus_stops[sid]=NS(id=sid,name='same name',lat=38.0015+i*.0001,lon=140)
            a.boarding_stops.add(sid)
        values,scope=a.endpoint_candidates(GeoPoint(38.00155,140),'origin')
        self.assertEqual(len(values),6)
        self.assertEqual(scope['eligible_count'],11)
        self.assertEqual(len(scope['omitted_stop_ids']),5)
        self.assertFalse(scope['outside_radius_compared'])
        self.assertFalse(scope['physical_walkability_verified'])

    def run_pairs(self,origins,destinations,results,**kw):
        a=adapter()
        with patch.object(a,'endpoint_candidates',side_effect=[(origins,{}),(destinations,{})]), \
             patch('sendai_coordinate_routes.search_practical_subway',side_effect=results) as search, \
             patch('sendai_coordinate_routes._candidate',side_effect=lambda n,j,r,o,d:(o['stop_id'],d['stop_id'])):
            result=a.for_fare_policy('sendai_fureai_pass').search(request(**kw))
        return result,search

    def test_farther_origin_can_arrive_earlier_and_walk_changes_boarding_ready(self):
        result,search=self.run_pairs((endpoint('a',1),endpoint('b',3)),(endpoint('c'),),
                                    [(journey(570),),(journey(560),)])
        self.assertEqual(result.candidates,[('sendai_bus:b','sendai_bus:c')])
        self.assertEqual([c.kwargs['departure_minute'] for c in search.call_args_list],[541,543])
        self.assertEqual([c.kwargs['parameters'].max_travel_minutes for c in search.call_args_list],[179,177])
        self.assertIs(search.call_args_list[0].kwargs['_request_materializations'],
                      search.call_args_list[1].kwargs['_request_materializations'])

    def test_destination_walk_reverses_arrival_order(self):
        result,_=self.run_pairs((endpoint('a'),),(endpoint('b',8),endpoint('c',1)),
                                [(journey(555),),(journey(559),)])
        self.assertEqual(result.candidates,[('sendai_bus:a','sendai_bus:c')])

    def test_fewest_transfers_preserves_shared_cost_then_arrival_ties(self):
        result,_=self.run_pairs((endpoint('a'),endpoint('b')), (endpoint('c'),),
                [(journey(550,boards=2,cost=1),),(journey(570,boards=1,cost=20),)],
                preference=RoutePreference.FEWEST_TRANSFERS)
        self.assertEqual(result.candidates,[('sendai_bus:b','sendai_bus:c')])

    def test_missed_service_is_not_replaced_by_zero_walk_query(self):
        result,search=self.run_pairs((endpoint('a',2),),(endpoint('b',1),),[()])
        self.assertEqual(result.candidates,[])
        self.assertEqual(search.call_args.kwargs['departure_minute'],542)
        search.assert_called_once()

    def test_limit_keeps_original_exception_and_marks_uncompared_pairs(self):
        error=RouteSearchLimitError('original max_visited diagnostic',reason='max_visited',diagnostics={'visited':100001})
        with self.assertRaises(RouteSearchLimitError) as caught:
            self.run_pairs((endpoint('a'),endpoint('b')), (endpoint('c'),),[(journey(550),),error])
        self.assertIs(caught.exception,error)
        info=error.diagnostics['coordinate_access']
        self.assertEqual(info['completed_pairs'],1)
        self.assertEqual(info['uncompared_pairs'],[['sendai_bus:b','sendai_bus:c']])
        self.assertFalse(info['comparison_complete'])
        self.assertEqual(error.diagnostics['visited'],100001)

    def test_origin_walk_cannot_cross_civil_day(self):
        with self.assertRaisesRegex(RouteInputError,'civil-day'):
            self.run_pairs((endpoint('a',2),),(endpoint('b'),),[],
                departure_at=datetime(2026,11,30,23,59,tzinfo=ZoneInfo('Asia/Tokyo')))

    def test_request_deadline_never_returns_a_partial_winner(self):
        with patch('sendai_coordinate_routes.monotonic',side_effect=[0,16,16]):
            with self.assertRaises(RouteSearchLimitError) as caught:
                self.run_pairs((endpoint('a'),),(endpoint('b'),),[])
        self.assertFalse(caught.exception.diagnostics['coordinate_access']['comparison_complete'])
        self.assertEqual(caught.exception.diagnostics['coordinate_access']['completed_pairs'],0)

    def test_geometric_same_pole_is_reported_as_no_transit_not_free_walking(self):
        a=adapter();point=GeoPoint(38.0016,140)
        values,info=a.endpoint_candidates(point,'origin')
        value=values[:1]
        with patch.object(a,'endpoint_candidates',return_value=(value,info)), \
             patch('sendai_coordinate_routes.search_practical_subway') as search:
            result=a.for_fare_policy('sendai_fureai_pass').search(request())
        self.assertEqual(result.candidates,[])
        self.assertEqual(result.meta['coordinate_access']['non_transit_pairs'],[[value[0]['stop_id']]*2])
        search.assert_not_called()


if __name__=='__main__':unittest.main()
