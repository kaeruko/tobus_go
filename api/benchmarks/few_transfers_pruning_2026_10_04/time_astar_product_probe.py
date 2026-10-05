"""Measure production time A*, including static-index warmup and fixed RT.

Reuse the reviewed RSS loader/adapter/identity pipeline. No search priority or
budget is replaced. Frozen delays are synthetic and never fetched from APIs.
Historical experiment results are read-only references.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import inspect
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import rss_probe as rss
from time_astar_experiment import CASES as STATIC_CASES, _replace_once

OUT = rss.OUT / "time_astar_product_2026_10_05"
CASES = dict(STATIC_CASES,
             shibuya_rt_1014=dict(STATIC_CASES["shibuya_1014"]))


@contextmanager
def record_bounds(reports):
    import tokyo_search_labels as labels
    builder = labels.make_time_bounds

    def measured(*args, **kwargs):
        bound = builder(*args, **kwargs)
        reports.append(bound.report)
        return bound

    labels.make_time_bounds = measured
    try:
        yield
    finally:
        labels.make_time_bounds = builder


def _configure_rt(data, case):
    if case != "shibuya_rt_1014":
        return
    manager = data["TM"]
    manager.realtime_delays = {
        str(record.get("train_num") or ""): 18.0
        for records in manager.train_patterns_weekday.values() for record in records
    }
    # Product delay lookup uses ODPT route identities, not GTFS route IDs.
    manager.bus_realtime_delays = {
        "odpt.Busroute:Toei.Nishiki37": 0.3,
        "odpt.Busroute:Toei.T01": 0.3,
    }
    manager.train_status_text = {}
    manager.train_service_suspended = set()


def worker(args):
    OUT.mkdir(parents=True, exist_ok=True)
    reports = []
    body = {**rss.BASE, **CASES[args.case], "pref": args.mode}
    source = inspect.getsource(rss.worker)
    source = _replace_once(source, '    active = calendar.active_trip_ids(dt.date(2026, 10, 4))',
                           '    active = calendar.active_trip_ids(dt.date.fromisoformat(_REQUEST_DATE))')
    source = _replace_once(source, '    phases["after_compiled_bus_gtfs_load"] = read()',
                           '    phases["after_compiled_bus_gtfs_load"] = read()\n'
                           '    _CONFIGURE_RT(data, args.case)\n'
                           '    from tokyo_time_bounds import prepare_static_time_index\n'
                           '    _index_started = time.perf_counter()\n'
                           '    prepare_static_time_index(data["TM"], te.gtfs_repo)\n'
                           '    _index_build_ms = (time.perf_counter() - _index_started) * 1000\n'
                           '    phases["after_time_interval_index"] = read()')
    source = _replace_once(source,
                           'now=lambda: dt.datetime(2026, 10, 4, 18, 40, tzinfo=ZoneInfo("Asia/Tokyo")),',
                           'now=lambda: _FIXED_NOW,')
    source = _replace_once(source,
                           '    reference_path = OUT / f"implementation_{args.mode}_route.json"\n'
                           '    reference = normalized(json.loads(reference_path.read_text(encoding="utf-8")))',
                           '    reference = {}')
    source = _replace_once(source, '        result = payload = None\n        with Sampler',
                           '        result = payload = None\n'
                           '        _bound_start = len(_BOUND_REPORTS)\n        with Sampler')
    source = _replace_once(source,
                           '                row["same_as_previous_baseline_excluding_step_ids"] = comparable_payload == reference if args.case == "baseline" else None',
                           '                row["same_as_previous_baseline_excluding_step_ids"] = None')
    source = _replace_once(source, '        row["core_ms"] = sum(calls)',
                           '        row["core_ms"] = sum(calls)\n'
                           '        row["bounds"] = _BOUND_REPORTS[_bound_start:]\n'
                           '        _arrival = re.search(r"fastest search raw result: arr_min=([0-9.]+)", log.getvalue())\n'
                           '        row["raw_arrival_minute"] = float(_arrival.group(1)) if _arrival else None')
    source = _replace_once(source, '            row["arrivals"] = [candidate["arrival_time"] for candidate in result["candidates"]]',
                           '            row["arrivals"] = [candidate["arrival_time"] for candidate in result["candidates"]]\n'
                           '            if iteration == 0:\n'
                           '                write_json(OUT / f"rss_{args.mode}_{args.case}_verified_route.json", result)')
    source = _replace_once(source,
                           'ROOT / "api/tokyo_timetable_choices.py", ROOT / "api/app/services/train_route_identity.py")',
                           'ROOT / "api/tokyo_timetable_choices.py", ROOT / "api/tokyo_time_bounds.py",\n'
                           '                  ROOT / "api/tokyo_time_rounding.py", ROOT / "api/tokyo_few_transfers_bounds.py",\n'
                           '                  ROOT / "api/app/services/train_route_identity.py")')
    source = _replace_once(source, '    output = OUT / f"rss_{args.mode}_{args.case}.json"',
                           '    report["static_interval_index_build_ms"] = _index_build_ms\n'
                           '    report["realtime_snapshot"] = _RT_SCOPE\n'
                           '    output = OUT / f"rss_{args.mode}_{args.case}.json"')
    fixed_now = (dt.datetime.fromisoformat(body["target_date_str"] + "T" + body["start_time"])
                 .replace(tzinfo=ZoneInfo("Asia/Tokyo")) if args.case == "shibuya_rt_1014" else
                 dt.datetime(2026, 10, 4, 18, 40, tzinfo=ZoneInfo("Asia/Tokyo")))
    namespace = dict(rss.__dict__, OUT=OUT, CASES=CASES,
                     _REQUEST_DATE=body["target_date_str"], _BOUND_REPORTS=reports,
                     _CONFIGURE_RT=_configure_rt, _FIXED_NOW=fixed_now,
                     _RT_SCOPE=("synthetic frozen rail +18s and ODPT Nishiki37/T01 +0.3min"
                                if args.case == "shibuya_rt_1014" else "static; realtime disabled"))
    exec(compile(source, "<reviewed_RSS_pipeline_production_time_Astar>", "exec"), namespace)
    with record_bounds(reports):
        return namespace["worker"](args)


def _compare(mode, case):
    if mode == "time":
        reference = (rss.OUT / "time_experiment_2026_10_05/astar"
                     / f"rss_time_{case}_verified_route.json")
    else:
        reference = rss.OUT / "few_astar_product_2026_10_05" / f"rss_{mode}_baseline_route.json"
    suffix = "_verified_route.json" if mode == "time" else "_route.json"
    current = OUT / f"rss_{mode}_{case}{suffix}"
    if not reference.exists() or not current.exists():
        return None
    first = rss.normalized(json.loads(reference.read_text(encoding="utf-8")))
    second = rss.normalized(json.loads(current.read_text(encoding="utf-8")))
    return {"reference": str(reference.relative_to(rss.OUT)),
            "same_full_payload_except_step_ids": first == second}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--mode", choices=("time", "cost", "fewTransfers"), default="time")
    parser.add_argument("--case", choices=tuple(CASES), default="shibuya_1014")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--single-case", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    if args.worker:
        return worker(args)
    manifest = rss.prepare()
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"scope": "Production time A*: static interval index at data warmup; destination bound query-local. No priority clone/budget increase/HTTP/live RT/Lambda.",
              "created_at_jst": dt.datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
              "compiled_bus_record_counts": manifest["record_counts"], "measurements": []}
    pairs = [(args.mode, args.case)] if args.single_case else [
        *(("time", case) for case in CASES),
        ("cost", "previous_2040"), ("fewTransfers", "previous_2040"),
    ]
    for mode, case in pairs:
        repeats = args.repeats if mode == "time" and case == "shibuya_1014" else 1
        command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
                   "--worker", "--mode", mode, "--case", case, "--repeats", str(repeats)]
        completed = subprocess.run(command, cwd=rss.ROOT, capture_output=True,
                                   text=True, encoding="utf-8")
        if completed.returncode:
            print(completed.stdout, completed.stderr, flush=True)
            raise RuntimeError(f"Worker failed: {mode}/{case}")
        print(completed.stdout.strip(), flush=True)
        measured = json.loads((OUT / f"rss_{mode}_{case}.json").read_text(encoding="utf-8"))
        measured["comparison"] = _compare(mode, case)
        report["measurements"].append(measured)
        rss.write_json(OUT / "results.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
