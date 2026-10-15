"""Opt-in, finite-query audit of Tokyo's first time goal; never a backend.

The oracle closes raw-schedule operational states WITHOUT dominance, A*, a
depth cutoff, or a product timetable/bounds builder. Reverse reachability of
absolute terminal clocks supplies a completion witness at every state. Cost
and boarding count are deliberately absent: neither constrains Tokyo time
feasibility. Concrete runs, occurrences, boarding provenance and both walking
resources remain. Repeated identical operational states can be quotiented,
including zero-time cycles; an unfinished closure is an error, not a proof.

The comparison driver separately checks the whole reachable transition
relation against a fresh canonical static provider, then observes the actual
unmodified search with a thread-local trace. It checks every true dominance,
resource rejection, OPEN witness, actual priority, and first active goal pop.
Only the supplied finite, closed query is certified. No universal network,
secondary cost, candidate-class or top-k claim follows from a synthetic run.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import inspect
import math
import sys
from types import MappingProxyType

import networkx as nx

from route_engine import RouteContractError
import toei_engine as engine
import tokyo_search_labels as integration
import tokyo_timetable_choices as timetable
import transit_search_labels as forward
from gtfs_loader import GtfsRepository
from tokyo_destination_bounds_audit import _digest_rows, _graph_digest, _sources_digest
from tokyo_time_projection_proof import (
    _ast_digest, _check_binary64_environment, _check_reviewed_contract,
)
from tokyo_time_rounding import TimeRoundingGuard
from tokyo_time_rounding_audit import (
    float_bits, verify_guard_coefficients, verify_guard_equivalence,
)


class SearchCorrectnessError(RouteContractError):
    """A failed obligation, with index-only counterexample data (no raw IDs)."""

    def __init__(self, reason, **counterexample):
        self.reason = reason
        self.counterexample = {"reason": reason, **counterexample}
        super().__init__("Tokyo first-arrival audit rejected: reason=" + reason)


def _stop(reason, **context):
    raise SearchCorrectnessError(reason, **context)


def _number(value):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or value < 0 or value > 2**53):
        _stop("unsupported_numeric_domain")
    return float(value)


@dataclass(frozen=True)
class SearchLimits:
    # No implicit substitution of stage-4's audit Nf=100000 for production.
    profile: str
    max_visited: int
    max_expanded: int
    time_limit_sec: float

    def __post_init__(self):
        if (self.profile not in ("synthetic_explicit", "production_fastest")
                or type(self.max_visited) is not int or self.max_visited < 1
                or type(self.max_expanded) is not int or self.max_expanded < 1
                or type(self.time_limit_sec) not in (int, float)
                or not math.isfinite(self.time_limit_sec) or self.time_limit_sec <= 0):
            _stop("invalid_explicit_search_limits")
        if (self.profile == "production_fastest"
                and (self.max_visited, self.max_expanded, self.time_limit_sec)
                != (200000, 100000, 15.0)):
            _stop("production_search_limits_differ")


@dataclass(frozen=True)
class RawStop:
    stop_id: str
    sequence: int
    arrival: int
    departure: int
    pickup: int = 0


@dataclass(frozen=True)
class RawRun:
    provider: str
    service_key: str
    run_id: str
    line_id: object
    stops: tuple[RawStop, ...]
    trip_id: str | None = None
    train_number: str | None = None
    route_id: str | None = None
    service_id: str | None = None
    active: bool = True


# A separate data representation, not a product future_key or provider call.
_RIDE_FIELDS = ("provider", "service_key", "run_id", "line_id", "sequence",
                "board_sequence", "departure_minute", "trip_id", "train_number",
                "route_id", "service_id")


@dataclass(frozen=True)
class State:
    node: object
    clock: float
    total: float
    segment: float
    ride: tuple | None = None


def _state(label):
    return State(label.node, float(label.time), float(label.total_walk),
                 float(label.segment_walk), None if label.ride is None else
                 tuple(getattr(label.ride, field) for field in _RIDE_FIELDS))


@dataclass(frozen=True)
class Query:
    start: object
    target: object
    start_minute: float
    max_travel_min: float
    virtual: tuple = ()  # ((node, (cost, meters)), ...), preserves graph order.
    bus_only: bool = False

    @property
    def deadline(self):
        return self.start_minute + self.max_travel_min


class CompletionOracle:
    """Exhaustive finite operational closure and independent terminal-clock DP.

    Accepted graph vocabulary is intentionally narrow: physical walks,
    physical-to-line board, same-line ride, line-to-physical alight/xfer.
    Exact stop IDs and explicit run/line bindings are required. Unsupported
    schemas/aliases must be reviewed, never inferred by a fallback.
    """

    def __init__(self, graph, runs, query, *, max_states, max_transitions):
        if (type(graph) is not nx.DiGraph or type(query) is not Query
                or type(runs) is not tuple or type(query.virtual) is not tuple
                or type(query.bus_only) is not bool):
            _stop("unsupported_oracle_inputs")
        if any(type(value) is not int or value < 1
               for value in (max_states, max_transitions)):
            _stop("invalid_oracle_work_limits")
        self.graph, self.runs, self.query = graph, runs, query
        _number(query.start_minute)
        _number(query.max_travel_min)
        _number(query.deadline)
        if query.start not in graph or query.start[0] != "phys":
            _stop("physical_graph_start_required")
        if query.target[0] != "phys":
            _stop("physical_target_required")
        virtual = dict(query.virtual)
        if len(virtual) != len(query.virtual):
            _stop("duplicate_virtual_seed")
        for cost, meters in virtual.values():
            _number(cost)
            _number(meters)
        self.virtual = MappingProxyType(virtual)
        for node, attrs in graph.nodes(data=True):
            if (type(node) is not tuple or len(node) not in (2, 3)
                    or node[0] not in ("phys", "line")
                    or (node[0] == "phys" and len(node) != 2)
                    or (node[0] == "line" and (len(node) != 3
                        or attrs.get("mode") not in ("bus", "rail")))):
                _stop("unsupported_graph_node")
        for left, right, edge in graph.edges(data=True):
            _number(edge.get("w", 0.0))
            kind = edge.get("etype")
            shapes = {"walk": ("phys", "phys"), "board": ("phys", "line"),
                      "ride": ("line", "line"), "alight": ("line", "phys"),
                      "xfer": ("line", "phys")}
            if kind not in shapes or (left[0], right[0]) != shapes[kind]:
                _stop("unsupported_graph_transition")
            if kind == "walk":
                _number(edge.get("meters", 0.0))
                if "reviewed_walk_minutes" in edge:
                    value = edge["reviewed_walk_minutes"]
                    if (type(value) is not int or value < 0
                            or value < math.ceil(edge.get("meters", 0.0) / 80.0)):
                        _stop("invalid_reviewed_walk")
            elif kind in ("board", "alight", "xfer") and left[1] != right[1]:
                _stop("different_stop_access_edge")
            elif kind == "ride" and (left[2] != right[2]
                    or graph.nodes[left]["mode"] != edge.get("mode")
                    or graph.nodes[right]["mode"] != edge.get("mode")):
                _stop("different_line_ride_edge")
        self.run_by_key = {}
        for run in runs:
            if (type(run) is not RawRun or run.provider not in ("rail", "bus")
                    or type(run.stops) is not tuple or len(run.stops) < 2
                    or type(run.active) is not bool):
                _stop("unsupported_raw_run")
            key = (run.provider, run.service_key, run.run_id, run.line_id)
            if key in self.run_by_key:
                _stop("duplicate_raw_run")
            self.run_by_key[key] = run
            for index, stop in enumerate(run.stops):
                if (type(stop) is not RawStop or type(stop.sequence) is not int
                        or type(stop.arrival) is not int or type(stop.departure) is not int
                        or type(stop.pickup) is not int or stop.pickup not in (0, 1)):
                    _stop("unsupported_raw_stop_or_conditional_pickup")
                _number(stop.arrival)
                _number(stop.departure)
                if (stop.arrival > stop.departure or (index and
                        (stop.sequence <= run.stops[index - 1].sequence
                         or stop.arrival < run.stops[index - 1].departure))):
                    _stop("invalid_raw_stop_order_or_clock")

        initial = State(query.start, float(query.start_minute), 0.0, 0.0)
        states, index, edges, attempts = [initial], {initial: 0}, [], []
        transition_count = 0
        position = 0
        while position < len(states):
            state = states[position]
            rows = tuple(self.attempts(state)) if state.node != query.target else ()
            children = []
            for child, reason in rows:
                transition_count += 1
                if transition_count > max_transitions:
                    _stop("oracle_transition_limit", states=len(states), attempts=transition_count)
                if reason is not None:
                    continue
                if child not in index:
                    if len(states) >= max_states:
                        _stop("oracle_state_limit", states=len(states), attempts=transition_count)
                    index[child] = len(states)
                    states.append(child)
                children.append(index[child])
            edges.append(tuple(children))
            attempts.append(rows)
            position += 1
        self.states, self.index = tuple(states), MappingProxyType(index)
        self.edges, self.rows = tuple(edges), tuple(attempts)
        self.attempt_count = transition_count
        reverse = [[] for _ in states]
        for parent, children in enumerate(edges):
            for child in children:
                reverse[child].append(parent)
        values, next_step, work = [math.inf] * len(states), {}, deque()
        for i, state in enumerate(states):
            if state.node == query.target:
                values[i] = state.clock
                work.append(i)
        # Absolute goal clocks, no elapsed weights, heap, A* or dominance.
        while work:
            child = work.popleft()
            for parent in reverse[child]:
                if values[child] < values[parent]:
                    values[parent] = values[child]
                    next_step[parent] = child
                    work.append(parent)
        self.values = tuple(values)
        self.next_step = MappingProxyType(next_step)

    def reason(self, state, previous_clock):
        if state.clock < previous_clock:
            return "clock_decrease"
        if state.clock > self.query.deadline:
            return "deadline"
        if state.total > 3000.0:
            return "total_walk"
        if state.segment > 600.0:
            return "segment_walk"
        return None

    def attempts(self, state):
        node, clock, total, segment, ride = (
            state.node, state.clock, state.total, state.segment, state.ride)
        if node in self.virtual:
            _, meters = self.virtual[node]
            child = State(self.query.target, clock + meters / 80.0,
                          total + meters, segment + meters)
            yield child, self.reason(child, clock)
        for following, edge in self.graph[node].items():
            kind = edge["etype"]
            if self.query.bus_only and (edge.get("mode") == "rail" or any(
                    n[0] == "line" and self.graph.nodes[n]["mode"] == "rail"
                    for n in (node, following))):
                continue
            if kind == "walk":
                meters = edge.get("meters", 0.0)
                meters = meters if meters > 0 else 1.0
                elapsed = (float(edge["reviewed_walk_minutes"])
                           if "reviewed_walk_minutes" in edge else meters / 80.0)
                child = State(following, clock + elapsed, total + meters, segment + meters)
                yield child, self.reason(child, clock)
            elif kind == "board":
                mode = self.graph.nodes[following]["mode"]
                ready = clock + (2 if mode == "rail" else 0)
                for run in self.runs:
                    if not run.active or run.provider != mode or run.line_id != following[2]:
                        continue
                    if mode == "bus" and self.graph.nodes[following].get("route_id") != run.route_id:
                        continue
                    for stop, after in zip(run.stops, run.stops[1:]):
                        if stop.stop_id != node[1] or stop.departure < ready or stop.pickup == 1:
                            continue
                        next_node = ("line", after.stop_id, run.line_id)
                        if (not self.graph.has_edge(following, next_node)
                                or self.graph[following][next_node].get("etype") != "ride"):
                            continue
                        token = (run.provider, run.service_key, run.run_id, run.line_id,
                                 stop.sequence, stop.sequence, float(stop.departure),
                                 run.trip_id, run.train_number, run.route_id, run.service_id)
                        child = State(following, float(stop.departure), total, 0.0, token)
                        yield child, self.reason(child, clock)
            elif kind == "ride" and ride is not None:
                run = self.run_by_key[ride[:4]]
                for stop, after in zip(run.stops, run.stops[1:]):
                    if (stop.sequence == ride[4] and stop.stop_id == node[1]
                            and after.stop_id == following[1]
                            and stop.departure >= clock):
                        token = (*ride[:4], after.sequence, *ride[5:])
                        child = State(following, float(after.arrival), total, 0.0, token)
                        yield child, self.reason(child, clock)
            elif kind in ("alight", "xfer") and ride is not None and ride[4] != ride[5]:
                child = State(following, clock + (1.0 if ride[0] == "rail" else 0.0), total, 0.0)
                yield child, self.reason(child, clock)

    def value(self, state):
        if state not in self.index:
            _stop("state_outside_complete_oracle")
        return self.values[self.index[state]]

    def witness(self, state):
        i = self.index[state]
        if math.isinf(self.values[i]):
            return ()
        path, seen = [], set()
        while True:
            if i in seen:
                _stop("cyclic_oracle_witness")
            path.append(i)
            seen.add(i)
            if self.states[i].node == self.query.target:
                return tuple(path)
            i = self.next_step[i]


def verify_dominance_witness(oracle, first, second):
    """Check this actual discard, including a previously expanded dominator."""
    if oracle.value(first) > oracle.value(second):
        _stop("dominance_loses_earliest_completion", retained=oracle.index[first],
              discarded=oracle.index[second], discarded_witness=oracle.witness(second),
              retained_witness=oracle.witness(first))


def verify_open_witness(oracle, states):
    value = min((oracle.value(state) for state in states), default=math.inf)
    if value != oracle.values[0]:
        _stop("open_loses_earliest_completion", expected_witness=oracle.witness(oracle.states[0]))


def verify_first_goal(oracle, state):
    if (state.node != oracle.query.target or state.clock != oracle.values[0]
            or oracle.value(state) != state.clock):
        _stop("first_goal_is_not_earliest", goal=oracle.index.get(state),
              expected_witness=oracle.witness(oracle.states[0]))


def verify_resource_rejection(oracle, state, previous_clock):
    reason = oracle.reason(state, previous_clock)
    if reason is None:
        _stop("resource_pruning_discards_legal_state", state=oracle.index.get(state),
              witness=oracle.witness(state) if state in oracle.index else ())
    return reason


_EXTRA_OBJECTS = (forward._Frontier, forward._Label, forward._compact_queue,
                  engine.find_fastest_path, forward._path, forward.SelectedPath,
                  integration.SelectedPath)
_EXTRA_HASHES = (
    "34bd41ee00e5e1d12d74b88d732f116d78441c6bb55d80e5a664933ad2388225",
    "bb17b85f6bd7dfaa98dcb162be734dbd47f7c30d7d7961ece0baecf7940287fa",
    "eb8762d14fc5734f23349698da44c0b708bbc90d38af94790b66447f229beefb",
    "3e773c159e96b8dc9e8f44651150da8ca2c9662c8e37433aba26a31d2a4b5bd8",
    "10bb976035e6dad0da2c29b675302cc498bc6f2e1c730e12ef2c6f3df673bb3b",
    "886a71c317e22a8d0a37c4a0b81a0ba4467df94a39dd5499f2e11460dc5fe646",
    "194645a0376b7446fa1d9e4d681548727bf64218ecf903db6c1f97f161e54baf",
)
_FRONTIER_METHODS = {name: method for name, method in vars(forward._Frontier).items()
                     if inspect.isfunction(method)}


def _check_contract(choices):
    _check_binary64_environment()
    _check_reviewed_contract(choices, lambda: None)  # Source checks, not an old audit gate.
    current = (forward._Frontier, forward._Label, forward._compact_queue, engine.find_fastest_path,
               forward._path, forward.SelectedPath, integration.SelectedPath)
    for index, (value, original, digest) in enumerate(zip(current, _EXTRA_OBJECTS, _EXTRA_HASHES)):
        if value is not original or _ast_digest(value) != digest:
            _stop("unreviewed_search_implementation", contract_index=index)
    if (any(getattr(forward._Frontier, name) is not method
            for name, method in _FRONTIER_METHODS.items())
            or integration._Frontier is not forward._Frontier
            or integration._Label is not forward._Label
            or integration._compact_queue is not forward._compact_queue
            or engine.MAX_TOTAL_WALK_M != 3000.0 or engine.MAX_WALK_SEG_M != 600.0):
        _stop("different_search_bindings_or_resources")


def _product_children(oracle, state, choices):
    """Comparison side only. The oracle never calls this dispatch/provider."""
    graph, query = oracle.graph, oracle.query
    node, clock, total, segment = state.node, state.clock, state.total, state.segment
    ride = None if state.ride is None else timetable.RideState(*state.ride)
    if node in oracle.virtual:
        _, meters = oracle.virtual[node]
        child = State(query.target, clock + meters / 80.0, total + meters, segment + meters)
        if child.clock <= query.deadline and child.total <= 3000.0 and child.segment <= 600.0:
            yield child
    for following, edge in graph[node].items():
        if query.bus_only and engine._edge_uses_rail(graph, node, following):
            continue
        kind, next_total, next_segment = edge["etype"], total, 0.0
        if kind == "walk":
            meters = edge.get("meters", 0.0) if edge.get("meters", 0.0) > 0 else 1.0
            next_total, next_segment = total + meters, segment + meters
            if next_total > 3000.0 or next_segment > 600.0:
                continue
        options = None
        if kind == "board":
            ready = clock + (2 if graph.nodes[following]["mode"] == "rail" else 0)
            options = choices.board_options(node, following, ready)
        elif kind == "ride" and ride is not None:
            options = choices.ride_options(node, following, clock, ride)
        elif kind in ("alight", "xfer") and ride is not None:
            if ride.sequence == ride.board_sequence:
                continue
            options = ((clock + integration._alight_minutes(ride), None),)
        if options is None:
            arrival = engine.advance_time(graph, choices.manager, node, following, clock,
                                          choices.day_type, use_realtime=False, edge=edge)
            options = () if arrival is None else ((arrival, None),)
        for arrival, next_ride in options:
            if clock <= arrival <= query.deadline:
                yield State(following, float(arrival), next_total, next_segment,
                            None if next_ride is None else tuple(
                                getattr(next_ride, field) for field in _RIDE_FIELDS))


def _line(fragment):
    lines, base = inspect.getsourcelines(forward.search_labels)
    matches = [base + i for i, text in enumerate(lines) if text.rstrip() == fragment]
    if len(matches) != 1:
        _stop("unreviewed_trace_location")
    return matches[0]


class _Observer:
    def __init__(self, oracle, limits):
        self.oracle, self.limits = oracle, limits
        self.counts = Counter()
        self.bounds = self.guard = self.goal = None
        self.goal_chain = ()
        self.loop = _line("    while queue:")
        self.goal_test = _line("        if label.node == target:")
        self.walk_reject = _line("                if total > max_total_walk or segment > max_segment_walk:") + 1
        self.fresh_reject = _line("                if label.ride.sequence == label.ride.board_sequence:") + 1
        self.virtual_test = _line("            if arrival <= deadline and total <= max_total_walk and segment <= max_segment_walk:")
        self.arrival_test = _line("                if arrival < label.time or arrival > deadline:")
        self.nested_codes = {code.co_name: code for code in forward.search_labels.__code__.co_consts
                             if inspect.iscode(code)}

    def rejection(self, state, previous):
        reason = verify_resource_rejection(self.oracle, state, previous)
        self.counts["pruned_" + reason] += 1

    def trace(self, frame, event, arg):
        code, local = frame.f_code, frame.f_locals
        if code is forward._Frontier._dominates.__code__:
            if event == "return" and arg:
                verify_dominance_witness(self.oracle, _state(local["first"]), _state(local["second"]))
                self.counts["dominance_witnesses"] += 1
                new = frame.f_back.f_locals["label"]
                self.counts["generation_dominance_rejections" if local["second"] is new
                            else "invalidated_previous_labels"] += 1
                if local["first"].expanded:
                    self.counts["expanded_dominator_witnesses"] += 1
            return self.trace
        if code is self.nested_codes["offer"]:
            if event == "call":
                state = _state(local["label"])
                reason = self.oracle.reason(state, self.oracle.query.start_minute)
                if reason is not None:
                    self.rejection(state, self.oracle.query.start_minute)
                else:
                    self.oracle.value(state)
                    self.counts["offers"] += 1
            return self.trace
        if code is not forward.search_labels.__code__:
            return None
        if event == "line":
            line = frame.f_lineno
            if line == self.loop:
                # After a full expansion, its descendants replace the popped
                # witness; checking halfway through an expansion is invalid.
                self.bounds, self.guard = local["bounds"], local["arrival_bound"]
                entries = [entry for entry in local["queue"] if entry[2].active and not entry[2].expanded]
                verify_open_witness(self.oracle, (_state(entry[2]) for entry in entries))
                self.counts["open_witness_checkpoints"] += 1
                for priority, _, label in entries:
                    state = _state(label)
                    if priority[0] > self.oracle.value(state):
                        _stop("queued_priority_exceeds_completion", state=self.oracle.index[state],
                              witness=self.oracle.witness(state))
            elif line == self.goal_test and local["label"].node == self.oracle.query.target:
                state = _state(local["label"])
                verify_first_goal(self.oracle, state)
                if float_bits(float(self.guard(state.clock, self.bounds(state.node)))) != float_bits(state.clock):
                    _stop("goal_priority_is_not_clock")
                self.goal = state
                chain, label = [], local["label"]
                while label is not None:
                    chain.append(_state(label))
                    label = label.parent
                self.goal_chain = tuple(reversed(chain))
                self.counts["first_active_goal_pop"] += 1
            elif line == self.walk_reject:
                label = local["label"]
                child = State(local["following"], label.time, local["total"], local["segment"])
                self.rejection(child, label.time)
            elif line == self.fresh_reject:
                self.counts["fresh_alight_rejections"] += 1
            elif line == self.virtual_test:
                label = local["label"]
                child = State(self.oracle.query.target, local["arrival"], local["total"], local["segment"])
                if self.oracle.reason(child, label.time) is not None:
                    self.rejection(child, label.time)
            elif line == self.arrival_test:
                label = local["label"]
                if local["arrival"] < label.time or local["arrival"] > self.oracle.query.deadline:
                    child = State(local["following"], local["arrival"], local["total"], local["segment"])
                    self.rejection(child, label.time)
        return self.trace


def audit_first_arrival(graph, choices, runs, query, *, limits,
                        max_oracle_states, max_oracle_transitions,
                        require_true_top_k=False):
    """Audit a fixed finite static query, or raise; never certify partial work.

    Supply independent RawRun rows, not rows obtained from product choices.
    Oracle work limits are admission limits; neither a suffix-length premise
    nor replacements for the actual search budgets. Observation overhead is
    charged to the unchanged search deadline. Original exceptions propagate.
    """
    if require_true_top_k is not False:
        _stop("true_top_k_is_not_certified")
    if type(limits) is not SearchLimits:
        _stop("explicit_search_limits_required")
    if sys.gettrace() is not None:
        _stop("existing_trace_observer")
    if (type(choices) is not timetable.TimetableChoices or choices.graph is not graph
            or choices.use_realtime is not False or choices.deadline != query.deadline
            or not choices._has_rail_data or not choices._has_bus_data
            or type(choices.manager) is not engine.TimetableManager
            or type(choices.repository) is not GtfsRepository or not choices.repository.trips
            or choices.can_wait_offboard is not True
            or choices.rail_boarding_minutes != 2):
        _stop("canonical_static_fixed_provider_required")
    for owner, names in ((choices.manager, ("train_patterns_weekday", "train_patterns_weekend")),
                         (choices.repository, ("trips", "stop_times", "stop_time_boarding",
                          "routes", "stops", "route_name_to_id", "timetable_index"))):
        if any(type(getattr(owner, name)) not in (dict, defaultdict) for name in names):
            _stop("custom_static_source_container")
    if choices._rail_built or any(getattr(choices, name) for name in (
            "_runs", "_positions", "_rail_departures", "_rail_clocks", "_rail_delays",
            "_rail_segments", "_bus_departures", "_bus_run_cache", "_line_route_cache",
            "_bus_pattern_terminals", "_bus_pole_stop_ids", "_concrete_board_options")):
        _stop("fresh_search_provider_required")
    _check_contract(choices)
    before = (_graph_digest(graph, lambda: None),
              _sources_digest(choices.manager, choices.repository, lambda: None),
              _digest_rows(choices.repository.timetable_index.items(), lambda: None))
    oracle = CompletionOracle(graph, runs, query, max_states=max_oracle_states,
                              max_transitions=max_oracle_transitions)
    comparison = timetable.TimetableChoices(
        graph, choices.manager, choices.day_type, use_realtime=False,
        deadline=query.deadline, bus_repository=choices.repository)
    for i, state in enumerate(oracle.states):
        if state.node == query.target:
            continue
        expected = {oracle.states[j] for j in oracle.edges[i]}
        actual = set(_product_children(oracle, state, comparison))
        if actual != expected:
            _stop("independent_transition_relation_differs", state=i,
                  missing=len(expected - actual), unexpected=len(actual - expected),
                  expected_witness=oracle.witness(state))
    observer = _Observer(oracle, limits)
    generator = integration.search_labels(
        graph, choices, query.start, query.target, mode="time",
        start_minute=query.start_minute, max_search=1,
        max_visited=limits.max_visited, max_expanded=limits.max_expanded,
        max_travel_min=query.max_travel_min, time_limit_sec=limits.time_limit_sec,
        max_total_walk=3000.0, max_segment_walk=600.0, walk_speed=80.0,
        rail_boarding_minutes=2, virtual_connections=dict(query.virtual),
        edge_uses_rail=lambda u, v: query.bus_only and engine._edge_uses_rail(graph, u, v),
        advance_time=lambda u, v, clock, edge: engine.advance_time(
            graph, choices.manager, u, v, clock, choices.day_type,
            use_realtime=False, edge=edge))
    try:
        sys.settrace(observer.trace)
        candidate = next(generator, None)
    except BaseException as error:
        # Retain the same exception, traceback, reason and original diagnostics.
        error.tokyo_correctness_audit = {"certified": False, "counts": dict(observer.counts),
                                       "search_profile": limits.profile}
        raise
    finally:
        sys.settrace(None)
        generator.close()
    if observer.bounds is None or observer.guard is None:
        _stop("search_bounds_not_observed")
    guard_args = dict(start_minute=query.start_minute, deadline=query.deadline,
                      max_forward_steps=limits.max_visited,
                      max_reverse_steps=observer.bounds.report["nodes"] + 1,
                      max_edge_minutes=observer.bounds.report["max_edge_minutes"])
    verify_guard_coefficients(observer.guard, **guard_args)
    verify_guard_equivalence(observer.guard, TimeRoundingGuard(**guard_args))
    for i, state in enumerate(oracle.states):
        priority = observer.guard(state.clock, observer.bounds(state.node))
        if priority > oracle.values[i]:
            _stop("state_priority_exceeds_completion", state=i, witness=oracle.witness(state))
    optimum = oracle.values[0]
    if candidate is None:
        if not math.isinf(optimum) or observer.goal is not None:
            _stop("queue_exhausted_with_legal_completion", witness=oracle.witness(oracle.states[0]))
        termination = "queue_exhausted"
    else:
        if (observer.goal is None or observer.counts["first_active_goal_pop"] != 1
                or float_bits(float(candidate["path"].arrival_minute)) != float_bits(optimum)):
            _stop("yield_differs_from_first_goal")
        chain, path = observer.goal_chain, candidate["path"]
        expected_rides = {i: state.ride for i, state in enumerate(chain[1:]) if state.ride is not None}
        actual_rides = {i: tuple(getattr(ride, field) for field in _RIDE_FIELDS)
                        for i, ride in path.edge_rides.items()}
        if (list(path) != [state.node for state in chain]
                or tuple(float_bits(float(clock)) for clock in path.edge_times)
                != tuple(float_bits(state.clock) for state in chain[1:])
                or actual_rides != expected_rides or candidate["walk_m"] != chain[-1].total
                or chain[0] != oracle.states[0]
                or any(oracle.index[after] not in oracle.edges[oracle.index[before]]
                       for before, after in zip(chain, chain[1:]))):
            _stop("returned_path_is_not_legal_goal_witness")
        termination = "first_goal_pop_consumer_close"
    _check_contract(choices)
    after = (_graph_digest(graph, lambda: None),
             _sources_digest(choices.manager, choices.repository, lambda: None),
             _digest_rows(choices.repository.timetable_index.items(), lambda: None))
    if before != after:
        _stop("source_or_graph_changed")
    return {
        "scope": "fixed_finite_operational_query_primary_arrival_only",
        "earliest_arrival_verified": True,
        "independent_transition_closure_verified": True,
        "dominance_completion_witnesses_verified": True,
        "resource_pruning_verified": True,
        "first_goal_pop_verified": candidate is not None,
        "queue_exhaustion_verified": candidate is None,
        "finite_query_priority_admissibility_verified": True,
        "same_arrival_cost_optimality_verified": False,
        "candidate_class_completeness_verified": False,
        "true_top_k_verified": False,
        "unexpanded_suffix_step_bound_verified": False,
        "unconditional_search_correctness_verified": False,
        "operational_calendar_verified": False, "realtime_verified": False,
        "production_fastest_limits_used": limits.profile == "production_fastest",
        "search_entrypoint": "tokyo_search_labels.search_labels",
        "public_find_fastest_path_executed": False,
        "route_search_executed": True,
        "search_limit_profile": limits.profile,
        "max_visited": limits.max_visited, "max_expanded": limits.max_expanded,
        "time_limit_sec": limits.time_limit_sec, "max_search": 1,
        "guard_parameters": observer.guard.report,
        "oracle_states": len(oracle.states), "oracle_attempts": oracle.attempt_count,
        "oracle_work_limits": {"states": max_oracle_states, "transitions": max_oracle_transitions},
        "counts": dict(observer.counts), "termination": termination,
        "arrival_minute": None if candidate is None else candidate["path"].arrival_minute,
        "graph_digest": before[0], "source_digest": before[1],
        "query_and_raw_runs_digest": _digest_rows((query, runs), lambda: None),
        "accepted_audits_rerun": False, "runtime_selection": "not_selected_audit_only",
    }
