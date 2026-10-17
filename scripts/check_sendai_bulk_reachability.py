"""One fixed 24-rail-origin coverage measure using the retained raw oracle."""
import argparse
import base64
from datetime import date
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'api')]
from tests.sendai_bulk_fixture import read,load_source
from tests.sendai_municipal_oracle import rows,runs,arrivals
from scripts.check_sendai_expansion import raw_day_kinds


def compute():
    source=load_source();review=read('municipal_review_20261017_bulk.json')
    old=read('municipal_review_20261017_stage8.json');day=date(2026,11,19)
    previous={s for p in old['bus_patterns'] for s in p['stop_ids']}
    added=sorted({s for p in review['bus_patterns'] for s in p['stop_ids']}-previous)
    pub=read('published_20230701.json');raw={n:base64.b64decode(v['cp932_base64'],validate=True) for n,v in pub.items()}
    all_runs=runs(source['files'],raw,{day:raw_day_kinds(review['operating_period'])[day]},day,review)
    if any(max(r['arrs'])>=1440+540 for r in all_runs):raise ValueError('previous-day run may intersect the fixed morning window')
    hub={s for l in review['bus_subway_transfers'] for s in (l['from_stop_id'],l['to_stop_id']) if s.startswith('sendai_subway:')}
    rail=sorted({s for r in all_runs if r['mode']=='rail' for s in r['stops']}-hub)
    # A non-hub origin needs a rail ride to any connection; a new concrete
    # bus pole has no rail link. Thus counted paths include rail AND bus.
    if len(added)!=1834 or len(rail)!=24 or any(s in added for l in review['bus_subway_transfers'] for s in (l['from_stop_id'],l['to_stop_id'])):
        raise AssertionError('explicit new-area mixed-mode universe differs')
    names={'sendai_bus:'+r['stop_id']:r['stop_name'] for r in rows(source['files']['stops.txt'])}
    window=[r for r in all_runs if min(r['deps'])<=720 and max(r['arrs'])>=540]
    by_pole={s:0 for s in added};by_rail={s:0 for s in rail};found=[]
    for station in rail:
        values=arrivals(window,review,station,540,max_boardings=3,max_minutes=180)
        for stop in added:
            if stop in values:
                found.append([station,stop,str(values[stop])]);by_pole[stop]+=1;by_rail[station]+=1
    served=[s for s in added if by_pole[s]]
    return dict(civil_date=day.isoformat(),departure_minute=540,max_boardings=3,max_travel_minutes=180,
        direction='rail_to_new_bus',rail_origins=len(rail),new_bus_poles=len(added),
        possible_pairs=len(rail)*len(added),pairs=len(found),served_new_poles=len(served),
        served_new_stop_names=len({names[s] for s in served}),
        served_rail_origins=sum(bool(v) for v in by_rail.values()),previous_pairs=0,
        by_rail_origin=by_rail,by_new_pole=by_pole,
        od_arrival_sha256=hashlib.sha256(json.dumps(found,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
        note='All 24 non-interchange rail origins to 1834 added concrete poles, one fixed window; each counted route requires rail and bus. No all-day or reverse-direction claim.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--print-candidate',action='store_true');a=p.parse_args()
    result=compute()
    if not a.print_candidate and result!=read('municipal_bulk_reachability_20261017.json'):
        raise AssertionError('fixed raw bulk coverage or arrival evidence differs')
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))
    if not a.print_candidate:print('SENDAI_BULK_NEW_AREA_REACHABILITY_OK')


if __name__=='__main__':main()
