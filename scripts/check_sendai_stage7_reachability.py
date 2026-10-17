"""Finite new-area reachability using the existing independent raw oracle.

Counts directed concrete OD pairs at ONE fixed date/time, not all-day coverage
or geographic catchments. It never supplies production routes or modifies data.
"""
from __future__ import annotations
import argparse
import base64
from datetime import date
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'api')]
from scripts.check_sendai_expansion import raw_day_kinds
from tests.sendai_municipal_oracle import optimum, rows, runs

F=ROOT/'api/tests/fixtures/sendai_subway'


def compute(source,review,previous,published):
    day=date(2026,11,19);start=540;limit=180
    old={s for p in previous['bus_patterns'] for s in p['stop_ids']}
    added={s for p in review['bus_patterns'] for s in p['stop_ids']}-old
    hub_bus={'sendai_bus:50_850','sendai_bus:50_210'}
    hub_rail={'sendai_subway:namboku/仙台','sendai_subway:tozai/仙台'}
    if len(added)!=44 or not hub_bus<=added:raise ValueError('Explicit new-area scope changed')
    new_paths={s for p in review['bus_patterns'][len(previous['bus_patterns']):] for s in p['stop_ids']}
    if new_paths!=added:raise ValueError('New bus paths must be concretely disjoint for this metric')
    names={'sendai_bus:'+r['stop_id']:r['stop_name'] for r in rows(source['files']['stops.txt'])}
    raw={n:base64.b64decode(v['cp932_base64'],validate=True) for n,v in published.items()}
    all_runs=runs(source['files'],raw,raw_day_kinds(review['operating_period']),day,review)
    # Keep every run whose absolute clocks intersect the fixed 180-minute
    # query window, including previous-day >24h services if present. This is
    # just the same oracle's finite input window, never a different algorithm.
    window=[r for r in all_runs if min(r['deps'])<=start+limit and max(r['arrs'])>=start]
    rail=sorted({s for r in all_runs if r['mode']=='rail' for s in r['stops']}-hub_rail)
    bus=sorted(added-hub_bus)
    if len(rail)!=28 or len(bus)!=42:raise ValueError('Explicit non-hub OD universe changed')
    # New bus paths share no concrete pole with the preceding bus scope.
    # With the eight Sendai links removed there is no edge to the rail/old
    # component; same names are not edges. Do not claim station-adjacent walks
    # alone as bus+rail trips: both Sendai bus poles/rail endpoints are omitted.
    new_links=review['bus_subway_transfers'][len(previous['bus_subway_transfers']):]
    if len(new_links)!=8 or review['bus_subway_transfers'][:-8]!=previous['bus_subway_transfers']:
        raise ValueError('Expected exactly eight new directed Sendai links')
    if any((l['from_stop_id'] in added or l['to_stop_id'] in added) for l in previous['bus_subway_transfers']):
        raise ValueError('New area already had an old rail connection')
    result=dict(civil_date=day.isoformat(),departure_minute=start,max_boardings=3,max_travel_minutes=limit,
        scope='44 added concrete poles; exclude two Sendai bus poles and both Sendai rail vertices; bus+rail required by disjoint concrete topology',
        added_bus_poles=44,nonhub_bus_poles=len(bus),nonhub_stop_names=len({names[b] for b in bus}),rail_vertices=len(rail),
        previous_new_area_pairs=0,without_sendai_links_pairs=0)
    for direction in ('bus_to_rail','rail_to_bus'):
        found=[];by_bus={b:0 for b in bus};by_rail={r:0 for r in rail}
        for b in bus:
            for r in rail:
                origin,dest=(b,r) if direction=='bus_to_rail' else (r,b)
                answer=optimum(window,review,origin,dest,start,max_boardings=3,max_minutes=limit)
                if answer is not None:
                    found.append([origin,dest,str(answer)]);by_bus[b]+=1;by_rail[r]+=1
        canonical=json.dumps(found,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        served=[b for b,n in by_bus.items() if n]
        result[direction]=dict(pairs=len(found),possible_pairs=len(bus)*len(rail),
            served_bus_poles=len(served),served_stop_names=len({names[b] for b in served}),
            served_rail_vertices=sum(bool(n) for n in by_rail.values()),
            by_bus_pole=by_bus,by_rail_vertex=by_rail,od_arrival_sha256=hashlib.sha256(canonical).hexdigest())
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--print-candidate',action='store_true',help='Print original-oracle evidence; never overwrite expectations')
    args=p.parse_args()
    read=lambda n:json.loads((F/n).read_text(encoding='utf-8'))
    result=compute(read('municipal_bus_subset_20261006_stage7.json'),read('municipal_review_20261017_stage7.json'),
        read('municipal_review_20261017_stage6.json'),read('published_20230701.json'))
    if not args.print_candidate and result!=read('municipal_reachability_20261017_stage7.json'):
        raise AssertionError('Fixed new-area independent reachability or arrivals changed')
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2),flush=True)
    if not args.print_candidate:print('SENDAI_STAGE7_NEW_AREA_REACHABILITY_OK')


if __name__=='__main__':main()
