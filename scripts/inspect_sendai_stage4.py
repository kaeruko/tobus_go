"""Inventory new routes at exact reviewed hub poles; no fare approval or search."""
from __future__ import annotations
import argparse
import base64
from collections import Counter, defaultdict
import csv
from datetime import date
import io
import json
from pathlib import Path
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'api'))
from scripts.derive_sendai_expansion_subset import derive
from scripts.inspect_sendai_expansion import FILES
from sendai_transit import load_sendai_dataset, SENDAI_MANIFEST_FILENAME
from tests.sendai_municipal_oracle import raw_services

SHA = '53a08400776b3229743b24eb53566eb523b354a5b783dcfffd3e40f39258e6a2'
HUBS = {'1085_0','1085_12','5181_0','5181_11'}


def inspect(directory):
    manifest=json.loads((directory/SENDAI_MANIFEST_FILENAME).read_text(encoding='utf-8'))
    if manifest['sha256'] != SHA or manifest['published_version'] != '20261007_20261130':
        raise ValueError('Exact approved original feed and version required')
    load_sendai_dataset(directory, expected_service_date='2026-10-16')
    files={n:(directory/n).read_text(encoding='utf-8-sig') for n in FILES}
    rows={n:list(csv.DictReader(io.StringIO(v))) for n,v in files.items()}
    review=json.loads((ROOT/'api/tests/fixtures/sendai_subway/municipal_review_20261017_stage3.json').read_text(encoding='utf-8'))
    existing={p['route_id'].split(':',1)[1] for p in review['bus_patterns']}
    known_stops={s.split(':',1)[1] for p in review['bus_patterns'] for s in p['stop_ids']}
    stops={r['stop_id']:r for r in rows['stops.txt']}
    routes={r['route_id']:r for r in rows['routes.txt']}
    times=defaultdict(list)
    for r in rows['stop_times.txt']:times[r['trip_id']].append(r)
    candidates={t['route_id'] for t in rows['trips.txt'] if t['route_id'] not in existing
        and any(r['stop_id'] in HUBS for r in times[t['trip_id']])}
    days=(date(2026,11,19),date(2026,11,21),date(2026,11,23))
    services=[raw_services(files,d) for d in days]
    grouped=defaultdict(list)
    for t in rows['trips.txt']:
        if t['route_id'] in candidates:grouped[t['route_id']].append(t)
    summary=[]
    for rid,trips in grouped.items():
        patterns=defaultdict(list)
        for t in trips:
            seq=tuple(r['stop_id'] for r in sorted(times[t['trip_id']],key=lambda r:int(r['stop_sequence'])))
            patterns[seq].append(t)
        hub_trips=[t for t in trips if any(r['stop_id'] in HUBS for r in times[t['trip_id']])]
        stop_ids={s for seq in patterns for s in seq}
        summary.append(dict(route_id=rid,number=routes[rid]['route_short_name'],trips=len(trips),
            daily=[sum(t['service_id'] in active for t in trips) for active in services],
            hub_daily=[sum(t['service_id'] in active for t in hub_trips) for active in services],
            pattern_count=len(patterns),new_stops=len(stop_ids-known_stops),
            patterns=[dict(stop_ids=list(seq),stop_names=[stops[s]['stop_name'] for s in seq],
                coordinates=[[stops[s]['stop_lat'],stops[s]['stop_lon']] for s in seq],
                trips=len(tt),services=dict(Counter(t['service_id'] for t in tt))) for seq,tt in patterns.items()]))
    summary.sort(key=lambda r:(-r['hub_daily'][0],-r['new_stops'],r['route_id']))
    # A bounded inventory selection, never an operational/free-scope decision.
    selected=tuple(r['route_id'] for r in summary if r['pattern_count']<=4 and r['hub_daily'][0]>0)[:3]
    if len(selected)!=3:raise ValueError('Expected three bounded hub-route candidates')
    source=dict(source_url=manifest['source_url'],source_zip_sha256=SHA,
        source_member_sha256={n:manifest['file_sha256'][n] for n in FILES},files=files)
    # Retain the combined exact original row order so the existing source-row
    # verifier can check a later expansion without weakening its comparison.
    subset=derive(source,tuple(sorted(existing))+selected)
    return dict(hub_stop_ids=sorted(HUBS),daily_dates=[d.isoformat() for d in days],
        selection='first three by weekday trips on exact reviewed hub poles, new stop count, exact route ID; <=4 complete patterns; no free approval',
        selected_route_ids=selected,routes=summary),subset


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bus-gtfs-dir',type=Path,required=True)
    args=p.parse_args()
    summary,subset=inspect(args.bus_gtfs_dir)
    print('SENDAI_STAGE4_INVENTORY='+json.dumps(summary,ensure_ascii=False,sort_keys=True),flush=True)
    packed=zlib.compress(json.dumps(subset,ensure_ascii=False,sort_keys=True).encode('utf-8'),9)
    print('SENDAI_STAGE4_SUBSET_ZLIB_BASE64='+base64.b64encode(packed).decode('ascii'),flush=True)


if __name__=='__main__':main()
