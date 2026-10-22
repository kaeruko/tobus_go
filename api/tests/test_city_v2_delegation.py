"""Tokyo and generic GTFS adapters share SearchCore v2 without retries."""
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
from tests.test_route_engine_contract import _dataset, _request


class CityV2DelegationTests(unittest.TestCase):
    def test_tokyo_and_scheduled_v2_import_the_same_search_labels(self):
        import tokyo_search_labels
        self.assertIs(tokyo_search_labels._shared_search_labels, transit_search_labels.search_labels)
        self.assertIs(transit_timetable_choices.search_labels, transit_search_labels.search_labels)

    def test_generic_bus_backend_delegates_to_v2_without_v1_factory(self):
        backend = GtfsRouteEngine(_dataset("fixture_bus"), walk_radius_m=100)
        self.assertIsInstance(backend.search_core, NetworkSearchCore)
        with patch("transit_timetable_choices.search_labels",
                   wraps=transit_search_labels.search_labels) as core:
            with contextlib.redirect_stdout(io.StringIO()):
                result = backend.search(_request())
        self.assertTrue(core.called)
        self.assertTrue(result.candidates)
        self.assertFalse(hasattr(backend, "engine"))

    def test_shared_search_propagates_the_original_failure(self):
        backend = GtfsRouteEngine(_dataset("fixture_bus"), walk_radius_m=100)
        error = RuntimeError("unique core failure")
        with patch("transit_timetable_choices.search_labels", side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                backend.search(_request())
        self.assertIs(caught.exception, error)

    def test_tokyo_api_default_and_shared_schema_are_preserved(self):
        from app.route_endpoint import ApiRouteRequest
        from app.route_only_routes import SharedNetworkApiRouteRequest
        values = dict(alat=35, alon=139, blat=35.1, blon=139.1)
        self.assertEqual(ApiRouteRequest(**values).pref, "cost")
        self.assertEqual(SharedNetworkApiRouteRequest(**values).pref, "time")
        self.assertEqual(SharedNetworkApiRouteRequest(**values, pref="cost").pref, "cost")

    def test_v1_backend_alias_and_compatibility_rank_are_removed(self):
        import gtfs_route_backend
        self.assertFalse(hasattr(gtfs_route_backend, "GtfsRouteBackend"))
        self.assertFalse(hasattr(transit_timetable_choices, "_LegacyPathRanks"))
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "gtfs_route_backend.py").read_text(encoding="utf-8"))
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertNotIn("search_core_factory", imports)
        self.assertNotIn("transit_engine", imports)
        self.assertFalse((root / "transit_network_experiment.py").exists())

    def test_v1_implementations_are_absent_and_active_dtos_are_separate(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("transit_engine.py", "search_core_factory.py", "rust_transit_search_core.py",
                     "native/transit_search_core/Cargo.toml"):
            self.assertFalse((root / name).exists(), name)
        from transit_search_dto import BatchSearchRequest
        self.assertEqual(BatchSearchRequest.__module__, "transit_search_dto")
