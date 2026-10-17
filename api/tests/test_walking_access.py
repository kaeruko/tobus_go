"""Parity at coordinate/access boundaries, without another route searcher."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import networkx as nx

from gtfs_route_backend import nearby_stops as gtfs_nearby_stops
from route_engine import GeoPoint, RouteCandidate, RouteInputError, WalkStep
from toei_engine import get_virtual_connections, haversine, nearest_phys
from walking_access import (
    ReviewedCoordinateAccessRules, ReviewedPoleAccess, distance_candidates,
    haversine_m, nearby_stops, reviewed_coordinate_endpoint,
    walking_elapsed_minutes, walking_minutes, walking_metrics,
)


class WalkingAccessTests(unittest.TestCase):
    def test_one_distance_implementation_retains_coordinates_and_units(self):
        self.assertIs(haversine, haversine_m)
        self.assertIs(gtfs_nearby_stops, nearby_stops)
        self.assertEqual(haversine_m(38.224419, 140.876138, 38.224419, 140.876138), 0)
        self.assertAlmostEqual(haversine_m(0, 0, 0, 1), 111194.92664455874, places=8)
        # Value captured from the unchanged Tokyo haversine implementation.
        self.assertAlmostEqual(haversine_m(35.71, 139.84, 35.73, 139.71), 11944.846838955098, places=8)

    def test_inclusive_radius_keeps_source_order_but_gtfs_uses_distance_id_order(self):
        points = [("second", 0, 80), ("first", 0, 0), ("outside", 0, 80.001)]
        self.assertEqual(list(distance_candidates(points, 0, 0, radius_m=80,
                                                  distance=lambda a,b,c,d: d)),
                         [("second", 80), ("first", 0)])
        stops = {key: SimpleNamespace(id=key, lat=38.0, lon=140.0) for key in ("b", "a")}
        self.assertEqual([stop.id for stop,_ in nearby_stops(stops,38.0,140.0,radius_m=1,candidate_limit=1)], ["a"])

    def test_tokyo_nearest_ties_station_filter_and_index_empty_fallback_remain(self):
        graph = nx.DiGraph()
        bus_b, bus_a = ("phys", "b"), ("phys", "a")
        station = ("phys", "odpt.Station:Toei.fixture")
        for node in (bus_b, bus_a, station):
            graph.add_node(node, lat=35.0, lon=139.0)
        self.assertEqual(nearest_phys(graph,35,139), (bus_b,0))
        self.assertEqual(nearest_phys(graph,35,139,station_only=True), (station,0))
        index = SimpleNamespace(nearby_candidates=Mock(return_value=[]))
        self.assertEqual(nearest_phys(graph,35,139,spatial_index=index), (bus_b,0))
        index.nearby_candidates.assert_called_once_with(35,139,1000)
        index.nearby_candidates.return_value=[(bus_a,35,139),(bus_b,35,139)]
        self.assertEqual(nearest_phys(graph,35,139,spatial_index=index), (bus_a,0))
        # A nonempty index without a station never triggers a new full scan.
        self.assertEqual(nearest_phys(graph,35,139,station_only=True,spatial_index=index), (None,1e30))

    def test_tokyo_virtual_candidates_keep_weight_floor_radius_and_index_order(self):
        graph=nx.DiGraph()
        points=[(("phys","b"),0,80.5),(("phys","a"),0,0),(("phys","outside"),0,81)]
        for node,lat,lon in points:
            graph.add_node(node,lat=lat,lon=lon)
        with patch('toei_engine.haversine',side_effect=lambda a,b,c,d:d):
            for index in (None,SimpleNamespace(nearby_candidates=Mock(return_value=points))):
                node,connections=get_virtual_connections(graph,0,0,walk_radius=80.5,spatial_index=index)
                self.assertEqual(node,("phys","dest:0.000000,0.000000"))
                # The original cost multiplies AFTER dividing metres by 80.
                self.assertEqual(connections,[(points[0][0],1.5093750000000001,80.5),(points[1][0],1.5,0)])

    def test_distance_time_rounding_is_separate_from_reviewed_minutes(self):
        for meters,minutes in ((0,0),(.1,1),(80,1),(80.001,2),(166.4,3)):
            self.assertEqual(walking_minutes(meters),minutes)
        self.assertEqual(walking_minutes(90,speed_m_per_min=60),2)
        self.assertEqual(walking_elapsed_minutes(8),.1)
        self.assertEqual(walking_elapsed_minutes(8,minimum_minutes=1.0),1.0)
        review=self.review()
        self.assertEqual(review.endpoint()['minutes'],1)  # Not replaced by 8/80.

    @staticmethod
    def review():
        return ReviewedPoleAccess('origin','feed:a','version',((0,0),(0,1),(1,1),(1,0)),
            'reviewed one-way path',SimpleNamespace(uri='https://example.test/map',sha256='a'*64),
            minutes=1,meters=8,label='reviewed waiting pavement')

    def test_directional_review_is_boundary_inclusive_and_ambiguity_fails_closed(self):
        review=self.review()
        for point in (GeoPoint(.5,.5),GeoPoint(0,.5)):
            self.assertTrue(review.matches(point,'origin'))
            self.assertFalse(review.matches(point,'destination'))
        self.assertFalse(review.matches(GeoPoint(-.001,.5),'origin'))
        rules=ReviewedCoordinateAccessRules(600,.01)
        kwargs=dict(stops={},boarding_stops=set(),rules=rules)
        self.assertEqual(reviewed_coordinate_endpoint(GeoPoint(.5,.5),'origin',reviews=(review,),**kwargs),review.endpoint())
        for role,reviews in (('destination',(review,)),('origin',(review,review))):
            with self.assertRaisesRegex(RouteInputError,'unreviewed_coordinate_access'):
                reviewed_coordinate_endpoint(GeoPoint(.5,.5),role,reviews=reviews,**kwargs)
        # The reverse direction requires its own record, not an inferred edge.
        reverse=replace(review,role='destination',path_description='separately reviewed reverse')
        self.assertEqual(reviewed_coordinate_endpoint(GeoPoint(.5,.5),'destination',reviews=(review,reverse),**kwargs),reverse.endpoint())

    def test_same_position_roles_preserve_pole_ids_and_nearby_is_not_permission(self):
        stops={key:SimpleNamespace(id=key,lat=38,lon=140,name=key) for key in ('board','alight')}
        kwargs=dict(stops=stops,boarding_stops={'board'},reviews=(),rules=ReviewedCoordinateAccessRules(600,.01))
        for role,key in (('origin','board'),('destination','alight')):
            endpoint=reviewed_coordinate_endpoint(GeoPoint(38,140),role,**kwargs)
            self.assertEqual((endpoint['stop_id'],endpoint['minutes'],endpoint['meters']), (key,0,0))
        with self.assertRaisesRegex(RouteInputError,'unreviewed_coordinate_access'):
            reviewed_coordinate_endpoint(GeoPoint(38.00005,140),'origin',**kwargs)
        with self.assertRaisesRegex(RouteInputError,'unreviewed_coordinate_access'):
            reviewed_coordinate_endpoint(GeoPoint(38,140),'origin',**{**kwargs,'boarding_stops':set(stops)})

    def test_shared_walk_contract_preserves_unknown_distance_and_estimate_evidence(self):
        details={'physical_walk_meters':None,'walking_time_measured':False,'notice':'推定・未実測'}
        walk=WalkStep('駅アクセス（推定・未保証）','pole','station',10,0,
                      step_id='access',extra={'planning_details':details}).to_mapping()
        payload={'id':'contract','lines':[],'boards':0,'transfers':0,'total_time':10,
                 'points':[],'arrival_time':'09:10','steps':[walk],**walking_metrics([walk])}
        result=RouteCandidate.from_mapping(payload).to_mapping()
        self.assertEqual(result['walking_distance_meters'],0)
        self.assertEqual(result['walking_segment_count'],1)
        self.assertEqual(result['steps'][0],walk)
        self.assertIsNone(result['steps'][0]['planning_details']['physical_walk_meters'])


if __name__=='__main__':
    unittest.main()
