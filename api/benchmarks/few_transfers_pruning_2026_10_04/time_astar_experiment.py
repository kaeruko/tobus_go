"""Offline earliest-arrival comparison: reverse time bound and boarding cache.

Production files, dominance, selected runs, exact walking resources and safety
budgets are unchanged. Only an audited in-memory copy of search_labels is
selected in isolated measurement workers. All measurements use static data.
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

OUT = rss.OUT / "time_experiment_2026_10_05"
CASES = {
    "shibuya_1014": {"target_date_str": "2026-10-05", "start_time": "10:14",
                     "blat": 35.658034, "blon": 139.701636},
    "shibuya_0741": {"target_date_str": "2026-10-05", "start_time": "07:41",
                     "blat": 35.658034, "blon": 139.701636},
    "previous_2040": {},
    "tokyo_toyosu": {"alat": 35.681236, "alon": 139.767125,
                     "blat": 35.6544, "blon": 139.7965, "start_time": "10:00"},
}
VARIANTS = ("baseline", "cache", "astar", "combined")


def _replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError("Product source no longer matches the time experiment adapter")
    return source.replace(old, new, 1)


def make_search_variant(variant, reports=None):
    import tokyo_search_labels as labels
    from time_astar_bounds import make_time_bounds
    from time_board_cache import install_board_cache

    if variant not in VARIANTS:
        raise ValueError(variant)
    if variant == "baseline":
        return labels.search_labels
    reports = [] if reports is None else reports

    def measured_bounds(*args, **kwargs):
        bound = make_time_bounds(*args, **kwargs)
        bound.report["kind"] = "time_bound"
        reports.append(bound.report)
        return bound

    def measured_cache(*args, **kwargs):
        report = install_board_cache(*args, **kwargs)
        report["kind"] = "boarding_cache"
        reports.append(report)
        return report

    source = inspect.getsource(labels.search_labels)
    source = _replace_once(source, "    cost_bound = None\n",
                           "    cost_bound = None\n"
                           "    _time_bound = _time_guard = None\n")
    source = _replace_once(source, "            return (label.time, label.cost, label.boardings)",
                           "            if _time_bound is not None:\n"
                           "                return (_time_guard(label.time, _time_bound(label.node)),\n"
                           "                        label.cost, label.boardings, label.time)\n"
                           "            return (label.time, label.cost, label.boardings)")
    source = _replace_once(source, '    if mode == "fewTransfers":\n        # Query-local:',
                           '    if mode == "time":\n'
                           '        if _TIME_VARIANT in ("cache", "combined"):\n'
                           '            _install_time_cache(choices, start_minute, check_deadline=check_deadline)\n'
                           '        if _TIME_VARIANT in ("astar", "combined"):\n'
                           '            _time_bound = _make_time_bound(graph, choices, target, virtual_connections,\n'
                           '                edge_uses_rail=edge_uses_rail, walk_speed=walk_speed,\n'
                           '                rail_boarding_minutes=rail_boarding_minutes, check_deadline=check_deadline)\n'
                           '            _time_bound.report["initial_bound_minutes"] = _time_bound(start)\n'
                           '            _time_guard = CostRoundingGuard(\n'
                           '                max_edge_cost=max(max_travel_min, _time_bound.report["max_edge_minutes"]),\n'
                           '                max_forward_steps=max_visited,\n'
                           '                max_reverse_steps=_time_bound.report["nodes"] + 1)\n'
                           '            _time_bound.report["rounding_guard_scope"] = "static prototype; product float-arrival contract requires separate RT audit"\n'
                           '            bounds = _time_bound\n'
                           '        check_deadline()\n'
                           '    if mode == "fewTransfers":\n        # Query-local:')
    namespace = dict(labels.__dict__, _TIME_VARIANT=variant,
                     _make_time_bound=measured_bounds, _install_time_cache=measured_cache)
    exec(compile(source, "<offline_time_priority_and_boarding_experiment>", "exec"), namespace)
    return namespace["search_labels"]


@contextmanager
def selected_variant(variant, reports):
    import tokyo_search_labels as labels
    original = labels.search_labels
    labels.search_labels = make_search_variant(variant, reports)
    try:
        yield
    finally:
        labels.search_labels = original


def worker(args):
    destination = OUT / args.variant
    destination.mkdir(parents=True, exist_ok=True)
    reports = []
    request = {**rss.BASE, **CASES[args.case], "pref": "time"}
    source = inspect.getsource(rss.worker)
    source = _replace_once(source, '    active = calendar.active_trip_ids(dt.date(2026, 10, 4))',
                           '    active = calendar.active_trip_ids(dt.date.fromisoformat(_REQUEST_DATE))')
    source = _replace_once(source,
                           '    reference_path = OUT / f"implementation_{args.mode}_route.json"\n'
                           '    reference = normalized(json.loads(reference_path.read_text(encoding="utf-8")))',
                           '    reference = {}')
    source = _replace_once(source,
                           '        result = payload = None\n        with Sampler',
                           '        result = payload = None\n'
                           '        _reports_start = len(_TIME_REPORTS)\n        with Sampler')
    source = _replace_once(source,
                           '                row["same_as_previous_baseline_excluding_step_ids"] = comparable_payload == reference if args.case == "baseline" else None',
                           '                row["same_as_previous_baseline_excluding_step_ids"] = None')
    source = _replace_once(source, '        row["core_ms"] = sum(calls)',
                           '        row["core_ms"] = sum(calls)\n'
                           '        row["experiment_reports"] = _TIME_REPORTS[_reports_start:]\n'
                           '        _arrival = re.search(r"fastest search raw result: arr_min=([0-9.]+)", log.getvalue())\n'
                           '        row["raw_arrival_minute"] = float(_arrival.group(1)) if _arrival else None')
    source = _replace_once(source, '            row["arrivals"] = [candidate["arrival_time"] for candidate in result["candidates"]]',
                           '            row["arrivals"] = [candidate["arrival_time"] for candidate in result["candidates"]]\n'
                           '            if iteration == 0:\n'
                           '                write_json(OUT / f"rss_{args.mode}_{args.case}_verified_route.json", result)')
    source = _replace_once(source, '    output = OUT / f"rss_{args.mode}_{args.case}.json"',
                           '    report["variant"] = _VARIANT\n'
                           '    report["experiment_sha256"] = {path.name: sha(path) for path in _EXPERIMENT_FILES}\n'
                           '    output = OUT / f"rss_{args.mode}_{args.case}.json"')
    namespace = dict(rss.__dict__, OUT=destination, CASES=CASES,
                     _REQUEST_DATE=request["target_date_str"], _TIME_REPORTS=reports,
                     _VARIANT=args.variant, _EXPERIMENT_FILES=[
                         Path(__file__), Path(__file__).with_name("time_astar_bounds.py"),
                         Path(__file__).with_name("time_board_cache.py"),
                     ])
    exec(compile(source, "<reviewed_RSS_pipeline_time_experiment>", "exec"), namespace)
    with selected_variant(args.variant, reports):
        return namespace["worker"](SimpleNamespace(mode="time", case=args.case, repeats=args.repeats))


def _comparison(case, variant):
    def payload(name):
        path = OUT / name / f"rss_time_{case}_verified_route.json"
        return rss.normalized(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None
    first, second = payload("baseline"), payload(variant)
    if first is None or second is None:
        return None
    return {"same_full_verified_payload_except_step_ids": first == second,
            "same_arrival_times": [c["arrival_time"] for c in first["candidates"]]
            == [c["arrival_time"] for c in second["candidates"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--variant", choices=VARIANTS, default="combined")
    parser.add_argument("--case", choices=tuple(CASES), default="shibuya_1014")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--single-case", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    if args.worker:
        return worker(args)
    manifest = rss.prepare()
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"scope": "Offline time-only prototype; current product baseline vs query board cache, static reverse-time A*, and both. Exact resources/dominance/runs/budgets unchanged; sequential fresh Windows processes; no HTTP/live RT/Lambda.",
              "created_at_jst": dt.datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
              "compiled_bus_record_counts": manifest["record_counts"], "measurements": []}
    selected_cases = (args.case,) if args.single_case else tuple(CASES)
    for case in selected_cases:
        for variant in VARIANTS:
            command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
                       "--worker", "--variant", variant, "--case", case,
                       "--repeats", str(args.repeats)]
            completed = subprocess.run(command, cwd=rss.ROOT, capture_output=True, text=True, encoding="utf-8")
            if completed.returncode:
                print(completed.stdout, completed.stderr, flush=True)
                raise RuntimeError(f"Worker failed: {variant}/{case}")
            print(variant, completed.stdout.strip(), flush=True)
            measured = json.loads((OUT / variant / f"rss_time_{case}.json").read_text(encoding="utf-8"))
            measured["baseline_comparison"] = _comparison(case, variant)
            report["measurements"].append(measured)
            rss.write_json(OUT / "results.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
