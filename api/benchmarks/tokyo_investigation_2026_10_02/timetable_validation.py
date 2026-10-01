"""Lightweight equivalence checks for Tokyo train timetable indexing.

Run with Python from any directory. Production files are read but not modified.
Only the required TimetableManager methods are loaded, avoiding API startup.
This validates lookup semantics; it is not a performance benchmark.
"""

from __future__ import annotations

import ast
import bisect
import json
from collections import defaultdict
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2] / "toei_engine.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"), filename=str(SOURCE))
manager_node = next(
    node for node in tree.body
    if isinstance(node, ast.ClassDef) and node.name == "TimetableManager"
)
methods = {"__init__", "_guess_railway_id", "get_next_train_arrival"}
manager_node.body = [
    node for node in manager_node.body
    if isinstance(node, ast.FunctionDef) and node.name in methods
]
namespace = {"defaultdict": defaultdict}
exec(compile(ast.Module(body=[manager_node], type_ignores=[]), str(SOURCE), "exec"), namespace)
TimetableManager = namespace["TimetableManager"]


def build_index(manager):
    result = {}
    for day, timetable in (
        ("weekday", manager.train_patterns_weekday),
        ("weekend", manager.train_patterns_weekend),
    ):
        for station, rows in timetable.items():
            for row in rows:
                result.setdefault((day, station, row["next_sta"]), []).append(row)
    # Preserve each row's position relative to equal-departure rows.
    return {
        key: (rows, [row["dep"] for row in rows])
        for key, rows in result.items()
    }


def grouped_lookup(manager, index, current_sta, next_sta, minute,
                   day_type="weekday", delays_snapshot=None, use_realtime=True):
    railway = manager._guess_railway_id(current_sta)
    if use_realtime and railway in manager.train_service_suspended:
        return None
    day = "weekday" if day_type == "weekday" else "weekend"
    rows, departures = index.get((day, current_sta, next_sta), ([], []))
    if not use_realtime:
        position = bisect.bisect_left(departures, minute)
        return rows[position]["arr"] + 0.0 if position < len(rows) else None

    # Adjusted departures may be unsorted. Preserve the original base-time order.
    delays = delays_snapshot if delays_snapshot is not None else manager.realtime_delays
    penalty = 10.0 if railway and "遅延" in manager.train_status_text.get(railway, "") else 0.0
    for row in rows:
        delay = delays.get(row["train_num"], 0) / 60.0
        if delay == 0 and penalty > 0:
            delay = penalty
        if row["dep"] + delay >= minute:
            return row["arr"] + delay
    return None


def main():
    station = "odpt.Station:Toei.Asakusa.A"
    b = "odpt.Station:Toei.Asakusa.B"
    c = "odpt.Station:Toei.Asakusa.C"
    railway = "odpt.Railway:Toei.Asakusa"
    manager = TimetableManager()
    # Sorted as in load_train_timetables; ties intentionally have different arrivals.
    weekday = [
        {"dep": 0, "arr": 2, "next_sta": b, "train_num": "midnight"},
        {"dep": 600, "arr": 605, "next_sta": c, "train_num": "opposite"},
        {"dep": 600, "arr": 608, "next_sta": b, "train_num": "T1"},
        {"dep": 600, "arr": 609, "next_sta": b, "train_num": "T2"},
        {"dep": 610, "arr": 617, "next_sta": b, "train_num": "T3"},
        {"dep": 1450, "arr": 1455, "next_sta": b, "train_num": "late"},
    ]
    manager.train_patterns_weekday = {station: weekday}
    manager.train_patterns_weekend = {station: [dict(row, dep=row["dep"] + 3, arr=row["arr"] + 3) for row in weekday]}
    index = build_index(manager)
    checked = 0
    scenarios = (
        ("normal", {}, {}, set()),
        ("numeric_delay_and_order_reversal", {"T1": 1200, "T2": 30, "T3": 60}, {}, set()),
        ("status_delay_fallback", {"T1": 120}, {railway: "遅延しています"}, set()),
        ("suspended", {"T1": 1200}, {railway: "運転見合わせ"}, {railway}),
    )
    for scenario, delays, status, suspended in scenarios:
        manager.realtime_delays = delays
        manager.train_status_text = status
        manager.train_service_suspended = suspended
        for source_station in (station, "missing-station"):
            for destination in (b, c, "missing-next-station"):
                for day in ("weekday", "saturday", "holiday"):
                    for realtime in (False, True):
                        for snapshot in (None, {}, dict(delays)):
                            for minute in (-1, 0, 0.5, 599.5, 600, 600.1, 610, 610.5, 620, 1450, 1450.1, 1500):
                                kwargs = dict(day_type=day, delays_snapshot=snapshot, use_realtime=realtime)
                                original = manager.get_next_train_arrival(source_station, destination, minute, **kwargs)
                                optimized = grouped_lookup(manager, index, source_station, destination, minute, **kwargs)
                                assert original == optimized, (scenario, source_station, destination, minute, kwargs, original, optimized)
                                checked += 1

    # Counterexample: base-time bisect skips a train delayed into the boarding window.
    manager.train_patterns_weekday = {station: [
        {"dep": 600, "arr": 605, "next_sta": b, "train_num": "delayed"},
        {"dep": 610, "arr": 615, "next_sta": b, "train_num": "on-time"},
    ]}
    manager.realtime_delays = {"delayed": 1200}
    manager.train_status_text = {}
    manager.train_service_suspended = set()
    original = manager.get_next_train_arrival(station, b, 615, use_realtime=True)
    skipped_position = bisect.bisect_left([600, 610], 615)
    incorrect_base_bisect = None if skipped_position == 2 else "unexpected"
    assert original == 625.0 and incorrect_base_bisect is None
    # Sorting adjusted departures also changes today's base-order-first policy.
    existing_order_result = manager.get_next_train_arrival(station, b, 590, use_realtime=True)
    actual_order_first_arrival = 615.0
    assert existing_order_result == 625.0 and existing_order_result != actual_order_first_arrival
    print(json.dumps({
        "equivalence_checks": checked,
        "mismatches": 0,
        "validated": ["stable station-and-next-station grouping", "static bisect including departure ties", "numeric delays", "status fallback", "suspension", "weekday and weekend", "fractional minutes", "midnight and after-midnight", "empty snapshot", "missing station"],
        "unsafe_realtime_base_bisect": {"minute": 615, "original": original, "base_bisect": incorrect_base_bisect},
        "unsafe_realtime_actual_sort": {"minute": 590, "original": existing_order_result, "actual_sort": actual_order_first_arrival},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
