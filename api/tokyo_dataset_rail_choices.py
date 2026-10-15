"""Explicit scheduled-only rail bridge on the unchanged Tokyo graph.

Binding validation may consult an independent old provider. Selected rail
board/ride transitions only use DatasetTimetableChoices. Tokyo's existing bus,
state, metadata and lower-bound protocols remain explicit dependencies.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date
import hashlib
import json
import math
from types import MappingProxyType

from route_engine import RouteContractError
from tokyo_timetable_choices import TimetableChoices, RideState, _Run, _Stop, _railway_id
from transit_dataset import ServiceException
from transit_network import line_node
from transit_timetable_choices import DatasetTimetableChoices, ScheduledRideState


_PROFILES = ('weekday', 'saturday', 'holiday')
_CALENDARS = {
    'odpt.Calendar:Weekday': frozenset(('weekday',)),
    'odpt.Calendar:Saturday': frozenset(('saturday',)),
    'odpt.Calendar:Holiday': frozenset(('holiday',)),
    'odpt.Calendar:SaturdayHoliday': frozenset(('saturday', 'holiday')),
}


def _source_digest(manager):
    # Full contents, not just container identity/length: same-size edits fail.
    return hashlib.sha256(json.dumps((manager.train_patterns_weekday,
        manager.train_patterns_weekend), sort_keys=True, allow_nan=False,
        separators=(',', ':')).encode('utf-8')).digest()


def project_legacy_rail_snapshot(snapshot, day_type):
    """Explicit legacy date-policy projection, NOT official service validity.

    Caller supplies a validated Tokyo ServiceDayType. No calendar/name guessing,
    implicit today, dependency recovery, or alternate clock convention.
    """
    day = getattr(day_type, 'service_date', None)
    profile = str(day_type)
    if type(day) is not date or profile not in _PROFILES:
        raise RouteContractError('Tokyo rail bridge requires an explicit date and legacy day profile')
    import jpholiday
    expected = ('holiday' if day.weekday() == 6 or jpholiday.is_holiday(day)
                else 'saturday' if day.weekday() == 5 else 'weekday')
    if profile != expected:
        raise RouteContractError('Tokyo rail bridge date/profile disagrees with legacy holiday policy')
    datasets = []
    for dataset in snapshot.datasets:
        exceptions = []
        calendars = {}
        for key, calendar in dataset.calendars.items():
            if calendar.source_id not in _CALENDARS:
                raise RouteContractError(f'unsupported Tokyo rail calendar: {calendar.source_id}')
            calendars[key] = replace(calendar, weekdays=(False,) * 7,
                                     start_date=day, end_date=day)
            if profile in _CALENDARS[calendar.source_id]:
                exceptions.append(ServiceException(key, day, 1))
        datasets.append(replace(dataset, calendars=MappingProxyType(calendars),
                                service_exceptions=tuple(exceptions)))
    return replace(snapshot, datasets=tuple(datasets))


class TokyoRailDatasetBinding:
    """One-to-one verified source trip / old concrete part / occurrence binding."""

    def __init__(self, snapshot, manager, *, check_deadline=lambda: None):
        if len(snapshot.datasets) != 1:
            raise RouteContractError('Tokyo rail bridge requires one explicit rail feed')
        dataset = snapshot.datasets[0]
        if (any(route.mode.value != 'rail' for route in snapshot.routes.values())
                or snapshot.allowed_trip_ids != frozenset(dataset.trips)):
            raise RouteContractError('Tokyo rail bridge requires rail-only complete source scope')
        if getattr(manager, 'train_run_schema_version', None) != 1:
            raise RouteContractError('Tokyo rail bridge requires source run/occurrence metadata; no repair')
        sources = {trip.source_id: key for key, trip in snapshot.trips.items()}
        if len(sources) != len(snapshot.trips):
            raise RouteContractError('Tokyo rail bridge source trip identity is not unique')
        profiles = {profile: set() for profile in _PROFILES}
        for source, key in sources.items():
            check_deadline()
            trip = snapshot.trips[key]
            if not trip.train_number:
                raise RouteContractError(f'Tokyo rail bridge requires train number: {source}')
            calendar = dataset.calendars[trip.service_id].source_id
            if calendar not in _CALENDARS:
                raise RouteContractError(f'unsupported Tokyo rail calendar: {calendar}')
            for profile in _CALENDARS[calendar]:
                profiles[profile].add(key)
            rows = snapshot.rows_by_trip[key]
            for position, row in enumerate(rows):
                if row.sequence != position + 1:
                    raise RouteContractError(f'Tokyo rail bridge requires contiguous source sequence: {source} sequence={row.sequence}')
                for clock in (row.arrival_minute, row.departure_minute):
                    if clock is not None and (clock.denominator != 1 or clock > 2**53):
                        raise RouteContractError(f'Tokyo rail bridge requires exact integral minute clocks; no rounding: {source} sequence={row.sequence}')
                if row.pickup_type != 0 or row.drop_off_type != 0:
                    raise RouteContractError(f'Tokyo rail bridge unsupported source boarding flags: {source}')
        # Refuse legacy/opaque identity and malformed rows before the old
        # reference builder could silently skip or coerce them.
        for name in ('train_patterns_weekday', 'train_patterns_weekend'):
            for station, records in getattr(manager, name).items():
                check_deadline()
                for record in records:
                    for field in ('run_key', 'train_num', 'calendar', 'next_sta'):
                        value = record.get(field)
                        if not isinstance(value, str) or not value or value.strip() != value:
                            raise RouteContractError(f'Tokyo rail bridge invalid source identity: station={station!r} field={field}')
                    if (record['calendar'] not in _CALENDARS
                            or (name == 'train_patterns_weekday') != (record['calendar'] == 'odpt.Calendar:Weekday')):
                        raise RouteContractError(f'Tokyo rail bridge source calendar/bucket differs: station={station!r}')
                    for field in ('dep', 'arr', 'stop_sequence'):
                        if type(record.get(field)) is not int or record[field] < 0:
                            raise RouteContractError(f'Tokyo rail bridge invalid source integer: station={station!r} field={field}')
                    if record['arr'] < record['dep']:
                        raise RouteContractError(f'Tokyo rail bridge backwards source interval: station={station!r}')
                    key = sources.get(record['run_key'])
                    if key is None:
                        raise RouteContractError(f'Tokyo rail bridge unknown source run: {record["run_key"]}')
                    trip = snapshot.trips[key]
                    if (trip.train_number != record['train_num']
                            or dataset.calendars[trip.service_id].source_id != record['calendar']
                            or snapshot.routes[trip.route_id].source_id != _railway_id(station)):
                        raise RouteContractError(f'Tokyo rail bridge source route/calendar/number differs: {trip.source_id}')
        initial = _source_digest(manager)
        # Validate ALL profiles before publishing a usable binding. Ambiguous or
        # split legacy parts are rejected, never joined or partially admitted.
        for profile in _PROFILES:
            check_deadline()
            reference = TimetableChoices(snapshot.graph, manager, day_type=profile,
                                         use_realtime=False, deadline=float('inf'))
            reference._build_rail()
            expected = profiles[profile]
            observed = set()
            for (_, run_id), run in reference._runs.items():
                check_deadline()
                key = sources.get(run.source_run_key)
                if key not in expected or key in observed:
                    raise RouteContractError(f'Tokyo rail bridge missing/ambiguous/split source run: {run_id}')
                trip = snapshot.trips[key]
                if run_id != f'{profile}|{trip.source_id}|part:0':
                    raise RouteContractError(f'Tokyo rail bridge unsupported legacy run part: {run_id}')
                rows = snapshot.rows_by_trip[key]
                stops = self._stops(snapshot, key)
                if run.train_number != trip.train_number or run.stops != stops:
                    raise RouteContractError(f'Tokyo rail bridge source clock/sequence/stop/number differs: {trip.source_id}')
                observed.add(key)
            if observed != expected:
                raise RouteContractError(f'Tokyo rail bridge source run scope differs: profile={profile} missing={len(expected-observed)}')
        if initial != _source_digest(manager):
            raise RouteContractError('Tokyo rail source changed during binding validation')
        edges = defaultdict(list)
        for pair, departures in snapshot.departures.items():
            check_deadline()
            if not departures:
                raise RouteContractError('Tokyo rail bridge empty common departure index')
            _, key, position = departures[0]
            stop = snapshot.rows_by_trip[key][position].stop_id
            edges[snapshot.stops[stop].source_id].append(pair)
        self.snapshot = snapshot
        self.source_trips = MappingProxyType(sources)
        self.edges = MappingProxyType({key: tuple(value) for key, value in edges.items()})
        self.profile_trips = MappingProxyType({key: frozenset(value) for key, value in profiles.items()})
        self.source_digest = initial

    @staticmethod
    def _stops(snapshot, key):
        rows = snapshot.rows_by_trip[key]
        return tuple(_Stop(snapshot.stops[row.stop_id].source_id, position,
            float(row.departure_minute if position == 0 else row.arrival_minute),
            float(row.arrival_minute if position == len(rows)-1 else row.departure_minute))
            for position, row in enumerate(rows))

    def choices(self, graph, manager, **kwargs):
        return TokyoDatasetRailChoices(graph, manager, binding=self, **kwargs)


class TokyoDatasetRailChoices(TimetableChoices):
    """Common scheduled rail; existing Tokyo bus and validated reference bounds."""

    def __init__(self, graph, manager, *, binding, day_type, use_realtime,
                 deadline, delays_snapshot=None, bus_repository=None,
                 rail_boarding_minutes=2):
        if use_realtime is not False:
            raise RouteContractError('Tokyo dataset rail bridge is scheduled-only; realtime unsupported')
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline < 0:
            raise RouteContractError('Tokyo rail bridge requires a finite nonnegative deadline')
        projected = project_legacy_rail_snapshot(binding.snapshot, day_type)
        kwargs = dict(day_type=day_type, use_realtime=False, deadline=deadline,
            delays_snapshot=delays_snapshot, bus_repository=bus_repository,
            rail_boarding_minutes=rail_boarding_minutes)
        super().__init__(graph, manager, **kwargs)
        self.binding = binding
        self.scheduled = DatasetTimetableChoices(projected,
            service_date=day_type.service_date, deadline=deadline)
        # Explicit independent dependency. Do not pass this subclass through
        # make_time_bounds' standard-provider gate or change the gate itself.
        self.time_bounds_choices = TimetableChoices(graph, manager, **kwargs)
        self._common_rail_keys = {}

    def prepare(self, check_deadline):
        check_deadline()
        if _source_digest(self.manager) != self.binding.source_digest:
            raise RouteContractError('Tokyo rail source changed since binding validation')
        check_deadline()
        self.scheduled.prepare(check_deadline)
        if self.scheduled.active_trips != self.binding.profile_trips[str(self.day_type)]:
            raise RouteContractError('Tokyo rail bridge active trip scope differs')

    def _fallback_options(self, *args):
        raise RouteContractError('Tokyo rail bridge does not support opaque timetable providers')

    def _common_run(self, key):
        trip = self.binding.snapshot.trips[key]
        run_id = f'{self.service_key}|{trip.source_id}|part:0'
        if ('rail', run_id) not in self._runs:
            stops = self.binding._stops(self.binding.snapshot, key)
            run = _Run('rail', run_id, stops, train_number=trip.train_number,
                       source_run_key=trip.source_id)
            self._save_run(run)
            self._common_rail_keys[run_id] = key
            self._rail_delays[run_id] = 0.0
            self._rail_segments[run_id] = tuple({
                'origin_id': current.stop_id, 'next_sta': following.stop_id,
                'dep': int(current.departure), 'arr': int(following.arrival),
                'train_num': trip.train_number, 'run_key': trip.source_id,
                'stop_sequence': current.sequence,
                'actual_dep': current.departure, 'actual_arr': following.arrival,
            } for current, following in zip(stops, stops[1:]))
        return self._runs['rail', run_id]

    def _rail_options(self, u, v, ready):
        self.scheduled._require_prepared()
        snapshot = self.binding.snapshot
        options = []
        for a, b in self.binding.edges.get(v[1], ()):
            for departure, selected in self.scheduled.board_options(a, b, ready):
                rows = snapshot.rows_by_trip[selected.trip_id]
                following = snapshot.stops[rows[selected.position+1].stop_id].source_id
                next_node = ('line', following, self._line_id(v))
                if not self.graph.has_edge(v, next_node):
                    continue
                edge = self.graph[v][next_node]
                if edge.get('etype') != 'ride' or edge.get('mode', 'rail') != 'rail':
                    continue
                run = self._common_run(selected.trip_id)
                state = RideState('rail', self.service_key, run.run_id,
                    self._line_id(v), selected.sequence-1, selected.board_sequence-1,
                    float(departure), train_number=run.train_number)
                options.append((float(departure), state))
        return tuple(sorted(options, key=lambda option:
            (option[0], option[1].run_id, option[1].sequence)))

    def ride_options(self, u, v, clock, state):
        if state is None:
            return ()
        if state.provider == 'bus':
            return super().ride_options(u, v, clock, state)
        if state.provider != 'rail':
            raise RouteContractError('Tokyo rail bridge requires concrete run states')
        self.scheduled._require_prepared()
        if self._line_id(u) != state.line_id or self._line_id(v) != state.line_id:
            return ()
        key = self._common_rail_keys[state.run_id]
        rows = self.binding.snapshot.rows_by_trip[key]
        position = state.sequence
        if position+1 >= len(rows):
            return ()
        current, following = self._runs['rail', state.run_id].stops[position:position+2]
        if current.stop_id != u[1] or following.stop_id != v[1] or clock > current.departure:
            return ()
        pattern = self.binding.snapshot.trip_patterns[key]
        selected = ScheduledRideState(key, self.scheduled.service_date, pattern,
            position, state.board_sequence, position+1, state.board_sequence+1)
        result = self.scheduled.ride_options(line_node(pattern, position),
            line_node(pattern, position+1), clock, selected)
        return tuple((float(arrival), replace(state, sequence=continued.sequence-1))
            for arrival, continued in result if arrival <= self.deadline)
