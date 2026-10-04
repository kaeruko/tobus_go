"""Check partial Tokyo results with the logged OD/time and local static data.

No GTFS-RT feed snapshot was supplied, so this is a static control rather than
a replay of the incident. It uses product budgets and the product collector.
Historical A* and RSS artifacts are left intact.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import gc
import io
import json
import pickle
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import rss_probe as rss

OUT = rss.OUT / "partial_search_2026_10_05_static.json"


def main():
    # Match the existing local RSS runner's dependency fallback.
    sys.path.append(str(Path(sys.base_prefix) / "Lib/site-packages"))
    import toei_engine as te
    from app.route_endpoint import ApiRouteRequest, to_domain_request
    from app.services.train_realtime import StaticTrainGtfs, parse_static_gtfs
    from app.services.train_route_identity import enrich_route_result_train_trip_ids
    from app.services.train_service_calendar import parse_train_service_calendar
    from gtfs_state import load_compiled_state
    from route_engine import RouteSearchLimitError, serialize_route_result
    from tokyo_route_engine import TokyoRouteDependencies, TokyoRouteEngine

    prebuilt = rss.ROOT / "api/data/app_data_search_labels.pkl"
    with prebuilt.open("rb") as stream:
        data = pickle.load(stream)
    manifest = json.loads((rss.ASSETS / "manifest.json").read_text(encoding="utf-8"))
    load_compiled_state(te.gtfs_repo, str(rss.ASSETS / "compiled.pkl.gz"),
                        expected_source_sha256=manifest["source_sha256"])
    archive = rss.ROOT / "api/data/Toei-Train-GTFS.zip"
    content = archive.read_bytes()
    static = parse_static_gtfs(content)
    calendar = parse_train_service_calendar(content)
    active = calendar.active_trip_ids(dt.date(2026, 10, 5))
    active_static = StaticTrainGtfs({key: trip for key, trip in static.trips.items() if key in active})
    del content
    engine = TokyoRouteEngine(SimpleNamespace(state=SimpleNamespace(
        G=data["G"], TM=data["TM"], SI=data["SI"], WALK_RAD=data["WALK_RAD"],
    )), dependencies=TokyoRouteDependencies(
        now=lambda: dt.datetime(2026, 10, 4, 18, 40, tzinfo=ZoneInfo("Asia/Tokyo")),
    ))
    body = {"alat": 35.708166, "alon": 139.817434,
            "blat": 35.658034, "blon": 139.701636,
            "pref": "cost", "bus_only": False, "start_time": "07:18",
            "target_date_str": "2026-10-05", "limit": 5}
    read_memory = rss.memory_reader()
    gc.collect()
    report = {"scope": "Logged OD/time, local static data; no HTTP, live RT or incident feed replay. Product budgets unchanged.",
              "request": body, "before": read_memory(),
              "sha256": {path.name: rss.sha(path) for path in (
                  prebuilt, archive, rss.ROOT / "api/toei_engine.py",
                  rss.ROOT / "api/tokyo_search_labels.py", rss.ROOT / "api/route_engine.py",
                  rss.ROOT / "api/tokyo_route_engine.py",
                  rss.ROOT / "api/app/services/train_route_identity.py")}}
    log = io.StringIO()
    started = time.perf_counter()
    payload = None
    with contextlib.redirect_stdout(log):
        try:
            payload = serialize_route_result(engine.search(to_domain_request(ApiRouteRequest(**body))))
            report["search_candidates"] = len(payload["candidates"])
            report["meta"] = payload["meta"]
            verified = enrich_route_result_train_trip_ids(
                payload, timetable_manager=data["TM"], day_type=te.determine_day_type(body["target_date_str"]),
                static_gtfs=active_static,
            )
            report["verified_candidates"] = len(verified["candidates"])
            report["arrivals"] = [candidate["arrival_time"] for candidate in verified["candidates"]]
            report["identity_rejections"] = verified.get("meta", {}).get("train_identity_rejected_candidates", [])
        except Exception as error:
            report["error"] = f"{type(error).__name__}: {error}"
            if isinstance(error, RouteSearchLimitError):
                report["termination_reason"] = error.reason
                report["search_diagnostics"] = error.diagnostics
    report["full_ms"] = (time.perf_counter() - started) * 1000
    report["after"] = read_memory()
    report["stats"] = re.findall(r"^\[ROUTE_DEBUG\] cost stats:.*$", log.getvalue(), re.M)
    rss.write_json(OUT, report)
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ("sha256", "stats", "before", "after")}, ensure_ascii=False, indent=2))
    return 1 if report.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
