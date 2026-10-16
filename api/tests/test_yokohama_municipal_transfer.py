"""Synthetic bus/subway handoff regression tests (no runtime/ODPT IO)."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fare_policy import YOKOHAMA_WELFARE_PASS_SOURCE
from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata
from yokohama_fare_coverage import YokohamaFareCoverage

JST = ZoneInfo("Asia/Tokyo")
DAY = "2026-10-14"


def _feed(root: Path, *, rail: bool) -> YokohamaFareCoverage:
    feed = "yokohama_subway" if rail else "yokohama_bus"
    if rail:
        inputs = {
            "stops.txt": (
                "stop_id,stop_name,stop_lat,stop_lon\n"
                "S,桜木町,35.4651,139.6251\nD,関内,35.4500,139.6300\n"
            ),
            "routes.txt": "route_id,route_short_name,route_long_name,route_type\nBLUE,ブルーライン,市営地下鉄,1\n",
            "trips.txt": "route_id,service_id,trip_id\nBLUE,ALL,TRAIN1\nBLUE,ALL,TRAIN2\n",
            "stop_times.txt": (
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                "TRAIN1,09:25:00,09:25:00,S,1\n"
                "TRAIN1,09:40:00,09:40:00,D,2\n"
                "TRAIN2,10:00:00,10:00:00,D,1\n"
                "TRAIN2,10:20:00,10:20:00,S,2\n"
            ),
        }
        operator = "yokohama_municipal_subway"
        routes = {"yokohama_subway:BLUE": "local"}
    else:
        inputs = {
            "stops.txt": (
                "stop_id,stop_name,stop_lat,stop_lon\n"
                "O,横浜駅前,35.4700,139.6200\nB,桜木町,35.4650,139.6250\n"
            ),
            "routes.txt": (
                "route_id,route_short_name,route_long_name,route_type\n"
                "BUS,008系統,市営バス,3\nX,あかいくつ,観光,3\n"
            ),
            "trips.txt": (
                "route_id,service_id,trip_id\n"
                "BUS,ALL,BUS1\nBUS,ALL,BUS2\nX,ALL,EXPRESS\n"
            ),
            "stop_times.txt": (
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                "BUS1,09:05:00,09:05:00,O,1\n"
                "BUS1,09:20:00,09:20:00,B,2\n"
                "BUS2,10:26:00,10:26:00,B,1\n"
                "BUS2,10:41:00,10:41:00,O,2\n"
                "EXPRESS,09:01:00,09:01:00,O,1\n"
                "EXPRESS,09:10:00,09:10:00,B,2\n"
            ),
        }
        operator = "yokohama_municipal_bus"
        routes = {"yokohama_bus:BUS": "local", "yokohama_bus:X": "sightseeing"}
    inputs["calendar.txt"] = (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "ALL,1,1,1,1,1,1,1,20260101,20261231\n"
    )
    for name, contents in inputs.items():
        (root / name).write_text(contents, encoding="utf-8")
    metadata = FeedMetadata(
        feed_id=feed,
        source_type="gtfs",
        source_uri="https://api.odpt.org/api/v4/files/odpt/YokohamaMunicipal/",
        version="synthetic-v1",
        fetched_at=datetime(2026, 10, 14, tzinfo=JST),
    )
    dataset = GtfsTransitAdapter.load(root, metadata=metadata)
    raw = {
        "schema_version": 1,
        "city": "yokohama",
        "feed_id": feed,
        "feed_version": metadata.version,
        "feed_source_uri": metadata.source_uri,
        "operator_id": operator,
        "policy_source_uri": YOKOHAMA_WELFARE_PASS_SOURCE,
        "reviewed_on": DAY,
        "routes": routes,
        "stop_municipalities": {},
    }
    path = root / "coverage.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return YokohamaFareCoverage.load(path, dataset=dataset)
