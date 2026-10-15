"""Read-only Tokyo rail input/legacy concrete-run gate, not shared routing parity.

No network, calendar inference, rounding, prebuilt repair or file output.
Optional pickle input must be an explicitly selected trusted local artifact.
"""
from __future__ import annotations

import argparse
from collections import Counter
import contextlib
import hashlib
import io
import json
from pathlib import Path
import pickle
import re
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import networkx as nx
from toei_engine import TimetableManager
from tokyo_timetable_choices import TimetableChoices, _calendar_matches, _railway_id
from transit_dataset import service_time_to_second


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def records(path):
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    # These are explicit accepted Tokyo load_json envelopes, not error recovery.
    if isinstance(value, dict):
        value = value["result"] if "result" in value else [value]
    if not isinstance(value, list) or not value or any(not isinstance(r, dict) for r in value):
        raise ValueError(f"require nonempty ODPT record list: {path}")
    return value


def required(record, field, where):
    value = record.get(field)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"invalid {field}: {where}")
    return value


def source_intervals(entries):
    """Reference the current Tokyo loader's *explicit* minute rollover contract.

    Raw source seconds are validated first. HH:MM:SS is not converted to HH:MM
    to make the old loader accept it, even when its seconds happen to be zero.
    """
    intervals = []
    calendars, dates = Counter(), Counter()
    seen = set()
    midnight_wraps = repeated_stops = missing_arrival = missing_departure = 0
    source_clocks = []
    for entry_index, entry in enumerate(entries):
        run = entry.get("owl:sameAs") or entry.get("@id")
        if not isinstance(run, str) or not run or run.strip() != run or run in seen:
            raise ValueError(f"missing/duplicate explicit rail run identity: record={entry_index}")
        seen.add(run)
        calendar = required(entry, "odpt:calendar", run)
        railway = required(entry, "odpt:railway", run)
        number = required(entry, "odpt:trainNumber", run)
        calendars[calendar] += 1
        if "dc:date" in entry:
            dates[required(entry, "dc:date", run)] += 1
        objects = entry.get("odpt:trainTimetableObject")
        if not isinstance(objects, list) or len(objects) < 2:
            raise ValueError(f"require at least two rail stop objects: {run}")
        previous = None
        floor = 0
        stop_ids = []
        for sequence, obj in enumerate(objects):
            if not isinstance(obj, dict):
                raise ValueError(f"invalid stop object: {run} sequence={sequence}")
            dep_station, arr_station = obj.get("odpt:departureStation"), obj.get("odpt:arrivalStation")
            if dep_station and arr_station and dep_station != arr_station:
                raise ValueError(f"different arrival/departure stations: {run} sequence={sequence}")
            station = dep_station or arr_station
            if not isinstance(station, str) or _railway_id(station) != railway:
                raise ValueError(f"station/railway identity mismatch: {run} sequence={sequence}")
            stop_ids.append(station)
            clocks = {}
            for field in ("odpt:arrivalTime", "odpt:departureTime"):
                value = obj.get(field)
                if value is None or value == "":
                    clocks[field] = None
                    continue
                if not isinstance(value, str):
                    raise ValueError(f"invalid source clock type: {run} sequence={sequence} field={field}")
                try:
                    seconds = service_time_to_second(value)
                except ValueError as error:
                    raise ValueError(f"invalid source clock: {run} sequence={sequence} field={field}: {error}") from error
                source_clocks.append(seconds)
                if len(value.split(":")) != 2:
                    raise ValueError(f"legacy Tokyo loader requires HH:MM; source precision must not be rewritten: {run} sequence={sequence} field={field}")
                clocks[field] = seconds // 60  # Exact divisibility established by HH:MM.
            arrival, departure = clocks["odpt:arrivalTime"], clocks["odpt:departureTime"]
            missing_arrival += arrival is None
            missing_departure += departure is None
            if previous is not None and previous[1] is not None and arrival is not None:
                dep = previous[1]
                while dep < floor:
                    dep += 1440
                    midnight_wraps += 1
                arr = arrival
                while arr < dep:
                    arr += 1440
                    midnight_wraps += 1
                floor = arr
                if dep >= 99999 or arr >= 99999:
                    raise ValueError(f"legacy sentinel clock collision: {run} sequence={sequence}")
                intervals.append((calendar, run, previous[2], previous[0], station, dep, arr, number))
            previous = station, departure if departure is not None else arrival, sequence
        repeated_stops += len(stop_ids) != len(set(stop_ids))
    if not intervals:
        raise ValueError("no comparable rail intervals")
    return intervals, {"runs": len(seen), "source_intervals": len(intervals),
        "calendars": dict(sorted(calendars.items())),
        "source_date_count": len(dates), "source_date_min": min(dates) if dates else None,
        "source_date_max": max(dates) if dates else None,
        "source_clock_min_seconds": min(source_clocks), "source_clock_max_seconds": max(source_clocks),
        "clocks_below_03h": sum(s < 10800 for s in source_clocks),
        "legacy_rollover_additions": midnight_wraps, "runs_with_repeated_stops": repeated_stops,
        "missing_arrival_clocks": missing_arrival, "missing_departure_clocks": missing_departure}


def manager_intervals(manager):
    if not isinstance(manager, TimetableManager):
        raise ValueError("prebuilt TM must be a Tokyo TimetableManager")
    result = []
    for is_weekday, target in ((True, manager.train_patterns_weekday), (False, manager.train_patterns_weekend)):
        for origin, rows in target.items():
            for row in rows:
                for field in ("calendar", "run_key", "next_sta", "train_num"):
                    required(row, field, f"prebuilt/manager origin={origin}")
                if type(row.get("stop_sequence")) is not int:
                    raise ValueError("rail run occurrence missing; prebuilt repair is not performed")
                if is_weekday != ("Weekday" in row["calendar"]):
                    raise ValueError("rail calendar stored in wrong legacy bucket")
                if type(row.get("dep")) is not int or type(row.get("arr")) is not int:
                    raise ValueError("legacy rail clocks must remain integer minutes")
                result.append((row["calendar"], row["run_key"], row["stop_sequence"], origin,
                    row["next_sta"], row["dep"], row["arr"], row["train_num"]))
    return result


def compare_intervals(expected, actual, stage):
    left, right = Counter(expected), Counter(actual)
    if left != right:
        raise AssertionError(f"{stage} differs: missing_count={sum((left-right).values())} extra_count={sum((right-left).values())}")


def choices_intervals(manager, expected, day):
    selected = [r for r in expected if ("Weekday" in r[0]) == (day == "weekday")
                and _calendar_matches(r[0], day)]
    graph = nx.DiGraph()
    origins = set()
    calendars = {r[1]: r[0] for r in expected}
    for _, _, _, origin, following, _, _, _ in selected:
        line = _railway_id(origin)
        u, v = ("line", origin, line), ("line", following, line)
        graph.add_node(u, mode="rail")
        graph.add_node(v, mode="rail")
        graph.add_edge(u, v, etype="ride", mode="rail")
        origins.add(u)
    choices = TimetableChoices(graph, manager, day, use_realtime=False, rail_boarding_minutes=0)
    result = []
    for u in sorted(origins):
        for dep, state in choices.board_options(("phys", u[1]), u, 0):
            run = choices._runs[(state.provider, state.run_id)]
            position = choices._positions[(state.provider, state.run_id)][state.sequence]
            following = run.stops[position + 1].stop_id
            for _, continued in choices.ride_options(u, ("line", following, u[2]), dep, state):
                meta = choices.metadata(continued)
                source_run = meta["run_key"]
                result.append((calendars[source_run], source_run, state.sequence, u[1], following,
                    meta["scheduled_departure_minute"], meta["scheduled_arrival_minute"], meta["train_number"]))
    compare_intervals(selected, result, f"concrete choices/{day}")
    return {"profile": day, "intervals": len(result), "differences": 0}


def inspect(train_path, prebuilt_path=None):
    expected, summary = source_intervals(records(train_path))
    manager = TimetableManager()
    with contextlib.redirect_stdout(io.StringIO()):
        manager.load_train_timetables(str(train_path))
    compare_intervals(expected, manager_intervals(manager), "raw loader")
    summary["choices"] = [choices_intervals(manager, expected, day)
                          for day in ("weekday", "saturday", "holiday")]
    summary["prebuilt_verified"] = False
    if prebuilt_path is not None:
        with prebuilt_path.open("rb") as stream:
            data = pickle.load(stream)
        if not isinstance(data, dict) or "TM" not in data:
            raise ValueError("trusted prebuilt must contain TM")
        compare_intervals(expected, manager_intervals(data["TM"]), "prebuilt TM")
        summary["prebuilt_choices"] = [choices_intervals(data["TM"], expected, day)
                                      for day in ("weekday", "saturday", "holiday")]
        summary["prebuilt_verified"] = True
    summary.update(shared_adapter_verified=False, operational_calendar_verified=False,
                   route_ranking_verified=False, realtime_verified=False, lambda_startup_verified=False)
    return summary


def git(*parts):
    return subprocess.run(["git", "-C", str(ROOT), *parts], check=True,
        capture_output=True, text=True, encoding="utf-8").stdout.strip()


def check_repository(expected):
    if re.fullmatch(r"[0-9a-f]{40}", expected) is None:
        raise ValueError("expected-sha requires a full lowercase SHA")
    if git("rev-parse", "HEAD") != expected or git("branch", "--show-current") != "main" or git("status", "--porcelain"):
        raise ValueError("require clean main at expected SHA; no pull/stash/reset performed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-timetables", type=Path, required=True)
    parser.add_argument("--trusted-prebuilt", type=Path)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    check_repository(args.expected_sha)
    paths = {"train_timetables": args.train_timetables.resolve()}
    if args.trusted_prebuilt is not None:
        paths["trusted_prebuilt"] = args.trusted_prebuilt.resolve()
    before = {k: sha256(p) for k, p in paths.items()}
    summary = inspect(paths["train_timetables"], paths.get("trusted_prebuilt"))
    if before != {k: sha256(p) for k, p in paths.items()}:
        raise AssertionError("input files changed during verification")
    check_repository(args.expected_sha)
    print(json.dumps({"sha": args.expected_sha, "python": sys.version, "input_hashes": before,
                      **summary}, ensure_ascii=True))
    print("READ_ONLY_TOKYO_RAIL_INPUT_OK")


if __name__ == "__main__":
    main()
