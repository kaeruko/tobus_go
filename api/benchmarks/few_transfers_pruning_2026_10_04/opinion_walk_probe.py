"""Read-only probes of existing fewTransfers scalar dominance and walk limits.

All walk weights follow the current production formula; boarding and ride
weights use the production constants. Only synthetic local graph data is used.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "api"))
import toei_engine as te


class Timetable:
    def get_next_bus_departure(self, pole_id, route_id, current_time_min, **kwargs):
        # Both five-boarding branches reach their last service before 21:50.
        # They then reach the shared node at exactly the same time.
        if route_id.endswith("-4"):
            departure = 21 * 60 + 50
            return (departure, route_id) if current_time_min <= departure else (None, None)
        return current_time_min, route_id


def physical(graph, name):
    node = ("phys", name)
    graph.add_node(node, name=name)
    return node


def walk(graph, left, right, meters):
    graph.add_edge(left, right, etype="walk", meters=meters,
                   w=te.WALK_COST * max(1.0, meters / te.WALK_SPEED_M_PER_MIN))


def add_total_branch(graph, start, merge, name, walk_m, extra_rides):
    current = start
    branch_nodes = []
    for segment in range(5):
        midpoint = physical(graph, f"{name}-walk-{segment}-mid")
        board_at = physical(graph, f"{name}-walk-{segment}-end")
        branch_nodes.extend((midpoint, board_at))
        walk(graph, current, midpoint, walk_m / 10)
        walk(graph, midpoint, board_at, walk_m / 10)
        route = f"{name}-{segment}"
        previous = ("line", f"{name}-ride-{segment}-0", route)
        graph.add_node(previous, name=previous[1], mode="bus", route_id=route)
        branch_nodes.append(previous)
        graph.add_edge(board_at, previous, etype="board", w=te.TRANSFER_PENALTY)
        ride_edges = 1 + (extra_rides if segment == 0 else 0)
        for ride_index in range(ride_edges):
            following = ("line", f"{name}-ride-{segment}-{ride_index + 1}", route)
            graph.add_node(following, name=following[1], mode="bus", route_id=route)
            branch_nodes.append(following)
            graph.add_edge(previous, following, etype="ride", mode="bus", w=te.BUS_RIDE_COST)
            previous = following
        current = merge if segment == 4 else physical(graph, f"{name}-alight-{segment}")
        if current != merge:
            branch_nodes.append(current)
        graph.add_edge(previous, current, etype="alight", w=0.0)
    return branch_nodes


def enumerate_paths(graph, start, destination):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        paths = list(te.find_few_transfers_paths_generator(
            graph, Timetable(), start, destination, start_time_str="20:40",
            use_realtime=False, time_limit_sec=10.0,
        ))
    return paths, output.getvalue().splitlines()


def prefix_state(graph, path):
    current_time = te.time_str_to_min("20:40")
    total_walk = seg_walk = cost = 0.0
    boardings = 0
    for left, right in zip(path, path[1:]):
        edge = graph[left][right]
        cost += edge["w"]
        if edge["etype"] == "walk":
            total_walk += edge["meters"]
            seg_walk += edge["meters"]
        else:
            seg_walk = 0.0
        boardings += edge["etype"] == "board"
        current_time = te.advance_time(graph, Timetable(), left, right, current_time,
                                       use_realtime=False, edge=edge)
    return {"cost": cost, "arrival_time_min": current_time,
            "total_walk_m": total_walk, "seg_walk_m": seg_walk,
            "walk_bucket": int(seg_walk // 25), "boardings": boardings}


def inspect_counterexample(graph, start, merge, destination, removed_nodes):
    full_paths, full_trace = enumerate_paths(graph, start, destination)
    reduced = graph.copy()
    reduced.remove_nodes_from(removed_nodes)
    reduced_paths, reduced_trace = enumerate_paths(reduced, start, destination)
    prefix_states = [prefix_state(graph, path) for path in nx.all_simple_paths(graph, start, merge)]
    assert len(full_paths) == 0, full_paths
    assert len(reduced_paths) == 1, reduced_paths
    return {"prefix_states_at_merge": prefix_states,
            "full_graph_candidate_count": len(full_paths),
            "after_removing_cheap_branch_candidate_count": len(reduced_paths),
            "surviving_candidate": reduced_paths[0],
            "full_graph_trace": full_trace, "reduced_graph_trace": reduced_trace}


def total_walk_counterexample():
    graph = nx.DiGraph()
    start, merge, destination = [physical(graph, node) for node in ("start", "merge", "destination")]
    removed_nodes = add_total_branch(graph, start, merge, "cheap-long", 2600, 0)
    add_total_branch(graph, start, merge, "dearer-short", 2300, 8)
    walk(graph, merge, destination, 500)
    result = inspect_counterexample(graph, start, merge, destination, removed_nodes)
    cheap, short = result["prefix_states_at_merge"]
    assert cheap["cost"] < short["cost"]
    assert cheap["arrival_time_min"] == short["arrival_time_min"]
    assert cheap["boardings"] == short["boardings"] == 5
    assert cheap["seg_walk_m"] == short["seg_walk_m"] == 0
    result.update({"description": "Equal arrival time, boardings and consecutive walk at merge. Lower-cost 2600 m label cannot walk the final 500 m; 2300 m label can.",
                   "final_walk_m": 500,
                   "complete_total_walk_m": [3100, 2800],
                   "violated_constraint": "total_walk_m > 3000 for cheap branch only"})
    return result


def segment_bucket_counterexample():
    graph = nx.DiGraph()
    start, merge, destination = [physical(graph, node) for node in ("start", "merge", "destination")]
    removed_nodes = []
    for name, lengths in (("cheap-long", (199, 200, 200)), ("dearer-short", (40, 268, 268))):
        current = start
        for index, distance in enumerate(lengths):
            following = merge if index == 2 else physical(graph, f"{name}-{index}")
            if name == "cheap-long" and following != merge:
                removed_nodes.append(following)
            walk(graph, current, following, distance)
            current = following
    walk(graph, merge, destination, 10)
    result = inspect_counterexample(graph, start, merge, destination, removed_nodes)
    cheap, short = result["prefix_states_at_merge"]
    assert cheap["cost"] < short["cost"]
    assert cheap["walk_bucket"] == short["walk_bucket"] == 23
    result.update({"description": "599 m and 576 m share bucket 23. The short branch costs slightly more because its first 40 m walk has the production minimum one-minute cost. Only it can walk the final 10 m.",
                   "final_walk_m": 10,
                   "complete_seg_walk_m": [609, 586],
                   "violated_constraint": "seg_walk_m > 600 for cheap branch only"})
    return result


if __name__ == "__main__":
    result = {
        "production_limits": {"MAX_TOTAL_WALK_M": te.MAX_TOTAL_WALK_M,
                              "MAX_WALK_SEG_M": te.MAX_WALK_SEG_M},
        "quoted_numbers": {
            "prefix_total_walk_m": [590, 300], "final_walk_m": 400,
            "complete_total_walk_m": [990, 700],
            "both_pass_total_limit": all(value <= te.MAX_TOTAL_WALK_M for value in (990, 700)),
            "caveat": "These values alone do not demonstrate a total-walk-limit violation. A prior ride must reset consecutive walk; otherwise both totals exceed the 600 m consecutive limit.",
        },
        "total_walk_counterexample": total_walk_counterexample(),
        "segment_bucket_counterexample": segment_bucket_counterexample(),
        "interpretation": "Current scalar-cost dominance can remove the only feasible path under each production walking constraint. No product source or limit was changed.",
    }
    out_path = Path(__file__).resolve().with_name("opinion_walk_results.json")
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
