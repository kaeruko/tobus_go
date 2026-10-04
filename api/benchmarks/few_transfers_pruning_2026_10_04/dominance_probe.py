"""Synthetic, read-only probe of current fewTransfers label dominance.

Run from repository root using api/.venv-route/Scripts/python.exe -X utf8.
No application source is patched and no remote requests are made.
"""
from __future__ import annotations

import contextlib
from collections import defaultdict
import io
import json
import pickle
import sys
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "api"))
import toei_engine as te


class Timetable:
    def get_next_bus_departure(self, pole_id, route_id, current_time_min, **kwargs):
        departures = {"late-cheap": 20 * 60 + 55, "early-extra-stop": 20 * 60 + 41}
        departure = departures[route_id]
        return (departure, route_id) if current_time_min <= departure else (None, None)

    def get_next_train_arrival(self, current_sta, next_sta, current_time_min, **kwargs):
        # FIFO last train: both earlier labels can wait for this same service.
        return 20 * 60 + 55 if current_time_min <= 20 * 60 + 50 else None


def counterexample():
    graph = nx.DiGraph()
    start, merge, destination = [("phys", value) for value in ("start", "merge", "destination")]
    a0, a1 = [("line", value, "late-cheap") for value in ("start", "merge")]
    b0, b1, b2 = [("line", value, "early-extra-stop") for value in ("start", "middle", "merge")]
    r0, r1 = [("line", value, "rail") for value in ("merge", "destination")]
    for node in (start, merge, destination):
        graph.add_node(node, name=node[1])
    for node in (a0, a1, b0, b1, b2):
        graph.add_node(node, mode="bus", route_id=node[2], name=node[1])
    for node in (r0, r1):
        graph.add_node(node, mode="rail", name=node[1])
    for physical, line in ((start, a0), (start, b0), (merge, r0)):
        graph.add_edge(physical, line, etype="board", w=5.0)
    for left, right in ((a0, a1), (b0, b1), (b1, b2)):
        graph.add_edge(left, right, etype="ride", mode="bus", w=0.8)
    graph.add_edge(r0, r1, etype="ride", mode="rail", w=0.8)
    for line, physical in ((a1, merge), (b2, merge), (r1, destination)):
        graph.add_edge(line, physical, etype="alight", w=0.0)

    def run(candidate_graph):
        with contextlib.redirect_stdout(io.StringIO()):
            found = list(te.find_few_transfers_paths_generator(
                candidate_graph, Timetable(), start, destination,
                start_time_str="20:40", use_realtime=False,
            ))
        return found

    full_result = run(graph)
    early_graph = graph.copy()
    early_graph.remove_nodes_from((a0, a1))
    early_only_result = run(early_graph)
    return {
        "description": "Cheaper 1-stop bus reaches merge at 20:58:30; dearer 2-stop bus reaches it at 20:47. Only the latter catches the last train at 20:50.",
        "complete_graph_candidate_count": len(full_result),
        "after_removing_late_cheap_branch_candidate_count": len(early_only_result),
        "early_feasible_candidate": early_only_result,
        "full_graph_has_all_feasible_edges": True,
        "interpretation": "Scalar cost dominance discards the early feasible label even under this FIFO timetable.",
    }


def static_fifo_observations():
    """Record static adjacent train services whose arrival order reverses."""
    with contextlib.redirect_stdout(io.StringIO()):
        with (ROOT / "api/data/app_data.pkl").open("rb") as stream:
            timetable = pickle.load(stream)["TM"]
    groups = defaultdict(list)
    for kind, patterns in (
        ("weekday", timetable.train_patterns_weekday),
        ("weekend", timetable.train_patterns_weekend),
    ):
        for origin, rows in patterns.items():
            for row in rows:
                groups[(kind, origin, row["next_sta"])].append(row)
    reversals = []
    for (kind, origin, destination), rows in groups.items():
        ordered = sorted(rows, key=lambda row: row["dep"])
        for earlier, later in zip(ordered, ordered[1:]):
            if later["dep"] <= earlier["dep"] or later["arr"] >= earlier["arr"]:
                continue
            early_time = earlier["dep"]
            later_time = earlier["dep"] + 0.5
            day_type = "weekday" if kind == "weekday" else "holiday"
            reversals.append({
                "kind": kind, "origin": origin, "destination": destination,
                "earlier_service": earlier, "later_service": later,
                "early_input_min": early_time,
                "early_output_min": timetable.get_next_train_arrival(
                    origin, destination, early_time, day_type=day_type, use_realtime=False,
                ),
                "later_input_min": later_time,
                "later_output_min": timetable.get_next_train_arrival(
                    origin, destination, later_time, day_type=day_type, use_realtime=False,
                ),
            })
    return {"pair_count": len(groups), "adjacent_reversal_count": len(reversals), "examples": reversals}


if __name__ == "__main__":
    result = counterexample()
    assert result["complete_graph_candidate_count"] == 0
    assert result["after_removing_late_cheap_branch_candidate_count"] == 1
    result["static_fifo_check"] = static_fifo_observations()
    (Path(__file__).resolve().parent / "dominance_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
