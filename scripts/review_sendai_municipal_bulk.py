"""Compile an explicit whole-path group review to the existing bus contract.

Inventory is not approval. Every complete pattern must have exactly one
retained human review decision; new/changed paths fail closed. No coordinate,
endpoint, short-number or office-wide automatic free-scope inference occurs.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))
from sendai_transit import load_sendai_dataset, SENDAI_MANIFEST_FILENAME

FILES = ('agency.txt', 'feed_info.txt', 'routes.txt', 'trips.txt',
         'stop_times.txt', 'stops.txt', 'calendar.txt', 'calendar_dates.txt')
SOURCE_SHA = '53a08400776b3229743b24eb53566eb523b354a5b783dcfffd3e40f39258e6a2'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def source_from_directory(root):
    # Existing loader checks original ZIP, all member SHAs, operator, version
    # and coverage. This compiler is never an alternative GTFS adapter.
    dataset = load_sendai_dataset(root, expected_service_date='2026-10-16')
    manifest = json.loads((root / SENDAI_MANIFEST_FILENAME).read_text(encoding='utf-8'))
    if manifest['sha256'] != SOURCE_SHA or manifest['published_version'] != '20261007_20261130':
        raise ValueError('explicit approved municipal source required')
    source = dict(source_url=manifest['source_url'], source_zip_sha256=manifest['sha256'],
        source_member_sha256={n: manifest['file_sha256'][n] for n in FILES},
        files={n: (root / n).read_text(encoding='utf-8-sig') for n in FILES})
    return dataset, source


def inventory(source):
    if source['source_zip_sha256'] != SOURCE_SHA:
        raise ValueError('inventory source ZIP differs')
    tables = {}
    for name in FILES:
        reader = csv.DictReader(io.StringIO(source['files'][name]))
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError('missing/duplicate source header: ' + name)
        tables[name] = list(reader)
        if any(None in r for r in tables[name]):
            raise ValueError('extra source columns: ' + name)
    agency = tables['agency.txt']
    if len(agency) != 1 or (agency[0]['agency_id'], agency[0]['agency_name']) != ('8000020041009', '仙台市交通局'):
        raise ValueError('only the reviewed municipal operator may be inventoried')
    routes = {r['route_id']: r for r in tables['routes.txt']}
    trips = {t['trip_id']: t for t in tables['trips.txt']}
    stops = {s['stop_id']: s for s in tables['stops.txt']}
    if any(len(values) != len(tables[name]) for values, name in (
        (routes, 'routes.txt'), (trips, 'trips.txt'), (stops, 'stops.txt'))):
        raise ValueError('duplicate raw identity')
    if any(r['agency_id'] != agency[0]['agency_id'] or r['route_type'] != '3' for r in routes.values()):
        raise ValueError('unreviewed operator or non-bus route')
    rows = defaultdict(list)
    for row in tables['stop_times.txt']:
        if row['trip_id'] not in trips or row['stop_id'] not in stops:
            raise ValueError('unknown raw trip/pole reference')
        rows[row['trip_id']].append(row)
    groups = {}
    for tid, trip in trips.items():
        rr = sorted(rows[tid], key=lambda r: int(r['stop_sequence']))
        if len(rr) < 2 or len({r['stop_sequence'] for r in rr}) != len(rr):
            raise ValueError('invalid complete source sequence: ' + tid)
        key = trip['route_id'], tuple(r['stop_id'] for r in rr)
        group = groups.setdefault(key, [])
        group.append(tid)
    patterns = []
    for (route, stop_ids), tids in sorted(groups.items()):
        identity = dict(route_id='sendai_bus:' + route, stop_ids=['sendai_bus:' + s for s in stop_ids])
        # Full source trip rows, occurrence order, pickup/dropoff, exact clocks
        # and calendars stay independent of the generated approval contract.
        contract = {tid: dict(trip=trips[tid], stop_times=sorted(rows[tid], key=lambda r: int(r['stop_sequence'])))
                    for tid in sorted(tids)}
        patterns.append(dict(**identity, pattern_id=digest(identity),
            short_name=routes[route]['route_short_name'],
            stop_names=[stops[s]['stop_name'] for s in stop_ids],
            trip_ids=['sendai_bus:' + tid for tid in sorted(tids)],
            office_ids=sorted({trips[t]['jp_office_id'] for t in tids}),
            services=dict(sorted(Counter(trips[t]['service_id'] for t in tids).items())),
            source_contract_sha256=digest(contract)))
    report = dict(routes=len(routes), patterns=len(patterns), trips=len(trips),
        stop_times=len(tables['stop_times.txt']), source_stops=len(stops),
        used_stops=len({r['stop_id'] for r in tables['stop_times.txt']}),
        service_ids=sorted({t['service_id'] for t in trips.values()}),
        calendar_sha256=digest([tables['calendar.txt'], tables['calendar_dates.txt']]),
        patterns_sha256=digest(patterns))
    return patterns, report


def compile_review(source, previous, scope):
    patterns, totals = inventory(source)
    if (scope['schema_version'] != 1 or scope['source_zip_sha256'] != SOURCE_SHA
            or scope['inventory'] != totals):
        raise ValueError('exact full-source inventory review differs')
    decisions = {}
    groups = {}
    for group in scope['groups']:
        if group['id'] in groups or not group['reason'].strip() or not group['evidence']:
            raise ValueError('duplicate/incomplete whole-path group review')
        if group['decision'] not in ('approved_whole_run', 'outside_city', 'unconfirmed'):
            raise ValueError('unknown review decision')
        if group['decision'] == 'approved_whole_run' and (
                group['entire_driven_path_municipality'] != '04100' or group['service_kind'] != 'local'):
            raise ValueError('group is not reviewed local whole-path scope')
        groups[group['id']] = group
        for key in group['pattern_ids']:
            if key in decisions:
                raise ValueError('pattern has multiple review decisions')
            decisions[key] = group
    if set(decisions) != {p['pattern_id'] for p in patterns}:
        raise ValueError('every exact complete pattern requires one explicit decision')
    approved = {p['pattern_id']: p for p in patterns
                if decisions[p['pattern_id']]['decision'] == 'approved_whole_run'}
    old_keys = set()
    for p in previous['bus_patterns']:
        key = digest({k: p[k] for k in ('route_id', 'stop_ids')})
        if key not in approved or any(p[k] != approved[key][k] for k in ('route_id', 'stop_ids', 'stop_names')) or sorted(p['trip_ids']) != approved[key]['trip_ids']:
            raise ValueError('previous verified pattern is not preserved')
        old_keys.add(key)
    new = []
    for key, p in sorted(approved.items()):
        if key in old_keys:
            continue
        g = decisions[key]
        new.append(dict(**{k: p[k] for k in ('route_id', 'stop_ids', 'stop_names', 'trip_ids')},
            entire_driven_path_municipality='04100', service_kind='local',
            map_evidence=g['evidence'][0], review_group=g['id'],
            source_contract_sha256=p['source_contract_sha256']))
    result = {**previous, 'stage_profile': 'sendai_municipal_bulk_v1',
        'coverage_label': f'仙台市営バス{len({p["route_id"] for p in approved.values()})}/{totals["routes"]}路線ID・{sum(len(p["trip_ids"]) for p in approved.values()):,}便＋地下鉄2線（開発検証・市外通過便除外）',
        'bus_patterns': previous['bus_patterns'] + new,
        'bulk_scope_sha256': digest(scope)}
    report = {**totals, 'approved': {}, 'decisions': {}}
    for status in ('approved_whole_run', 'outside_city', 'unconfirmed'):
        pp = [p for p in patterns if decisions[p['pattern_id']]['decision'] == status]
        value = dict(routes=len({p['route_id'] for p in pp}), patterns=len(pp),
                     trips=sum(len(p['trip_ids']) for p in pp),
                     stops=len({s for p in pp for s in p['stop_ids']}))
        report['decisions'][status] = value
    report['approved'] = report['decisions']['approved_whole_run']
    report['new_trips'] = report['approved']['trips'] - sum(len(p['trip_ids']) for p in previous['bus_patterns'])
    report['approved_pattern_ids'] = sorted(approved)
    report['excluded_patterns'] = [{**p, 'reason_group': decisions[p['pattern_id']]['id']}
        for p in patterns if p['pattern_id'] not in approved]
    return result, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bus-gtfs-dir', type=Path, required=True)
    parser.add_argument('--scope', type=Path, required=True)
    parser.add_argument('--previous-review', type=Path, required=True)
    args = parser.parse_args()
    _, source = source_from_directory(args.bus_gtfs_dir)
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    review, report = compile_review(source, read(args.previous_review), read(args.scope))
    print(json.dumps(dict(review=review, report=report), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
