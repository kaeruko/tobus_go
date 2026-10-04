"""Tokyo fewTransfers: a query-local lexicographic reverse lower bound.

``make_bounds`` returns a callable whose result is (minimum remaining boardings,
minimum remaining legacy cost *among continuations with that boarding count*). The
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

The caller must use this only to order the queue.  In particular,
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


def _upper_product(first, second):
    if first == 0.0 or second == 0.0:
        return 0.0
    return math.nextafter(first * second, math.inf)


def _upper_sum(first, second):
    if first == 0.0:
        return second
    if second == 0.0:
        return first
    return math.nextafter(first + second, math.inf)


def _upper_steps(value):
    try:
        steps = int(value)
    except (TypeError, ValueError, OverflowError):
        return math.inf
    if steps < 0 or steps != value:
        raise ValueError("cost addition limits must be nonnegative integers")
    try:
        result = float(steps)
    except OverflowError:
        return math.inf
    return math.nextafter(result, math.inf) if steps else 0.0


def _upper_gamma(steps):
    """An upper bound for n*u/(1-n*u), including coefficient rounding."""
    if steps == 0.0:
        return 0.0
    product = _upper_product(steps, 2.0**-53)
    if not math.isfinite(product) or product >= 1.0:
        return math.inf
    # The denominator needs a lower bound so division gives an upper bound.
    denominator = math.nextafter(1.0 - product, -math.inf)
    if denominator <= 0.0:
        return math.inf
    return math.nextafter(product / denominator, math.inf)


class CostRoundingGuard:
    """Conservative A* total cost under the forward float-addition objective.

    ``max_edge_cost`` bounds every included edge, including virtual destination
    edges. ``max_forward_steps`` bounds the cost additions of every completed
    path the search can yield within its pop budget. ``max_reverse_steps``
    bounds a simple path in the relaxed graph (allocated states plus one is
    sufficient, including a virtual destination edge).

    The graph costs are finite and nonnegative. For binary64 unit roundoff
    u=2**-53, n additions have error bounded by gamma(n)*sum(operands), where
    gamma(n)=n*u/(1-n*u). A reverse shortest path can be chosen simple: removing
    a nonnegative cycle cannot increase its boarding count or real cost.
    Rounded addition of nonnegative costs is monotone, so reverse Dijkstra's
    cost is no larger than the rounded reverse sum along that minimum path.
    Consequently its conditional cost h is at most the mathematical relaxed
    minimum H plus

        E_reverse = gamma(N_reverse) * N_reverse * max_edge_cost.

    Every stored prefix starts at zero and uses at most N_forward additions,
    so its float cost g is bounded by

        G_max = N_forward * max_edge_cost * (1 + gamma(N_forward)).

    For a suffix after g, its actual accumulated float cost F is at least its
    mathematical total g+C minus the query-wide bound

        E_forward = gamma(N_forward) * (G_max + N_forward * max_edge_cost).

    Likewise h <= H_max = N_reverse*max_edge_cost + E_reverse. When the
    remaining boarding counts agree, H <= C. Subtracting both errors and one
    ulp of G_max+H_max for the rounded g+h, then rounding the subtraction
    downward, therefore gives a total estimate <= F. Since nonnegative
    additions also imply g<=F, clamping this estimate to g remains safe.
    Coefficients, sums and products used for error bounds are rounded upward;
    the gamma denominator is rounded downward. All error terms are fixed for
    the query so equal g+h priorities do not acquire a prefix-dependent bias.
    The final estimate is used only as a queue priority.

    A zero bound (including a goal) returns g exactly. If an error computation
    becomes nonfinite or n*u>=1, or g/h exceeds its computed global upper bound,
    only the cost heuristic is disabled: return g and retain the independent
    boarding-count bound. The caller supplies a finite, nonnegative prefix;
    a negative prefix or parameter is rejected.
    """

    __slots__ = ("_enabled", "_prefix_upper", "_remaining_upper", "_error")

    def __init__(self, max_edge_cost, max_forward_steps, max_reverse_steps):
        self._enabled = False
        self._prefix_upper = 0.0
        self._remaining_upper = 0.0
        self._error = 0.0
        try:
            weight = float(max_edge_cost)
        except (TypeError, ValueError, OverflowError):
            return
        if weight < 0.0:
            raise ValueError("maximum edge cost must be nonnegative")
        forward_steps = _upper_steps(max_forward_steps)
        reverse_steps = _upper_steps(max_reverse_steps)
        if not all(math.isfinite(value) for value in (weight, forward_steps, reverse_steps)):
            return
        forward_gamma = _upper_gamma(forward_steps)
        reverse_gamma = _upper_gamma(reverse_steps)
        forward_weight_sum = _upper_product(forward_steps, weight)
        reverse_weight_sum = _upper_product(reverse_steps, weight)
        reverse_error = _upper_product(reverse_gamma, reverse_weight_sum)
        if not all(math.isfinite(value) for value in
                   (forward_gamma, reverse_gamma, forward_weight_sum, reverse_error)):
            return
        prefix_upper = _upper_sum(forward_weight_sum,
                                  _upper_product(forward_gamma, forward_weight_sum))
        remaining_upper = _upper_sum(reverse_weight_sum, reverse_error)
        forward_error = _upper_product(
            forward_gamma, _upper_sum(prefix_upper, forward_weight_sum))
        total_upper = _upper_sum(prefix_upper, remaining_upper)
        if not math.isfinite(total_upper):
            return
        sum_error = math.nextafter(math.ulp(total_upper), math.inf)
        error = _upper_sum(_upper_sum(reverse_error, forward_error), sum_error)
        if not math.isfinite(error):
            return
        self._prefix_upper = prefix_upper
        self._remaining_upper = remaining_upper
        self._error = error
        self._enabled = True

    def __call__(self, prefix_cost, remaining_cost):
        prefix = float(prefix_cost)
        if prefix < 0.0:
            raise ValueError("prefix cost must be nonnegative")
        if not self._enabled or not math.isfinite(prefix) or prefix > self._prefix_upper:
            return prefix
        try:
            remaining = float(remaining_cost)
        except (TypeError, ValueError, OverflowError):
            return prefix
        if (remaining <= 0.0 or not math.isfinite(remaining)
                or remaining > self._remaining_upper):
            return prefix
        total = prefix + remaining
        if not math.isfinite(total):
            return prefix
        return max(prefix, math.nextafter(total - self._error, -math.inf))


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
                max_segment_walk=600.0, bucket_meters=25.0, check_deadline=None):
    """Build a reverse bound; True from edge_uses_rail excludes that edge.

    ``virtual_connections`` is already normalized by the caller as
    ``node -> (cost, meters)``. Include these direct walking connections even
    when target is also a graph node, matching the forward search's actions.
    Graph nodes, edge attributes and the exclusion predicate must stay fixed
    during construction.  Negative/nonfinite costs are rejected even on
    excluded edges, so the report audits the whole supplied graph.

    ``report['array_bytes']`` measures retained arrays, not the Python node
    lookup dictionary, temporary queue/CSR arrays, or process RSS. Process-memory
    measurements must account for those costs as well.

    ``check_deadline`` is an optional no-argument callback. It shares the
    forward search's original deadline and raises the caller's normal safety
    exception; construction never catches it or substitutes a different limit.
    Checks happen between bounded batches in every potentially long loop and
    before and after bulk allocations. No cache survives the query.
    """
    started = time.perf_counter()
    check = check_deadline if check_deadline is not None else lambda: None
    check()
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
    nodes = []
    ids = {}
    for index, node in enumerate(graph):
        if (index & 1023) == 0:
            check()
        nodes.append(node)
        ids[node] = index
    check()
    if len(nodes) >= _INF_BOARDINGS:
        raise ValueError("node count exceeds the array index range")
    incoming_counts = array.array("I", [0]) * len(nodes)
    check()
    has_incoming_walk = bytearray(len(nodes))
    check()
    included_edges = excluded_edges = 0
    minimum_cost = math.inf
    maximum_cost = 0.0
    for edge_number, (previous, following, edge) in enumerate(graph.edges(data=True)):
        if (edge_number & 1023) == 0:
            check()
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
    check()
    if included_edges >= _INF_BOARDINGS:
        raise ValueError("edge count exceeds the array index range")

    widths = array.array("I")
    offsets = array.array("I", [0])
    for index, flag in enumerate(has_incoming_walk):
        if (index & 1023) == 0:
            check()
        width = bucket_count if flag else 1
        widths.append(width)
        total = offsets[-1] + width
        if total >= _INF_BOARDINGS:
            raise ValueError("relaxed state count exceeds the array index range")
        offsets.append(total)
    check()
    allocated_states = offsets[-1]
    boards = array.array("I", [_INF_BOARDINGS]) * allocated_states
    check()
    costs = array.array("d", [math.inf]) * allocated_states
    check()

    # Incoming edges use CSR arrays rather than a list of per-node tuples.
    incoming_offsets = array.array("I", [0])
    for index, count in enumerate(incoming_counts):
        if (index & 1023) == 0:
            check()
        incoming_offsets.append(incoming_offsets[-1] + count)
    check()
    cursor = array.array("I", incoming_offsets[:-1])
    check()
    previous_nodes = array.array("I", [0]) * included_edges
    check()
    walk_buckets = array.array("q", [-1]) * included_edges
    check()
    boarding_edges = bytearray(included_edges)
    check()
    edge_costs = array.array("d", [0.0]) * included_edges
    check()
    for edge_number, (previous, following, edge) in enumerate(graph.edges(data=True)):
        if (edge_number & 1023) == 0:
            check()
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

    check()
    queue = []
    queue_peak = 0
    resource_visits = 0

    def relax(node_id, resource, remaining_boardings, remaining_cost):
        nonlocal queue_peak, resource_visits
        resource_visits += 1
        if (resource_visits & 1023) == 0:
            check()
        state = offsets[node_id] + resource
        if (remaining_boardings < boards[state]
                or (remaining_boardings == boards[state] and remaining_cost < costs[state])):
            boards[state] = remaining_boardings
            costs[state] = remaining_cost
            heapq.heappush(queue, (remaining_boardings, remaining_cost, node_id, resource))
            queue_peak = max(queue_peak, len(queue))

    check()
    seeded_node_ids = set()
    missing_virtual_nodes = 0
    if target in ids:
        node_id = ids[target]
        for resource in range(widths[node_id]):
            relax(node_id, resource, 0, 0.0)
        seeded_node_ids.add(node_id)
    for seed_number, (node, (cost, meters)) in enumerate((virtual_connections or {}).items()):
        if (seed_number & 1023) == 0:
            check()
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
            seeded_node_ids.add(node_id)
            for resource in range(available):
                relax(node_id, resource, 0, cost)

    check()
    queue_pops = settled_states = 0
    edge_visits = 0
    while queue:
        if (queue_pops & 1023) == 0:
            check()
        remaining_boardings, remaining_cost, node_id, resource = heapq.heappop(queue)
        queue_pops += 1
        state = offsets[node_id] + resource
        if remaining_boardings != boards[state] or remaining_cost != costs[state]:
            continue
        settled_states += 1
        for edge_index in range(incoming_offsets[node_id], incoming_offsets[node_id + 1]):
            edge_visits += 1
            if (edge_visits & 1023) == 0:
                check()
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

    check()
    unreachable_states = 0
    for index, value in enumerate(boards):
        if (index & 1023) == 0:
            check()
        unreachable_states += value == _INF_BOARDINGS
    check()
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
        "seeded_nodes": len(seeded_node_ids), "missing_virtual_nodes": missing_virtual_nodes,
        "unreachable_allocated_states": unreachable_states,
        "lower_bound": "lexicographic (minimum remaining boardings, minimum cost conditional on that boarding count)",
        "unreachable_policy": "zero bound; priority only, no pruning",
    }
    check()
    report["build_ms"] = (time.perf_counter() - started) * 1000.0
    return RelaxedBounds(ids, target, offsets, widths, boards, costs, bucket_meters,
                         capacity, max_segment_walk, report)
