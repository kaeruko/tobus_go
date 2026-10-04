"""Offline fewTransfers-only A* comparison against current Tokyo labels.

Product files remain unchanged. Only the fewTransfers heap priority is replaced
in a checked in-memory copy. Dominance, exact resources, run selection, queue
compaction and all safety budgets are the current production implementation.
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

OUT = rss.OUT / "few_astar_2026_10_05"
CASES = dict(rss.CASES)
CASES.update({
    "tokyo_toyosu": {"alat": 35.681236, "alon": 139.767125,
                     "blat": 35.6544, "blon": 139.7965, "start_time": "10:00"},
    "shinjuku_asakusa": {"alat": 35.690921, "alon": 139.700258,
                        "blat": 35.71165, "blon": 139.79662, "start_time": "10:00"},
    "tokyo_toyosu_bus_only": {"alat": 35.681236, "alon": 139.767125,
                              "blat": 35.6544, "blon": 139.7965,
                              "start_time": "10:00", "bus_only": True},
})


def _replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError("Current search source no longer matches experiment adapter")
    return source.replace(old, new, 1)


def make_search_variant(reports=None):
    import tokyo_search_labels as labels
    from few_astar_bounds import make_bounds

    reports = [] if reports is None else reports

    def measured_bounds(*args, **kwargs):
        bound = make_bounds(*args, **kwargs)
        reports.append(bound.report)
        return bound

    source = inspect.getsource(labels.search_labels)
    source = _replace_once(source, "    started = time.monotonic()\n",
                           "    started = time.monotonic()\n"
                           "    _bound = (_make_experiment_bounds(graph, target, virtual_connections,\n"
                           "        edge_uses_rail=edge_uses_rail, max_segment_walk=max_segment_walk)\n"
                           "        if mode == 'fewTransfers' else None)\n"
                           "    if _bound is not None:\n"
                           "        _bound.report['initial_bound'] = list(_bound(start, 0.0))\n")
    source = _replace_once(source,
                           "            return (label.boardings, label.cost, label.time)",
                           "            hb, hc = _bound(label.node, label.segment_walk)\n"
                           "            return (label.boardings + hb, label.cost + hc,\n"
                           "                    label.boardings, label.cost, label.time)")
    namespace = dict(labels.__dict__, _make_experiment_bounds=measured_bounds)
    exec(compile(source, "<fewTransfers_astar_priority_experiment>", "exec"), namespace)
    return namespace["search_labels"]


@contextmanager
def selected_variant(variant, reports):
    import tokyo_search_labels as labels

    original = labels.search_labels
    if variant == "astar":
        labels.search_labels = make_search_variant(reports)
    elif variant != "baseline":
        raise ValueError(variant)
    try:
        yield
    finally:
        labels.search_labels = original


def worker(args):
    OUT.mkdir(parents=True, exist_ok=True)
    destination = OUT / args.variant
    destination.mkdir(parents=True, exist_ok=True)
    bounds_reports = []
    # Reuse the reviewed RSS data loading, adapter, details, static GTFS
    # identity and memory counters. Keep this experiment's files separate.
    source = inspect.getsource(rss.worker)
    source = _replace_once(source,
                           '    reference_path = OUT / f"implementation_{args.mode}_route.json"',
                           '    reference_path = _REFERENCE_PATH')
    source = _replace_once(source,
                           '        result = payload = None\n        with Sampler',
                           '        result = payload = None\n'
                           '        _bound_start = len(_BOUND_REPORTS)\n        with Sampler')
    source = _replace_once(source, '        row["core_ms"] = sum(calls)',
                           '        row["core_ms"] = sum(calls)\n'
                           '        row["bounds"] = _BOUND_REPORTS[_bound_start:]')
    source = _replace_once(source, '    output = OUT / f"rss_{args.mode}_{args.case}.json"',
                           '    report["variant"] = _VARIANT\n'
                           '    report["experiment_sha256"] = {path.name: sha(path) for path in _EXPERIMENT_FILES}\n'
                           '    output = OUT / f"rss_{args.mode}_{args.case}.json"')
    namespace = dict(rss.__dict__, OUT=destination, CASES=CASES,
                     _REFERENCE_PATH=rss.OUT / "implementation_fewTransfers_route.json",
                     _BOUND_REPORTS=bounds_reports, _VARIANT=args.variant,
                     _EXPERIMENT_FILES=[Path(__file__), Path(__file__).with_name("few_astar_bounds.py")])
    exec(compile(source, "<reviewed_RSS_probe_fewTransfers_experiment>", "exec"), namespace)
    with selected_variant(args.variant, bounds_reports):
        return namespace["worker"](SimpleNamespace(mode="fewTransfers", case=args.case, repeats=args.repeats))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--variant", choices=("baseline", "astar"), default="astar")
    parser.add_argument("--case", choices=tuple(CASES), default="baseline")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--baseline-only", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    if args.worker:
        return worker(args)
    manifest = rss.prepare()
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"scope": "Offline fewTransfers only. Current product search vs priority-only A*. Uncached bounds in every query, no pruning or budget increases, no HTTP/live RT/Lambda.",
              "created_at_jst": dt.datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
              "compiled_bus_record_counts": manifest["record_counts"], "cases": []}
    selected_cases = ("baseline",) if args.baseline_only else tuple(CASES)
    for case in selected_cases:
        row = {"case": case}
        for variant in ("baseline", "astar"):
            command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
                       "--worker", "--variant", variant, "--case", case,
                       "--repeats", str(args.repeats if case == "baseline" else 1)]
            completed = subprocess.run(command, cwd=rss.ROOT, capture_output=True, text=True, encoding="utf-8")
            if completed.returncode:
                print(completed.stdout, completed.stderr, flush=True)
                raise RuntimeError(f"Worker failed: {variant}/{case}")
            print(variant, completed.stdout.strip(), flush=True)
            row[variant] = json.loads((OUT / variant / f"rss_fewTransfers_{case}.json").read_text(encoding="utf-8"))
        route_paths = [OUT / variant / f"rss_fewTransfers_{case}_route.json" for variant in ("baseline", "astar")]
        if all(path.exists() for path in route_paths):
            row["same_full_payload_excluding_step_ids"] = (
                rss.normalized(json.loads(route_paths[0].read_text(encoding="utf-8")))
                == rss.normalized(json.loads(route_paths[1].read_text(encoding="utf-8"))))
        report["cases"].append(row)
        rss.write_json(OUT / "results.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
