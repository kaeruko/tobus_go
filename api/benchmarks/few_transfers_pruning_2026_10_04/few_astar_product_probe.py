"""Measure the shipped fewTransfers A* path without replacing its priority.

The reviewed RSS loader, route adapter and static GTFS identity pipeline are
reused. Bounds are wrapped only to copy diagnostics, and call the product
builder unchanged. Historical experimental measurements are never overwritten.
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
from few_astar_experiment import CASES, _replace_once

OUT = rss.OUT / "few_astar_product_2026_10_05"


@contextmanager
def record_bounds(reports):
    import tokyo_search_labels as labels

    builder = labels.make_bounds

    def measured(*args, **kwargs):
        bound = builder(*args, **kwargs)
        reports.append(bound.report)
        return bound

    labels.make_bounds = measured
    try:
        yield
    finally:
        labels.make_bounds = builder


def worker(args):
    OUT.mkdir(parents=True, exist_ok=True)
    reports = []
    source = inspect.getsource(rss.worker)
    source = _replace_once(source,
                           '    reference_path = OUT / f"implementation_{args.mode}_route.json"',
                           '    reference_path = _REFERENCE_PATH')
    source = _replace_once(source, '        result = payload = None\n        with Sampler',
                           '        result = payload = None\n'
                           '        _bound_start = len(_BOUND_REPORTS)\n        with Sampler')
    source = _replace_once(source, '        row["core_ms"] = sum(calls)',
                           '        row["core_ms"] = sum(calls)\n'
                           '        row["bounds"] = _BOUND_REPORTS[_bound_start:]')
    source = _replace_once(source,
                           'ROOT / "api/tokyo_timetable_choices.py", ROOT / "api/app/services/train_route_identity.py")',
                           'ROOT / "api/tokyo_timetable_choices.py", ROOT / "api/tokyo_few_transfers_bounds.py",\n'
                           '                  ROOT / "api/app/services/train_route_identity.py")')
    namespace = dict(rss.__dict__, OUT=OUT, CASES=CASES,
                     _REFERENCE_PATH=rss.OUT / f"implementation_{args.mode}_route.json",
                     _BOUND_REPORTS=reports)
    exec(compile(source, "<reviewed_RSS_probe_production_Astar>", "exec"), namespace)
    with record_bounds(reports):
        return namespace["worker"](args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--mode", choices=("fewTransfers", "cost", "time"), default="fewTransfers")
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
    selected_cases = ("baseline",) if args.baseline_only else tuple(CASES)
    pairs = [("fewTransfers", case) for case in selected_cases]
    pairs.extend((mode, "baseline") for mode in ("cost", "time"))
    report = {"scope": "Current product code, default fewTransfers A*; no priority clone, no cache, no budget increase. Current cost/time controls. Static Windows process RSS, no HTTP/live RT/Lambda.",
              "created_at_jst": dt.datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
              "compiled_bus_record_counts": manifest["record_counts"], "measurements": []}
    for mode, case in pairs:
        command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--worker", "--mode", mode,
                   "--case", case, "--repeats", str(args.repeats if case == "baseline" else 1)]
        completed = subprocess.run(command, cwd=rss.ROOT, capture_output=True, text=True, encoding="utf-8")
        if completed.returncode:
            print(completed.stdout, completed.stderr, flush=True)
            raise RuntimeError(f"Worker failed: {mode}/{case}")
        print(completed.stdout.strip(), flush=True)
        measured_path = OUT / f"rss_{mode}_{case}.json"
        measured = json.loads(measured_path.read_text(encoding="utf-8"))
        reference_path = (rss.OUT / "few_astar_2026_10_05" / "astar" / f"rss_{mode}_{case}_route.json"
                          if mode == "fewTransfers" else rss.OUT / f"rss_{mode}_{case}_route.json")
        current_path = OUT / f"rss_{mode}_{case}_route.json"
        if reference_path.exists() and current_path.exists() and not measured["runs"][0].get("error"):
            measured["same_as_preimplementation_payload_excluding_step_ids"] = (
                rss.normalized(json.loads(reference_path.read_text(encoding="utf-8")))
                == rss.normalized(json.loads(current_path.read_text(encoding="utf-8"))))
        report["measurements"].append(measured)
        rss.write_json(OUT / "results.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
