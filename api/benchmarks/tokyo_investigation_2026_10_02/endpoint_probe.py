"""Reproduce Tokyo API request counts without making any network requests.

Run from api/: python benchmarks/tokyo_investigation_2026_10_02/endpoint_probe.py
The synthetic ZIP is intentionally tiny: this verifies request counts and
contract behavior, not production download time or GTFS parsing performance.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import sys
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI

from app.route_endpoint import ApiRouteRequest, register_route_endpoint
from app.services import train_realtime, train_service_calendar
from app.train_routes import TrainRouteIdentityRequest, register_train_routes
from route_engine import RouteSearchResult


def _csv(headers, rows) -> str:
    content = io.StringIO(newline="")
    writer = csv.writer(content)
    writer.writerow(headers)
    writer.writerows(rows)
    return content.getvalue()


def _train_fixture() -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("stops.txt", _csv(
            ["stop_id", "stop_code", "stop_name"],
            [
                ["115", "A15", "GTFS東日本橋"],
                ["116", "A16", "GTFS浅草橋"],
                ["117", "A17", "GTFS蔵前"],
            ],
        ))
        archive.writestr("trips.txt", _csv(
            ["route_id", "service_id", "trip_id"],
            [["1", "daily", "121603T0"]],
        ))
        archive.writestr("stop_times.txt", _csv(
            ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
            [
                ["121603T0", "16:25:00", "16:25:00", "115", 9],
                ["121603T0", "16:27:00", "16:28:00", "116", 10],
                ["121603T0", "16:30:00", "16:30:00", "117", 11],
            ],
        ))
        archive.writestr("calendar.txt", _csv(
            ["service_id", "monday", "tuesday", "wednesday", "thursday",
             "friday", "saturday", "sunday", "start_date", "end_date"],
            [["daily", 1, 1, 1, 1, 1, 1, 1, "20260101", "20261231"]],
        ))
    return content.getvalue()


async def _identity_probe() -> dict:
    station_ids = [
        "odpt.Station:Toei.Asakusa.HigashiNihombashi",
        "odpt.Station:Toei.Asakusa.Asakusabashi",
        "odpt.Station:Toei.Asakusa.Kuramae",
    ]
    patterns = {
        station_ids[0]: [{"dep": 985, "arr": 987, "next_sta": station_ids[1], "train_num": "N1"}],
        station_ids[1]: [{"dep": 988, "arr": 990, "next_sta": station_ids[2], "train_num": "N1"}],
    }
    app = FastAPI()
    app.state.TM = SimpleNamespace(
        train_patterns_weekday=patterns,
        train_patterns_weekend=patterns,
        realtime_delays={},
        train_status_text={},
    )
    register_train_routes(app)
    endpoint = next(route.endpoint for route in app.routes
                    if getattr(route, "path", None) == "/train/resolve-route-identities")
    request = TrainRouteIdentityRequest(
        target_date_str="2026-10-02",
        candidates=[{"id": "Fastest", "steps": [{
            "step_id": "rail-1", "kind": "rail",
            "departure_time": "16:22", "arrival_time": "16:30",
            "boarding_minutes": 2,
            "stops": [
                dict(id=stop_id, odpt_id=station_id, name=name)
                for stop_id, station_id, name in zip(
                    ["A15", "A16", "A17"],
                    station_ids,
                    ["東日本橋", "浅草橋", "蔵前"],
                )
            ],
        }]}],
    )
    fetch = AsyncMock(return_value=_train_fixture())
    # Only the network boundary is mocked. Both ZIP parsers, calendar filtering,
    # ODPT matching, exact static-trip matching, and endpoint logic execute.
    with patch.object(train_realtime, "_static_gtfs", None), \
         patch.object(train_service_calendar, "_calendar_index", None), \
         patch.object(train_realtime, "_fetch_bytes", fetch), \
         patch.object(train_service_calendar, "_fetch_bytes", fetch):
        cold_response = await endpoint(request)
        cold_count = fetch.await_count
        warm_response = await endpoint(request)
        calls = [dict(url=call.args[0], timeout_seconds=call.kwargs["timeout_seconds"])
                 for call in fetch.await_args_list]
        resolved = cold_response["candidates"][0]["steps"][0]
        assert cold_count == 2
        assert fetch.await_count == cold_count
        assert calls[0]["url"] == calls[1]["url"]
        assert cold_response == warm_response
        assert resolved["trip_id"] == "121603T0"
        assert resolved["departure_time"] == "16:25"
        assert [stop["id"] for stop in resolved["stops"]] == ["115", "116", "117"]
        assert cold_response["rejections"] == []
        return {
            "fixture": "one trip, three stations; exact ODPT/static match",
            "cold_external_fetch_count": cold_count,
            "warm_additional_external_fetch_count": fetch.await_count - cold_count,
            "both_fetches_use_same_url": calls[0]["url"] == calls[1]["url"],
            "cold_fetches": calls,
            "responses_identical": cold_response == warm_response,
            "resolved_trip_id": resolved["trip_id"],
            "resolved_departure_time": resolved["departure_time"],
            "rejections": cold_response["rejections"],
        }


class _CountingSearchEngine:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = 0

    def search(self, request):
        with self.lock:
            self.active += 1
            self.calls += 1
            self.max_active = max(self.max_active, self.active)
        # Yield the worker thread; a concurrent call could overlap this delay.
        time.sleep(0.01)
        with self.lock:
            self.active -= 1
        return RouteSearchResult(candidates=[])


async def _route_lock_probe() -> dict:
    app = FastAPI()
    engine = _CountingSearchEngine()
    app.state.loading_status = "ready"
    app.state.route_engine = engine
    register_route_endpoint(app, warmup_message="warming up")
    endpoint = next(route.endpoint for route in app.routes
                    if getattr(route, "path", None) == "/route")
    request = ApiRouteRequest(
        alat=35.69, alon=139.78, blat=35.71, blon=139.80,
        pref="time", target_date_str="2026-10-02", start_time="16:00",
    )
    responses = await asyncio.gather(*(endpoint(request) for _ in range(3)))
    assert engine.calls == 3
    assert engine.max_active == 1
    assert all(response == {"candidates": [], "meta": {}} for response in responses)
    return {
        "concurrent_endpoint_calls": 3,
        "engine_call_count": engine.calls,
        "maximum_simultaneous_engine_calls": engine.max_active,
        "note": "Per-instance serialization only; no production latency measurement.",
    }


async def _run() -> dict:
    return {
        "scope": "Tokyo API; no external network; production code unmodified",
        "train_identity": await _identity_probe(),
        "shared_route_lock": await _route_lock_probe(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(asyncio.run(_run()), ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(result, encoding="utf-8")
    print(result, end="")


if __name__ == "__main__":
    main()
