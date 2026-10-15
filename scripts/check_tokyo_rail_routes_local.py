"""Read-only static Tokyo rail binding/graph/ranked-sample gate.

No download, repair, realtime, output file, fallback OD, bus matrix, bus bound
inspection, provider selection in production, or second search algorithm.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import pickle
import sys
from types import MappingProxyType
from typing import Mapping
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))
sys.path.insert(0, str(ROOT / 'scripts'))

import networkx as nx
import toei_engine as engine
from check_tokyo_odpt_local import (check_repository, compare_intervals,
    manager_intervals, records, resolve_probe_dates, sha256, source_intervals)
from gtfs_loader import GtfsRepository
from route_engine import RouteContractError
from tokyo_dataset_rail_choices import TokyoRailDatasetBinding
from tokyo_timetable_choices import TimetableChoices
from transit_adapters.odpt import OdptCalendarRule, OdptTransitAdapter
from transit_dataset import FeedMetadata
from transit_network import NetworkCosts, build_transit_network


def load_binding(train, stations, railways, manager):
    # This validates source compatibility for this new binding, not the already
    # accepted bus input/ranking/minima gates.
    entries = records(train)
    expected, _ = source_intervals(entries)
    compare_intervals(expected, manager_intervals(manager), 'pinned rail source/prebuilt')
    day = date(2000, 1, 1)
    rules = {row[0]: OdptCalendarRule((False,) * 7, day, day) for row in expected}
    digest = hashlib.sha256(json.dumps({name: sha256(path) for name, path in
        (('train', train), ('stations', stations), ('railways', railways))},
        sort_keys=True).encode('ascii')).hexdigest()
    dataset = OdptTransitAdapter.build(metadata=FeedMetadata('tokyo_rail_probe',
        'odpt-local-probe', train.as_uri(), 'sha256:' + digest,
        datetime.now(timezone.utc)), stations=records(stations),
        railways=records(railways), train_timetables=entries,
        calendar_rules=rules, train_clock_convention='ordered_run')
    snapshot = build_transit_network((dataset,), allowed_trip_ids=dataset.trips,
                                     walking_links=(), costs=NetworkCosts())
    return TokyoRailDatasetBinding(snapshot, manager)


def compare_choices(graph, manager, repository, profile, binding, deadline):
    """Compare every graph boarding occurrence and its complete continuation.

    Metadata at the boarding origin AND each downstream occurrence is compared.
    This exercises different origins on the same run, dwell, loops and terminal.
    """
    kwargs = dict(day_type=profile, use_realtime=False, deadline=deadline,
                  bus_repository=repository)
    old = TimetableChoices(graph, manager, **kwargs)
    new = binding.choices(graph, manager, **kwargs)
    new.prepare(lambda: None)
    boardings = continuations = 0
    for u, v, edge in graph.edges(data=True):
        if edge.get('etype') != 'board' or graph.nodes[v].get('mode') != 'rail':
            continue
        left, right = old.board_options(u, v, 0), new.board_options(u, v, 0)
        if left != right:
            raise RouteContractError(f'rail boarding order/state differs: date={profile.service_date} node={v!r}')
        boardings += len(left)
        for (clock, state), (_, other) in zip(left, right):
            node = v
            while True:
                if old.metadata(state) != new.metadata(other) or state.future_key != other.future_key:
                    raise RouteContractError(f'rail metadata/future state differs: run={state.run_id} sequence={state.sequence}')
                run = old._runs['rail', state.run_id]
                position = old._positions['rail', state.run_id][state.sequence]
                if position+1 >= len(run.stops):
                    break
                following = ('line', run.stops[position+1].stop_id, state.line_id)
                if not graph.has_edge(node, following):
                    break
                a = old.ride_options(node, following, clock, state)
                b = new.ride_options(node, following, clock, other)
                if a != b:
                    raise RouteContractError(f'rail same-run continuation differs: run={state.run_id} sequence={state.sequence}')
                if not a:
                    break
                continuations += 1
                clock, state = a[0]
                _, other = b[0]
                node = following
    if not boardings or not continuations:
        raise RouteContractError('rail graph gate did not exercise board/ride')
    return {'boarding_options': boardings, 'continuations': continuations,
            'metadata_differences': 0, 'differences': 0}


def structural_cases(graph, manager, repository, profile, deadline):
    """Deterministic, distinct structural ODs for reference-only preselection.

    One source witness clock per (category, origin, destination). Structure does
    not certify that a required mode appears in the top requested candidates.
    """
    choices = TimetableChoices(graph, manager, profile, use_realtime=False,
                              deadline=deadline, bus_repository=repository)
    seen = set()
    rail_edges = sorted(((u, v) for u, v, e in graph.edges(data=True)
                         if e.get('etype') == 'board' and graph.nodes[v].get('mode') == 'rail'), key=repr)
    for origin, node in rail_edges:
        for departure, state in choices.board_options(origin, node, 2):
            run = choices._runs['rail', state.run_id]
            pos = choices._positions['rail', state.run_id][state.sequence]
            arrival_node = ('line', run.stops[pos+1].stop_id, state.line_id)
            physical = ('phys', arrival_node[1])
            if (not graph.has_edge(node, arrival_node) or not graph.has_edge(arrival_node, physical)
                    or graph[arrival_node][physical].get('etype') not in ('alight', 'xfer')
                    or origin == physical):
                continue
            arrival = run.stops[pos+1].arrival + 1
            minute = departure - 2
            if not float(minute).is_integer():
                raise RouteContractError('rail sample requires integral source minutes; no rounding')
            identity = ('rail_only', origin, physical)
            if identity not in seen:
                seen.add(identity)
                yield ('rail_only', origin, physical, int(minute))
            access = [(physical, arrival, False)]
            for target, edge in sorted(graph[physical].items(), key=lambda item: repr(item[0])):
                if edge.get('etype') == 'walk':
                    # Use the unchanged forward evaluator, not a guessed speed.
                    walk_arrival = engine.advance_time(graph, choices.manager, physical,
                        target, arrival, profile, {}, use_realtime=False, edge=edge)
                    if walk_arrival is not None:
                        access.append((target, walk_arrival, True))
            for stop, ready, walked in access:
                for board, edge in sorted(graph[stop].items(), key=lambda item: repr(item[0])):
                    if edge.get('etype') != 'board':
                        continue
                    mode = graph.nodes[board].get('mode')
                    kind = 'rail_bus' if mode == 'bus' else 'walking_transfer' if mode == 'rail' and walked else None
                    if kind is None:
                        continue
                    options = choices.board_options(stop, board, ready + (2 if mode == 'rail' else 0))
                    for dep, selected in options:
                        vehicle = choices._runs[selected.provider, selected.run_id]
                        position = choices._positions[selected.provider, selected.run_id][selected.sequence]
                        following_stop = vehicle.stops[position+1].stop_id
                        if mode == 'bus':
                            next_nodes = [n for n, e in graph[board].items() if e.get('etype') == 'ride'
                                and e.get('mode', 'bus') == 'bus' and choices._stop_id(n[1]) == following_stop]
                        else:
                            next_nodes = [('line', following_stop, selected.line_id)]
                        feasible = False
                        for next_node in sorted(next_nodes, key=repr):
                            destination = ('phys', next_node[1])
                            if (destination in (origin, physical) or not graph.has_edge(board, next_node)
                                    or not graph.has_edge(next_node, destination)):
                                continue
                            if vehicle.stops[position+1].arrival+1 > minute+engine.MAX_TRAVEL_MIN:
                                continue
                            feasible = True
                            identity = (kind, origin, destination)
                            if identity not in seen:
                                seen.add(identity)
                                yield (kind, origin, destination, int(minute))
                            break
                        if feasible:
                            break


def search_sample(graph, manager, repository, profile, case, mode, limit, factory=None):
    kind, origin, destination, minute = case
    if type(minute) is not int or minute < 0:
        raise ValueError('rail sample requires nonnegative integer minute; no rounding')
    results = []
    extra = {} if factory is None else {'choices_factory': factory}
    with patch.object(engine, 'gtfs_repo', repository):
        generator = engine._tokyo_label_search(graph, manager, origin, destination,
            f'{minute//60:02d}:{minute%60:02d}', profile, mode, limit, 100000,
            engine.MAX_TRAVEL_MIN, None, 15.0, None, None, False, False, **extra)
        try:
            for candidate in generator:
                path = candidate['path']
                modes = {s.provider for s in path.edge_rides.values() if s is not None}
                edges = [graph[u][v] for u,v in zip(path,path[1:])]
                rail_positions = [i for i,e in enumerate(edges) if e.get('etype') == 'ride' and e.get('mode','rail') == 'rail'
                                  and graph.nodes[path[i]].get('mode') == 'rail']
                rail_boards = sum(e.get('etype') == 'board' and graph.nodes[path[i+1]].get('mode') == 'rail'
                                  for i,e in enumerate(edges))
                walked_transfer = (rail_boards >= 2 and bool(rail_positions) and any(
                    e.get('etype') == 'walk' and min(rail_positions) < i < max(rail_positions)
                    for i,e in enumerate(edges)))
                relevant = ('rail' in modes and (kind != 'rail_only' or 'bus' not in modes)
                    and (kind != 'rail_bus' or 'bus' in modes)
                    and (kind != 'walking_transfer' or walked_transfer))
                results.append({'cost':candidate['cost'], 'path':list(path),
                    'edge_times':path.edge_times, 'walk_m':candidate['walk_m'],
                    'selected_rides':{i:asdict(s) for i,s in path.edge_rides.items()},
                    'metadata':{i:path.choices.metadata(s) for i,s in path.edge_rides.items()},
                    'relevant': relevant})
                if len(results) == limit:
                    break
        finally:
            generator.close()
    return results


def route_sample(graph, manager, repository, profile, case, mode, limit, factory=None):
    """Strict comparison execution: no category loss or replacement is allowed."""
    results = search_sample(graph, manager, repository, profile, case, mode, limit, factory)
    if not results or not any(row['relevant'] for row in results):
        raise RouteContractError(f'fixed rail sample lacks required category: case={case[0]} mode={mode}; no replacement OD')
    return results


KINDS = ('rail_only', 'rail_bus', 'walking_transfer')
MODES = ('time', 'fewTransfers', 'cost')


@dataclass(frozen=True, slots=True)
class RailSamplePlan:
    cases: Mapping[tuple[str, str], tuple]
    baseline: Mapping[tuple[str, str], tuple]
    selection_queries: int
    nonmatching_queries: int
    max_selection_queries: int
    max_candidates: int


def select_cases(graph, manager, repository, profile, deadline, limit=3, *, max_selection_queries=90):
    """Select ONLY from successful reference searches, before any comparison.

    An ordinary result with no category witness rejects a prospective OD.
    Exceptions (including search limits/partial failures) are never caught.
    Each (category, mode) fixes its own reference-qualified OD/clock. The
    candidate limit stays identical during selection and comparison.
    The finite query budget is explicit; exhaustion is failure, never success.
    """
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError('max-candidates must be an integer in [1,5]')
    if type(max_selection_queries) is not int or max_selection_queries < len(KINDS)*len(MODES):
        raise ValueError('max-selection-queries must be an integer >= 9')
    cases, baseline = {}, {}
    queries = rejected = 0
    required = tuple((kind, mode) for kind in KINDS for mode in MODES)
    for case in structural_cases(graph, manager, repository, profile, deadline):
        kind = case[0]
        for mode in MODES:
            key = kind, mode
            if key in cases:
                continue
            if queries == max_selection_queries:
                raise RouteContractError(f'rail reference preselection budget exhausted: queries={queries} nonmatching={rejected} missing={sorted(set(required)-cases.keys())}; no common-provider comparison started')
            queries += 1
            rows = search_sample(graph, manager, repository, profile, case, mode, limit)
            if not rows or not any(row['relevant'] for row in rows):
                rejected += 1
                continue
            cases[key] = case
            baseline[key] = tuple(rows)
        if len(cases) == len(required):
            return RailSamplePlan(MappingProxyType({key:cases[key] for key in required}),
                MappingProxyType(baseline), queries, rejected, max_selection_queries, limit)
    raise RouteContractError(f'no reference-qualified rail sample: queries={queries} nonmatching={rejected} missing={sorted(set(required)-cases.keys())}; no common-provider comparison started')


def compare_plan(graph, manager, repository, profile, binding, plan, limit):
    """Execute every frozen comparison once; propagate mismatches and failures."""
    if limit != plan.max_candidates or type(limit) is not int:
        raise RouteContractError('frozen rail sample candidate limit changed; no comparison started')
    reports = []
    for (kind, mode), case in plan.cases.items():
        old = plan.baseline[kind, mode]
        new = route_sample(graph, manager, repository, profile, case, mode, limit, binding.choices)
        if old != tuple(new):
            raise RouteContractError(f'rail ranked sample differs: date={profile.service_date} case={kind} mode={mode}; frozen sample is not replaced')
        reports.append({'date':profile.service_date.isoformat(), 'case':kind,
            'mode':mode, 'candidates':len(old),
            'sample_id':hashlib.sha256(json.dumps((profile.service_date.isoformat(),case),
                ensure_ascii=True).encode('ascii')).hexdigest(),
            'matching_candidates':sum(row['relevant'] for row in old), 'differences':0})
    return reports


def inspect(train, stations, railways, prebuilt, gtfs, expected_version, day_values, limit, *, max_selection_queries=90):
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError('max-candidates must be an integer in [1,5]')
    if type(max_selection_queries) is not int or max_selection_queries < 9:
        raise ValueError('max-selection-queries must be an integer >= 9')
    dates, holiday_version = resolve_probe_dates(day_values)
    if not dates:
        raise ValueError('at least one explicit query date is required')
    # Validate GTFS edition without running accepted bus comparison/compiled gates.
    import csv
    with (gtfs/'feed_info.txt').open(encoding='utf-8-sig', newline='') as stream:
        info = list(csv.DictReader(stream))
    if len(info) != 1 or info[0].get('feed_version') != expected_version:
        raise ValueError('pinned GTFS feed version differs')
    start = date.fromisoformat(info[0]['feed_start_date']) if '-' in info[0]['feed_start_date'] else datetime.strptime(info[0]['feed_start_date'],'%Y%m%d').date()
    end = date.fromisoformat(info[0]['feed_end_date']) if '-' in info[0]['feed_end_date'] else datetime.strptime(info[0]['feed_end_date'],'%Y%m%d').date()
    if start > end or any(not start <= day <= end for day,_ in dates):
        raise ValueError('query date outside pinned GTFS feed dates')
    with prebuilt.open('rb') as stream:
        data = pickle.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get('G'), nx.DiGraph) or not isinstance(data.get('TM'), engine.TimetableManager):
        raise ValueError('trusted prebuilt requires Tokyo G/TM; no repair')
    graph, manager = data['G'], data['TM']
    binding = load_binding(train, stations, railways, manager)
    repository = GtfsRepository('tokyo_rail_bus_reference').load_data(str(gtfs))
    reports = []
    choice_reports = []
    plans = []
    selection_reports = []
    for day, _ in dates:
        profile = engine.ServiceDayType(str(engine.determine_day_type(day)),day,
                                       repository.get_active_service_ids(day),True)
        deadline = max(float(row.departure_minute if row.arrival_minute is None else row.arrival_minute)
                       for rows in binding.snapshot.rows_by_trip.values() for row in rows)
        plan = select_cases(graph, manager, repository, profile, deadline, limit,
                            max_selection_queries=max_selection_queries)
        plans.append((profile, plan, deadline))
        selection_reports.append({'date':day.isoformat(),
            'selection_queries':plan.selection_queries, 'nonmatching_queries':plan.nonmatching_queries,
            'max_selection_queries':plan.max_selection_queries,
            'selected_cases':len(plan.cases), 'selected_od_clocks':len(set(plan.cases.values())),
            'selection_scope':'per_date_category_mode', 'all_modes_reference_qualified':True})
    # Freeze ALL dates before starting ranked common-provider comparisons.
    for profile, plan, deadline in plans:
        choice_report = compare_choices(graph, manager, repository, profile, binding, deadline)
        choice_report['date'] = profile.service_date.isoformat()
        choice_reports.append(choice_report)
        reports.extend(compare_plan(graph, manager, repository, profile, binding, plan, limit))
    return {'sample_selection':'reference_ranked_preselection_then_frozen_comparison',
        'selection_reports':selection_reports,
        'audit_mode':'tokyo_common_rail_label_route_sample', 'date_cases':reports, 'date_choices':choice_reports,
        'common_rail_sample_rank_verified':True, 'rail_binding_verified':True,
        'bus_provider':'existing_tokyo', 'time_bounds_provider':'validated_tokyo_reference',
        'calendar_projection':'legacy_date_policy_compatibility_only',
        'holiday_dependency_version':holiday_version, 'walking_policy':'unchanged_supplied_tokyo_graph',
        'operational_calendar_verified':False, 'common_dataset_route_ranking_verified':False,
        'realtime_verified':False, 'lambda_startup_verified':False, 'true_top_k_verified':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('train-timetables','stations','railways','trusted-prebuilt','gtfs-dir'):
        parser.add_argument('--'+flag, type=Path, required=True)
    parser.add_argument('--expected-feed-version', required=True)
    parser.add_argument('--query-date', action='append', required=True)
    parser.add_argument('--max-candidates', type=int, default=3)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--max-selection-queries', type=int, default=90)
    args = parser.parse_args()
    check_repository(args.expected_sha)
    paths = {key:getattr(args,key).resolve() for key in
             ('train_timetables','stations','railways','trusted_prebuilt')}
    root = args.gtfs_dir.resolve()
    def inputs():
        return {**{key:sha256(path) for key,path in paths.items()},
                **{'gtfs/'+path.name:sha256(path) for path in sorted(root.glob('*.txt'))}}
    before = inputs()
    result = inspect(paths['train_timetables'],paths['stations'],paths['railways'],
        paths['trusted_prebuilt'],root,args.expected_feed_version,args.query_date,args.max_candidates,
        max_selection_queries=args.max_selection_queries)
    if before != inputs():
        raise AssertionError('input files changed during rail verification')
    check_repository(args.expected_sha)
    print(json.dumps({'sha':args.expected_sha,'python':sys.version,'input_hashes':before,**result},ensure_ascii=True))
    print('READ_ONLY_TOKYO_COMMON_RAIL_ROUTE_SAMPLE_OK')


if __name__ == '__main__':
    main()
