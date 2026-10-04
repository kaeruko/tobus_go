"""Resource-aware labels shared by Tokyo's three search objectives."""

from __future__ import annotations

import heapq
import itertools
import time
from collections import defaultdict
from dataclasses import dataclass, replace

from route_engine import RouteSearchLimitError


class SelectedPath(list):
    """Ordinary path nodes with query-local clocks and selected vehicle runs.

    List equality/serialization stays compatible with existing callers.  The
    private selection is consumed by detail generation before path is removed
    from the HTTP response.
    """

    def __init__(self, nodes, edge_times, edge_rides, choices, start_minute):
        super().__init__(nodes)
        self.edge_times = edge_times
        self.edge_rides = edge_rides
        self.choices = choices
        self.timetable_manager = choices.manager
        self.use_realtime = choices.use_realtime
        self.start_minute = start_minute

    @property
    def arrival_minute(self):
        return self.edge_times[-1] if self.edge_times else self.start_minute


@dataclass(slots=True, eq=False)
class _Label:
    node: object
    cost: float
    time: float
    total_walk: float
    segment_walk: float
    boardings: int
    ride: object = None
    parent: object = None
    active: bool = True
    expanded: bool = False


class _Frontier:
    def __init__(self, target, mode, can_wait):
        self.target = target
        self.mode = mode
        self.can_wait = can_wait
        self.labels = {}
        self.count = 0

    def _key(self, label):
        if label.node == self.target:
            # Completed paths have no future resource requirements.  Preserve
            # the historical final-walk candidate groups without using buckets
            # to equate resources at an intermediate node.
            return ("goal", label.boardings if self.mode == "fewTransfers" else None,
                    int(label.segment_walk // 25))
        context = label.ride.future_key if label.ride is not None else None
        conservative_time = None
        if context is not None or not self.can_wait:
            conservative_time = label.time
        # Fastest arrival has no boarding-count objective or hard boarding
        # constraint.  Equivalent continuations can therefore be compared
        # across boarding counts.  Keeping them separate retains arbitrarily
        # many immediate board/alight cycles even when every resource is worse.
        # The other objectives keep their conservative boarding-count groups.
        boardings = None if self.mode == "time" else label.boardings
        return (label.node, boardings, context, conservative_time)

    def _dominates(self, first, second):
        if first.node == self.target:
            return (first.time <= second.time if self.mode == "time"
                    else first.cost <= second.cost)
        # Comfort cost does not constrain earliest arrival.  A strictly earlier
        # offboard label can wait and reproduce a later label's continuation.
        # At equal times keep the cheaper prefix, preserving the queue's
        # preference for continuing a run over needless alight/board cycles.
        cost_ok = (first.cost <= second.cost
                   or (self.mode == "time" and first.time < second.time))
        return (cost_ok and first.time <= second.time
                and first.total_walk <= second.total_walk
                and first.segment_walk <= second.segment_walk)

    def add(self, label):
        key = self._key(label)
        existing = self.labels.get(key, ())
        if any(self._dominates(other, label) for other in existing):
            label.active = False
            return False
        kept = []
        for other in existing:
            if self._dominates(label, other):
                other.active = False
                self.count -= 1
            else:
                kept.append(other)
        kept.append(label)
        self.labels[key] = kept
        self.count += 1
        return True


def _path(label, choices, start_minute):
    chain = []
    while label is not None:
        chain.append(label)
        label = label.parent
    chain.reverse()
    return SelectedPath(
        [item.node for item in chain],
        [item.time for item in chain[1:]],
        {index: item.ride for index, item in enumerate(chain[1:])
         if item.ride is not None},
        choices, start_minute,
    )


def _compact_queue(queue):
    """Discard only entries which could not expand on their eventual pop.

    Keep each original (priority, sequence, label) tuple so candidate ordering
    stays unchanged. Frontier and parent references remain intact.
    """
    original_size = len(queue)
    kept = [entry for entry in queue
            if entry[2].active and not entry[2].expanded]
    removed = original_size - len(kept)
    if removed:
        queue[:] = kept
        heapq.heapify(queue)
    return removed


def search_labels(graph, choices, start, target, *, mode, start_minute,
                  max_search, max_visited, max_travel_min, time_limit_sec,
                  max_total_walk, max_segment_walk, walk_speed,
                  rail_boarding_minutes, advance_time, virtual_connections,
                  edge_uses_rail, heuristic=lambda node: 0.0,
                  max_expanded=None):
    """Yield feasible paths, using one frontier at generation and pop time.

    The queue uses the existing objective (no reverse A* lower bound).  A stale
    label is discarded by its identity, rather than a second scalar-cost map.
    """
    started = time.monotonic()
    deadline = start_minute + max_travel_min
    frontier = _Frontier(target, mode, choices.can_wait_offboard)
    queue = []
    sequence = itertools.count()
    counts = {name: defaultdict(int) for name in
              ("popped", "expanded", "dominated", "yielded")}
    popped = expanded = yielded = 0
    compacted_count = 0
    next_compaction_pop = 1000

    def priority(label):
        if mode == "fewTransfers":
            return (label.boardings, label.cost, label.time)
        if mode == "time":
            return (label.time, label.cost, label.boardings)
        return (label.cost + heuristic(label.node), label.cost, label.time)

    def offer(label):
        if (label.time > deadline or label.total_walk > max_total_walk
                or label.segment_walk > max_segment_walk):
            return
        if frontier.add(label):
            heapq.heappush(queue, (priority(label), next(sequence), label))
        else:
            counts["dominated"][label.boardings] += 1

    def stats(tag):
        fields = " ".join(
            f"{name}_by_boardings={{" + ", ".join(
                f"{key}:{value}" for key, value in sorted(counter.items())) + "}"
            for name, counter in counts.items())
        print(f"[ROUTE_DEBUG] {mode} stats: tag={tag} visited={popped} "
              f"yielded={yielded} queue={len(queue)} g_score={len(frontier.labels)} "
              f"best_cost={expanded} frontier_labels={frontier.count} "
              f"compacted_count={compacted_count} "
              f"elapsed_sec={time.monotonic() - started:.3f} {fields}", flush=True)

    def fail(reason):
        stats("abort:" + reason)
        raise RouteSearchLimitError(
            f"{mode} search safety limit exceeded: reason={reason} "
            f"visited={popped} yielded={yielded} queue={len(queue)} "
            f"g_score={len(frontier.labels)} best_cost={expanded} "
            f"elapsed_sec={time.monotonic() - started:.3f} "
            f"max_visited={max_visited} max_search={max_search} "
            f"time_limit_sec={time_limit_sec}")

    offer(_Label(start, 0.0, start_minute, 0.0, 0.0, 0))
    while queue:
        if time.monotonic() - started > time_limit_sec:
            fail("time_limit_sec")
        if popped >= next_compaction_pop:
            compacted_count += _compact_queue(queue)
            next_compaction_pop = popped + 1000
            # Charge compaction to the same deadline before another expansion.
            # It reduces actual heap pops, never the expanded-label budget
            # (including fastest search's unchanged 100,000-expansion limit).
            if time.monotonic() - started > time_limit_sec:
                fail("time_limit_sec")
            if not queue:
                break
        if len(queue) > 250000:
            fail("queue_size")
        if frontier.count > 500000:
            fail("g_score_size")
        _, _, label = heapq.heappop(queue)
        popped += 1
        counts["popped"][label.boardings] += 1
        if popped > max_visited:
            fail("max_visited")
        if not label.active or label.expanded:
            continue
        label.expanded = True
        expanded += 1
        counts["expanded"][label.boardings] += 1
        if max_expanded is not None and expanded > max_expanded:
            fail("max_expanded")
        if popped % 5000 == 0:
            stats("tick")
        if label.node == target:
            if yielded >= max_search:
                fail("max_search")
            yielded += 1
            counts["yielded"][label.boardings] += 1
            stats("yield")
            yield {"cost": label.cost, "path": _path(label, choices, start_minute),
                   "walk_m": label.total_walk}
            if mode != "fewTransfers" and yielded >= max_search:
                return
            continue

        direct = virtual_connections.get(label.node)
        can_walk_direct = False
        if direct is not None:
            cost, meters = direct
            arrival = label.time + meters / walk_speed
            total = label.total_walk + meters
            segment = label.segment_walk + meters
            if arrival <= deadline and total <= max_total_walk and segment <= max_segment_walk:
                can_walk_direct = True
                offer(_Label(target, label.cost + cost, arrival, total, segment,
                             label.boardings, parent=label))

        for following, edge in graph[label.node].items():
            etype = edge.get("etype")
            if can_walk_direct and etype == "walk":
                continue
            if edge_uses_rail(label.node, following):
                continue
            total = label.total_walk
            segment = 0.0
            if etype == "walk":
                meters = edge.get("meters", 0.0)
                step = meters if meters > 0 else 1.0
                total += step
                segment = label.segment_walk + step
                # Reject physical limits before any timetable evaluation.
                if total > max_total_walk or segment > max_segment_walk:
                    continue
            cost = label.cost + edge.get("w", 0.0)
            boardings = label.boardings + (etype == "board")
            options = None
            if etype == "board" and graph.nodes[following].get("mode") in ("bus", "rail"):
                ready = label.time + (rail_boarding_minutes
                                       if graph.nodes[following].get("mode") == "rail" else 0)
                options = choices.board_options(label.node, following, ready)
            elif etype == "ride" and label.ride is not None:
                if label.ride.provider.startswith("opaque-"):
                    # Graph-only test timetables have no concrete run data.
                    # Retain their injected clock evaluator, with conservative
                    # time equality in the frontier.
                    arrival = advance_time(label.node, following, label.time, edge)
                    options = () if arrival is None else ((arrival, replace(
                        label.ride, sequence=label.ride.sequence + 1)),)
                else:
                    options = choices.ride_options(label.node, following, label.time, label.ride)
            elif etype in ("alight", "xfer") and label.ride is not None:
                moved_bus = (label.ride.provider == "bus"
                             and label.ride.sequence != label.ride.board_sequence)
                options = ((label.time + (0.0 if moved_bus else 1.0), None),)
            if options is None:
                arrival = advance_time(label.node, following, label.time, edge)
                options = () if arrival is None else ((arrival, None),)
            for arrival, ride in options:
                if arrival < label.time or arrival > deadline:
                    continue
                offer(_Label(following, cost, arrival, total, segment, boardings,
                             ride=ride, parent=label))
    stats("queue_exhausted")
