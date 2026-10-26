import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_tokyo_metro_transfers.py"
SPEC = importlib.util.spec_from_file_location("audit_tokyo_metro_transfers", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _station(station_id, name, connections):
    return {
        "owl:sameAs": station_id,
        "odpt:stationTitle": {"ja": name},
        "odpt:connectingStation": connections,
        "geo:lat": 35.0,
        "geo:long": 139.0,
    }


class TokyoMetroTransferAuditTest(unittest.TestCase):
    def test_groups_pair_relations_into_ranked_station_complexes(self):
        stations = [
            _station("odpt.Station:TokyoMetro.A.Alpha", "甲", [
                "odpt.Station:TokyoMetro.B.Alpha",
                "odpt.Station:TokyoMetro.C.Alpha",
            ]),
            _station("odpt.Station:TokyoMetro.B.Alpha", "甲", [
                "odpt.Station:TokyoMetro.A.Alpha",
                "odpt.Station:TokyoMetro.C.Alpha",
            ]),
            _station("odpt.Station:TokyoMetro.C.Alpha", "甲", [
                "odpt.Station:TokyoMetro.A.Alpha",
                "odpt.Station:TokyoMetro.B.Alpha",
            ]),
            _station("odpt.Station:TokyoMetro.A.Beta", "乙", [
                "odpt.Station:Toei.Mita.Beta",
            ]),
        ]
        manifest = {
            "schema": "tokyo_metro_reviewed_transfer/v1",
            "transfers": [{
                "from_station_id": "odpt.Station:TokyoMetro.A.Alpha",
                "to_station_id": "odpt.Station:TokyoMetro.B.Alpha",
                "minimum_minutes": 4,
                "walking_distance_meters": 100,
                "evidence_urls": ["https://www.tokyometro.jp/example"],
                "reviewed_at": "2026-10-24",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            station_path, manifest_path = root / "stations.json", root / "manifest.json"
            station_path.write_text(json.dumps(stations), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            audit = MODULE.build_audit(station_path, manifest_path)

        self.assertEqual(audit["schema"], "tokyo_metro_transfer_audit/v3")
        self.assertEqual(audit["counts"], {
            "total": 4,
            "reviewed": 1,
            "automatic_same_station": 0,
            "nonreciprocal_same_station": 0,
            "unresolved": 3,
            "metro_to_metro": 3,
            "metro_to_toei": 1,
        })
        self.assertEqual(audit["complex_counts"], {
            "total": 2,
            "fully_reviewed": 0,
            "partially_reviewed": 1,
            "unreviewed": 1,
        })
        first, second = audit["complexes"]
        self.assertEqual(first["station_slugs"], ["Alpha"])
        self.assertEqual(first["pair_count"], 3)
        self.assertEqual(first["reviewed_pairs"], 1)
        self.assertEqual(first["unresolved_pairs"], 2)
        self.assertEqual(first["review_priority"], 1)
        self.assertEqual(second["station_slugs"], ["Beta"])
        self.assertEqual(second["unresolved_pairs"], 1)

    def test_v2_audit_uses_the_validated_common_model_values(self):
        stations = [
            _station("odpt.Station:TokyoMetro.A.Alpha", "甲", [
                "odpt.Station:TokyoMetro.B.Alpha",
            ]),
            _station("odpt.Station:TokyoMetro.B.Alpha", "甲", [
                "odpt.Station:TokyoMetro.A.Alpha",
            ]),
        ]
        manifest = {
            "schema": "tokyo_metro_transfer_policy/v2",
            "automatic_model": {
                "version": "odpt_same_station_conservative/v1",
                "eligible_relation": "same_station_slug",
                "unmatched_relation_policy": "disabled_requires_override",
                "minimum_minutes": 17,
                "walk_resource_meters": 550,
                "distance_basis": "unknown_consumes_full_segment_limit",
                "time_basis": "app_conservative_allowance",
                "official_minimum": False,
            },
            "overrides": [],
            "exceptions": [{
                "from_station_id": "odpt.Station:TokyoMetro.A.Alpha",
                "to_station_id": "odpt.Station:TokyoMetro.B.Alpha",
                "directions": "from_to",
                "available_windows": [{"start": "05:00", "end": "24:10"}],
                "evidence_urls": ["https://www.tokyometro.jp/example"],
                "reason": "fixture directed passage",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            station_path, manifest_path = root / "stations.json", root / "manifest.json"
            station_path.write_text(json.dumps(stations), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            audit = MODULE.build_audit(station_path, manifest_path)

        self.assertEqual(audit["counts"]["automatic_same_station"], 1)
        row = audit["connections"][0]
        self.assertEqual(row["status"], "automatic_same_station")
        self.assertEqual(row["minimum_minutes"], 17)
        self.assertEqual(row["walk_resource_meters"], 550.0)
        self.assertIsNone(row["walking_distance_meters"])
        self.assertEqual(row["evidence"], {
            "official_connection_verified": True,
            "path_verified": False,
            "physical_distance_verified": False,
            "minimum_time_verified": False,
            "direction_restrictions_verified": True,
            "availability_hours_verified": True,
        })


if __name__ == "__main__":
    unittest.main()
