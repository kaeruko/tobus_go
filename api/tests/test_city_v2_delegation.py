"""Tokyo and Sendai share one expansion implementation; no v1 retry."""
from dataclasses import replace
from pathlib import Path
import ast
import contextlib
import io
import unittest
from unittest.mock import patch

import transit_search_labels
import transit_timetable_choices
from transit_network_core import NetworkSearchCore
from gtfs_route_backend import GtfsRouteEngine
from sendai_transit import SendaiRouteBackend
from tests.test_route_engine_contract import _dataset, _request
from tests.test_sendai_practical import inputs, load, build, query


class CityV2DelegationTests(unittest.TestCase):
    def test_tokyo_and_scheduled_v2_import_the_same_search_labels(self):
        import tokyo_search_labels
        self.assertIs(tokyo_search_labels._shared_search_labels,transit_search_labels.search_labels)
        self.assertIs(transit_timetable_choices.search_labels,transit_search_labels.search_labels)

    def test_sendai_and_generic_bus_backends_delegate_to_v2_and_never_v1_factory(self):
        for cls,feed in ((SendaiRouteBackend,'sendai_bus'),(GtfsRouteEngine,'fixture_bus')):
            with self.subTest(city=feed):
                backend=cls(_dataset(feed),walk_radius_m=100)
                self.assertIsInstance(backend.search_core,NetworkSearchCore)
                with patch('transit_timetable_choices.search_labels',wraps=transit_search_labels.search_labels) as core:
                    with contextlib.redirect_stdout(io.StringIO()):result=backend.search(_request())
                self.assertTrue(core.called);self.assertTrue(result.candidates)
                self.assertFalse(hasattr(backend,'engine'))  # Deleted compatibility alias.

    def test_practical_search_calls_same_core_and_propagates_original_failure(self):
        net=build(load(inputs()))
        with patch('transit_timetable_choices.search_labels',wraps=transit_search_labels.search_labels) as core:
            self.assertTrue(query(net,'namboku/泉中央','tozai/荒井'))
        self.assertTrue(core.called)
        error=RuntimeError('unique core failure')
        with patch('transit_timetable_choices.search_labels',side_effect=error):
            with self.assertRaises(RuntimeError) as caught:query(net,'namboku/泉中央','namboku/仙台')
        self.assertIs(caught.exception,error)

    def test_estimates_cannot_enter_unaware_coordinate_serializer(self):
        backend=GtfsRouteEngine(load(inputs()).dataset)
        from transit_search_dto import BatchSearchRequest, SearchEndpoint
        from datetime import date
        with self.assertRaisesRegex(ValueError,'estimate-aware serializer'):
            backend.search_core.search(BatchSearchRequest(date(2026,10,16),600,
                (SearchEndpoint('sendai_subway:namboku/泉中央'),),
                (SearchEndpoint('sendai_subway:namboku/仙台'),),'fastest'))

    def test_unreleased_city_does_not_reinterpret_tokyo_comfort_as_few_transfers(self):
        from route_engine import RouteInputError, RoutePreference
        backend=SendaiRouteBackend(_dataset('sendai_bus'),walk_radius_m=100)
        with self.assertRaisesRegex(RouteInputError,'comfort/cost'):
            backend.search(replace(_request(),preference=RoutePreference.COMFORT))

    def test_tokyo_api_default_is_preserved_and_unreleased_schema_selects_time(self):
        from app.route_endpoint import ApiRouteRequest
        from app.route_only_routes import SharedNetworkApiRouteRequest
        values=dict(alat=35,alon=139,blat=35.1,blon=139.1)
        self.assertEqual(ApiRouteRequest(**values).pref,'cost')
        self.assertEqual(SharedNetworkApiRouteRequest(**values).pref,'time')
        self.assertEqual(SharedNetworkApiRouteRequest(**values,pref='cost').pref,'cost')

    def test_v1_backend_alias_and_city_compatibility_rank_are_removed(self):
        import gtfs_route_backend
        self.assertFalse(hasattr(gtfs_route_backend,'GtfsRouteBackend'))
        self.assertFalse(hasattr(transit_timetable_choices,'_LegacyPathRanks'))
        root=Path(__file__).resolve().parents[1]
        for filename in ('sendai_transit.py','gtfs_route_backend.py'):
            tree=ast.parse((root/filename).read_text(encoding='utf-8'))
            imports=[node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
            self.assertNotIn('search_core_factory',imports)
            self.assertNotIn('transit_engine',imports)
        self.assertFalse((root/'transit_network_experiment.py').exists())

    def test_v1_implementations_are_absent_and_active_dtos_are_separate(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('transit_engine.py','search_core_factory.py','rust_transit_search_core.py',
                     'native/transit_search_core/Cargo.toml'):
            self.assertFalse((root/name).exists(),name)
        from transit_search_dto import BatchSearchRequest
        self.assertEqual(BatchSearchRequest.__module__,'transit_search_dto')
