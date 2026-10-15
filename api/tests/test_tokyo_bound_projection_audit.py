"""Independent audit regressions for static Tokyo common graph projection."""
from __future__ import annotations

from datetime import date
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import networkx as nx

from route_engine import RouteContractError
from tests import test_tokyo_bus_choices_contract as bus
from tests import test_tokyo_dataset_rail_choices as rail_choice_tests
from tests import test_tokyo_waiting_contract as rail
from tokyo_bound_projection_audit import _compare_projection, _common_bus_minima
from tokyo_rail_interval_audit import _collect_static_rail_minima
from tokyo_timetable_choices import TimetableChoices

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_tokyo_graph_projection_local.py"
spec = importlib.util.spec_from_file_location("tokyo_graph_projection_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class TokyoGraphProjectionAuditTest(unittest.TestCase):
    def setUp(self):
        fixture = rail_choice_tests.TokyoDatasetRailChoicesTest()
        fixture.fixture(rail._run("run", (("A", 600), ("B", 606))))
        self.rail_snapshot = fixture.snapshot
        self.graph = nx.compose(fixture.graph, bus._graph(("Q", "Z")))
        self.manager = fixture.manager
        self.repository = bus._repository(
            ("bus", "active", (("Q", 604, 604), ("Z", 615, 615))),
            ("later", "active", (("Q", 605, 605), ("Z", 607, 607))),
        )
        self.repository.service_calendar["active"] = {
            "start_date": "20260101", "end_date": "20261231",
            "weekdays": (True,) * 7,
        }
        self.day = bus.engine.ServiceDayType(
            "weekday", date(2026, 9, 4), frozenset(("active",)), True
        )
        rail._walk(self.graph, rail._physical("B"), bus._phys("Q"), 160)
        self.choices = TimetableChoices(
            self.graph, self.manager, day_type=self.day,
            use_realtime=False, deadline=3000, bus_repository=self.repository,
        )
        self.rail_minima = _collect_static_rail_minima(
            self.rail_snapshot, lambda: None
        )[0]
        # Independent bus fixture source: no call to the old interval gate.
        self.bus_minima = {
            (self.choices._bus_route(bus._line("Q")), "Q", "Z"): 2.0,
        }
        self.target = bus._phys("Z")
        self.virtual = {
            rail._physical("B"): (0.0, 80.0),
            ("virtual-node-not-in-graph",): (0.0, 160.0),
        }

    def compare(self, **kw):
        args = dict(
            graph=self.graph, choices=self.choices,
            rail_minima=self.rail_minima, bus_minima=self.bus_minima,
            target=self.target, virtual_connections=self.virtual,
            edge_uses_rail=lambda _u, _v: False,
        )
        args.update(kw)
        return _compare_projection(**args)

    def test_whole_graph_all_edges_and_virtual_destination_seed_match(self):
        result = self.compare()
        self.assertTrue(result["common_graph_edge_projection_verified"])
        self.assertTrue(result["common_graph_seed_projection_verified"])
        self.assertEqual(result["graph_edges"], self.graph.number_of_edges())
        self.assertGreater(result["rail_rides"], 0)
        self.assertGreater(result["bus_rides"], 0)
        self.assertGreater(result["known_ride_edges"], 0)
        self.assertGreater(result["walk_edges"], 0)
        self.assertGreater(result["board_edges"], 0)
        self.assertGreater(result["alight_transfer_edges"], 0)
        self.assertEqual(result["virtual_seed_entries"], 1)
        self.assertEqual(result["missing_virtual_nodes"], 1)
        self.assertFalse(result["destination_bounds_verified"])
        self.assertFalse(result["priority_rounding_verified"])

    def test_bus_only_explicit_rail_exclusion_matches(self):
        from toei_engine import _edge_uses_rail
        result = self.compare(
            edge_uses_rail=lambda u, v: _edge_uses_rail(self.graph, u, v),
        )
        self.assertGreater(result["excluded_edges"], 0)
        self.assertEqual(result["rail_rides"], 0)
        self.assertGreater(result["bus_rides"], 0)
        self.assertTrue(result["common_graph_edge_projection_verified"])

    def test_changed_common_minima_are_rejected_not_accepted_as_zero(self):
        pair = next(iter(self.rail_minima))
        corrupted = dict(self.rail_minima)
        corrupted[pair] += 1.0
        with self.assertRaisesRegex(RouteContractError, "edge weight differs"):
            self.compare(rail_minima=corrupted)
        broken_bus = {key: value + 1.0 for key, value in self.bus_minima.items()}
        with self.assertRaisesRegex(RouteContractError, "edge weight differs"):
            self.compare(bus_minima=broken_bus)

    def test_reference_edge_or_seed_mismatch_does_not_retry(self):
        calls = []
        def change(u, v, value):
            calls.append((u, v))
            return 99.0 if value is not None else 1.0
        with self.assertRaisesRegex(RouteContractError, "edge weight differs"):
            self.compare(observed_edge_transform=change)
        self.assertEqual(len(calls), 1)

        original = RuntimeError("deadline interrupted")
        with self.assertRaises(RuntimeError) as raised:
            self.compare(check_deadline=lambda: (_ for _ in ()).throw(original))
        self.assertIs(raised.exception, original)

    def test_nonstandard_and_opaque_reference_cannot_pass(self):
        self.choices.use_realtime = True
        with self.assertRaisesRegex(RouteContractError, "static reference"):
            self.compare()
        self.choices.use_realtime = False
        graph = self.graph.copy()
        graph.add_edge(bus._phys("Q"), bus._line("Q"), etype="xfer", mode="bus")
        with self.assertRaisesRegex(RouteContractError, "noncanonical entry"):
            self.compare(graph=graph)

    def test_explicit_observer_is_opt_in_and_old_api_still_works(self):
        from tokyo_time_bounds import make_time_bounds
        reference = make_time_bounds(
            self.graph, self.choices, self.target, self.virtual,
            edge_uses_rail=lambda _u, _v: False,
        )
        self.assertTrue(reference.report["scope"].startswith("static:"))
        self.assertEqual(reference.report["seeded_nodes"], 2)

    def test_cli_emits_marker_only_after_source_comparison_completes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("train.json", "stations.json", "railways.json", "trusted.pkl"):
                (root / name).write_text("pinned", encoding="utf-8")
            argv = [
                str(SCRIPT),
                "--train-timetables", str(root / "train.json"),
                "--stations", str(root / "stations.json"),
                "--railways", str(root / "railways.json"),
                "--gtfs-dir", str(root),
                "--expected-feed-version", "fixture",
                "--trusted-prebuilt", str(root / "trusted.pkl"),
                "--expected-prebuilt-sha256", "a" * 64,
                "--expected-sha", "b" * 40,
            ]
            with (patch.object(sys, "argv", argv),
                  patch.object(probe, "check_repository"),
                  patch.object(probe, "sha256", return_value="a" * 64),
                  patch.object(probe, "fingerprints", return_value={}),
                  patch.object(probe, "inspect", return_value={
                      "common_graph_edge_projection_verified": True,
                  }),
                  patch.object(probe.engine, "_tokyo_label_search",
                               side_effect=AssertionError("OD search must not run")),
                  io.StringIO() as output,
                  patch("sys.stdout", output)):
                probe.main()
                report, marker = output.getvalue().splitlines()[-2:]
            self.assertTrue(json.loads(report)["common_graph_edge_projection_verified"])
            self.assertEqual(marker, "READ_ONLY_TOKYO_COMMON_GRAPH_PROJECTION_OK")

            with (patch.object(sys, "argv", argv),
                  patch.object(probe, "check_repository"),
                  patch.object(probe, "sha256", return_value="a" * 64),
                  patch.object(probe, "fingerprints", return_value={}),
                  patch.object(probe, "inspect",
                               side_effect=RuntimeError("projection failed")),
                  io.StringIO() as output,
                  patch("sys.stdout", output)):
                with self.assertRaisesRegex(RuntimeError, "projection failed"):
                    probe.main()
                self.assertNotIn("READ_ONLY_TOKYO_COMMON_GRAPH_PROJECTION_OK",
                                 output.getvalue())


if __name__ == "__main__":
    unittest.main()
