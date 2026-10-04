"""Query-local Tokyo timetable choices with a concrete vehicle run.

Waiting is represented by choosing any departure after the ready time.  Once
boarded, a state can only move to the next occurrence on that same run.  The
old small timetable doubles used by graph-only tests retain an opaque fallback;
they do not supply enough data to claim the concrete-run contract.
"""

from __future__ import annotations

import bisect
import copy
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class RideState:
    provider: str
    service_key: str
    run_id: str
    line_id: Any
    sequence: int
    board_sequence: int
    departure_minute: float
    trip_id: str | None = None
    train_number: str | None = None
    route_id: str | None = None
    service_id: str | None = None

    @property
    def future_key(self):
        return (self.provider, self.service_key, self.run_id,
                self.line_id, self.sequence)


@dataclass(frozen=True, slots=True)
class _Stop:
    stop_id: str
    sequence: int
    arrival: float
    departure: float


@dataclass(frozen=True, slots=True)
class _Run:
    provider: str
    run_id: str
    stops: tuple[_Stop, ...]
    train_number: str | None = None
    trip_id: str | None = None
    route_id: str | None = None
    service_id: str | None = None
    source_run_key: str | None = None


def _railway_id(station_id):
    if not isinstance(station_id, str) or not station_id.startswith("odpt.Station:"):
        return None
    return "odpt.Railway:" + station_id.split(":", 1)[1].rsplit(".", 1)[0]


def _normalize_route(value):
    table = str.maketrans("０１２３４５６７８９　（）", "0123456789 ()")
    return str(value).translate(table).replace(" ", "")


def _scheduled_clock(value):
    # ODPT and GTFS source clocks are integral service-day minutes.  Preserve
    # that wire type in pinned identity metadata after internal float math.
    return int(value) if float(value).is_integer() else value


def _calendar_matches(calendar, day_type):
    if not calendar:
        return True  # Legacy saved tables do not retain this source field.
    day = str(day_type)
    if "Weekday" in calendar:
        return day == "weekday"
    saturday, holiday = "Saturday" in calendar, "Holiday" in calendar
    if day == "weekday" and (saturday or holiday):
        return False
    if day == "saturday":
        return saturday
    if day == "holiday":
        return holiday
    return True  # Historical callers used a generic 'weekend' string.


def _freeze_manager(manager, use_realtime, delays_snapshot):
    """Copy mutable inputs, leaving static large departure arrays shared.

    Static graph/feed data is installed as a complete version outside a query.
    Realtime containers can be updated during a query, so none of those remain
    shared with the live manager.  A fresh cache avoids modifying its caches.
    """
    frozen = copy.copy(manager)
    for attribute in (
        "realtime_delays", "bus_realtime_delays", "latest_bus_positions",
        "train_status_text", "train_service_suspended", "latest_train_info",
        "latest_gtfsrt_vehicles",
    ):
        if hasattr(manager, attribute):
            setattr(frozen, attribute, copy.deepcopy(getattr(manager, attribute)))
    if hasattr(manager, "realtime_delays"):
        frozen.realtime_delays = dict(
            delays_snapshot if use_realtime and delays_snapshot is not None
            else (getattr(manager, "realtime_delays", {}) if use_realtime else {})
        )
    if not use_realtime:
        for attribute in ("bus_realtime_delays", "train_status_text"):
            if hasattr(frozen, attribute):
                setattr(frozen, attribute, {})
        if hasattr(frozen, "train_service_suspended"):
            frozen.train_service_suspended = set()
    if hasattr(manager, "_service_departures_cache"):
        frozen._service_departures_cache = {}
    return frozen


class TimetableChoices:
    """Enumerate feasible boarding choices and same-run continuations.

    ``ready_minute`` already includes rail boarding preparation.  All clocks
    are service-day minutes (including values greater than 1440), and every
    option is checked against the original query's common ``deadline``.
    """

    def __init__(self, graph, manager, day_type="weekday", use_realtime=True,
                 delays_snapshot=None, deadline=float("inf"),
                 bus_repository=None, rail_boarding_minutes=2):
        self.graph = graph
        self.day_type = day_type
        self.use_realtime = use_realtime
        self.deadline = deadline
        self.rail_boarding_minutes = rail_boarding_minutes
        self.manager = _freeze_manager(manager, use_realtime, delays_snapshot)
        self.repository = bus_repository
        date = getattr(day_type, "service_date", None)
        self.service_key = date.isoformat() if date is not None else str(day_type)
        self.active_services = (
            frozenset(day_type.active_service_ids)
            if getattr(day_type, "has_gtfs_calendar", False) else None
        )
        self._runs = {}
        self._positions = {}
        self._rail_departures = defaultdict(list)
        self._rail_clocks = {}
        self._rail_delays = {}
        self._rail_segments = {}
        self._rail_built = False
        self._bus_departures = {}
        self._bus_run_cache = {}
        self._line_route_cache = {}
        self._delays = dict(getattr(self.manager, "realtime_delays", {}))
        self._has_rail_data = hasattr(self.manager, "train_patterns_weekday")
        self._has_bus_data = hasattr(self.manager, "bus_departures_weekday")
        # Opaque custom timetable objects do not establish arbitrary waiting
        # choices; the search must compare their times conservatively.
        self.can_wait_offboard = (
            self._has_rail_data and self._has_bus_data
            and self.repository is not None
            and bool(getattr(self.repository, "trips", {}))
        )

    def _save_run(self, run):
        self._runs[(run.provider, run.run_id)] = run
        self._positions[(run.provider, run.run_id)] = {
            stop.sequence: index for index, stop in enumerate(run.stops)
        }

    def _rail_delay(self, station, train_number):
        if not self.use_realtime:
            return 0.0
        delay = float(self._delays.get(train_number, 0.0)) / 60.0
        if delay == 0 and "遅延" in getattr(self.manager, "train_status_text", {}).get(
            _railway_id(station), ""
        ):
            delay = 10.0
        return delay

    def _rail_suspended(self, station):
        return self.use_realtime and _railway_id(station) in getattr(
            self.manager, "train_service_suspended", set()
        )

    def _build_rail(self):
        if self._rail_built:
            return
        self._rail_built = True
        target = getattr(
            self.manager,
            "train_patterns_weekday" if self.day_type == "weekday"
            else "train_patterns_weekend", {},
        )
        groups = defaultdict(list)
        seen = set()
        for station, records in target.items():
            for record in records:
                if not _calendar_matches(record.get("calendar"), self.day_type):
                    continue
                number = str(record.get("train_num") or "")
                explicit = record.get("run_key") or record.get("run_id")
                # Saved Tokyo data has one entry for each calendar/railway/num.
                # New loads retain the source run key and stop sequence, which
                # also distinguish repeated numbers in independently supplied
                # runs.  Calendar and railway are included in legacy keys.
                run_key = str(explicit or (
                    f"legacy:{self.day_type}:{_railway_id(station)}:{number}"
                ))
                sequence = record.get("stop_sequence")
                identity = (run_key, station, record.get("next_sta"),
                            record.get("dep"), record.get("arr"), sequence)
                if identity in seen:
                    continue
                seen.add(identity)
                dep, arr = float(record["dep"]), float(record["arr"])
                following = record.get("next_sta")
                if following is None or arr < dep:
                    continue
                groups[(run_key, number)].append((station, following, dep, arr, sequence))

        for (run_key, number), edges in groups.items():
            explicit_order = all(edge[4] is not None for edge in edges)
            edges.sort(key=(lambda e: (e[4], e[2], e[0], e[1])) if explicit_order
                       else (lambda e: (e[2], e[3], e[0], e[1])))
            chains = []
            for edge in edges:
                current, following, dep, arr, sequence = edge
                compatible = [
                    chain for chain in chains
                    if chain[-1][1] == current and chain[-1][3] <= dep
                    and (not explicit_order or chain[-1][4] + 1 == sequence)
                ]
                # Ambiguous unannotated data is split, never guessed into a
                # continuation.  A split remains boardable at its own origin.
                if len(compatible) == 1:
                    compatible[0].append(edge)
                else:
                    chains.append([edge])
            for chain_index, chain in enumerate(chains):
                concrete_key = f"{self.service_key}|{run_key}|part:{chain_index}"
                first = chain[0]
                first_sequence = int(first[4]) if explicit_order else 0
                stops = [_Stop(first[0], first_sequence, first[2], first[2])]
                for index, edge in enumerate(chain):
                    sequence = int(edge[4]) + 1 if explicit_order else index + 1
                    departure = chain[index + 1][2] if index + 1 < len(chain) else edge[3]
                    stops.append(_Stop(edge[1], sequence, edge[3], departure))
                run = _Run("rail", concrete_key, tuple(stops), train_number=number,
                           source_run_key=run_key)
                self._save_run(run)
                delay = self._rail_delay(stops[0].stop_id, number)
                self._rail_delays[concrete_key] = delay
                self._rail_segments[concrete_key] = tuple({
                    "origin_id": edge[0], "next_sta": edge[1],
                    "dep": _scheduled_clock(edge[2]), "arr": _scheduled_clock(edge[3]),
                    "train_num": number,
                    "run_key": run_key,
                    "stop_sequence": stops[index].sequence,
                    "actual_dep": edge[2] + delay, "actual_arr": edge[3] + delay,
                } for index, edge in enumerate(chain))
                for index, stop in enumerate(run.stops[:-1]):
                    actual = stop.departure + delay
                    self._rail_departures[stop.stop_id].append((actual, concrete_key, stop.sequence))
        for station, entries in self._rail_departures.items():
            entries.sort()
            self._rail_clocks[station] = tuple(entry[0] for entry in entries)

    def _line_id(self, node):
        return node[2] if len(node) > 2 else self.graph.nodes[node].get("line")

    def _rail_options(self, u, v, ready):
        station = v[1]
        if self._rail_suspended(station):
            return ()
        self._build_rail()
        entries = self._rail_departures.get(station, ())
        start = bisect.bisect_left(self._rail_clocks.get(station, ()), ready)
        out = []
        for departure, run_id, sequence in entries[start:]:
            if departure > self.deadline:
                break
            run = self._runs[("rail", run_id)]
            index = self._positions[("rail", run_id)][sequence]
            next_station = run.stops[index + 1].stop_id
            next_node = ("line", next_station, self._line_id(v))
            if not self.graph.has_edge(v, next_node):
                continue
            edge = self.graph[v][next_node]
            if edge.get("etype") != "ride" or edge.get("mode", "rail") != "rail":
                continue
            state = RideState("rail", self.service_key, run_id, self._line_id(v),
                              sequence, sequence, departure, train_number=run.train_number)
            out.append((departure, state))
        return tuple(out)

    def _stop_id(self, pole):
        if not isinstance(pole, str):
            return None
        if "BusstopPole" in pole:
            match = re.search(r"\.(\d{1,5})\.(\d{1,2})(?:\.|$)", pole)
            return f"{int(match[1]):04d}-{int(match[2]):02d}" if match else None
        return pole if pole in getattr(self.repository, "stops", {}) else None

    def _bus_route(self, node):
        line_id = self._line_id(node)
        if line_id in self._line_route_cache:
            return self._line_route_cache[line_id]
        raw = self.graph.nodes[node].get("route_id")
        route = raw if raw in getattr(self.repository, "routes", {}) else None
        if route is None:
            display = self.graph.nodes[node].get("disp") or ""
            if display:
                route = getattr(self.repository, "route_name_to_id", {}).get(
                    _normalize_route(display.split()[0])
                )
        self._line_route_cache[line_id] = route
        return route

    def _bus_delay(self, node):
        route = self.graph.nodes[node].get("route_id")
        return float(getattr(self.manager, "bus_realtime_delays", {}).get(route, 0.0)) \
            if self.use_realtime else 0.0

    def _bus_run(self, trip_id):
        if trip_id in self._bus_run_cache:
            return self._bus_run_cache[trip_id]
        trip = self.repository.trips.get(trip_id)
        times = self.repository.stop_times.get(trip_id, {})
        if not trip or not times:
            self._bus_run_cache[trip_id] = None
            return None
        stops = tuple(_Stop(stop_id, int(sequence), float(arrival), float(departure))
                      for sequence, (stop_id, arrival, departure) in sorted(times.items()))
        if any(stop.arrival > stop.departure for stop in stops) or any(
            right.arrival < left.departure for left, right in zip(stops, stops[1:])
        ):
            self._bus_run_cache[trip_id] = None
            return None
        run_id = f"{getattr(self.repository, 'feed_id', 'toei-bus')}|{self.service_key}|{trip_id}"
        run = _Run("bus", run_id, stops, trip_id=trip_id,
                   route_id=trip.get("route_id"), service_id=trip.get("service_id"))
        self._save_run(run)
        self._bus_run_cache[trip_id] = run
        return run

    def _bus_options(self, u, v, ready):
        route = self._bus_route(v)
        stop_id = self._stop_id(u[1])
        if route is None or stop_id is None:
            return ()
        key = (route, stop_id)
        if key not in self._bus_departures:
            entries = tuple(getattr(self.repository, "timetable_index", {}).get(
                f"{route}|{stop_id}", ()))
            self._bus_departures[key] = (entries, tuple(entry[0] for entry in entries))
        entries, clocks = self._bus_departures[key]
        delay = self._bus_delay(v)
        start = bisect.bisect_left(clocks, ready - delay)
        out = []
        for scheduled, sequence, trip_id in entries[start:]:
            departure = float(scheduled) + delay
            if departure > self.deadline:
                break
            trip = self.repository.trips.get(trip_id)
            if not trip or self.active_services is not None and trip.get("service_id") not in self.active_services:
                continue
            run = self._bus_run(trip_id)
            if run is None:
                continue
            position = self._positions[("bus", run.run_id)].get(sequence)
            if position is None or position + 1 == len(run.stops):
                continue
            following = run.stops[position + 1].stop_id
            # The graph may contain multiple patterns of the same route.  A
            # selected trip must have an actual next stop reachable in this
            # pattern; matching only route_id would permit direction changes.
            if not any(
                edge.get("etype") == "ride" and edge.get("mode", "bus") == "bus"
                and self._stop_id(node[1]) == following
                for node, edge in self.graph[v].items()
            ):
                continue
            state = RideState("bus", self.service_key, run.run_id, self._line_id(v),
                              sequence, sequence, departure, trip_id=trip_id,
                              route_id=run.route_id, service_id=run.service_id)
            out.append((departure, state))
        return tuple(out)

    def _fallback_options(self, u, v, ready, mode):
        # Only managers without concrete timetable data use this compatibility
        # path.  Production managers with empty schedules yield no options.
        if mode == "rail":
            departure = ready
            identity = "opaque-rail"
        else:
            route = self.graph.nodes[v].get("route_id")
            departure, identity = self.manager.get_next_bus_departure(
                u[1], route, ready, pole_name=self.graph.nodes[u].get("name"),
                day_type=self.day_type, use_realtime=self.use_realtime,
            )
            if departure is None:
                return ()
        if departure > self.deadline:
            return ()
        # Opaque runs cannot identify equivalent continuations.  Distinguish
        # boarding place and departure to prevent accidental cross-run merging.
        run_id = repr((mode, self._line_id(v), u, v, identity, departure))
        state = RideState("opaque-" + mode, self.service_key, run_id,
                          self._line_id(v), 0, 0, float(departure))
        return ((float(departure), state),)

    def board_options(self, u, v, ready_minute):
        if ready_minute > self.deadline:
            return ()
        mode = self.graph.nodes[v].get("mode")
        if mode == "rail":
            if self._has_rail_data:
                return self._rail_options(u, v, ready_minute)
            return self._fallback_options(u, v, ready_minute, mode)
        if mode == "bus":
            if self.repository is not None and getattr(self.repository, "trips", {}):
                # A canonical GTFS graph can use exact bus data even with a
                # small injected manager that only models train clocks.
                if self._bus_route(v) is not None and self._stop_id(u[1]) is not None:
                    return self._bus_options(u, v, ready_minute)
                if self._has_bus_data and "BusstopPole" in str(u[1]):
                    # Production ODPT poles without an exact feed match do
                    # not acquire a fabricated run.  Synthetic non-ODPT graph
                    # fixtures retain their existing injected evaluator.
                    return ()
            return self._fallback_options(u, v, ready_minute, mode)
        return ()

    def ride_options(self, u, v, current_minute, state):
        if state is None or self._line_id(u) != state.line_id or self._line_id(v) != state.line_id:
            return ()
        edge = self.graph[u][v]
        if state.provider.startswith("opaque-"):
            if state.provider == "opaque-rail":
                arrival = self.manager.get_next_train_arrival(
                    u[1], v[1], current_minute, day_type=self.day_type,
                    delays_snapshot=self._delays, use_realtime=self.use_realtime,
                )
            else:
                meters = edge.get("meters", 0)
                arrival = current_minute + (float(meters) / 250.0 + 0.8 if meters > 0 else 2.5)
            if arrival is None or arrival < current_minute or arrival > self.deadline:
                return ()
            return ((float(arrival), replace(state, sequence=state.sequence + 1)),)
        run = self._runs.get((state.provider, state.run_id))
        if run is None:
            return ()
        position = self._positions[(state.provider, state.run_id)].get(state.sequence)
        if position is None or position + 1 >= len(run.stops):
            return ()
        current, following = run.stops[position:position + 2]
        if state.provider == "rail":
            if current.stop_id != u[1] or following.stop_id != v[1] or self._rail_suspended(u[1]):
                return ()
            delay = self._rail_delays[state.run_id]
            departure, arrival = current.departure + delay, following.arrival + delay
        else:
            if current.stop_id != self._stop_id(u[1]) or following.stop_id != self._stop_id(v[1]):
                return ()
            board = run.stops[self._positions[("bus", state.run_id)][state.board_sequence]]
            delay = state.departure_minute - board.departure
            departure, arrival = current.departure + delay, following.arrival + delay
        if departure < current_minute or arrival < departure or arrival > self.deadline:
            return ()
        return ((arrival, replace(state, sequence=following.sequence)),)

    def metadata(self, state):
        if state is None:
            return {}
        result = {
            "provider": state.provider, "run_key": state.run_id,
            "run_id": state.run_id,
            "service_key": state.service_key, "train_number": state.train_number,
            "trip_id": state.trip_id, "route_id": state.route_id,
            "service_id": state.service_id, "board_sequence": state.board_sequence,
            "sequence": state.sequence, "actual_departure_minute": state.departure_minute,
        }
        run = self._runs.get((state.provider, state.run_id))
        if run is None:
            return result
        if run.source_run_key is not None:
            result["run_key"] = run.source_run_key
        positions = self._positions[(state.provider, state.run_id)]
        board, current = run.stops[positions[state.board_sequence]], run.stops[positions[state.sequence]]
        result["origin_stop_id"] = board.stop_id
        result["destination_stop_id"] = current.stop_id
        result["scheduled_departure_minute"] = _scheduled_clock(board.departure)
        result["scheduled_arrival_minute"] = _scheduled_clock(current.arrival)
        if state.provider == "rail":
            delay = self._rail_delays[state.run_id]
            begin, end = positions[state.board_sequence], positions[state.sequence]
            result["segment_records"] = tuple(dict(record) for record in
                self._rail_segments[state.run_id][begin:end])
        else:
            # Actual bus delay at board time is fixed for the complete run.
            delay = state.departure_minute - board.departure
        result["actual_arrival_minute"] = current.arrival + delay
        result["stops"] = tuple(stop.stop_id for stop in run.stops)
        return result
