"""Measure the Tokyo app's read-only route + train-identity request sequence.

Run from the repository root with api/.venv-route/Scripts/python.exe -X utf8.
This does not update app data or deployment configuration.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx


OUT = Path(__file__).resolve().parent
JST = dt.timezone(dt.timedelta(hours=9))
CONFIG_FILE_ID = "1pbE5qFpgDzVhYl8wA1qp4T_7jOsB2s68"
BODY = {
    "alat": "35.708166", "alon": "139.817434",
    "blat": "35.6636842", "blon": "139.6977409",
    "start_time": "20:40", "target_date_str": "2026-10-04",
    "bus_only": False,
}


def write_json(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def timed_request(client, method, url, *, body=None, timeout=60):
    started_at = dt.datetime.now(JST).isoformat()
    started = time.perf_counter()
    response = client.request(method, url, json=body, timeout=timeout)
    decoded = response.json()
    elapsed_ms = (time.perf_counter() - started) * 1000
    return decoded, {
        "started_at_jst": started_at,
        "status_code": response.status_code,
        "elapsed_ms": elapsed_ms,
        "response_bytes": len(response.content),
    }


def summarize_candidate(candidate):
    steps = []
    for step in candidate.get("steps", []):
        steps.append({
            key: step.get(key) for key in (
                "kind", "title", "from", "from_", "to", "departure_time",
                "arrival_time", "minutes", "meters", "tripId", "trip_id",
                "routeId", "route_id", "departureStopId", "arrivalStopId",
            ) if step.get(key) is not None
        })
    return {
        key: candidate.get(key) for key in (
            "id", "lines", "total_time", "arrival_time", "transfers", "walk_m",
            "walking_distance_meters", "walking_segment_count", "rides",
            "score_label", "cost_score", "departure_date", "is_future_suggestion",
        )
    } | {"steps": steps}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", help="Explicit known Tokyo endpoint; otherwise use app runtime config")
    parser.add_argument("--retry-few-transfers", action="store_true", help="Append one retry to existing measurements")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "request": BODY, "scope": "Tokyo only; real HTTP, read-only route requests",
        "origin": "十間橋 GTFS 0751-01", "destination": "渋谷区役所本庁舎",
        "destination_source": "https://www.city.shibuya.tokyo.jp/shisetsu/kuyakusho/kuyakusho/service_center.html",
        "notes": [
            "First observed request is not proof of a Lambda cold start.",
            "HTTP timings include this PC's network, server work, and JSON decoding; not mobile rendering.",
            "Runtime-config fetch and warmup are measured separately from search.",
            "App passes pref=cost when no preference is selected; limit defaults to 5.",
            "Requests run sequentially; no endpoint load test.",
        ],
        "runs": [],
    }
    if args.retry_few_transfers:
        report = json.loads((OUT / "http_results.json").read_text(encoding="utf-8"))
    with httpx.Client(headers={"X-App-City": "tokyo"}, follow_redirects=True) as client:
        api_base = report["api_base"] if args.retry_few_transfers else args.api_base
        if api_base is None:
            config_url = "https://drive.google.com/uc?export=download&id=" + CONFIG_FILE_ID + "&t=" + str(int(time.time() * 1000))
            config, timing = timed_request(client, "GET", config_url, timeout=12)
            if timing["status_code"] != 200:
                raise RuntimeError("Runtime config could not be fetched")
            report["runtime_config_timing"] = timing
            api_base = config["api_base"]
        parsed = urlparse(api_base)
        if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".on.aws"):
            raise RuntimeError("Expected the configured public HTTPS Lambda endpoint")
        api_base = api_base.rstrip("/")
        report["api_base"] = api_base
        if not args.retry_few_transfers:
            warmup, report["warmup_timing"] = timed_request(client, "GET", api_base + "/warmup")
            report["warmup_response"] = warmup
            write_json("http_results.json", report)
            if warmup.get("city") != "tokyo" or warmup.get("status") != "ready":
                raise RuntimeError("Tokyo warmup did not report ready")
        runs = [("cost", 1), ("cost", 2), ("cost", 3), ("time", 1), ("fewTransfers", 1)]
        if args.retry_few_transfers:
            repeat = max(row["repeat"] for row in report["runs"] if row["mode"] == "fewTransfers") + 1
            runs = [("fewTransfers", repeat)]
        for mode, repeat in runs:
            run = {"mode": mode, "repeat": repeat}
            started = time.perf_counter()
            payload, timing = timed_request(client, "POST", api_base + "/route", body=BODY | {"pref": mode})
            run["route"] = timing
            write_json(f"http_{mode}_{repeat}_route.json", payload)
            if timing["status_code"] == 200:
                candidates = payload.get("candidates", [])
                run["raw_candidate_count"] = len(candidates)
                run["route_meta"] = payload.get("meta")
                run["raw_candidates"] = [summarize_candidate(item) for item in candidates]
                if any(step.get("kind") == "rail" for item in candidates for step in item.get("steps", [])):
                    identity, identity_timing = timed_request(
                        client, "POST", api_base + "/train/resolve-route-identities",
                        body={"candidates": candidates, "target_date_str": BODY["target_date_str"]},
                    )
                    run["train_identity"] = identity_timing
                    write_json(f"http_{mode}_{repeat}_identities.json", identity)
                    if identity_timing["status_code"] == 200:
                        final_candidates = identity.get("candidates", [])
                        run["rejections"] = identity.get("rejections", [])
                        run["app_would_error"] = bool(candidates and not final_candidates)
                    else:
                        final_candidates = []
                        run["identity_error"] = identity
                        run["app_would_error"] = True
                else:
                    final_candidates = candidates
                    run["rejections"] = []
                    run["app_would_error"] = False
                run["display_candidate_count"] = len(final_candidates)
                run["display_candidates"] = [summarize_candidate(item) for item in final_candidates]
            else:
                run["route_error"] = payload
                run["app_would_error"] = True
            run["sequence_wall_ms"] = (time.perf_counter() - started) * 1000
            run["api_total_ms"] = run["route"]["elapsed_ms"] + run.get("train_identity", {}).get("elapsed_ms", 0)
            report["runs"].append(run)
            write_json("http_results.json", report)
            print(json.dumps({key: run.get(key) for key in ("mode", "repeat", "api_total_ms", "raw_candidate_count", "display_candidate_count", "app_would_error")}, ensure_ascii=False), flush=True)
        for mode in ("cost", "time", "fewTransfers"):
            rows = [run for run in report["runs"] if run["mode"] == mode]
            report.setdefault("summary", {})[mode] = {
                "samples": len(rows),
                "api_total_median_ms": statistics.median(row["api_total_ms"] for row in rows),
                "route_median_ms": statistics.median(row["route"]["elapsed_ms"] for row in rows),
                "identity_median_ms": statistics.median(row.get("train_identity", {}).get("elapsed_ms", 0) for row in rows),
            }
        write_json("http_results.json", report)


if __name__ == "__main__":
    main()
