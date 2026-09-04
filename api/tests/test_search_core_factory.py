from __future__ import annotations

import importlib.util
import unittest
from datetime import date
from unittest.mock import patch

from route_engine import RouteEngineUnavailableError
from gtfs_route_backend import GtfsRouteEngine
from search_core_factory import (
    ShadowTransitSearchCore,
    create_search_core,
)
from tests.test_route_search_golden import load_golden_fixture
from transit_engine import (
    BatchSearchRequest,
    PythonTransitSearchCore,
    SearchCore,
    SearchEndpoint,
)


class SearchCoreFactoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset, cls.fixture = load_golden_fixture()

    def test_python_is_the_safe_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            core = create_search_core(self.dataset)
        self.assertIsInstance(core, PythonTransitSearchCore)
        self.assertIsInstance(core, SearchCore)

    def test_invalid_mode_fails_at_startup(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "ROUTE_SEARCH_CORE"):
            create_search_core(self.dataset, mode="automatic")

    def test_rust_mode_does_not_silently_fallback(self) -> None:
        with patch(
            "rust_transit_search_core.RustTransitSearchCore",
            side_effect=RouteEngineUnavailableError("extension missing"),
        ):
            with self.assertRaisesRegex(
                RouteEngineUnavailableError,
                "extension missing",
            ):
                create_search_core(self.dataset, mode="rust")

    @unittest.skipUnless(
        importlib.util.find_spec("_transit_search_core") is not None,
        "Rust extension is not installed",
    )
    def test_rust_and_shadow_modes_implement_the_same_contract(self) -> None:
        from rust_transit_search_core import RustTransitSearchCore

        rust_core = create_search_core(self.dataset, mode="rust")
        shadow_core = create_search_core(self.dataset, mode="shadow")
        self.assertIsInstance(rust_core, RustTransitSearchCore)
        self.assertIsInstance(shadow_core, ShadowTransitSearchCore)
        self.assertIsInstance(rust_core, SearchCore)
        self.assertIsInstance(shadow_core, SearchCore)

        request = BatchSearchRequest(
            service_date=date.fromisoformat(self.fixture["service_date"]),
            departure_minute=595,
            origins=(SearchEndpoint("golden:A", 2, 125.5, 1),),
            destinations=(SearchEndpoint("golden:D", 3, 205.25, 2),),
            preference="fastest",
        )
        self.assertEqual(
            shadow_core.search(request).pairs,
            rust_core.search(request).pairs,
        )

    @unittest.skipUnless(
        importlib.util.find_spec("_transit_search_core") is not None,
        "Rust extension is not installed",
    )
    def test_gtfs_backend_uses_the_configured_core(self) -> None:
        from rust_transit_search_core import RustTransitSearchCore

        with patch.dict(
            "os.environ",
            {"ROUTE_SEARCH_CORE": "rust"},
            clear=False,
        ):
            backend = GtfsRouteEngine(self.dataset)

        self.assertIsInstance(backend.search_core, RustTransitSearchCore)

    def test_shadow_reports_a_structural_mismatch_but_returns_python(self) -> None:
        request = BatchSearchRequest(
            service_date=date.fromisoformat(self.fixture["service_date"]),
            departure_minute=595,
            origins=(SearchEndpoint("golden:A", 2, 125.5, 1),),
            destinations=(SearchEndpoint("golden:D", 3, 205.25, 2),),
            preference="fastest",
        )
        python_core = PythonTransitSearchCore(self.dataset)
        mismatches = []

        class EmptyCore:
            def search(self, value: BatchSearchRequest):
                result = python_core.search(value)
                return type(result)(pairs=(), diagnostics=result.diagnostics)

        shadow = ShadowTransitSearchCore(
            python_core,
            EmptyCore(),
            mismatch_callback=mismatches.append,
        )
        with self.assertLogs("search_core_factory", level="ERROR"):
            result = shadow.search(request)

        self.assertTrue(result.pairs)
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(
            mismatches[0]["event"],
            "route_search_shadow_mismatch",
        )
        python_pair = mismatches[0]["python"]["pairs"][0]
        self.assertEqual(
            python_pair["origin"],
            {"walk_minutes": 2, "walk_meters": 125.5, "rank": 1},
        )
        self.assertEqual(
            python_pair["destination"],
            {"walk_minutes": 3, "walk_meters": 205.25, "rank": 2},
        )
        self.assertEqual(
            python_pair["final_arrival_minute"],
            python_pair["arrival_minute"] + 3,
        )
        self.assertEqual(
            mismatches[0]["python"]["diagnostics"]["termination_reason"],
            "completed",
        )


if __name__ == "__main__":
    unittest.main()
