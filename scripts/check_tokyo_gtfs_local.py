"""Read-only pinned Tokyo bus GTFS input and concrete-choice comparison.

No network, source updates, clock rounding for comparison, production graph,
realtime, inferred walking links or backend fallback.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))
sys.path.insert(0, str(ROOT / 'scripts'))

import networkx as nx
from check_tokyo_odpt_local import check_repository, sha256
from gtfs_loader import GtfsRepository
from toei_engine import ServiceDayType, TimetableManager
from tokyo_timetable_choices import TimetableChoices
from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata, TransitMode
from transit_network import NetworkCosts, build_transit_network, line_node
from transit_timetable_choices import DatasetTimetableChoices


def parse_day(value):
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError('date requires zero-padded YYYY-MM-DD')
    return result


def fingerprints(root):
    return {path.name: sha256(path) for path in sorted(root.glob('*.txt'))}


def feed_info(root, expected_version, days):
    with (root / 'feed_info.txt').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1 or rows[0].get('feed_version') != expected_version:
        raise ValueError('require exactly one feed_info row at explicit expected feed version')
    info = rows[0]
    def source_day(field):
        value = info[field]
        result = datetime.strptime(value, '%Y%m%d').date()
        if result.strftime('%Y%m%d') != value:
            raise ValueError(f'invalid feed_info {field}')
        return result
    start, end = source_day('feed_start_date'), source_day('feed_end_date')
    if end < start or any(not start <= day <= end for day in days):
        raise ValueError('query dates outside pinned feed_info validity')
    frequencies = root / 'frequencies.txt'
    if frequencies.exists():
        with frequencies.open(encoding='utf-8-sig', newline='') as stream:
            if next(csv.DictReader(stream), None) is not None:
                raise ValueError('frequency-based trips unsupported; no expansion or alternate feed')
    return {'feed_version': expected_version, 'feed_start_date': start.isoformat(),
            'feed_end_date': end.isoformat()}


def compare(expected, actual, stage):
    if Counter(expected) != Counter(actual):
        raise AssertionError(f'{stage} concrete interval multiset differs')


class TokyoBoardingContractError(ValueError):
    """Unsupported legacy/shared contract with bounded local diagnostics."""

    def __init__(self, first_trip, first_sequence, diagnostics):
        self.diagnostics = diagnostics
        super().__init__('legacy Tokyo ignores boarding/alighting flags; shared choice parity not established: '
            f'{first_trip} sequence={first_sequence}; diagnostics=' + json.dumps(diagnostics, ensure_ascii=True))


def check_boarding_contract(dataset, snapshot, days):
    # Complete diagnostics before attempting either choice provider. Do not
    # filter trips, remove flags or continue comparison after this gate fails.
    date_counts = {day: {'date': day.isoformat(), 'conflicting_rows': 0,
        'boarding_conflicts': 0, 'alighting_conflicts': 0} for day in days}
    active = {day: dataset.active_service_ids(day) for day in days}
    date_trips = {day: set() for day in days}
    affected_trips, examples = set(), []
    kinds = Counter()
    rows_count = boarding_count = alighting_count = 0
    first = None
    for trip_id, rows in snapshot.rows_by_trip.items():
        trip = snapshot.trips[trip_id]
        for index, row in enumerate(rows):
            boarding = index < len(rows) - 1 and row.pickup_type != 0
            alighting = index > 0 and row.drop_off_type != 0
            if not boarding and not alighting:
                continue
            if first is None:
                first = trip_id, row.sequence
            rows_count += 1
            boarding_count += boarding
            alighting_count += alighting
            affected_trips.add(trip_id)
            kinds[row.pickup_type, row.drop_off_type] += 1
            active_dates = [day for day in days if trip.service_id in active[day]]
            for day in active_dates:
                date_counts[day]['conflicting_rows'] += 1
                date_counts[day]['boarding_conflicts'] += boarding
                date_counts[day]['alighting_conflicts'] += alighting
                date_trips[day].add(trip_id)
            if len(examples) < 5:
                stop = snapshot.stops[row.stop_id]
                examples.append({'trip_id': trip.source_id,
                    'route_id': snapshot.routes[trip.route_id].source_id,
                    'stop_id': stop.source_id, 'stop_name': stop.name, 'sequence': row.sequence,
                    'pickup_type': row.pickup_type, 'drop_off_type': row.drop_off_type,
                    'boarding_conflict': boarding, 'alighting_conflict': alighting,
                    'active_query_dates': [day.isoformat() for day in active_dates]})
    if first is not None:
        raise TokyoBoardingContractError(*first, {'conflicting_rows': rows_count,
            'boarding_conflicts': boarding_count, 'alighting_conflicts': alighting_count,
            'affected_trips': len(affected_trips), 'flag_pairs': [
                {'pickup': p, 'drop_off': d, 'rows': n} for (p, d), n in sorted(kinds.items())],
            'dates': [{**date_counts[day], 'affected_trips': len(date_trips[day])} for day in days],
            'examples': examples, 'examples_limit': 5, 'production_graph_reachability_verified': False})


def inspect(root, expected_version, day_values):
    days = tuple(parse_day(value) for value in day_values)
    if not days or len(set(days)) != len(days):
        raise ValueError('require explicit unique query dates')
    info = feed_info(root, expected_version, days)
    dataset = GtfsTransitAdapter.load(root, metadata=FeedMetadata(
        'tokyo_bus_probe', 'gtfs-local-probe', root.resolve().as_uri(), expected_version,
        datetime.now(timezone.utc)))
    flags = Counter((row.pickup_type, row.drop_off_type) for row in dataset.stop_times)
    for row in dataset.stop_times:
        if (row.arrival_service_seconds is None or row.departure_service_seconds is None
                or row.arrival_service_seconds % 60 or row.departure_service_seconds % 60):
            raise ValueError(f'legacy comparison requires exact minute-aligned source seconds: {row.trip_id} sequence={row.sequence}')
    if any(route.mode != TransitMode.BUS for route in dataset.routes.values()):
        raise ValueError('Tokyo bus comparison requires a bus-only feed; no route exclusion')
    snapshot = build_transit_network((dataset,), allowed_trip_ids=dataset.trips,
                                    walking_links=(), costs=NetworkCosts())
    check_boarding_contract(dataset, snapshot, days)
    repository = GtfsRepository('tokyo_bus_probe')
    repository.load_data(str(root))
    if set(repository.stops) != {s.source_id for s in dataset.stops.values()} or set(repository.routes) != {r.source_id for r in dataset.routes.values()}:
        raise AssertionError('legacy/shared stop or route scope differs')
    if set(repository.trips) != {t.source_id for t in dataset.trips.values()}:
        raise AssertionError('legacy/shared trip scope differs')
    for stop in dataset.stops.values():
        old = repository.stops[stop.source_id]
        if (stop.name, stop.name_en, stop.lat, stop.lon) != (old['name'], old['name_en'], old['lat'], old['lon']):
            raise AssertionError(f'stop/official English/coordinate metadata differs: {stop.source_id}')
    for route in dataset.routes.values():
        old = repository.routes[route.source_id]
        if (route.short_name, route.long_name) != (old.get('route_short_name') or '', old.get('route_long_name') or ''):
            raise AssertionError(f'route display metadata differs: {route.source_id}')
    graph = nx.DiGraph()
    expected_all = []
    for trip_id, rows in snapshot.rows_by_trip.items():
        trip = snapshot.trips[trip_id]
        old = repository.trips[trip.source_id]
        route = snapshot.routes[trip.route_id].source_id
        prefix = dataset.metadata.feed_id + ':'
        if not trip.service_id.startswith(prefix):
            raise AssertionError(f'non-namespaced service identity: {trip.source_id}')
        service = trip.service_id[len(prefix):]
        if (route, service, trip.headsign, trip.direction_id) != (
                old['route_id'], old['service_id'], old.get('trip_headsign') or '', old.get('direction_id') or None):
            raise AssertionError(f'trip metadata differs: {trip.source_id}')
        source_rows = repository.stop_times[trip.source_id]
        if set(source_rows) != {r.sequence for r in rows}:
            raise AssertionError(f'concrete occurrence scope differs: {trip.source_id}')
        for row in rows:
            stop = snapshot.stops[row.stop_id].source_id
            if (stop, row.arrival_minute, row.departure_minute) != source_rows[row.sequence]:
                raise AssertionError(f'concrete source clock/stop differs: {trip.source_id} sequence={row.sequence}')
        for current, following in zip(rows, rows[1:]):
            a, b = snapshot.stops[current.stop_id].source_id, snapshot.stops[following.stop_id].source_id
            u, v = ('line', a, 'gtfs:' + route), ('line', b, 'gtfs:' + route)
            graph.add_node(u, mode='bus', route_id=route)
            graph.add_node(v, mode='bus', route_id=route)
            graph.add_edge(u, v, etype='ride', mode='bus')
            expected_all.append((trip.source_id, current.sequence, a, b,
                                 current.departure_minute, following.arrival_minute))
    deadline = max(r[5] for r in expected_all)
    reports = []
    for day in days:
        active = repository.get_active_service_ids(day)
        shared_services = dataset.active_service_ids(day)
        prefix = dataset.metadata.feed_id + ':'
        if active != frozenset(key[len(prefix):] for key in shared_services):
            raise AssertionError(f'active service scope differs: {day}')
        active_trips = {key for key, trip in repository.trips.items() if trip['service_id'] in active}
        if not active_trips:
            raise ValueError(f'no active source trips on explicit query date: {day}')
        expected = [r for r in expected_all if r[0] in active_trips]
        legacy = TimetableChoices(graph, TimetableManager(), ServiceDayType('gtfs', day, active, True),
                                  use_realtime=False, deadline=deadline, bus_repository=repository)
        old_rows = []
        for u in graph:
            for dep, state in legacy.board_options(('phys', u[1]), u, 0):
                run = legacy._runs[('bus', state.run_id)]
                position = legacy._positions[('bus', state.run_id)][state.sequence]
                following = run.stops[position + 1].stop_id
                for arr, _ in legacy.ride_options(u, ('line', following, u[2]), dep, state):
                    old_rows.append((state.trip_id, state.sequence, u[1], following, dep, arr))
        compare(expected, old_rows, f'legacy choices/{day}')
        shared = DatasetTimetableChoices(snapshot, service_date=day, deadline=deadline)
        shared.prepare(lambda: None)
        if {snapshot.trips[key].source_id for key in shared.active_trips} != active_trips:
            raise AssertionError(f'active trip scope differs: {day}')
        new_rows = []
        for u, v in snapshot.departures:
            for dep, state in shared.board_options(u, v, 0):
                rows = snapshot.rows_by_trip[state.trip_id]
                for arr, continued in shared.ride_options(v, line_node(state.pattern, state.position + 1), dep, state):
                    new_rows.append((snapshot.trips[state.trip_id].source_id, state.sequence,
                        snapshot.stops[rows[state.position].stop_id].source_id,
                        snapshot.stops[rows[continued.position].stop_id].source_id, dep, arr))
        compare(expected, new_rows, f'shared choices/{day}')
        reports.append({'date': day.isoformat(), 'active_services': len(active),
                        'active_trips': len(active_trips), 'intervals': len(expected), 'differences': 0})
    return {**info, 'stops': len(dataset.stops), 'routes': len(dataset.routes), 'trips': len(dataset.trips),
        'stop_times': len(dataset.stop_times), 'pickup_dropoff_counts': [
            {'pickup': p, 'drop_off': d, 'rows': n} for (p, d), n in sorted(flags.items())],
        'date_choices': reports, 'source_metadata_verified': True, 'bus_choice_parity_verified': True,
        'walking_links': 0, 'production_graph_verified': False, 'route_ranking_verified': False,
        'realtime_verified': False, 'compiled_gtfs_verified': False, 'lambda_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gtfs-dir', type=Path, required=True)
    parser.add_argument('--expected-feed-version', required=True)
    parser.add_argument('--query-date', action='append', required=True)
    parser.add_argument('--expected-sha', required=True)
    args = parser.parse_args()
    check_repository(args.expected_sha)
    root = args.gtfs_dir.resolve()
    before = fingerprints(root)
    result = inspect(root, args.expected_feed_version, args.query_date)
    if before != fingerprints(root):
        raise AssertionError('GTFS input files changed during comparison')
    check_repository(args.expected_sha)
    print(json.dumps({'sha': args.expected_sha, 'python': sys.version, 'input_hashes': before, **result}))
    print('READ_ONLY_TOKYO_BUS_INPUT_OK')


if __name__ == '__main__':
    main()
