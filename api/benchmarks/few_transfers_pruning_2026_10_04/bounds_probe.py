"""Offline experiment only: admissible remaining-boarding bounds for Tokyo.

Application files remain unchanged. The generator is copied in memory; the
only exploration change is the heap priority (g + a relaxed reverse bound).
The baseline 100,000-pop safety limit is retained.
"""
from __future__ import annotations

import array
from collections import deque
import contextlib
import heapq
import hashlib
import inspect
import io
import json
import math
import pickle
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "api"))
import toei_engine as te

INF = 1_000_000
BUCKET_METERS = 25
BUCKETS = int(te.MAX_WALK_SEG_M // BUCKET_METERS) + 1
BOUND_REPORTS = []


def make_bounds(G, target, connections, bus_only):
    """Lexicographic distance in a relaxation of the original state graph.

    Walk consumes floor(meters / 25); non-walk resets walk to zero, matching
    production semantics. No timetable, elapsed-time or total-walk restriction
    is applied. Every legal original continuation is present in this graph.
    Query uses floor(actual seg_walk / 25): every legal continuation still fits
    because floor(a/25) + sum(floor(b_i/25)) <= floor((a+sum b_i)/25).
    Thus this is a lower bound on (remaining boardings, remaining legacy cost),
    not an assertion that a corresponding scheduled itinerary exists.
    """
    started = time.perf_counter()
    nodes = list(G)
    ids = {node: index for index, node in enumerate(nodes)}
    nstates = len(nodes) * BUCKETS
    boards = array.array("i", [INF]) * nstates
    costs = array.array("d", [math.inf]) * nstates
    incoming = [[] for _ in nodes]
    walk_resource_nodes = [False] * len(nodes)
    for u, v, edge in G.edges(data=True):
        if bus_only and te._edge_uses_rail(G, u, v):
            continue
        etype = edge.get("etype")
        walk = etype == "walk"
        meters = edge.get("meters", 0.0)
        effective_meters = meters if meters > 0 else 1.0
        q = int(effective_meters // BUCKET_METERS) if walk else None
        incoming[ids[v]].append((ids[u], q, int(etype == "board"), edge.get("w", 0.0)))
        if walk:
            walk_resource_nodes[ids[v]] = True
    queue = []

    def relax(index, b, c):
        if b < boards[index] or (b == boards[index] and c < costs[index]):
            boards[index] = b
            costs[index] = c
            heapq.heappush(queue, (b, c, index))

    if target in ids:
        for q in range(BUCKETS):
            relax(ids[target] * BUCKETS + q, 0, 0.0)
    else:
        direct = te._virtual_destination_connections_by_node(target, connections)
        for node, (cost, meters) in direct.items():
            if node not in ids:
                continue
            consumed = int(meters // BUCKET_METERS)
            for q in range(BUCKETS - consumed):
                relax(ids[node] * BUCKETS + q, 0, cost)

    popped = 0
    while queue:
        b, c, state = heapq.heappop(queue)
        if b != boards[state] or c != costs[state]:
            continue
        popped += 1
        node, q = divmod(state, BUCKETS)
        for prev, walk_q, board, cost in incoming[node]:
            if walk_q is not None:
                if q >= walk_q:
                    relax(prev * BUCKETS + q - walk_q, b, c + cost)
            elif q == 0:
                # A node with no incoming walk can only have resource zero:
                # every other incoming edge resets it. Omitting those
                # unreachable product states preserves every original path.
                for prev_q in (range(BUCKETS) if walk_resource_nodes[prev] else (0,)):
                    relax(prev * BUCKETS + prev_q, b + board, c + cost)
    report = {"build_ms": (time.perf_counter() - started) * 1000, "relaxed_states": popped,
              "allocated_states": nstates, "array_bytes": len(boards) * boards.itemsize + len(costs) * costs.itemsize,
              "bucket_meters": BUCKET_METERS}
    # Negative control: ignoring the walking resource can connect whole areas
    # by zero-boarding walk chains. This graph is admissible but very weak.
    node_only = [INF] * len(nodes)
    reverse_queue = deque()
    for node in ([target] if target in ids else te._virtual_destination_connections_by_node(target, connections)):
        if node in ids:
            node_only[ids[node]] = 0
            reverse_queue.append(ids[node])
    while reverse_queue:
        node = reverse_queue.popleft()
        for prev, _, board, _ in incoming[node]:
            value = node_only[node] + board
            if value < node_only[prev]:
                node_only[prev] = value
                if board:
                    reverse_queue.append(prev)
                else:
                    reverse_queue.appendleft(prev)
    report["node_only_board_zero_physical_nodes"] = sum(node_only[i] == 0 for i, node in enumerate(nodes) if node[0] == "phys")
    report["physical_nodes"] = sum(node[0] == "phys" for node in nodes)
    BOUND_REPORTS.append(report)

    def bound(node, seg_walk):
        if node == target:
            return 0, 0.0
        state = ids[node] * BUCKETS + int(seg_walk // BUCKET_METERS)
        if "initial_bound" not in report:
            report["initial_bound"] = {"node": node, "boardings": boards[state], "legacy_cost": costs[state], "node_only_boardings": node_only[ids[node]]}
        return boards[state], costs[state]
    return bound


def generator_variant():
    source = inspect.getsource(te.find_few_transfers_paths_generator)
    source = source.replace("    start_min = time_str_to_min(start_time_str)",
                            "    start_min = time_str_to_min(start_time_str)\n    _bound = _make_bounds(G, target_node, virtual_dest_connections, bus_only)")
    source = source.replace("pq = [(0, 0.0, start_node, 0.0, 0.0, start_min, start_idx)]",
                            "_hb, _hc = _bound(start_node, 0.0)\n    pq = [(_hb, _hc, 0, 0.0, start_node, 0.0, 0.0, start_min, start_idx)]")
    source = source.replace("        (\n            boardings,", "        (\n            _estimated_boardings,\n            _estimated_cost,\n            boardings,")
    source = source.replace("                            boardings,\n                            new_cost_v,",
                            "                            boardings,\n                            new_cost_v,\n                            boardings,\n                            new_cost_v,")
    source = source.replace("                    new_boardings,\n                    new_cost,\n                    v,",
                            "                    new_boardings + _bound(v, new_seg_walk_m)[0],\n                    new_cost + _bound(v, new_seg_walk_m)[1],\n                    new_boardings,\n                    new_cost,\n                    v,")
    source = source.replace('            yield {', '            _log_few_transfers_stats("yield_pre")\n            yield {')
    namespace = dict(te.__dict__, _make_bounds=make_bounds)
    exec(compile(source, "<bounds_probe_generator>", "exec"), namespace)
    return namespace["find_few_transfers_paths_generator"]


CASES = [
    {"id": "jukkembashi_shibuya", "origin": [35.708166, 139.817434], "destination": [35.6636842, 139.6977409], "date": "2026-10-04", "time": "20:40"},
    {"id": "tokyo_toyosu", "origin": [35.681236, 139.767125], "destination": [35.6544, 139.7965]},
    {"id": "shinjuku_asakusa", "origin": [35.690921, 139.700258], "destination": [35.71165, 139.79662]},
    {"id": "tokyo_toyosu_bus_only", "origin": [35.681236, 139.767125], "destination": [35.6544, 139.7965], "bus_only": True},
]


def run(data, case, variant):
    g, si = data["G"], data["SI"]
    origin, _ = te.nearest_phys(g, *case["origin"], spatial_index=si)
    target, connections = te.get_virtual_connections(g, *case["destination"], walk_radius=te.MAX_WALK_SEG_M, spatial_index=si)
    date = case.get("date", "2026-10-02")
    source = te.find_few_transfers_paths_generator
    te.find_few_transfers_paths_generator = variant
    captured = io.StringIO()
    started = time.perf_counter()
    try:
        with contextlib.redirect_stdout(captured):
            routes = te.search_best_routes_once(g, data["TM"], a_phys=origin, target_node=target,
                        virtual_dest_connections=connections, target_coords=case["destination"],
                        mode="fewTransfers", start_time=case.get("time", "10:00"), target_date_str=date,
                        day_type=te.determine_day_type(date), use_realtime=False, bus_only=case.get("bus_only", False), limit=5)
        return {"ms": (time.perf_counter() - started) * 1000, "routes": routes, "log": captured.getvalue()}
    except Exception as exc:
        return {"ms": (time.perf_counter() - started) * 1000, "error": f"{type(exc).__name__}: {exc}", "log": captured.getvalue()}
    finally:
        te.find_few_transfers_paths_generator = source


def main():
    with (ROOT / "api/data/app_data.pkl").open("rb") as stream:
        data = pickle.load(stream)
    with contextlib.redirect_stdout(io.StringIO()):
        te.gtfs_repo.load_data(str(ROOT / "api/data/ToeiBus-GTFS"))
    baseline = te.find_few_transfers_paths_generator
    variant = generator_variant()
    result = {"scope": "Offline, static, generator ordering only; no product writes; 100000 pop limit unchanged. Timings include uncached lower bound construction. Existing approximate dominance unchanged.",
              "runs_per_case": 1, "python": sys.version, "platform": platform.platform(),
              "source_sha256": hashlib.sha256((ROOT / "api/toei_engine.py").read_bytes()).hexdigest(),
              "graph": {"nodes": data["G"].number_of_nodes(), "edges": data["G"].number_of_edges()},
              "cases": []}
    for case in CASES:
        row = {"case": case, "baseline": run(data, case, baseline)}
        row["bounds"] = run(data, case, variant)
        row["bounds"]["preparation"] = BOUND_REPORTS[-1]
        if not row["baseline"].get("error") and not row["bounds"].get("error"):
            row["same_route_payload"] = row["baseline"]["routes"] == row["bounds"]["routes"]
        result["cases"].append(row)
        (OUT / "bounds_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(case["id"], "baseline", round(row["baseline"]["ms"], 2), len(row["baseline"].get("routes", [])),
              "bounds", round(row["bounds"]["ms"], 2), len(row["bounds"].get("routes", [])), row["bounds"].get("error"), flush=True)


if __name__ == "__main__":
    main()
