"""Read-only stage6 extraction from the *same* SHA-pinned official municipal GTFS.

Emits exact original source row order, explicit concrete trip/stop IDs and
a multipart base64 fixture for committing through a separate GitHub review.
This inspector neither approves a route nor registers a free-pass scope.
"""
from __future__ import annotations
import base64
from collections import Counter, defaultdict
import csv
from datetime import date
import io
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'api'))
from scripts.derive_sendai_expansion_subset import derive
from scripts.inspect_sendai_expansion import FILES
from sendai_transit import load_sendai_dataset, SENDAI_MANIFEST_FILENAME
from tests.sendai_municipal_oracle import raw_services

F=ROOT/'api/tests/fixtures/sendai_subway'
SOURCE_SHA='53a08400776b3229743b24eb53566eb523b354a5b783dcfffd3e40f39258e6a2'
RID='10022'


def inspect(directory: Path):
    manifest=json.loads((directory/SENDAI_MANIFEST_FILENAME).read_text(encoding='utf-8'))
    if manifest['sha256']!=SOURCE_SHA or manifest['published_version']!='20261007_20261130':
        raise ValueError('Different official municipal data version')
    load_sendai_dataset(directory,expected_service_date='2026-10-16')
    source=dict(source_url=manifest['source_url'],source_zip_sha256=SOURCE_SHA,
        source_member_sha256={n:manifest['file_sha256'][n] for n in FILES},
        files={n:(directory/n).read_text(encoding='utf-8-sig') for n in FILES})
    old=json.loads((F/'municipal_bus_subset_20261006_stage5.json').read_text(encoding='utf-8'))
    if derive(source,tuple(old['extraction']['route_ids']))!=old:
        raise ValueError('Previously reviewed source-row ordering changed')
    data={n:list(csv.DictReader(io.StringIO(s))) for n,s in source['files'].items()}
    selected=[t for t in data['trips.txt'] if t['route_id']==RID]
    if len(selected)!=26:
        raise ValueError('Arai16 concrete trip count changed')
    routes=[r for r in data['routes.txt'] if r['route_id']==RID]
    if len(routes)!=1 or routes[0]['route_short_name']!='16':
        raise ValueError('Wrong Arai16 exact route ID')
    selected_ids={t['trip_id'] for t in selected}
    stop_times=defaultdict(list)
    for row in data['stop_times.txt']:
        if row['trip_id'] in selected_ids:stop_times[row['trip_id']].append(row)
    paths={tuple(r['stop_id'] for r in stop_times[t['trip_id']]) for t in selected}
    if len(paths)!=1:raise ValueError('More than one source path, no implicit path approval')
    path,=paths
    if len(path)!=25 or path[0]!='5181_10' or path[-1]!='5181_0':
        raise ValueError('Arai16 full loop endpoint or length changed')
    if any(len(stop_times[t['trip_id']])!=25 for t in selected):
        raise ValueError('Arai16 truncated concrete trip')
    dates=('2026-11-19','2026-11-21','2026-11-23')
    daily=[sum(t['service_id'] in raw_services(source['files'],date.fromisoformat(d)) for t in selected) for d in dates]
    if daily!=[12,7,7]:raise ValueError('Arai16 daily service counts changed')
    old_stops={s.split(':',1)[1] for p in json.loads((F/'municipal_review_20261017_stage5.json').read_text(encoding='utf-8'))['bus_patterns'] for s in p['stop_ids']}
    stops={s['stop_id']:s for s in data['stops.txt']}
    pattern=dict(route_id='sendai_bus:'+RID,
        stop_ids=['sendai_bus:'+s for s in path],
        stop_names=[stops[s]['stop_name'] for s in path],
        trip_ids=['sendai_bus:'+t['trip_id'] for t in selected],
        entire_driven_path_municipality='sendai_only',
        service_kind='full_gtfs_calendar',
        map_evidence=[dict(uri='https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r0804-4_kasuminome.pdf',
            sha256='2b7191d3cc03de50f93ea4bfb3da9766abd8a86ccf624baf9b5c2290e64493e8')],
        review_note='Arai 16 reverse circular, exactly route 10022 and its 26 complete 25-stop source trips; fixed reverse poles. Official Kasuminome 2026/04 figure already reviewed in stage5. Bay1 connection is stage5 approved directional link, not a mirrored transfer.')
    # Preserve original rows of ALL approved routes, including the new reverse.
    new=derive(source,tuple(old['extraction']['route_ids'])+(RID,))
    summary=dict(pattern=pattern, daily=daily, services=dict(Counter(t['service_id'] for t in selected)),
        new_stop_ids=sorted(set(path)-old_stops),stop_rows=26*25,
        source_sha=SOURCE_SHA,source_version=manifest['published_version'],
        approved_prior_trip_count=310,expected_total_trip_count=336)
    return summary,new


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bus-gtfs-dir',type=Path,required=True)
    args=p.parse_args()
    summary,fixture=inspect(args.bus_gtfs_dir)
    print('SENDAI_STAGE6_INSPECTION='+json.dumps(summary,ensure_ascii=False,sort_keys=True),flush=True)
    data=(json.dumps(fixture,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
    encoded=base64.b64encode(data).decode('ascii')
    for i in range(0,len(encoded),4000):
        print(f'SENDAI_STAGE6_FIXTURE_{i//4000:05d}='+encoded[i:i+4000],flush=True)
    print(f'SENDAI_STAGE6_FIXTURE_END={len(data)}:{len(encoded)}:{(len(encoded)+3999)//4000}',flush=True)

if __name__=='__main__':main()
