from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import gc
import gzip
import hashlib
import io
import json
import pickle
import re
import sys
import time
import types
from pathlib import Path
from zoneinfo import ZoneInfo

import jpholiday
import networkx as nx


ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "api"
sys.path.insert(0, str(API))

import toei_engine as te  # noqa: E402
from tokyo_metro_gtfs import (  # noqa: E402
    add_tokyo_metro_to_graph,
    metro_service_is_active,
)
from tokyo_route_engine import (  # noqa: E402
    TokyoRouteDependencies,
    TokyoRouteEngine,
)


JST = ZoneInfo("Asia/Tokyo")
STAT = re.compile(r"([a-z_]+)=([^ ]+)")
SUPPORTED_SCOPES = {"toei_bus", "toei_subway", "tokyo_metro"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_path(parser: argparse.ArgumentParser, path: Path) -> None:
    if not path.exists():
        parser.error(f"required input does not exist: {path}")


def stats_from_log(text: str) -> list[dict]:
    rows: list[dict] = []
    for line in text.splitlines():
        if "[ROUTE_DEBUG]" not in line or " stats: " not in line:
            continue
        row: dict = dict(STAT.findall(line))
        for key in (
            "visited",
            "yielded",
            "queue",
            "g_score",
            "best_cost",
            "frontier_labels",
            "compacted_count",
        ):
            if key in row:
                row[key] = int(row[key])
        if "elapsed_sec" in row:
            row["elapsed_sec"] = float(row["elapsed_sec"])
        rows.append(row)
    return rows


def stable_candidate(candidate: dict) -> dict:
    result = {
        "id": candidate.get("id"),
        "departure_time": candidate.get("departure_time"),
        "arrival_time": candidate.get("arrival_time"),
        "rides": candidate.get("rides"),
        "transfers": candidate.get("transfers"),
        "total": candidate.get("total"),
        "contains_estimated_transfer": candidate.get(
            "contains_estimated_transfer", False
        ),
        "steps": [],
    }
    for step in candidate.get("steps", []):
        selected_run = step.get("selected_run")
        stable_run = None
        if isinstance(selected_run, dict):
            stable_run = {
                key: selected_run.get(key)
                for key in (
                    "provider",
                    "run_key",
                    "run_id",
                    "service_key",
                    "train_number",
                    "trip_id",
                    "route_id",
                    "service_id",
                    "origin_stop_id",
                    "destination_stop_id",
                    "origin_gtfs_stop_id",
                    "destination_gtfs_stop_id",
                    "scheduled_departure_minute",
                    "scheduled_arrival_minute",
                    "origin_sequence",
                    "destination_sequence",
                )
            }
        result["steps"].append(
            {
                "kind": step.get("kind"),
                "title": step.get("title"),
                "title_en": step.get("title_en"),
                "from": step.get("from_", step.get("from")),
                "from_en": step.get("from_en"),
                "to": step.get("to"),
                "to_en": step.get("to_en"),
                "departure_time": step.get("departure_time"),
                "arrival_time": step.get("arrival_time"),
                "minutes": step.get("minutes"),
                "meters": step.get("meters"),
                "route_id": step.get("route_id"),
                "trip_id": step.get("trip_id"),
                "selected_run": stable_run,
                "stops": [
                    {
                        "id": stop.get("id"),
                        "odpt_id": stop.get("odpt_id"),
                        "name": stop.get("name"),
                        "name_en": stop.get("name_en"),
                    }
                    for stop in step.get("stops", [])
                    if isinstance(stop, dict)
                ],
                "walking_connection_verified": step.get(
                    "walking_connection_verified"
                ),
                "walking_time_estimated": step.get("walking_time_estimated"),
            }
        )
    return result


def candidate_digest(candidates: list[dict]) -> str:
    encoded = json.dumps(
        candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def station_coordinates(graph, station_id: str) -> tuple[float, float]:
    node = ("phys", station_id)
    if node not in graph:
        raise RuntimeError(f"fixed corpus station is not loaded: {station_id}")
    data = graph.nodes[node]
    return float(data["lat"]), float(data["lon"])


def coordinates(graph, case: dict, prefix: str) -> tuple[float, float]:
    station_key = f"{prefix}_station_id"
    coordinate_key = prefix
    if station_key in case:
        return station_coordinates(graph, str(case[station_key]))
    value = case.get(coordinate_key)
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{case.get('name')}: invalid {coordinate_key}")
    return float(value[0]), float(value[1])


def validate_corpus(corpus: dict) -> None:
    contract = corpus["fixed_contract"]
    if contract["modes"] != ["time", "fewTransfers"]:
        raise ValueError("fixed modes changed")
    if contract["candidate_limits"] != [1, 2, 3, 4, 5]:
        raise ValueError("fixed candidate limits changed")
    if contract["estimated_transfer_modes"] != [False, True]:
        raise ValueError("fixed estimated-transfer modes changed")
    if (
        contract["time_limit_seconds"] != 15
        or contract["pop_limit"] != 100000
        or contract["max_travel_minutes"] != 240
    ):
        raise ValueError("fixed search limits changed")
    scopes = {frozenset(case["scope"]) for case in corpus["matrix_cases"]}
    expected = {
        frozenset({"toei_bus"}),
        frozenset({"toei_subway"}),
        frozenset({"tokyo_metro"}),
        frozenset({"toei_bus", "toei_subway"}),
        frozenset({"toei_bus", "tokyo_metro"}),
        frozenset({"toei_subway", "tokyo_metro"}),
        frozenset(SUPPORTED_SCOPES),
    }
    if scopes != expected:
        raise ValueError("matrix must contain each of the seven transport scopes once")

    holiday_cases = [
        case
        for case in corpus["supplemental_cases"]
        if "public_holiday" in case["tags"]
    ]
    if len(holiday_cases) != 1:
        raise ValueError("corpus must contain exactly one public-holiday case")
    holiday = holiday_cases[0]
    service_date = dt.date.fromisoformat(holiday["date"])
    expectation = holiday.get("calendar_expectation", {})
    if not expectation.get("official_holiday") or not jpholiday.is_holiday(service_date):
        raise ValueError(f"public-holiday case is not a Japanese holiday: {service_date}")
    if service_date.weekday() >= 5:
        raise ValueError("public-holiday case must prove a holiday exception, not weekend service")


def load_engine(args, corpus: dict):
    with args.app_data.open("rb") as source:
        data = pickle.load(source)
    with contextlib.redirect_stdout(io.StringIO()):
        te.gtfs_repo.load_data(str(args.bus_gtfs))
        feed = add_tokyo_metro_to_graph(
            data["G"],
            data["TM"],
            gtfs_dir=str(args.metro_gtfs),
            stations_path=str(args.metro_stations),
            railways_path=str(args.metro_railways),
            counterpart_stations_path=str(args.toei_stations),
            reviewed_transfers_path=str(args.transfer_manifest),
            walk_radius=data["WALK_RAD"],
        )
    expected = corpus["feed"]
    observed = {
        "version": feed.version,
        "valid_from": feed.start_date.isoformat(),
        "valid_until": feed.end_date.isoformat(),
    }
    if observed != {key: expected[key] for key in observed}:
        raise RuntimeError(f"GTFS validity/version mismatch: {observed}")
    validate_holiday_calendar(corpus, data["TM"])
    app = types.SimpleNamespace(state=types.SimpleNamespace(**data))
    engine = TokyoRouteEngine(
        app,
        dependencies=TokyoRouteDependencies(
            now=lambda: dt.datetime(2026, 10, 23, 8, 0, tzinfo=JST)
        ),
    )
    return engine, data, observed


def validate_holiday_calendar(corpus: dict, manager) -> None:
    case = next(
        case
        for case in corpus["supplemental_cases"]
        if "public_holiday" in case["tags"]
    )
    service_date = dt.date.fromisoformat(case["date"])
    expectation = case["calendar_expectation"]
    observed_day_type = te.determine_day_type(service_date)
    if observed_day_type != expectation["civil_day_type"]:
        raise RuntimeError(
            f"holiday day type mismatch: {service_date} -> {observed_day_type}"
        )
    exceptions = getattr(manager, "tokyo_metro_service_exceptions", {})
    day_exceptions = exceptions.get(service_date.strftime("%Y%m%d"), {})
    for service_id in expectation["gtfs_removed_service_ids"]:
        if metro_service_is_active(manager, service_id, service_date):
            raise RuntimeError(
                f"GTFS removed service is active on holiday: {service_id} {service_date}"
            )
        if day_exceptions and int(day_exceptions.get(service_id, 0)) != 2:
            raise RuntimeError(f"missing GTFS removal exception for service {service_id}")
    for service_id in expectation["gtfs_added_service_ids"]:
        if not metro_service_is_active(manager, service_id, service_date):
            raise RuntimeError(
                f"GTFS added service is inactive on holiday: {service_id} {service_date}"
            )
        if day_exceptions and int(day_exceptions.get(service_id, 0)) != 1:
            raise RuntimeError(f"missing GTFS addition exception for service {service_id}")


def run_search(
    engine: TokyoRouteEngine,
    graph,
    case: dict,
    *,
    mode: str,
    limit: int,
    estimated: bool,
) -> dict:
    origin = coordinates(graph, case, "origin")
    destination = coordinates(graph, case, "destination")
    gc.collect()
    log = io.StringIO()
    error = None
    payload = None
    started = time.perf_counter()
    try:
        with contextlib.redirect_stdout(log):
            payload = engine.search_legacy(
                alat=origin[0],
                alon=origin[1],
                blat=destination[0],
                blon=destination[1],
                pref=mode,
                transport_scope=frozenset(case["scope"]),
                include_estimated_transfers=estimated,
                start_time=case["time"],
                date_str=case["date"],
                limit=limit,
            )
    except Exception as exc:  # captured as regression evidence
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    stats = stats_from_log(log.getvalue())
    raw_candidates = [] if payload is None else payload.get("candidates", [])
    candidates = [stable_candidate(candidate) for candidate in raw_candidates]
    if not estimated and any(
        candidate["contains_estimated_transfer"] for candidate in candidates
    ):
        raise RuntimeError("ordinary corpus run returned an estimated transfer")
    return {
        "case": case["name"],
        "scope": case["scope"],
        "tags": case["tags"],
        "mode": mode,
        "candidate_limit": limit,
        "estimated_transfers": estimated,
        "date": case["date"],
        "time": case["time"],
        "elapsed_seconds": elapsed,
        "error": error,
        "candidate_count": len(candidates),
        "candidate_sha256": candidate_digest(candidates),
        "candidates": candidates,
        "max_pop": max((row.get("visited", 0) for row in stats), default=0),
        "max_retained_labels": max(
            (row.get("frontier_labels", 0) for row in stats), default=0
        ),
        "max_queue": max((row.get("queue", 0) for row in stats), default=0),
    }


def fixed_station_topology(engine: TokyoRouteEngine, cases: list[dict]) -> dict:
    evidence = {}
    for case in cases:
        if "origin_station_id" not in case or "destination_station_id" not in case:
            continue
        start = ("phys", case["origin_station_id"])
        target = ("phys", case["destination_station_id"])
        entry = {}
        for estimated in (False, True):
            graph, _ = engine._graph_for_scope(
                frozenset(case["scope"]),
                include_estimated_transfers=estimated,
            )
            entry["estimated" if estimated else "ordinary"] = nx.has_path(
                graph, start, target
            )
        evidence[case["name"]] = entry
    return evidence


def compare_rows(observed: list[dict], expected_path: Path) -> list[str]:
    if expected_path.suffix == ".gz":
        with gzip.open(expected_path, "rt", encoding="utf-8") as source:
            expected = json.load(source)["rows"]
    else:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))["rows"]
    keys = ("case", "mode", "candidate_limit", "estimated_transfers")
    expected_by_key = {tuple(row[key] for key in keys): row for row in expected}
    mismatches: list[str] = []
    for row in observed:
        key = tuple(row[name] for name in keys)
        old = expected_by_key.pop(key, None)
        if old is None:
            mismatches.append(f"unexpected row: {key}")
            continue
        for field in ("error", "candidate_count", "candidate_sha256", "candidates"):
            if row[field] != old[field]:
                mismatches.append(f"{key}: {field} changed")
    mismatches.extend(f"missing row: {key}" for key in expected_by_key)
    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed Tokyo Metro release corpus")
    parser.add_argument("--app-data", type=Path, required=True)
    parser.add_argument("--bus-gtfs", type=Path, required=True)
    parser.add_argument("--metro-archive", type=Path, required=True)
    parser.add_argument("--metro-gtfs", type=Path, required=True)
    parser.add_argument("--metro-stations", type=Path, required=True)
    parser.add_argument("--metro-railways", type=Path, required=True)
    parser.add_argument("--toei-stations", type=Path, required=True)
    parser.add_argument("--transfer-manifest", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=Path(__file__).with_name("corpus.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    for path in (
        args.app_data,
        args.bus_gtfs,
        args.metro_archive,
        args.metro_gtfs,
        args.metro_stations,
        args.metro_railways,
        args.toei_stations,
        args.transfer_manifest,
        args.corpus,
    ):
        require_path(parser, path)

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    validate_corpus(corpus)
    archive_hash = sha256(args.metro_archive)
    if archive_hash != corpus["feed"]["archive_sha256"]:
        parser.error(
            "Metro archive hash mismatch; refusing to substitute a different feed"
        )
    engine, data, feed = load_engine(args, corpus)
    contract = corpus["fixed_contract"]
    rows: list[dict] = []
    cases = [
        *(dict(case, _matrix=True) for case in corpus["matrix_cases"]),
        *(dict(case, _matrix=False) for case in corpus["supplemental_cases"]),
    ]
    topology_evidence = fixed_station_topology(engine, cases)
    for case in cases:
        limits = (
            contract["candidate_limits"]
            if case.pop("_matrix")
            else case["candidate_limits"]
        )
        for estimated in contract["estimated_transfer_modes"]:
            for mode in contract["modes"]:
                for limit in limits:
                    row = run_search(
                        engine,
                        data["G"],
                        case,
                        mode=mode,
                        limit=limit,
                        estimated=estimated,
                    )
                    rows.append(row)
                    print(
                        row["case"],
                        mode,
                        limit,
                        "estimated" if estimated else "ordinary",
                        f"{row['elapsed_seconds']:.3f}s",
                        f"pops={row['max_pop']}",
                        f"candidates={row['candidate_count']}",
                        row["error"] or "ok",
                        flush=True,
                    )

    toei_pairs: dict[tuple, dict[bool, dict]] = {}
    for row in rows:
        if "legacy_toei" not in row["tags"]:
            continue
        key = (row["case"], row["mode"], row["candidate_limit"])
        toei_pairs.setdefault(key, {})[row["estimated_transfers"]] = row
    toei_mode_mismatches = [
        key
        for key, pair in toei_pairs.items()
        if set(pair) != {False, True}
        or pair[False]["candidate_sha256"] != pair[True]["candidate_sha256"]
        or pair[False]["error"] != pair[True]["error"]
        or pair[False]["max_pop"] != pair[True]["max_pop"]
        or pair[False]["max_retained_labels"]
        != pair[True]["max_retained_labels"]
    ]
    mismatches = [] if args.baseline is None else compare_rows(rows, args.baseline)
    output = {
        "schema": "tokyo_metro_release_corpus_result/v1",
        "feed": {**feed, "archive_sha256": archive_hash},
        "transfer_manifest_sha256": sha256(args.transfer_manifest),
        "contract": contract,
        "fixed_station_topology": topology_evidence,
        "summary": {
            "rows": len(rows),
            "errors": sum(row["error"] is not None for row in rows),
            "limit_hits": sum(
                row["error"] is not None
                and ("max_visited" in row["error"] or "time_limit" in row["error"])
                for row in rows
            ),
            "max_pop": max((row["max_pop"] for row in rows), default=0),
            "max_retained_labels": max(
                (row["max_retained_labels"] for row in rows), default=0
            ),
            "toei_estimated_toggle_mismatches": toei_mode_mismatches,
            "correctness_comparison": {
                "performed": args.baseline is not None,
                "baseline_sha256": sha256(args.baseline) if args.baseline else None,
                "mismatches": len(mismatches),
            },
        },
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if mismatches:
        for mismatch in mismatches:
            print(f"MISMATCH: {mismatch}", file=sys.stderr)
    if toei_mode_mismatches:
        print(
            f"Toei-only result changed when estimated mode was toggled: {toei_mode_mismatches}",
            file=sys.stderr,
        )
    observed_errors = [row for row in rows if row["error"] is not None]
    if observed_errors:
        print(
            f"Unexpected search errors in {len(observed_errors)} corpus rows",
            file=sys.stderr,
        )
    return 1 if mismatches or toei_mode_mismatches or observed_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
