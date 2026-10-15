"""Opt-in Tokyo graph bridge to common scheduled BUS choices.

Rail is explicitly the existing Tokyo provider. This is not a production
selection, realtime implementation, new search loop or failure fallback.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date
import math
from types import MappingProxyType

from route_engine import RouteContractError
from tokyo_timetable_choices import RideState, TimetableChoices, _Run, _Stop
from transit_network import line_node
from transit_timetable_choices import DatasetTimetableChoices, ScheduledRideState


class TokyoBusDatasetBinding:
    """Validate a pinned dataset against Tokyo's reference input once.

    The reference repository supplies legacy graph ID binding and lower-bound
    inputs only. Boarding, continuation and selected bus metadata use snapshot.
    """

    def __init__(self, snapshot, repository):
        if len(snapshot.datasets) != 1 or snapshot.datasets[0].metadata.feed_id != repository.feed_id:
            raise RouteContractError('Tokyo bus bridge requires one matching explicit feed')
        if any(route.mode.value != 'bus' for route in snapshot.routes.values()):
            raise RouteContractError('Tokyo bus bridge requires a bus-only snapshot')
        if snapshot.allowed_trip_ids != frozenset(snapshot.datasets[0].trips):
            raise RouteContractError('Tokyo bus bridge requires the complete source trip scope')
        sources = {trip.source_id: key for key,trip in snapshot.trips.items()}
        if len(sources) != len(snapshot.trips) or set(sources) != set(repository.trips):
            raise RouteContractError('Tokyo bus bridge source trip scope differs')
        prefix = repository.feed_id + ':'
        for source_id, key in sources.items():
            trip, raw = snapshot.trips[key], repository.trips[source_id]
            route = snapshot.routes[trip.route_id]
            if (route.source_id,trip.service_id) != (raw['route_id'],prefix+raw['service_id']):
                raise RouteContractError(f'Tokyo bus bridge trip identity differs: {source_id}')
            rows = snapshot.rows_by_trip[key]
            if set(repository.stop_times[source_id]) != {row.sequence for row in rows}:
                raise RouteContractError(f'Tokyo bus bridge occurrence scope differs: {source_id}')
            for position,row in enumerate(rows):
                for clock in (row.arrival_minute,row.departure_minute):
                    if clock is None or clock.denominator != 1 or clock > 2**53:
                        raise RouteContractError(f'Tokyo bus bridge requires exact integral minute clocks; no rounding: {source_id} sequence={row.sequence}')
                if repository.stop_times[source_id][row.sequence] != (
                        snapshot.stops[row.stop_id].source_id,row.arrival_minute,row.departure_minute):
                    raise RouteContractError(f'Tokyo bus bridge source clock/stop differs: {source_id} sequence={row.sequence}')
                if repository.get_stop_time_boarding(source_id,row.sequence) != (row.pickup_type,row.drop_off_type):
                    raise RouteContractError(f'Tokyo bus bridge source flags differ: {source_id} sequence={row.sequence}')
                if ((position < len(rows)-1 and row.pickup_type not in (0,1))
                        or (position > 0 and row.drop_off_type != 0)):
                    raise RouteContractError(f'Tokyo bus bridge unsupported boarding/alighting contract: {source_id} sequence={row.sequence}')
        edges = defaultdict(list)
        for pair, departures in snapshot.departures.items():
            if not departures:
                raise RouteContractError('Tokyo bus bridge has an empty departure index')
            _, trip_id, position = departures[0]
            trip = snapshot.trips[trip_id]
            row = snapshot.rows_by_trip[trip_id][position]
            edges[snapshot.routes[trip.route_id].source_id,snapshot.stops[row.stop_id].source_id].append(pair)
        self.snapshot, self.repository = snapshot, repository
        self.source_trips = MappingProxyType(sources)
        self.edges = MappingProxyType({key:tuple(value) for key,value in edges.items()})

    def verify_static_bus_interval_minima(self, check_deadline):
        """Read-only gate: common schedule must reproduce Tokyo's static bus bounds.

        This compares adjacent interval minima, not destination A* bounds or
        ranked routes. It does not select a new provider or change any cache.
        """
        from tokyo_time_bounds import _adjacent_minutes, _build_bus_index

        minima = {}
        trip_count = stop_count = 0
        for trip_key, trip in self.snapshot.trips.items():
            check_deadline()
            trip_count += 1
            rows = self.snapshot.rows_by_trip[trip_key]
            stop_count += len(rows)
            route = self.snapshot.routes[trip.route_id].source_id
            for previous, following in zip(rows, rows[1:]):
                check_deadline()
                key = (
                    route,
                    self.snapshot.stops[previous.stop_id].source_id,
                    self.snapshot.stops[following.stop_id].source_id,
                )
                minutes = _adjacent_minutes(previous.departure_minute, following.arrival_minute)
                if minutes is None:
                    raise RouteContractError(
                        f'Tokyo common bus bounds contain an invalid interval: {key!r}'
                    )
                minima[key] = min(minima.get(key, math.inf), minutes)

        reference = _build_bus_index(
            None, (self.repository.trips, self.repository.stop_times), check_deadline
        )
        if reference.invalid or (reference.trips, reference.stops) != (trip_count, stop_count):
            raise RouteContractError(
                'Tokyo common bus bounds source coverage differs: '
                f'common=({trip_count},{stop_count}), '
                f'reference=({reference.trips},{reference.stops}), '
                f'reference_invalid={reference.invalid}'
            )
        if minima != reference.minima:
            keys = set(minima) | set(reference.minima)
            different = next(
                key for key in sorted(keys)
                if minima.get(key) != reference.minima.get(key)
            )
            raise RouteContractError(
                f'Tokyo common bus interval minimum differs: segment={different!r}, '
                f'common={minima.get(different)!r}, '
                f'reference={reference.minima.get(different)!r}'
            )
        return {
            'common_bus_interval_minima_verified': True,
            'bus_interval_pairs': len(minima),
            'bus_source_trips': trip_count,
            'bus_source_stop_times': stop_count,
            'bus_invalid_intervals': 0,
        }

    def choices(self, graph, manager, **kwargs):
        return TokyoDatasetBusChoices(graph,manager,binding=self,**kwargs)


class TokyoDatasetBusChoices(TimetableChoices):
    """Tokyo RideState/graph protocol; common provider for every bus choice."""

    def __init__(self, graph, manager, *, binding, day_type, use_realtime,
                 delays_snapshot=None, deadline, bus_repository, rail_boarding_minutes=2):
        if use_realtime is not False:
            raise RouteContractError('Tokyo dataset bus bridge is scheduled-only; realtime unsupported')
        if type(getattr(day_type,'service_date',None)) is not date or not math.isfinite(deadline):
            raise RouteContractError('Tokyo dataset bus bridge requires an explicit date and finite deadline')
        if bus_repository is not binding.repository or not getattr(day_type,'has_gtfs_calendar',False):
            raise RouteContractError('Tokyo dataset bus bridge requires the bound repository and real calendar')
        kwargs = dict(day_type=day_type,use_realtime=False,delays_snapshot=delays_snapshot,
                      deadline=deadline,bus_repository=bus_repository,rail_boarding_minutes=rail_boarding_minutes)
        super().__init__(graph,manager,**kwargs)
        self.binding = binding
        self.scheduled = DatasetTimetableChoices(binding.snapshot,service_date=day_type.service_date,deadline=deadline)
        # Explicit migration baseline: retain the reference Tokyo bounds and
        # rounding guards. No failed bound/provider is replaced by this object.
        self.time_bounds_choices = TimetableChoices(graph,manager,**kwargs)

    def prepare(self, check_deadline):
        self.scheduled.prepare(check_deadline)
        expected = frozenset(self.binding.source_trips[trip_id] for trip_id,trip in self.repository.trips.items()
                             if trip['service_id'] in self.active_services)
        if self.scheduled.active_trips != expected:
            raise RouteContractError('Tokyo dataset bus bridge active trip scope differs')
        check_deadline()

    def _fallback_options(self, *args):
        raise RouteContractError('Tokyo dataset bus bridge does not support opaque timetable providers')

    def _bus_run(self, trip_id):
        if trip_id not in self._bus_run_cache:
            key = self.binding.source_trips[trip_id]
            snapshot = self.binding.snapshot
            trip = snapshot.trips[key]
            stops = tuple(_Stop(snapshot.stops[row.stop_id].source_id,row.sequence,
                                float(row.arrival_minute),float(row.departure_minute))
                          for row in snapshot.rows_by_trip[key])
            run = _Run('bus',f'{self.repository.feed_id}|{self.service_key}|{trip_id}',stops,
                       trip_id=trip_id,route_id=snapshot.routes[trip.route_id].source_id,
                       service_id=trip.service_id[len(self.repository.feed_id)+1:])
            self._save_run(run)
            self._bus_run_cache[trip_id] = run
        return self._bus_run_cache[trip_id]

    def _bus_options(self, u, v, ready):
        self.scheduled._require_prepared()
        route, stop = self._bus_route(v), self._stop_id(u[1])
        terminal = self._bus_pattern_terminal_stop_id(v)
        snapshot = self.binding.snapshot
        options = []
        for a,b in self.binding.edges.get((route,stop),()):
            for departure, selected in self.scheduled.board_options(a,b,ready):
                rows = snapshot.rows_by_trip[selected.trip_id]
                if terminal is not None and snapshot.stops[rows[-1].stop_id].source_id != terminal:
                    continue
                following = snapshot.stops[rows[selected.position+1].stop_id].source_id
                if not any(edge.get('etype') == 'ride' and edge.get('mode','bus') == 'bus'
                           and self._stop_id(node[1]) == following for node,edge in self.graph[v].items()):
                    continue
                trip_id = snapshot.trips[selected.trip_id].source_id
                run = self._bus_run(trip_id)
                state = RideState('bus',self.service_key,run.run_id,self._line_id(v),
                    selected.sequence,selected.board_sequence,float(departure),trip_id=trip_id,
                    route_id=run.route_id,service_id=run.service_id)
                options.append((float(departure),state))
        # Tokyo's existing tie order differs from the common per-pattern index.
        return tuple(sorted(options,key=lambda option:(option[0],option[1].sequence,option[1].trip_id)))

    def ride_options(self, u, v, clock, state):
        if state is not None and state.provider not in ('bus','rail'):
            raise RouteContractError('Tokyo dataset bus bridge requires concrete run states')
        if state is None or state.provider != 'bus':
            return super().ride_options(u,v,clock,state)
        self.scheduled._require_prepared()
        if self._line_id(u) != state.line_id or self._line_id(v) != state.line_id:
            return ()
        if self.graph[u][v].get('etype') != 'ride':
            raise RouteContractError('Tokyo dataset bus continuation requires an existing ride edge')
        key = self.binding.source_trips[state.trip_id]
        run = self._bus_run(state.trip_id)
        positions = self._positions['bus',run.run_id]
        position = positions[state.sequence]
        if position+1 >= len(run.stops):
            return ()
        current,following = run.stops[position:position+2]
        if current.stop_id != self._stop_id(u[1]) or following.stop_id != self._stop_id(v[1]) or clock > current.departure:
            return ()
        pattern = self.binding.snapshot.trip_patterns[key]
        ride = ScheduledRideState(key,self.scheduled.service_date,pattern,position,
                                 positions[state.board_sequence],state.sequence,state.board_sequence)
        result = self.scheduled.ride_options(line_node(pattern,position),line_node(pattern,position+1),clock,ride)
        return tuple((float(arrival),replace(state,sequence=continued.sequence))
                     for arrival,continued in result if arrival <= self.deadline)
