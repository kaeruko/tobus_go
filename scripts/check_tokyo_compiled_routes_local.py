"""Read-only Tokyo graph sample: raw versus serialized compiled bus inputs.

Uses the existing Tokyo/shared label integration, never a second search loop.
No network, realtime, data repair, inferred links, output files or retry route.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import gzip
import io
import json
import pickle
from pathlib import Path
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))
sys.path.insert(0, str(ROOT / 'scripts'))

import networkx as nx
import toei_engine as engine
from check_tokyo_gtfs_local import check_boarding_contract, fingerprints, load_inputs
from check_tokyo_odpt_local import check_repository, manager_intervals, resolve_probe_dates, sha256
from gtfs_loader import GtfsRepository
from gtfs_state import GTFS_STATE_SCHEMA_VERSION, hydrate_repository_state, repository_state_payload
from tokyo_timetable_choices import TimetableChoices
from tokyo_dataset_bus_choices import TokyoBusDatasetBinding


def compiled_copy(repository):
    """Same pickle/gzip encoding settings as write_compiled_state, in memory."""
    stream = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', compresslevel=6, fileobj=stream, mtime=0) as compressed:
        pickle.dump(repository_state_payload(repository, '0' * 64), compressed,
                    protocol=pickle.HIGHEST_PROTOCOL)
    payload = stream.getvalue()
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode='rb') as compressed:
        state = pickle.load(compressed)
    target = GtfsRepository(repository.feed_id)
    hydrate_repository_state(target, state, expected_source_sha256='0' * 64)
    return target, len(payload)


def select_cases(graph, manager, repository, day):
    """First sorted active pickup=1 occurrence with both adjacent graph rides.

    Select before any search. A search failure is never replaced by another OD.
    Use only existing board/ride edges, preserving the supplied Tokyo walks.
    """
    choices = TimetableChoices(graph, manager, engine.determine_day_type(day.isoformat()),
                              use_realtime=False, deadline=3000, bus_repository=repository)
    bindings = {}
    for node, attrs in graph.nodes(data=True):
        if not isinstance(node, tuple) or len(node) != 3 or node[0] != 'line' or attrs.get('mode') != 'bus':
            continue
        phys = ('phys', node[1])
        if graph.has_edge(phys, node) and graph[phys][node].get('etype') == 'board':
            bindings.setdefault((choices._bus_route(node), choices._stop_id(node[1])), []).append(node)
    active = repository.get_active_service_ids(day)
    for trip_id in sorted(repository.stop_times):
        trip = repository.trips[trip_id]
        if trip['service_id'] not in active:
            continue
        rows = sorted(repository.stop_times[trip_id].items())
        for position in range(1, len(rows) - 1):
            sequence, current = rows[position]
            if repository.get_stop_time_boarding(trip_id, sequence) != (1, 0):
                continue
            previous_sequence, previous = rows[position - 1]
            _, following = rows[position + 1]
            if repository.get_stop_time_boarding(trip_id, previous_sequence)[0] != 0:
                continue
            for middle in sorted(bindings.get((trip['route_id'], current[0]), ())):
                terminal = choices._bus_pattern_terminal_stop_id(middle)
                if terminal is not None and terminal != rows[-1][1][0]:
                    continue
                before = [u for u in graph.predecessors(middle)
                          if graph[u][middle].get('etype') == 'ride'
                          and graph[u][middle].get('mode', 'bus') == 'bus'
                          and u[0] == 'line' and u[2] == middle[2]
                          and choices._stop_id(u[1]) == previous[0]]
                after = [v for v in graph.successors(middle)
                         if graph[middle][v].get('etype') == 'ride'
                         and graph[middle][v].get('mode', 'bus') == 'bus'
                         and v[0] == 'line' and v[2] == middle[2]
                         and choices._stop_id(v[1]) == following[0]]
                if not before or not after:
                    continue
                a, b, c = ('phys', sorted(before)[0][1]), ('phys', middle[1]), ('phys', sorted(after)[0][1])
                if len({a,b,c}) != 3 or any(node not in graph for node in (a,b,c)):
                    continue
                if (not graph.has_edge(a, sorted(before)[0])
                        or graph[a][sorted(before)[0]].get('etype') != 'board'):
                    continue
                # No rounding/clamping: this gate requires integral minute clocks.
                start = previous[2] - 2
                blocked_start = current[2] - 2
                if start < 0 or blocked_start < 0:
                    raise ValueError('selected probe clock precedes service-day zero')
                return (('through', a, c, start), ('alight', a, b, start),
                        ('blocked_origin', b, c, blocked_start))
    raise ValueError(f'no active pickup=1 occurrence with both adjacent graph rides on {day}')


def route_sample(graph, manager, repository, day, case, mode, limit, *, choices_factory=None):
    kind, origin, destination, minute = case
    if type(minute) is not int:
        raise ValueError('route sample requires integral source minutes; no rounding')
    clock = f'{minute // 60:02d}:{minute % 60:02d}'
    results = []
    with patch.object(engine, 'gtfs_repo', repository):
        extra = {} if choices_factory is None else {'choices_factory':choices_factory}
        generator = engine._tokyo_label_search(
            graph, manager, origin, destination, clock, engine.determine_day_type(day.isoformat()),
            mode, limit, 100000, engine.MAX_TRAVEL_MIN, None, 15.0, None, None, False, False, **extra)
        try:
            for candidate in generator:
                path = candidate['path']
                for state in path.edge_rides.values():
                    if state.provider == 'bus' and repository.get_stop_time_boarding(state.trip_id,state.board_sequence)[0] != 0:
                        raise AssertionError(f'prohibited boarding selected: date={day} case={kind} mode={mode}')
                results.append({'cost': candidate['cost'], 'path': list(path),
                    'edge_times': path.edge_times,
                    'selected_rides': {index:None if state is None else asdict(state)
                                       for index,state in path.edge_rides.items()}})
                if len(results) == limit:
                    break
        finally:
            generator.close()
    if not results:
        raise AssertionError(f'no route in selected sample: date={day} case={kind} mode={mode}')
    return results


def inspect(root, expected_version, day_values, prebuilt, limit, *, shared_bus=False):
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError('max_candidates must be an integer between 1 and 5')
    info, dataset, snapshot, days, _ = load_inputs(root, expected_version, day_values)
    _, holiday_version = resolve_probe_dates(day_values)
    check_boarding_contract(dataset, snapshot, days)
    repository = GtfsRepository('tokyo_bus_probe').load_data(str(root))
    if set(repository.trips) != {trip.source_id for trip in snapshot.trips.values()}:
        raise AssertionError('raw/shared trip scope differs')
    for trip_id, rows in snapshot.rows_by_trip.items():
        trip = snapshot.trips[trip_id]
        source = repository.trips[trip.source_id]
        prefix = dataset.metadata.feed_id + ':'
        if (source['route_id'],source['service_id']) != (
                snapshot.routes[trip.route_id].source_id,trip.service_id[len(prefix):]):
            raise AssertionError('raw/shared trip route or service identity differs')
        if set(repository.stop_times[trip.source_id]) != {row.sequence for row in rows}:
            raise AssertionError('raw/shared stop occurrence scope differs')
        for row in rows:
            if repository.stop_times[trip.source_id][row.sequence] != (
                    snapshot.stops[row.stop_id].source_id, row.arrival_minute, row.departure_minute):
                raise AssertionError('raw/shared source stop or clock differs')
            if repository.get_stop_time_boarding(trip.source_id, row.sequence) != (row.pickup_type,row.drop_off_type):
                raise AssertionError('raw/shared source boarding flags differ')
    compiled, byte_count = compiled_copy(repository)
    binding = TokyoBusDatasetBinding(snapshot,repository) if shared_bus else None
    with prebuilt.open('rb') as stream:
        data = pickle.load(stream)
    if not isinstance(data,dict) or not isinstance(data.get('G'),nx.DiGraph) or not isinstance(data.get('TM'),engine.TimetableManager):
        raise ValueError('trusted prebuilt requires Tokyo G and TM; no repair')
    graph, manager = data['G'], data['TM']
    if any(edge.get('etype') == 'ride' and edge.get('mode') == 'rail'
           for _,_,edge in graph.edges(data=True)) and not manager_intervals(manager):
        raise ValueError('rail graph requires concrete prebuilt train intervals; no repair')
    reports = []
    for day in days:
        prefix = dataset.metadata.feed_id + ':'
        if repository.get_active_service_ids(day) != frozenset(key[len(prefix):] for key in dataset.active_service_ids(day)):
            raise AssertionError(f'raw/shared active services differ on {day}')
        cases = select_cases(graph, manager, repository, day)
        for case in cases:
            for mode in ('time','fewTransfers','cost'):
                raw = route_sample(graph,manager,repository,day,case,mode,limit)
                restored = route_sample(graph,manager,compiled,day,case,mode,limit)
                if raw != restored:
                    raise AssertionError(f'raw/compiled ranked sample differs: date={day} case={case[0]} mode={mode}')
                if binding is not None:
                    shared = route_sample(graph,manager,repository,day,case,mode,limit,choices_factory=binding.choices)
                    if raw != shared:
                        raise AssertionError(f'Tokyo/common bus ranked sample differs: date={day} case={case[0]} mode={mode}')
                reports.append({'date':day.isoformat(),'case':case[0],'mode':mode,
                    'candidates':len(raw),'differences':0,
                    'bus_candidates':sum(any(state is not None and state['provider'] == 'bus'
                                             for state in row['selected_rides'].values()) for row in raw)})
    if not any(row['bus_candidates'] for row in reports):
        raise AssertionError('selected sample never exercised a bus ride; parity is insufficient')
    return {**info, 'audit_mode':('tokyo_common_bus_label_route_sample' if shared_bus else 'raw_compiled_label_route_sample'), 'date_cases':reports,
        'compiled_state_schema_version':GTFS_STATE_SCHEMA_VERSION,'serialized_bytes':byte_count,
        'raw_compiled_sample_rank_verified':True, 'common_dataset_route_ranking_verified':False,
        'common_bus_sample_rank_verified':shared_bus, 'rail_provider':'existing_tokyo',
        'common_bus_time_bounds_provider':'validated_tokyo_reference' if shared_bus else None,
        'realtime_verified':False,'lambda_startup_verified':False,
        'source_identity_kind':'synthetic_in_memory_not_source_zip_hash',
        'holiday_dependency_version':holiday_version,
        'walking_policy':'unchanged_supplied_tokyo_graph', 'true_top_k_verified':False}


def inspect_shared_bus_bounds(root, expected_version, day_values):
    """Audit source interval minima only; do not rerun the ranked OD samples."""
    info, dataset, snapshot, days, _ = load_inputs(root, expected_version, day_values)
    _, holiday_version = resolve_probe_dates(day_values)
    check_boarding_contract(dataset, snapshot, days)
    repository = GtfsRepository('tokyo_bus_probe').load_data(str(root))
    binding = TokyoBusDatasetBinding(snapshot, repository)
    prefix = dataset.metadata.feed_id + ':'
    for day in days:
        if repository.get_active_service_ids(day) != frozenset(
                key[len(prefix):] for key in dataset.active_service_ids(day)):
            raise AssertionError(f'raw/shared active services differ on {day}')
    verified = binding.verify_static_bus_interval_minima(lambda: None)
    return {
        **info, **verified,
        'audit_mode': 'tokyo_common_bus_static_interval_minima',
        'date_count': len(days),
        'common_bus_sample_rank_verified': False,
        'common_dataset_route_ranking_verified': False,
        'common_bus_time_bounds_provider': 'not_selected_audit_only',
        'rail_provider': 'not_evaluated',
        'realtime_verified': False,
        'lambda_startup_verified': False,
        'true_top_k_verified': False,
        'source_identity_kind': 'synthetic_in_memory_not_source_zip_hash',
        'holiday_dependency_version': holiday_version,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gtfs-dir',type=Path,required=True)
    parser.add_argument('--expected-feed-version',required=True)
    parser.add_argument('--query-date',action='append',required=True)
    parser.add_argument('--trusted-prebuilt',type=Path,required=True)
    parser.add_argument('--expected-sha',required=True)
    parser.add_argument('--max-candidates',type=int,default=3)
    parser.add_argument('--shared-bus',action='store_true')
    parser.add_argument('--shared-bus-bounds-only',action='store_true')
    args = parser.parse_args()
    if args.shared_bus and args.shared_bus_bounds_only:
        parser.error('--shared-bus and --shared-bus-bounds-only are mutually exclusive')
    check_repository(args.expected_sha)
    before = {**fingerprints(args.gtfs_dir),'trusted_prebuilt':sha256(args.trusted_prebuilt)}
    if args.shared_bus_bounds_only:
        result = inspect_shared_bus_bounds(args.gtfs_dir,args.expected_feed_version,args.query_date)
    else:
        result = inspect(args.gtfs_dir,args.expected_feed_version,args.query_date,args.trusted_prebuilt,args.max_candidates,
                         shared_bus=args.shared_bus)
    after = {**fingerprints(args.gtfs_dir),'trusted_prebuilt':sha256(args.trusted_prebuilt)}
    if before != after:
        raise AssertionError('inputs changed during route sample comparison')
    check_repository(args.expected_sha)
    print(json.dumps({'sha':args.expected_sha,'python':sys.version,'input_hashes':before,**result}))
    marker = ('READ_ONLY_TOKYO_COMMON_BUS_INTERVAL_MINIMA_OK' if args.shared_bus_bounds_only
              else 'READ_ONLY_TOKYO_COMMON_BUS_ROUTE_SAMPLE_OK' if args.shared_bus
              else 'READ_ONLY_TOKYO_COMPILED_ROUTE_SAMPLE_OK')
    print(marker)


if __name__ == '__main__':
    main()
