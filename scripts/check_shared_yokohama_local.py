"""Offline, read-only v1/shared comparison in separate processes.

No fetch, credential lookup, implicit walking links, backend retry or output
files. Only the head candidate is comparable to v1; additional shared
candidates are checked for feasibility, ordering and repeatability, not top-K
completeness. RSS is the OS working set; its peak is process-lifetime high water.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import contextlib
import csv
import ctypes
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from transit_engine import BatchSearchRequest, PythonTransitSearchCore, SearchEndpoint
from transit_network import NetworkCosts
from transit_timetable_choices import NetworkRideEvent, NetworkSearchParameters
from yokohama_fare_coverage import YokohamaFareCoverage
from yokohama_shared_network import build_shared_municipal_network, search_shared_municipal_network
from yokohama_subway import load_reviewed_yokohama_subway_coverage
from yokohama_transit import load_yokohama_bus_dataset

POLICIES = ("yokohama_welfare_special_pass", "yokohama_senior_special_pass")


def parse_day(value):
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError("date must be zero-padded YYYY-MM-DD")
    return result


class ProcessMemory:
    def __init__(self, source):
        self.source = source
        if source == "windows-psapi":
            if sys.platform != "win32":
                raise ValueError("windows-psapi requires Windows; no alternate memory provider")
            class Counters(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_uint32), ("faults", ctypes.c_uint32)] + [
                    (name, ctypes.c_size_t) for name in (
                        "peak_rss", "rss", "peak_paged", "paged", "peak_nonpaged",
                        "nonpaged", "pagefile", "peak_pagefile")]
            self.counters = Counters
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetCurrentProcess.argtypes = []
            kernel.GetCurrentProcess.restype = ctypes.c_void_p
            self.handle = kernel.GetCurrentProcess()
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            self.get_info = psapi.GetProcessMemoryInfo
            self.get_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_uint32]
            self.get_info.restype = ctypes.c_int
        elif source == "linux-proc":
            if sys.platform != "linux":
                raise ValueError("linux-proc requires Linux; no alternate memory provider")
        else:
            raise ValueError(f"unknown memory source: {source!r}")

    def sample(self):
        if self.source == "windows-psapi":
            value = self.counters()
            value.cb = ctypes.sizeof(value)
            if not self.get_info(self.handle, ctypes.byref(value), value.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            return {"rss_bytes": value.rss, "process_peak_rss_bytes": value.peak_rss}
        text = Path("/proc/self/status").read_text(encoding="ascii")
        def field(name):
            match = re.search(rf"^{name}:\s+(\d+) kB$", text, re.MULTILINE)
            if match is None:
                raise ValueError(f"missing Linux process memory field {name}")
            return int(match[1]) * 1024
        return {"rss_bytes": field("VmRSS"), "process_peak_rss_bytes": field("VmHWM")}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(128 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprints(config):
    files = {}
    for feed, key, manifest in (
        ("bus", "bus_dir", "yokohama_bus_gtfs_manifest.json"),
        ("subway", "subway_dir", "yokohama_subway_gtfs_manifest.json"),
    ):
        root = Path(config[key])
        paths = sorted(root.glob("*.txt")) + [root / manifest]
        if len(paths) < 2:
            raise ValueError(f"missing GTFS inventory for {feed}")
        files.update({f"{feed}/{p.name}": sha256(p) for p in paths})
    files["bus/selected_coverage.json"] = sha256(Path(config["bus_coverage"]))
    return files


def load_inputs(config):
    stamp = config["manifest_date"]
    bus = load_yokohama_bus_dataset(config["bus_dir"], expected_service_date=stamp)
    bus_coverage = YokohamaFareCoverage.load(config["bus_coverage"], dataset=bus)
    subway = load_reviewed_yokohama_subway_coverage(config["subway_dir"], expected_service_date=stamp)
    # Query dates differ from the manifest's prior validation stamp. Neither
    # the stamp nor source bytes are changed to make another day loadable.
    manifests = [json.loads((Path(config[key]) / name).read_text(encoding="utf-8"))
                 for key, name in (("bus_dir", "yokohama_bus_gtfs_manifest.json"),
                                   ("subway_dir", "yokohama_subway_gtfs_manifest.json"))]
    feed_periods = []
    for key in ("bus_dir", "subway_dir"):
        with (Path(config[key]) / "feed_info.txt").open(encoding="utf-8-sig", newline="") as handle:
            records = list(csv.DictReader(handle))
        if len(records) != 1:
            raise ValueError("require exactly one feed_info record")
        period = []
        for field in ("feed_start_date", "feed_end_date"):
            value = records[0].get(field)
            if value in (None, ""):
                period.append(None)  # Optional source field, not a replacement date.
            else:
                parsed = datetime.strptime(value, "%Y%m%d").date()
                if parsed.strftime("%Y%m%d") != value:
                    raise ValueError(f"invalid feed_info {field}")
                period.append(parsed)
        feed_periods.append(period)
    for text in config["dates"]:
        day = parse_day(text)
        for raw in manifests:
            if not parse_day(raw["valid_from"]) <= day <= parse_day(raw["valid_until"]):
                raise ValueError(f"query date outside pinned edition validity: {text}")
        for first, last in feed_periods:
            if (first is not None and day < first) or (last is not None and day > last):
                raise ValueError(f"query date outside source feed_info period: {text}")
    return bus_coverage, subway


def select_cases(coverages, days, hours):
    cases = []
    for coverage in coverages:
        free = coverage.municipal_free_coverage()
        if free is None:
            raise ValueError("no approved municipal trips")
        dataset = free.dataset
        rows = defaultdict(list)
        for row in dataset.stop_times:
            for minute, seconds in ((row.arrival_minute, row.arrival_service_seconds),
                                    (row.departure_minute, row.departure_service_seconds)):
                if seconds is not None and (seconds % 60 or minute != seconds // 60):
                    raise ValueError(f"v1 comparison requires minute-aligned source: "
                                     f"{row.trip_id} sequence={row.sequence}")
            rows[row.trip_id].append(row)
        rows = {key: tuple(sorted(value, key=lambda r: r.sequence)) for key, value in rows.items()}
        for day in days:
            active = dataset.active_service_ids(day)
            candidates = []
            for trip_id, times in rows.items():
                if dataset.trips[trip_id].service_id not in active:
                    continue
                boardable = [r for r in times if r.pickup_type == 0 and r.departure_minute is not None]
                if not boardable:
                    continue
                start = boardable[0]
                destinations = [r for r in times if r.sequence > start.sequence
                    and r.stop_id != start.stop_id and r.drop_off_type == 0
                    and r.arrival_minute is not None
                    and 0 < r.arrival_minute - start.departure_minute <= 120]
                if destinations:
                    candidates.append((start.departure_minute, trip_id, start.stop_id,
                                       destinations[-1].stop_id))
            candidates.sort()
            for hour in hours:
                choices = [c for c in candidates if hour * 60 <= c[0] < (hour + 1) * 60]
                if not choices:
                    raise ValueError(f"no approved case: feed={dataset.metadata.feed_id} "
                                     f"date={day} hour={hour}")
                departure, _, origin, destination = choices[0]
                cases.append((dataset.metadata.feed_id, day, hour, departure, origin, destination))
    return cases


def leg_key(leg):
    return (leg.trip_id, leg.route_id, leg.from_stop_id, leg.to_stop_id,
            leg.departure_minute, leg.arrival_minute, leg.stop_ids)


def candidate_key(journey, mode):
    primary = ((journey.arrival_minute, journey.rides) if mode == "time"
               else (journey.rides, journey.arrival_minute))
    return primary, tuple(leg_key(e) for e in journey.events)


def validate_journey(journey, context, day, origin, destination, departure):
    if not journey.events or journey.events[0].from_stop_id != origin or journey.events[-1].to_stop_id != destination:
        raise AssertionError("selected journey has incorrect endpoints")
    previous, stop = departure, origin
    for leg in journey.events:
        if not isinstance(leg, NetworkRideEvent):
            raise AssertionError("walking is disabled for this probe")
        if leg.trip_id not in context.snapshot.allowed_trip_ids:
            raise AssertionError("unapproved selected trip")
        rows = context.snapshot.rows_by_trip[leg.trip_id]
        positions = {r.sequence: i for i, r in enumerate(rows)}
        first, last = positions[leg.from_sequence], positions[leg.to_sequence]
        trip = context.snapshot.trips[leg.trip_id]
        dataset = next(d for d in context.snapshot.datasets if leg.trip_id.startswith(d.metadata.feed_id + ":"))
        if (last <= first or trip.service_id not in dataset.active_service_ids(day)
                or rows[first].pickup_type != 0 or rows[last].drop_off_type != 0
                or leg.route_id != trip.route_id or leg.from_stop_id != stop
                or leg.departure_minute < previous
                or leg.stop_ids != tuple(r.stop_id for r in rows[first:last + 1])
                or leg.from_stop_id != rows[first].stop_id or leg.to_stop_id != rows[last].stop_id
                or leg.departure_minute != rows[first].departure_minute
                or leg.arrival_minute != rows[last].arrival_minute or leg.service_date != day):
            raise AssertionError("selected interval differs from active approved source occurrence")
        previous, stop = leg.arrival_minute, leg.to_stop_id
    if journey.arrival_minute != previous:
        raise AssertionError("selected final clock differs from last leg")


def run_cases(coverages, config, engine, memory):
    if engine not in ("v1", "shared_head", "shared"):
        raise ValueError("engine must be explicitly v1, shared_head or shared")
    days = tuple(parse_day(d) for d in config["dates"])
    selection_start = time.perf_counter()
    cases = select_cases(coverages, days, config["hours"])
    case_selection_seconds = time.perf_counter() - selection_start
    setup_start = time.perf_counter()
    cores, context = {}, None
    if engine == "v1":
        for coverage in coverages:
            selected = coverage.municipal_free_coverage().dataset
            cores[selected.metadata.feed_id] = PythonTransitSearchCore(selected)
    setup_seconds = time.perf_counter() - setup_start
    setup = [{"stage": "v1_indexes", "seconds": setup_seconds, **memory.sample()}] if engine == "v1" else []
    results = []
    for policy in POLICIES:
        if engine != "v1":
            setup_start = time.perf_counter()
            context = build_shared_municipal_network(*coverages, policy_id=policy,
                                                    walking_links=(), costs=NetworkCosts())
            setup.append({"stage": "shared_snapshot", "policy": policy,
                          "seconds": time.perf_counter() - setup_start,
                          "nodes": len(context.snapshot.graph),
                          "edges": context.snapshot.graph.number_of_edges(),
                          "allowed_trips": len(context.snapshot.allowed_trip_ids), **memory.sample()})
        for feed, day, hour, departure, origin, destination in cases:
            for mode, preference in (("time", "fastest"), ("fewTransfers", "fewest_transfers")):
                durations, expected, count = [], None, 0
                before = memory.sample()
                for repeat in range(config["repeats"]):
                    print(json.dumps({"probe_query": {"engine": engine, "policy": policy,
                        "feed": feed, "date": day.isoformat(), "hour": hour, "mode": mode,
                        "repeat": repeat + 1}}), file=sys.stderr, flush=True)
                    start = time.perf_counter()
                    if engine == "v1":
                        itinerary = cores[feed].search(BatchSearchRequest(day, departure,
                            (SearchEndpoint(origin),), (SearchEndpoint(destination),), preference,
                            max_rides=6)).pairs[0].itinerary
                        if itinerary is None:
                            raise AssertionError(f"active seeded OD unreachable: {feed} {day} {hour}")
                        journeys = [itinerary]
                        keys = [tuple(leg_key(e) for e in itinerary.legs)]
                    else:
                        journeys = search_shared_municipal_network(context, origin, destination,
                            service_date=day, departure_minute=departure, mode=mode,
                            parameters=NetworkSearchParameters(max_candidates=(
                                1 if engine == "shared_head" else config["max_candidates"]),
                                                               few_transfers_tiebreak="arrival"))
                        if not journeys:
                            raise AssertionError(f"active seeded OD unreachable: {feed} {day} {hour}")
                        keys = [tuple(leg_key(e) for e in j.events) for j in journeys]
                    durations.append(time.perf_counter() - start)
                    if engine != "v1":
                        for journey in journeys:
                            validate_journey(journey, context, day, origin, destination, departure)
                        ordering = [candidate_key(j, mode) for j in journeys]
                        if ordering != sorted(ordering):
                            raise AssertionError("shared candidate rank is not lexicographic objective order")
                        if len(set(ordering)) != len(ordering):
                            raise AssertionError("shared candidates contain duplicate selected intervals")
                    encoded = [{"arrival": str(j.arrival_minute), "rides": j.rides,
                                "legs": [[*k[:4], str(k[4]), str(k[5]), list(k[6])] for k in key]}
                               for j, key in zip(journeys, keys)]
                    if repeat == 0:
                        expected, count = encoded, len(journeys)
                    elif encoded != expected:
                        raise AssertionError("repeated query changed selected candidates or order")
                results.append({"case": [policy, feed, day.isoformat(), hour, mode],
                    "candidates": expected, "candidate_count": count,
                    "seconds": durations, "memory_before": before, "memory_after": memory.sample()})
        # Release the old context before measuring the next pass's construction.
        context = None
    return {"case_selection_seconds": case_selection_seconds, "setup": setup, "results": results}


def worker(config, engine):
    memory = ProcessMemory(config["memory_source"])
    start = time.perf_counter()
    before = fingerprints(config)
    hash_seconds = time.perf_counter() - start
    start = time.perf_counter()
    coverages = load_inputs(config)
    load_seconds = time.perf_counter() - start
    loaded_memory = memory.sample()
    # Routing debug output is kept separate from the worker's JSON protocol.
    with contextlib.redirect_stdout(sys.stderr):
        result = run_cases(coverages, config, engine, memory)
    after = fingerprints(config)
    if before != after:
        raise AssertionError("source files changed during worker execution")
    return {"engine": engine, "memory_source": config["memory_source"],
            "input_hashes": before, "versions": {c.dataset.metadata.feed_id: c.dataset.metadata.version for c in coverages},
            "hash_seconds_before": hash_seconds, "load_seconds": load_seconds,
            "loaded_memory": loaded_memory, "final_memory": memory.sample(), **result}


def compare_workers(old, new):
    if old["input_hashes"] != new["input_hashes"] or old["versions"] != new["versions"]:
        raise AssertionError("workers did not use identical source files/versions")
    if len(old["results"]) != len(new["results"]) or not old["results"]:
        raise AssertionError("worker comparison case count mismatch or empty")
    for a, b in zip(old["results"], new["results"]):
        if a["case"] != b["case"] or a["candidates"][0] != b["candidates"][0]:
            raise AssertionError("v1/shared head selection differs: " + json.dumps({"v1": a, "shared": b}))
    return {"comparisons": len(old["results"]), "selection_differences": 0,
            "shared_queries_with_multiple_candidates": sum(r["candidate_count"] > 1 for r in new["results"]),
            "walking_links": 0, "top_k_completeness_verified": False}


def run_worker(config, engine):
    started = time.perf_counter()
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", engine],
        input=json.dumps(config), text=True, encoding="utf-8", capture_output=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
    if result.returncode:
        sys.stderr.write(result.stderr)
        result.check_returncode()
    output = json.loads(result.stdout)
    output["subprocess_wall_seconds"] = time.perf_counter() - started
    return output


def emit_report(result):
    # Completed measurements remain available if a subsequent worker fails.
    # Only the final marker certifies the entire matrix, including source/SHA.
    print(json.dumps({k: v for k, v in result.items() if k != "results"}), flush=True)
    for row in result["results"]:
        print(json.dumps({"engine": result["engine"],
                          **{k: v for k, v in row.items() if k != "candidates"}}), flush=True)


def main():
    if sys.argv[1:2] == ["--worker"]:
        if len(sys.argv) != 3:
            raise ValueError("worker requires exactly one explicit engine")
        print(json.dumps(worker(json.load(sys.stdin), sys.argv[2])))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus-gtfs-dir", type=Path, required=True)
    parser.add_argument("--bus-coverage", type=Path, required=True)
    parser.add_argument("--subway-gtfs-dir", type=Path, required=True)
    parser.add_argument("--manifest-date", required=True)
    parser.add_argument("--query-date", action="append", required=True)
    parser.add_argument("--hour", type=int, action="append", required=True)
    parser.add_argument("--memory-source", choices=("windows-psapi", "linux-proc"), required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-candidates", type=int, default=3)
    args = parser.parse_args()
    parse_day(args.manifest_date)
    for day in args.query_date:
        parse_day(day)
    if (args.repeats < 2 or args.max_candidates < 2
            or len(set(args.query_date)) != len(args.query_date)
            or len(set(args.hour)) != len(args.hour) or any(not 0 <= h <= 23 for h in args.hour)):
        raise ValueError("require >=2 repeats/candidates, unique dates/hours and hours 0..23")
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is None:
        raise ValueError("expected-sha must be a full lowercase SHA")
    def git(*parts):
        return subprocess.run(["git", "-C", str(ROOT), *parts], check=True,
                              capture_output=True, text=True, encoding="utf-8").stdout.strip()
    actual = git("rev-parse", "HEAD")
    if git("branch", "--show-current") != "main" or actual != args.expected_sha or git("status", "--porcelain"):
        raise ValueError("require clean main at expected SHA; no stash/reset/pull is performed")
    config = {"bus_dir": str(args.bus_gtfs_dir.resolve()), "bus_coverage": str(args.bus_coverage.resolve()),
              "subway_dir": str(args.subway_gtfs_dir.resolve()), "manifest_date": args.manifest_date,
              "dates": args.query_date, "hours": args.hour, "memory_source": args.memory_source,
              "repeats": args.repeats, "max_candidates": args.max_candidates}
    print(json.dumps({"sha": actual, "python": sys.version, "executable": sys.executable,
                      "memory_source": args.memory_source, "dates": args.query_date,
                      "hours": args.hour, "repeats": args.repeats, "max_candidates": args.max_candidates}), flush=True)
    # Head-only performance and multiple-candidate validation are distinct
    # workloads, each with its own OS process-lifetime peak.
    old = run_worker(config, "v1")
    emit_report(old)
    head = run_worker(config, "shared_head")
    compare_workers(old, head)
    emit_report(head)
    new = run_worker(config, "shared")
    summary = compare_workers(old, new)
    if fingerprints(config) != new["input_hashes"]:
        raise AssertionError("source files changed after worker comparisons")
    if git("rev-parse", "HEAD") != actual or git("status", "--porcelain"):
        raise AssertionError("repository changed during comparison")
    emit_report(new)
    print(json.dumps(summary))
    print("READ_ONLY_SHARED_MATRIX_OK")


if __name__ == "__main__":
    main()
