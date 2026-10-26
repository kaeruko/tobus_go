import json
import os
import tempfile
import unittest
from types import SimpleNamespace

import networkx as nx

from tokyo_static_compatibility import (
    TokyoStaticCompatibilityError,
    inspect_toei_bus_graph_gtfs,
    validate_release_sources,
    validate_toei_bus_graph_gtfs,
)


def _manager():
    return SimpleNamespace(
        train_patterns_weekday={},
        train_patterns_weekend={},
        bus_departures_weekday={},
        realtime_delays={},
        bus_realtime_delays={},
    )


def _repository(destination="0002-01"):
    return SimpleNamespace(
        is_loaded=True,
        routes={"R1": {}},
        route_name_to_id={"RouteA": "R1"},
        trips={"trip-1": {"route_id": "R1"}},
        stop_times={
            "trip-1": {
                1: ("0001-01", 600, 600),
                2: (destination, 610, 610),
            }
        },
    )


def _graph(destination_pole="odpt.BusstopPole:Toei.B.2.1", *, display="RouteA outbound"):
    graph = nx.DiGraph()
    origin = ("line", "odpt.BusstopPole:Toei.A.1.1", "buspat:test")
    destination = ("line", destination_pole, "buspat:test")
    graph.add_node(origin, route_id="odpt.Busroute:Toei.RouteA", disp=display)
    graph.add_node(destination, route_id="odpt.Busroute:Toei.RouteA", disp=display)
    graph.add_edge(origin, destination, etype="ride", mode="bus")
    return graph


class TokyoStaticCompatibilityTest(unittest.TestCase):
    def test_exact_bidirectional_adjacency_match_passes(self):
        report = validate_toei_bus_graph_gtfs(
            _graph(), _manager(), _repository()
        )
        self.assertTrue(report.compatible)
        self.assertEqual(report.graph_adjacencies, 1)
        self.assertEqual(report.gtfs_adjacencies, 1)

    def test_stale_graph_and_new_gtfs_fail_closed_in_both_directions(self):
        report = inspect_toei_bus_graph_gtfs(
            _graph(), _manager(), _repository(destination="0003-01")
        )
        self.assertEqual(report.graph_only, (("R1", "0001-01", "0002-01"),))
        self.assertEqual(report.gtfs_only, (("R1", "0001-01", "0003-01"),))
        with self.assertRaisesRegex(
            TokyoStaticCompatibilityError, "graph_only=1.*gtfs_only=1"
        ):
            validate_toei_bus_graph_gtfs(
                _graph(), _manager(), _repository(destination="0003-01")
            )

    def test_unresolved_route_identity_fails_closed(self):
        with self.assertRaisesRegex(
            TokyoStaticCompatibilityError, "unresolved_graph_edges=1"
        ):
            validate_toei_bus_graph_gtfs(
                _graph(display="Unknown"), _manager(), _repository()
            )

    def test_release_manifest_pins_bytes_and_record_count(self):
        with tempfile.TemporaryDirectory() as directory:
            data_path = os.path.join(directory, "source.json")
            manifest_path = os.path.join(directory, "manifest.json")
            payload = b'[{"id":1}]\n'
            with open(data_path, "wb") as target:
                target.write(payload)
            import hashlib

            manifest = {
                "schema": "toei_bus_static_release/v1",
                "snapshot_id": "test",
                "odpt_sources": [
                    {
                        "filename": "source.json",
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "records": 1,
                    }
                ],
            }
            with open(manifest_path, "w", encoding="utf-8") as target:
                json.dump(manifest, target)

            result = validate_release_sources(directory, manifest_path)
            self.assertEqual(result["snapshot_id"], "test")

            with open(data_path, "ab") as target:
                target.write(b" ")
            with self.assertRaisesRegex(
                TokyoStaticCompatibilityError, "checksum mismatch"
            ):
                validate_release_sources(directory, manifest_path)


if __name__ == "__main__":
    unittest.main()
