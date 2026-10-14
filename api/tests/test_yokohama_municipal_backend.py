"""Contract tests for the new Yokohama municipal multi-feed /route backend.

Synthetic feeds only. No network, GTFS downloads, Windows paths or API keys.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fare_policy import decorate_route_result_with_fare
from route_engine import (
    GeoPoint, RouteInputError, RoutePreference, RouteSearchLimitError,
    RouteSearchRequest,
    serialize_route_result,
)
from route_fare_scope import search_with_fare_scope
from test_yokohama_municipal_transfer import _feed
from yokohama_municipal_backend import (
    YokohamaMunicipalRouteBackend, load_reviewed_transfer_links,
)
from yokohama_municipal_transfer import ExplicitTransferLink

JST = ZoneInfo("Asia/Tokyo")
WELFARE = "yokohama_welfare_special_pass"
SENIOR = "yokohama_senior_special_pass"


def _request(
    origin=(35.4700, 139.6200),
    destination=(35.4500, 139.6300),
    *, hour=9, minute=0, bus_only=False, preference=RoutePreference.FASTEST,
):
    return RouteSearchRequest(
        origin=GeoPoint(*origin),
        destination=GeoPoint(*destination),
        departure_at=datetime(2026, 10, 14, hour, minute, tzinfo=JST),
        preference=preference,
        bus_only=bus_only,
    )


class MunicipalBackendContractTests(unittest.TestCase):
    def setUp(self):
        b = tempfile.TemporaryDirectory()
        r = tempfile.TemporaryDirectory()
        self.addCleanup(b.cleanup)
        self.addCleanup(r.cleanup)
        self.bus = _feed(Path(b.name), rail=False)
        self.rail = _feed(Path(r.name), rail=True)
        self.link = ExplicitTransferLink(
            bus_stop_id="yokohama_bus:B",
            subway_stop_id="yokohama_subway:S",
            walk_meters=120,
            walk_minutes=3,
            official_evidence_url="https://www.city.yokohama.lg.jp/kotsu/",
        )

    def _search(self, *, links=(), policy=WELFARE, **request_kwargs):
        engine = YokohamaMunicipalRouteBackend(
            self.bus, self.rail, transfer_links=links
        )
        result = search_with_fare_scope(engine, _request(**request_kwargs), policy)
        payload = serialize_route_result(result)
        decorate_route_result_with_fare(
            city_key="yokohama", result=payload, policy_id=policy
        )
        return payload

    def test_reviewed_bus_to_rail_through_public_contract_for_both_passes(self):
        for policy in (WELFARE, SENIOR):
            with self.subTest(policy=policy):
                payload = self._search(links=(self.link,), policy=policy)
                self.assertEqual(len(payload["candidates"]), 1)
                route = payload["candidates"][0]
                self.assertEqual(route["fare"]["payNowYen"], 0)
                self.assertEqual(route["fare"]["effectiveFareYen"], 0)
                self.assertEqual(route["fare"]["policyId"], policy)
                self.assertEqual(route["arrival_time"], "09:40")
                self.assertEqual(route["boards"], 2)
                self.assertEqual(route["transfers"], 1)
                ride = [x for x in route["steps"] if x["kind"] in ("bus", "rail")]
                self.assertEqual([x["kind"] for x in ride], ["bus", "rail"])
                self.assertEqual(
                    [x["trip_id"] for x in ride],
                    ["yokohama_bus:BUS1", "yokohama_subway:TRAIN1"],
                )
                self.assertEqual(
                    [x["departureStopId"] for x in ride],
                    ["yokohama_bus:O", "yokohama_subway:S"],
                )
                transfer = [x for x in route["steps"]
                            if x["kind"] == "walk" and x.get("walking_connection_verified")]
                self.assertEqual(len(transfer), 1)
                self.assertEqual(transfer[0]["minutes"], 3)
                self.assertEqual(transfer[0]["meters"], 120)
                self.assertTrue(payload["meta"]["unreviewed_transport_excluded"])
                self.assertEqual(payload["meta"]["reviewed_transfer_links"], 1)

    def test_reverse_rail_to_bus_preserves_direction_and_schedule(self):
        result = self._search(
            links=(self.link,), policy=SENIOR,
            origin=(35.4500, 139.6300),
            destination=(35.4700, 139.6200),
            hour=9, minute=55,
        )
        self.assertEqual(len(result["candidates"]), 1)
        route = result["candidates"][0]
        rides = [x for x in route["steps"] if x["kind"] in ("bus", "rail")]
        self.assertEqual([x["kind"] for x in rides], ["rail", "bus"])
        self.assertEqual([x["trip_id"] for x in rides],
                         ["yokohama_subway:TRAIN2", "yokohama_bus:BUS2"])
        self.assertEqual(route["arrival_time"], "10:41")

    def test_unreviewed_walking_connection_is_not_inferred_from_proximity(self):
        result = self._search()
        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["meta"]["unverified_walking_transfers_excluded"])
        self.assertEqual(result["meta"]["reviewed_transfer_links"], 0)

    def test_bus_only_excludes_rail_and_cross_feed_transfer(self):
        result = self._search(links=(self.link,), bus_only=True)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["meta"]["covered_modes"], ["bus"])

    def test_unreviewed_rail_disables_rail_and_transfer_not_bus(self):
        from dataclasses import replace
        self.rail = replace(
            self.rail, route_service_kinds={"yokohama_subway:BLUE": "unreviewed"},
        )
        result = self._search(links=(self.link,))
        self.assertEqual(result["candidates"], [])

    def test_policy_must_be_explicit_and_supported(self):
        engine = YokohamaMunicipalRouteBackend(self.bus, self.rail)
        for policy in ("normal", "tokyo_welfare_pass", ""):
            with self.subTest(policy=policy), self.assertRaises(RouteInputError):
                search_with_fare_scope(engine, _request(), policy)

    def test_opt_in_provisional_spatial_transfer_keeps_walk_unverified(self):
        engine = YokohamaMunicipalRouteBackend(
            self.bus, self.rail, estimated_transfer_mode=True,
        )
        for policy in (WELFARE, SENIOR):
            with self.subTest(policy=policy):
                result = search_with_fare_scope(engine, _request(), policy)
                payload = serialize_route_result(result)
                decorate_route_result_with_fare(
                    city_key="yokohama", result=payload, policy_id=policy,
                )
                self.assertEqual(len(payload["candidates"]), 1)
                candidate = payload["candidates"][0]
                rides = [x for x in candidate["steps"] if x["kind"] in ("bus", "rail")]
                self.assertEqual([x["trip_id"] for x in rides],
                                 ["yokohama_bus:BUS1", "yokohama_subway:TRAIN1"])
                self.assertEqual(candidate["fare"]["payNowYen"], 0)
                walks = [x for x in candidate["steps"]
                         if x["kind"] == "walk" and x.get("distance_basis") == "straight_line_estimate"]
                self.assertEqual(len(walks), 1)
                self.assertFalse(walks[0]["walking_connection_verified"])
                self.assertNotIn("evidence_url", walks[0])
                self.assertEqual(payload["meta"]["walking_transfer_basis"],
                                 "provisional_gtfs_proximity")
                self.assertFalse(payload["meta"]["unverified_walking_transfers_excluded"])

    def test_unreviewed_rail_never_enters_even_estimated_mode(self):
        from dataclasses import replace
        self.rail = replace(
            self.rail, route_service_kinds={"yokohama_subway:BLUE": "unreviewed"},
        )
        self.assertEqual(self._search_with_estimates(), [])

    def _search_with_estimates(self):
        engine = YokohamaMunicipalRouteBackend(
            self.bus, self.rail, estimated_transfer_mode=True,
        )
        return search_with_fare_scope(engine, _request(), WELFARE).candidates

    def test_estimate_limit_and_types_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "estimated_transfer_mode"):
            YokohamaMunicipalRouteBackend(self.bus, self.rail, estimated_transfer_mode=1)
        for radius in (0, True, 601):
            with self.subTest(radius=radius), self.assertRaisesRegex(ValueError, "estimated_radius_m"):
                YokohamaMunicipalRouteBackend(
                    self.bus, self.rail, estimated_transfer_mode=True, estimated_radius_m=radius,
                )
        engine = YokohamaMunicipalRouteBackend(
            self.bus, self.rail, estimated_transfer_mode=True,
            estimated_candidate_limit=1,
        )
        from dataclasses import replace
        stops = dict(self.bus.dataset.stops)
        b = stops["yokohama_bus:O"]
        stops[b.id] = replace(b, lat=35.4652, lon=139.6251)
        another_bus = replace(self.bus, dataset=replace(self.bus.dataset, stops=stops))
        engine = YokohamaMunicipalRouteBackend(
            another_bus, self.rail, estimated_transfer_mode=True,
            estimated_candidate_limit=1,
        )
        with self.assertRaisesRegex(RouteSearchLimitError, "too many provisional"):
            search_with_fare_scope(engine, _request(), WELFARE)

    def test_estimate_dev_refuses_hosted_backend_mode_before_loading_feed(self):
        from app.yokohama_runtime import setup_yokohama_on_startup
        app = SimpleNamespace(state=SimpleNamespace())
        with patch.dict(os.environ, {
            "YOKOHAMA_TRANSFER_WALK_MODE": "estimate_dev",
            "YOKOHAMA_REALTIME_MODE": "disabled",
        }):
            with self.assertRaisesRegex(RuntimeError, "only permitted in local"):
                asyncio.run(setup_yokohama_on_startup(app, "lambda"))

    def test_invalid_transfer_walk_mode_fails_before_loading_gtfs(self):
        from app.yokohama_runtime import setup_yokohama_on_startup
        app = SimpleNamespace(state=SimpleNamespace())
        with patch.dict(os.environ, {
            "YOKOHAMA_TRANSFER_WALK_MODE": "auto",
            "YOKOHAMA_REALTIME_MODE": "disabled",
        }):
            with self.assertRaisesRegex(RuntimeError, "must be 'reviewed'"):
                asyncio.run(setup_yokohama_on_startup(app, "local"))

    def test_http_route_estimated_transfer_local_only_with_both_passes(self):
        """Exercise startup → /route → fare quote with both synthetic feeds."""
        from dataclasses import replace
        from fastapi.testclient import TestClient
        from app.app_factory import create_app
        from test_yokohama_backend import _environment, _write_feed

        with tempfile.TemporaryDirectory() as busdir:
            root = Path(busdir)
            _write_feed(root)
            # Synthetic train: from the bus's arrival node D at 10:25
            # back toward S at 10:45. It is NOT a real Yokohama timetable.
            times = []
            for st in self.rail.dataset.stop_times:
                if st.trip_id == "yokohama_subway:TRAIN2":
                    minute = 625 if st.stop_id == "yokohama_subway:D" else 645
                    times.append(replace(
                        st, arrival_minute=minute, departure_minute=minute,
                    ))
                else:
                    times.append(st)
            rail = replace(
                self.rail,
                dataset=replace(self.rail.dataset, stop_times=tuple(times)),
            )
            for walk_mode, expected_count in (("reviewed", 0), ("estimate_dev", 1)):
                with self.subTest(walk_mode=walk_mode):
                    env = _environment(root)
                    env.update({
                        "YOKOHAMA_REALTIME_MODE": "disabled",
                        "YOKOHAMA_SUBWAY_GTFS_DIR": str(root),
                        "YOKOHAMA_TRANSFER_WALK_MODE": walk_mode,
                    })
                    with patch.dict(os.environ, env, clear=True), patch(
                        "yokohama_subway.load_reviewed_yokohama_subway_coverage",
                        return_value=rail,
                    ):
                        with TestClient(create_app("local")) as client:
                            for policy in (WELFARE, SENIOR):
                                response = client.post(
                                    "/route",
                                    headers={"X-App-City": "yokohama"},
                                    json={
                                        "alat": 35.4660, "alon": 139.6225,
                                        "blat": 35.4651, "blon": 139.6251,
                                        "pref": "shortTime",
                                        "start_time": "09:55",
                                        "target_date_str": "2026-08-29",
                                        "fare_policy_id": policy,
                                    },
                                )
                                self.assertEqual(response.status_code, 200, response.text)
                                data = response.json()
                                if walk_mode == "reviewed":
                                    self.assertEqual(data["candidates"], [])
                                else:
                                    self.assertGreaterEqual(len(data["candidates"]), 1)
                                self.assertEqual(
                                    data["meta"]["walking_transfer_basis"],
                                    "reviewed_links_only"
                                    if walk_mode == "reviewed"
                                    else "provisional_gtfs_proximity",
                                )
                                if walk_mode != "estimate_dev":
                                    continue
                                self.assertTrue(all(
                                    route["fare"]["payNowYen"] == 0
                                    and route["fare"]["effectiveFareYen"] == 0
                                    for route in data["candidates"]
                                ))
                                matching = [
                                    route for route in data["candidates"]
                                    if [x["trip_id"] for x in route["steps"]
                                        if x["kind"] in ("bus", "rail")]
                                    == ["yokohama_bus:T1", "yokohama_subway:TRAIN2"]
                                ]
                                self.assertTrue(matching, data["candidates"])
                                candidate = matching[0]
                                self.assertEqual(candidate["fare"]["policyId"], policy)
                                self.assertEqual(candidate["fare"]["payNowYen"], 0)
                                self.assertEqual(candidate["arrival_time"], "10:45")
                                transfer = [x for x in candidate["steps"]
                                            if x["kind"] == "walk" and x.get("distance_basis") == "straight_line_estimate"]
                                self.assertEqual(len(transfer), 1)
                                self.assertFalse(transfer[0]["walking_connection_verified"])
                                self.assertNotIn("evidence_url", transfer[0])
                                self.assertIn("推定", transfer[0]["title"])

    def test_source_links_are_version_pinned_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "links.json"
            good = {
                "schema_version": 1,
                "feed_versions": {
                    "yokohama_bus": self.bus.dataset.metadata.version,
                    "yokohama_subway": self.rail.dataset.metadata.version,
                },
                "links": [{
                    "bus_stop_id": self.link.bus_stop_id,
                    "subway_stop_id": self.link.subway_stop_id,
                    "walk_meters": self.link.walk_meters,
                    "walk_minutes": self.link.walk_minutes,
                    "official_evidence_url": self.link.official_evidence_url,
                }],
            }
            p.write_text(json.dumps(good), encoding="utf-8")
            before = p.read_bytes()
            links = load_reviewed_transfer_links(p, self.bus, self.rail)
            self.assertEqual(links, (self.link,))
            self.assertEqual(p.read_bytes(), before)
            wrong = dict(good)
            wrong["feed_versions"] = dict(good["feed_versions"],
                                           yokohama_subway="stale")
            p.write_text(json.dumps(wrong), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "edition mismatch"):
                load_reviewed_transfer_links(p, self.bus, self.rail)


if __name__ == "__main__":
    unittest.main()
