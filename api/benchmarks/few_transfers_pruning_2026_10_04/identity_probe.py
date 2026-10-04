"""Resolve corrected Tokyo candidates against the official train GTFS.

Default execution uses local files only. --download obtains the same official
archive as production and stores it under ignored api/data; no server writes,
deployment, realtime fetches, or route-search changes are performed.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import hashlib
import io
import json
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "api"))

from app.services.train_realtime import (
    STATIC_GTFS_URL,
    StaticTrainGtfs,
    TrainRealtimeError,
    _fetch_bytes,
    parse_static_gtfs,
)
from app.services.train_route_identity import enrich_route_result_train_trip_ids
from app.services.train_service_calendar import parse_train_service_calendar
import toei_engine as te


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-gtfs", type=Path, default=ROOT / "api/data/Toei-Train-GTFS.zip")
    parser.add_argument("--prebuilt", type=Path, default=ROOT / "api/data/app_data_search_labels.pkl")
    parser.add_argument("--date", default="2026-10-04")
    parser.add_argument("--route", type=Path, action="append")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    archive = args.train_gtfs.resolve()
    report = {
        "scope": "Train identity only, using active service-day trips and frozen search-selected rail clocks. Search timings, HTTP request time and realtime feeds are excluded. The official train GTFS archive is downloaded only when explicitly requested and absent locally.",
        "request_date": args.date,
        "official_source": STATIC_GTFS_URL,
        "archive_path": str(archive),
        "setup_ms": {},
        "routes": [],
    }
    if not archive.exists() and args.download:
        # The production downloader reads the configured ODPT token. It is
        # never printed or included in the report/command arguments.
        from dotenv import load_dotenv
        load_dotenv(ROOT / "api/.env")
        started = time.perf_counter()
        try:
            content = asyncio.run(_fetch_bytes(STATIC_GTFS_URL, timeout_seconds=30.0))
        except Exception as error:
            report["status"] = "download_failed"
            report["error_type"] = type(error).__name__
            # HTTP exception text may contain the authenticated request URL.
            # Only the production wrapper's sanitized message can be recorded.
            if isinstance(error, TrainRealtimeError):
                report["error_code"] = error.code
                report["error_message"] = error.message
            write_json(OUT / "identity_results.json", report)
            print("train GTFS download failed:", report["error_type"], report.get("error_code", ""))
            return 1
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(content)
        report["setup_ms"]["download"] = (time.perf_counter() - started) * 1000
    if not archive.exists():
        report["status"] = "train_gtfs_unavailable"
        report["error_message"] = "No local train GTFS archive. Use --train-gtfs or explicitly request --download."
        write_json(OUT / "identity_results.json", report)
        print(report["error_message"])
        return 1
    report["archive_sha256"] = sha(archive)
    report["archive_bytes"] = archive.stat().st_size
    report["observed_at_jst"] = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat()
    if args.download_only:
        report["status"] = "archive_available"
        write_json(OUT / "identity_results.json", report)
        print("train GTFS available:", archive.stat().st_size, "bytes")
        return 0

    started = time.perf_counter()
    content = archive.read_bytes()
    static = parse_static_gtfs(content)
    report["setup_ms"]["static_gtfs_parse"] = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    calendar = parse_train_service_calendar(content)
    active_ids = calendar.active_trip_ids(dt.date.fromisoformat(args.date))
    active_static = StaticTrainGtfs(trips={key: trip for key, trip in static.trips.items() if key in active_ids})
    report["setup_ms"]["calendar_parse_filter"] = (time.perf_counter() - started) * 1000
    report["static_trip_count"] = len(static.trips)
    report["active_trip_count"] = len(active_static.trips)
    started = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        with args.prebuilt.open("rb") as source:
            data = pickle.load(source)
    report["setup_ms"]["pickle_load"] = (time.perf_counter() - started) * 1000
    report["prebuilt_sha256"] = sha(args.prebuilt)
    report["identity_source_sha256"] = sha(ROOT / "api/app/services/train_route_identity.py")
    day_type = te.determine_day_type(args.date)
    paths = args.route or sorted(OUT.glob("implementation_*_route.json"))
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        started = time.perf_counter()
        result = enrich_route_result_train_trip_ids(
            payload,
            timetable_manager=data["TM"],
            day_type=day_type,
            static_gtfs=active_static,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        output_path = OUT / path.name.replace("implementation_", "identity_", 1)
        write_json(output_path, result)
        row = {
            "input": str(path), "input_sha256": sha(path),
            "output": str(output_path), "identity_ms": elapsed_ms,
            "input_candidates": len(payload.get("candidates", ())),
            "accepted_candidates": len(result.get("candidates", ())),
            "rejections": result.get("meta", {}).get("train_identity_rejected_candidates", []),
            "rail_steps": [{
                "candidate_id": candidate.get("id"),
                **{key: step.get(key) for key in
                   ("step_id", "title", "from_", "to", "trip_id", "route_id", "departure_time", "arrival_time")},
            } for candidate in result.get("candidates", ())
                for step in candidate.get("steps", ()) if step.get("kind") == "rail"],
        }
        report["routes"].append(row)
        print(path.name, "accepted", row["accepted_candidates"], "/", row["input_candidates"],
              "identity_ms", round(elapsed_ms, 3))
    report["status"] = "complete" if paths else "route_outputs_unavailable"
    write_json(OUT / "identity_results.json", report)
    return 0 if paths else 1


if __name__ == "__main__":
    raise SystemExit(main())
