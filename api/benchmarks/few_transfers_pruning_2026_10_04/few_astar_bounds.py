"""Offline fewTransfers experiment: a lexicographic reverse lower bound.

This module does not import or replace a production search.  ``make_bounds``
returns a callable whose result is (minimum remaining boardings, minimum
remaining legacy cost *among continuations with that boarding count*).  The
two components are a lexicographic pair, not independent scalar minima.

The relaxed graph ignores timetables, concrete runs, elapsed time and total
walking.  A walking edge consumes floor(effective meters / bucket meters),
and every other edge resets this resource to zero, matching search_labels.
For every feasible original continuation,

    floor(initial_segment / bucket) + sum(floor(edge_meters / bucket))
        <= floor((initial_segment + sum(edge_meters)) / bucket).

Thus a legal original walking segment also fits the relaxed capacity.  Every
original continuation is represented, except deliberately omitted resource
states handled by the safe zero fallback below.  Nonnegative edge costs make
reverse lexicographic Dijkstra valid.  Minimizing over this superset gives a
lexicographic lower bound: the cost comparison is needed only when the
minimum relaxed boarding count equals the actual remaining boarding count.

Nodes with no included incoming walking edge need only resource zero for
labels reached from a query's zero-resource start: every included incoming
edge resets the resource.  Positive-resource states at these nodes are not
allocated.  If an arbitrary external caller asks for such a state, or an
unknown/unreachable node, return (0, 0) rather than use it for pruning.

The experimental caller must use this only to order the queue.  In particular,
an unreachable relaxed state is not evidence for pruning a production label.
"""

from __future__ import annotations

import array
import heapq
import math
import time


_INF_BOARDINGS = 2**32 - 1


def _cost(value, description):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{description}: cost must be finite and nonnegative") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{description}: cost must be finite and nonnegative, got {value!r}")
    return result


def _walk_meters(edge, description):
    # This is deliberately the same fallback as the common label search.
    try:
        meters = float(edge.get("meters", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{description}: walking meters must be finite") from exc
    if not math.isfinite(meters):
        raise ValueError(f"{description}: walking meters must be finite")
    return meters if meters > 0 else 1.0


class RelaxedBounds:
    """Query-local, compact result of reverse relaxed-graph Dijkstra."""

    __slots__ = ("_ids", "_target", "_offsets", "_widths", "_boards", "_costs",
                 "_bucket", "_capacity", "_max_segment", "report")

    def __init__(self, ids, target, offsets, widths, boards, costs, bucket,
                 capacity, max_segment, report):
        self._ids = ids
        self._target = target
        self._offsets = offsets
        self._widths = widths
        self._boards = boards
        self._costs = costs
        self._bucket = bucket
        self._capacity = capacity
        self._max_segment = max_segment
        self.report = report

    def __call__(self, node, exact_segment_walk):
        if node == self._target:
            return 0, 0.0
        node_id = self._ids.get(node)
        if node_id is None:
            return 0, 0.0
        try:
            meters = float(exact_segment_walk)
        except (TypeError, ValueError):
            return 0, 0.0
        if not math.isfinite(meters) or meters < 0 or meters > self._max_segment:
            return 0, 0.0
        resource = int(meters // self._bucket)
        if resource > self._capacity or resource >= self._widths[node_id]:
            return 0, 0.0
        state = self._offsets[node_id] + resource
        boards = self._boards[state]
        cost = self._costs[state]
        if boards == _INF_BOARDINGS or not math.isfinite(cost):
            return 0, 0.0
        return boards, cost


def make_bounds(graph, target, virtual_connections=None, *,
                edge_uses_rail=lambda first, second: False,
                max_segment_walk=600.0, bucket_meters=25.0):
    """Build a reverse bound; True from edge_uses_rail excludes that edge.

    ``virtual_connections`` is already normalized by the caller as
    ``node -> (cost, meters)``.  It is used only when target is not a graph node.
    Graph nodes, edge attributes and the exclusion predicate must stay fixed
    during construction.  Negative/nonfinite costs are rejected even on
    excluded edges, so the report audits the whole supplied graph.

    ``report['array_bytes']`` measures retained arrays, not the Python node
    lookup dictionary, temporary queue/CSR arrays, or process RSS.  Use the
    experiment's process-memory sampler to measure those costs as well.
    """
    started = time.perf_counter()
    max_segment_walk = float(max_segment_walk)
    bucket_meters = float(bucket_meters)
    if not math.isfinite(max_segment_walk) or max_segment_walk < 0:
        raise ValueError("max_segment_walk must be finite and nonnegative")
    if not math.isfinite(bucket_meters) or bucket_meters <= 0:
        raise ValueError("bucket_meters must be finite and positive")
    capacity = int(max_segment_walk // bucket_meters)
    if capacity >= _INF_BOARDINGS:
        raise ValueError("walking bucket count exceeds the array index range")
    bucket_count = capacity + 1
    nodes = list(graph)
    ids = {node: index for index, node in enumerate(nodes)}
    if len(nodes) >= _INF_BOARDINGS:
        raise ValueError("node count exceeds the array index range")
    incoming_counts = array.array("I", [0]) * len(nodes)
    has_incoming_walk = bytearray(len(nodes))
    included_edges = excluded_edges = 0
    minimum_cost = math.inf
    maximum_cost = 0.0
    for previous, following, edge in graph.edges(data=True):
        cost = _cost(edge.get("w", 0.0), f"edge {previous!r} -> {following!r}")
        minimum_cost = min(minimum_cost, cost)
        maximum_cost = max(maximum_cost, cost)
        if edge_uses_rail(previous, following):
            excluded_edges += 1
            continue
        included_edges += 1
        incoming_counts[ids[following]] += 1
        if edge.get("etype") == "walk":
            _walk_meters(edge, f"edge {previous!r} -> {following!r}")
            has_incoming_walk[ids[following]] = 1
    if included_edges >= _INF_BOARDINGS:
        raise ValueError("edge count exceeds the array index range")

    widths = array.array("I", (bucket_count if flag else 1 for flag in has_incoming_walk))
    offsets = array.array("I", [0])
    for width in widths:
        total = offsets[-1] + width
        if total >= _INF_BOARDINGS:
            raise ValueError("relaxed state count exceeds the array index range")
        offsets.append(total)
    allocated_states = offsets[-1]
    boards = array.array("I", [_INF_BOARDINGS]) * allocated_states
    costs = array.array("d", [math.inf]) * allocated_states

    # Incoming edges use CSR arrays rather than a list of per-node tuples.
    incoming_offsets = array.array("I", [0])
    for count in incoming_counts:
        incoming_offsets.append(incoming_offsets[-1] + count)
    cursor = array.array("I", incoming_offsets[:-1])
    previous_nodes = array.array("I", [0]) * included_edges
    walk_buckets = array.array("q", [-1]) * included_edges
    boarding_edges = bytearray(included_edges)
    edge_costs = array.array("d", [0.0]) * included_edges
    for previous, following, edge in graph.edges(data=True):
        if edge_uses_rail(previous, following):
            continue
        following_id = ids[following]
        index = cursor[following_id]
        cursor[following_id] += 1
        previous_nodes[index] = ids[previous]
        if edge.get("etype") == "walk":
            consumed = int(_walk_meters(edge, "walking edge") // bucket_meters)
            # All values above capacity are equally unusable.  Clamping also
            # avoids overflowing an integer array for a very long finite edge.
            walk_buckets[index] = min(consumed, capacity + 1)
        boarding_edges[index] = edge.get("etype") == "board"
        edge_costs[index] = float(edge.get("w", 0.0))

    queue = []
    queue_peak = 0

    def relax(node_id, resource, remaining_boardings, remaining_cost):
        nonlocal queue_peak
        state = offsets[node_id] + resource
        if (remaining_boardings < boards[state]
                or (remaining_boardings == boards[state] and remaining_cost < costs[state])):
            boards[state] = remaining_boardings
            costs[state] = remaining_cost
            heapq.heappush(queue, (remaining_boardings, remaining_cost, node_id, resource))
            queue_peak = max(queue_peak, len(queue))

    seeded_nodes = 0
    missing_virtual_nodes = 0
    if target in ids:
        node_id = ids[target]
        for resource in range(widths[node_id]):
            relax(node_id, resource, 0, 0.0)
        seeded_nodes = 1
    else:
        for node, (cost, meters) in (virtual_connections or {}).items():
            cost = _cost(cost, f"virtual connection from {node!r}")
            try:
                meters = float(meters)
            except (TypeError, ValueError) as exc:
                raise ValueError("virtual walking meters must be finite and nonnegative") from exc
            if not math.isfinite(meters) or meters < 0:
                raise ValueError("virtual walking meters must be finite and nonnegative")
            if node not in ids:
                missing_virtual_nodes += 1
                continue
            node_id = ids[node]
            consumed = int(meters // bucket_meters)
            available = min(widths[node_id], bucket_count - consumed)
            if available > 0:
                seeded_nodes += 1
                for resource in range(available):
                    relax(node_id, resource, 0, cost)

    queue_pops = settled_states = 0
    while queue:
        remaining_boardings, remaining_cost, node_id, resource = heapq.heappop(queue)
        queue_pops += 1
        state = offsets[node_id] + resource
        if remaining_boardings != boards[state] or remaining_cost != costs[state]:
            continue
        settled_states += 1
        for edge_index in range(incoming_offsets[node_id], incoming_offsets[node_id + 1]):
            previous_id = previous_nodes[edge_index]
            consumed = walk_buckets[edge_index]
            next_cost = remaining_cost + edge_costs[edge_index]
            if consumed >= 0:
                previous_resource = resource - consumed
                if 0 <= previous_resource < widths[previous_id]:
                    relax(previous_id, previous_resource, remaining_boardings, next_cost)
            elif resource == 0:
                next_boardings = remaining_boardings + boarding_edges[edge_index]
                for previous_resource in range(widths[previous_id]):
                    relax(previous_id, previous_resource, next_boardings, next_cost)

    retained_array_bytes = sum(len(item) * item.itemsize for item in (offsets, widths, boards, costs))
    temporary_array_bytes = sum(len(item) * item.itemsize for item in (
        incoming_counts, incoming_offsets, cursor, previous_nodes, walk_buckets, edge_costs))
    temporary_array_bytes += len(has_incoming_walk) + len(boarding_edges)
    report = {
        "nodes": len(nodes), "included_edges": included_edges,
        "excluded_edges": excluded_edges,
        "graph_min_edge_cost": minimum_cost if math.isfinite(minimum_cost) else None,
        "graph_max_edge_cost": maximum_cost,
        "bucket_meters": bucket_meters, "max_segment_walk": max_segment_walk,
        "walking_bucket_count": bucket_count,
        "nodes_with_incoming_walk": sum(has_incoming_walk),
        "nominal_states": len(nodes) * bucket_count,
        "allocated_states": allocated_states,
        "omitted_zero_resource_only_states": len(nodes) * bucket_count - allocated_states,
        "array_bytes": retained_array_bytes,
        "temporary_array_bytes": temporary_array_bytes,
        "relaxed_states": settled_states,
        "queue_pops": queue_pops, "queue_peak": queue_peak,
        "seeded_nodes": seeded_nodes, "missing_virtual_nodes": missing_virtual_nodes,
        "unreachable_allocated_states": sum(value == _INF_BOARDINGS for value in boards),
        "lower_bound": "lexicographic (minimum remaining boardings, minimum cost conditional on that boarding count)",
        "unreachable_policy": "zero bound; priority only, no pruning",
    }
    report["build_ms"] = (time.perf_counter() - started) * 1000.0
    return RelaxedBounds(ids, target, offsets, widths, boards, costs, bucket_meters,
                         capacity, max_segment_walk, report)
