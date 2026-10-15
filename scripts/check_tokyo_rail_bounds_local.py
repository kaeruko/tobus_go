"""Read-only static Tokyo rail interval-minimum input audit, without OD searches.

Requires local ODPT JSON and an explicitly trusted Tokyo prebuilt. No GTFS,
query-date filtering, realtime, download, repair, source/cache writes, graph
projection, provider switch, bus audit, route comparison or output files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import pickle
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))
sys.path.insert(0, str(ROOT / 'scripts'))

import toei_engine as engine
from check_tokyo_odpt_local import check_repository, sha256
from check_tokyo_rail_routes_local import load_binding
from tokyo_rail_interval_audit import verify_static_rail_interval_minima


def inspect(train, stations, railways, prebuilt):
    with prebuilt.open('rb') as stream:
        data = pickle.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get('TM'), engine.TimetableManager):
        raise ValueError('trusted prebuilt requires Tokyo TM; no repair')
    # G is deliberately not inspected: graph projection is a separate gate.
    manager = data['TM']
    binding = load_binding(train, stations, railways, manager)
    verified = verify_static_rail_interval_minima(binding, manager)
    return {
        **verified,
        'audit_mode': 'tokyo_common_rail_static_interval_minima',
        'calendar_scope': 'all_source_calendars_no_date_filter',
        'interval_clock': 'current_departure_to_next_arrival_excludes_dwell',
        'float_policy': 'existing_tokyo_binary64_subtraction_downward_guard',
        'common_rail_time_bounds_provider': 'not_selected_audit_only',
        'rail_provider': 'not_selected_audit_only',
        'bus_provider': 'not_evaluated',
        'common_rail_sample_rank_verified': False,
        'common_rail_graph_projection_verified': False,
        'common_rail_destination_bounds_verified': False,
        'common_rail_priority_rounding_verified': False,
        'common_dataset_route_ranking_verified': False,
        'operational_calendar_verified': False,
        'realtime_verified': False,
        'lambda_startup_verified': False,
        'true_top_k_verified': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('train-timetables', 'stations', 'railways', 'trusted-prebuilt'):
        parser.add_argument('--'+flag, type=Path, required=True)
    parser.add_argument('--expected-sha', required=True)
    args = parser.parse_args()
    check_repository(args.expected_sha)
    paths = {key:getattr(args, key).resolve() for key in
             ('train_timetables', 'stations', 'railways', 'trusted_prebuilt')}
    before = {key:sha256(path) for key, path in paths.items()}
    result = inspect(paths['train_timetables'], paths['stations'], paths['railways'], paths['trusted_prebuilt'])
    if before != {key:sha256(path) for key, path in paths.items()}:
        raise AssertionError('inputs changed during rail interval audit')
    check_repository(args.expected_sha)
    print(json.dumps({'sha':args.expected_sha, 'python':sys.version,
                     'input_hashes':before, **result}, ensure_ascii=True))
    print('READ_ONLY_TOKYO_COMMON_RAIL_INTERVAL_MINIMA_OK')


if __name__ == '__main__':
    main()
