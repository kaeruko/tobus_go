"""Scheduled dataset integration for the existing shared label algorithm.

Offline/opt-in only. This module has no independent search loop, realtime
fetch, automatic provider selection, fare approval or production runtime hook.
The initial integration explicitly uses zero lower bounds for correctness work.
"""
from __future__ import annotations

import bisect
from collections import ChainMap
from dataclasses import dataclass, replace
from datetime import date
from fractions import Fraction
import itertools
import math

from route_engine import RouteContractError
from transit_dataset import PublishedMinuteProvenance
from transit_network import StandardTransferLink, DirectedWalkLink, TransitNetworkSnapshot, line_node, physical_node
from transit_search_labels import SelectedPath, _compact_queue, search_labels
from transit_time import exact_minutes


@dataclass(frozen=True, slots=True)
class ScheduledRideState:
    trip_id: str
    service_date: date
    pattern: int
    position: int
    board_position: int
    sequence: int
    board_sequence: int

    @property
    def future_key(self):
        # Retain the boarding origin for future boarding/alighting-aware fares.
        return (self.service_date, self.trip_id, self.pattern,
                self.position, self.board_position)


class DatasetTimetableChoices:
    can_wait_offboard = True

    def __init__(self, snapshot: TransitNetworkSnapshot, *, service_date: date,
                 deadline: int | float | Fraction):
        if type(service_date) is not date:
            raise ValueError("service_date must be a date")
        self.snapshot = snapshot
        self.service_date = service_date
        self.deadline = exact_minutes(deadline, field="deadline")
        self.active_trips = None
        self._board_cache = {}

    def prepare(self, check_deadline):
        """Build query-local service scope inside the core's safety deadline."""
        if self.active_trips is not None:
            raise RouteContractError("scheduled choices already prepared")
        active_services = set()
        for dataset in self.snapshot.datasets:
            for index, (key, calendar) in enumerate(dataset.calendars.items()):
                if index % 256 == 0:
                    check_deadline()
                if calendar.active_on(self.service_date):
                    active_services.add(key)
            for index, exception in enumerate(dataset.service_exceptions):
                if index % 256 == 0:
                    check_deadline()
                if exception.day == self.service_date:
                    if exception.exception_type == 1:
                        active_services.add(exception.service_id)
                    else:
                        active_services.discard(exception.service_id)
        active = set()
        for index, (trip_id, trip) in enumerate(self.snapshot.trips.items()):
            if index % 256 == 0:
                check_deadline()
            if trip.service_id in active_services:
                active.add(trip_id)
        check_deadline()
        self.active_trips = frozenset(active)

    def _require_prepared(self):
        if self.active_trips is None:
            raise RouteContractError("scheduled choices require explicit deadline-scoped preparation")

    def board_options(self, u, v, ready):
        self._require_prepared()
        ready = exact_minutes(ready, field="boarding ready time")
        key = u, v, ready
        if key in self._board_cache:
            return self._board_cache[key]
        if (u, v) not in self.snapshot.departures:
            raise RouteContractError(f"unknown scheduled boarding edge: {(u, v)!r}")
        rows = self.snapshot.departures[u, v]
        if ready > self.deadline:
            return ()
        first = bisect.bisect_left(rows, ready, key=lambda row: row[0])
        end = bisect.bisect_right(rows, self.deadline, key=lambda row: row[0])
        options = []
        for departure, trip_id, position in itertools.islice(rows, first, end):
            if trip_id not in self.active_trips:
                continue
            row = self.snapshot.rows_by_trip[trip_id][position]
            options.append((departure, ScheduledRideState(
                trip_id, self.service_date, self.snapshot.trip_patterns[trip_id],
                position, position, row.sequence, row.sequence)))
        result = tuple(options)
        self._board_cache[key] = result
        return result

    def ride_options(self, u, v, clock, ride):
        self._require_prepared()
        clock = exact_minutes(clock, field="selected ride clock")
        if (ride.trip_id not in self.active_trips or ride.service_date != self.service_date
                or ride.pattern != self.snapshot.trip_patterns[ride.trip_id]
                or u != line_node(ride.pattern, ride.position)
                or v != line_node(ride.pattern, ride.position + 1)):
            raise RouteContractError("selected scheduled run/occurrence does not match ride edge")
        rows = self.snapshot.rows_by_trip[ride.trip_id]
        if ride.position + 1 >= len(rows):
            raise RouteContractError("selected run continues past its terminal")
        current, following = rows[ride.position:ride.position + 2]
        if clock > current.departure_minute:
            raise RouteContractError("selected run departure is before current arrival clock")
        return ((following.arrival_minute, replace(
            ride, position=ride.position + 1, sequence=following.sequence)),)


@dataclass(frozen=True, slots=True)
class NetworkSearchParameters:
    max_candidates: int = 5
    max_boardings: int = 6
    max_visited: int = 100_000
    max_travel_minutes: int | float | Fraction = 240.0
    time_limit_seconds: float = 15.0
    max_total_walk_meters: float = 3000.0
    max_segment_walk_meters: float = 600.0
    rail_boarding_minutes: int | float | Fraction = 0.0
    bus_alighting_minutes: int | float | Fraction = 0.0
    rail_alighting_minutes: int | float | Fraction = 0.0
    few_transfers_tiebreak: str = "cost"

    def __post_init__(self):
        for name in ("max_candidates", "max_boardings", "max_visited"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive int")
        for name in ("time_limit_seconds", "max_total_walk_meters", "max_segment_walk_meters"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        for name in ("max_travel_minutes", "rail_boarding_minutes",
                     "bus_alighting_minutes", "rail_alighting_minutes"):
            exact_minutes(getattr(self, name), field=name)
        if self.time_limit_seconds == 0:
            raise ValueError("time_limit_seconds must be positive")
        if self.few_transfers_tiebreak not in ("cost", "arrival"):
            raise ValueError("few_transfers_tiebreak must be cost or arrival")


@dataclass(frozen=True, slots=True)
class NetworkRideEvent:
    trip_id: str
    source_trip_id: str
    route_id: str
    mode: str
    service_date: date
    feed_version: str
    from_stop_id: str
    to_stop_id: str
    from_sequence: int
    to_sequence: int
    departure_minute: Fraction
    arrival_minute: Fraction
    stop_ids: tuple[str, ...]
    source_pattern_id: str | None = None
    train_number: str | None = None
    source_train_type: str | None = None
    source_operator_id: str | None = None
    source_pattern_title: str | None = None
    from_stop_name_en: str | None = None
    to_stop_name_en: str | None = None
    route_name_en: str | None = None
    departure_provenance: PublishedMinuteProvenance | None = None
    arrival_provenance: PublishedMinuteProvenance | None = None


@dataclass(frozen=True, slots=True)
class NetworkWalkEvent:
    pinned_link: DirectedWalkLink
    departure_minute: Fraction
    arrival_minute: Fraction


@dataclass(frozen=True, slots=True)
class NetworkStandardTransferEvent:
    standard: StandardTransferLink
    departure_minute: Fraction
    arrival_minute: Fraction


@dataclass(frozen=True, slots=True)
class NetworkJourney:
    departure_minute: Fraction
    arrival_minute: Fraction
    cost: float
    walk_meters: float
    events: tuple[NetworkRideEvent | NetworkWalkEvent | NetworkStandardTransferEvent, ...]
    clock_profiles: tuple[str, ...] = ()

    @property
    def physical_walk_meters(self):
        # walk_meters is the charged label resource. An official transfer
        # standard has unknown physical distance, never a measured zero metres.
        return None if any(isinstance(e, NetworkStandardTransferEvent) for e in self.events) else self.walk_meters

    @property
    def rides(self):
        return sum(isinstance(event, NetworkRideEvent) for event in self.events)


class _ZeroBounds:
    def __init__(self, mode):
        self.mode = mode
        self.report = {}

    def __call__(self, node, segment_walk=None):
        return (0, 0.0) if self.mode == "fewTransfers" else 0.0


def _journey(snapshot, candidate, departure):
    path = candidate["path"]
    events, boarding = [], None
    previous = departure
    last_ride = None
    for index, (u, v) in enumerate(zip(path, path[1:])):
        edge = snapshot.graph[u][v]
        arrival = path.edge_times[index]
        if edge["etype"] == "board":
            boarding = path.edge_rides[index], arrival
        elif edge["etype"] == "ride":
            last_ride = path.edge_rides[index], arrival
        elif edge["etype"] == "alight":
            if boarding is None or last_ride is None:
                raise RouteContractError("selected journey alights without a travelled run")
            start, boarded_at = boarding
            end, arrived_at = last_ride
            if start.trip_id != end.trip_id or start.board_position != end.board_position:
                raise RouteContractError("selected journey changes its run mid-ride")
            rows = snapshot.rows_by_trip[start.trip_id]
            trip = snapshot.trips[start.trip_id]
            route = snapshot.routes[trip.route_id]
            events.append(NetworkRideEvent(
                trip.id, trip.source_id, route.id, route.mode.value,
                start.service_date, snapshot.feed_versions[trip.id.split(":", 1)[0]],
                rows[start.position].stop_id, rows[end.position].stop_id,
                start.sequence, end.sequence, boarded_at, arrived_at,
                tuple(row.stop_id for row in rows[start.position:end.position + 1]),
                trip.source_pattern_id, trip.train_number, trip.source_train_type,
                trip.source_operator_id, trip.source_pattern_title,
                snapshot.stops[rows[start.position].stop_id].name_en,
                snapshot.stops[rows[end.position].stop_id].name_en, route.name_en,
                rows[start.position].source.departure_provenance,
                rows[end.position].source.arrival_provenance))
            boarding = last_ride = None
        elif edge["etype"] == "walk":
            if "standard_transfer" in edge:
                events.append(NetworkStandardTransferEvent(edge["standard_transfer"], previous, arrival))
            else:
                events.append(NetworkWalkEvent(edge["reviewed_link"], previous, arrival))
        previous = arrival
    if boarding is not None:
        raise RouteContractError("selected journey ends on an unfinished ride")
    return NetworkJourney(departure, path.arrival_minute, candidate["cost"],
                          candidate["walk_m"], tuple(events),
                          tuple(dataset.metadata.clock_profile for dataset in snapshot.datasets))


class _TransitGoalView:
    """Read-only final-alighting suffix over the SAME reviewed graph.

    Only actual alight edges enter the suffix; search_labels already rejects
    alighting before travelling a stop. Copy only reverse-reachable walk nodes
    and their original edges, without computing new connections or weights.
    Normalizing the selected path restores every original concrete node.
    """
    def __init__(self, graph, destination):
        self.graph=graph
        suffix={destination};pending=[destination]
        while pending:
            node=pending.pop()
            for previous,edge in graph.pred[node].items():
                if edge['etype']=='walk' and previous not in suffix:
                    suffix.add(previous);pending.append(previous)
        copies={node:('transit_goal',node) for node in suffix}
        self.originals={copy:node for node,copy in copies.items()}
        self.nodes=ChainMap({copy:graph.nodes[node] for node,copy in copies.items()},graph.nodes)
        self.additions={copy:{} for copy in copies.values()}
        for node,copy in copies.items():
            for previous,edge in graph.pred[node].items():
                if edge['etype']=='alight':
                    self.additions.setdefault(previous,{})[copy]=edge
                elif edge['etype']=='walk':
                    self.additions[copies[previous]][copy]=edge
        self.adjacency={node:(extra if node in self.originals else ChainMap(extra,graph[node]))
                        for node,extra in self.additions.items()}
        self.target=copies[destination]

    def __getitem__(self,node):
        return self.adjacency[node] if node in self.adjacency else self.graph[node]

    def path(self,nodes,*args):
        return SelectedPath([self.originals.get(node,node) for node in nodes],*args)


def search_network(
    snapshot: TransitNetworkSnapshot, origin_stop_id: str, destination_stop_id: str,
    *, service_date: date, departure_minute: int | float | Fraction, mode: str,
    parameters: NetworkSearchParameters,
    _request_choices=None,
    _require_transit=False,
) -> tuple[NetworkJourney, ...]:
    if origin_stop_id not in snapshot.stops or destination_stop_id not in snapshot.stops:
        raise ValueError("unknown network origin/destination stop")
    departure_minute = exact_minutes(departure_minute, field="departure_minute")
    if not isinstance(parameters, NetworkSearchParameters):
        raise ValueError("explicit NetworkSearchParameters are required")
    travel_minutes = exact_minutes(parameters.max_travel_minutes, field="max_travel_minutes")
    boarding_minutes = exact_minutes(parameters.rail_boarding_minutes, field="rail_boarding_minutes")
    bus_alighting = exact_minutes(parameters.bus_alighting_minutes, field="bus_alighting_minutes")
    rail_alighting = exact_minutes(parameters.rail_alighting_minutes, field="rail_alighting_minutes")
    # Coordinate destinations are distance ordered: later access walks narrow
    # the transit window. Retain ONE existing provider for the same source,
    # origin and start, while its lookup window covers the requested window.
    # search_labels still rejects EVERY option after this pair's own deadline;
    # no search limit, clock, accepted departure or transfer is extended.
    choices_key = (id(snapshot), service_date, origin_stop_id, departure_minute, mode)
    query_deadline = departure_minute + travel_minutes
    if (_request_choices is None or _request_choices.get("key") != choices_key or
            _request_choices["choices"].deadline < query_deadline):
        choices = DatasetTimetableChoices(snapshot, service_date=service_date,
                                         deadline=query_deadline)
        if _request_choices is not None:
            _request_choices.update(key=choices_key, choices=choices,
                preparations=_request_choices.get("preparations", 0)+1)
    else:
        choices = _request_choices["choices"]
        _request_choices["reuse_hits"] = _request_choices.get("reuse_hits", 0)+1

    def prepare_bounds(check_deadline, deadline):
        # Explicit correctness baseline, not recovery from a failed A* builder.
        check_deadline()
        if choices.active_trips is None:
            choices.prepare(check_deadline)
        else:
            check_deadline()
        return _ZeroBounds(mode), lambda cost, remaining: cost, lambda clock, remaining: clock

    def advance_time(u, v, clock, edge):
        if edge["etype"] != "walk":
            raise RouteContractError(f"unexpected unscheduled edge: {edge['etype']}")
        return clock + edge["reviewed_walk_minutes"]

    def alight_minutes(ride):
        route = snapshot.routes[snapshot.trips[ride.trip_id].route_id]
        return bus_alighting if route.mode.value == "bus" else rail_alighting

    graph=snapshot.graph
    target=physical_node(destination_stop_id)
    path_factory=SelectedPath
    if _require_transit:
        graph=_TransitGoalView(graph,target)
        target=graph.target
        path_factory=graph.path
    generator = search_labels(
        graph, choices, physical_node(origin_stop_id), target,
        mode=mode, start_minute=departure_minute,
        max_search=parameters.max_candidates, max_visited=parameters.max_visited,
        max_travel_min=travel_minutes, time_limit_sec=parameters.time_limit_seconds,
        max_total_walk=parameters.max_total_walk_meters,
        max_segment_walk=parameters.max_segment_walk_meters,
        walk_speed=80.0, rail_boarding_minutes=boarding_minutes,
        advance_time=advance_time, virtual_connections={}, edge_uses_rail=lambda u, v: False,
        prepare_bounds=prepare_bounds, path_signature=tuple, path_factory=path_factory,
        compact_queue=_compact_queue,
        ride_options=lambda u, v, clock, ride, edge: choices.ride_options(u, v, clock, ride),
        alight_minutes=alight_minutes, walk_meters=lambda edge: edge["meters"],
        max_boardings=parameters.max_boardings,
        few_transfers_tiebreak=parameters.few_transfers_tiebreak,
    )
    try:
        return tuple(_journey(snapshot, candidate, departure_minute)
                     for candidate in itertools.islice(generator, parameters.max_candidates))
    finally:
        generator.close()

