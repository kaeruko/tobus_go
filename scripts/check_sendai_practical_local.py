"""Read-only fixed-route gate for the explicitly reviewed Sendai model.

Does not fetch, select alternate samples, invoke old audit gates or change data.
Unknown arrivals/transfer measurements/top-k remain uncertified after success.
"""
from __future__ import annotations
import argparse
import contextlib
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'api'))
from sendai_transit import load_sendai_dataset
from sendai_practical_bundle import load_reviewed_subway,build_reviewed_municipal_model
from sendai_practical_network import search_practical_subway,PracticalRide
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_municipal_oracle import runs,optimum,validate,rows


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs(args):
    paths=list(args.bus_gtfs_dir.glob('*.txt'))+[args.bus_gtfs_dir/'sendai_gtfs_manifest.json',args.bus_gtfs_dir/'sendai_gtfs_source.zip',args.subway_published,args.subway_review,args.municipal_review,args.cases,args.bus_subset]
    return {str(p.resolve()):digest(p) for p in paths}


def verify_subset(bus_dir,fixture,review):
    """Independently reproduce row filtering; subset is never used as fallback."""
    if fixture['source_zip_sha256']!=review['bus_source_sha256']:
        raise ValueError('subset provenance ZIP hash mismatch')
    if digest(bus_dir/'sendai_gtfs_source.zip')!=fixture['source_zip_sha256']:
        raise ValueError('approved ZIP differs from subset origin')
    complete={name:rows((bus_dir/name).read_text(encoding='utf-8-sig')) for name in fixture['files']}
    for name,sha in fixture['source_member_sha256'].items():
        if digest(bus_dir/name)!=sha:raise ValueError(f'source member changed: {name}')
    tripids={tid.split(':',1)[1] for p in review['bus_patterns'] for tid in p['trip_ids']}
    trips=[r for r in complete['trips.txt'] if r['trip_id'] in tripids]
    routeids={r['route_id'] for r in trips};serviceids={r['service_id'] for r in trips}
    stoprows=[r for r in complete['stop_times.txt'] if r['trip_id'] in tripids];stopids={r['stop_id'] for r in stoprows}
    selected={'trips.txt':trips,'stop_times.txt':stoprows,
        'routes.txt':[r for r in complete['routes.txt'] if r['route_id'] in routeids],
        'stops.txt':[r for r in complete['stops.txt'] if r['stop_id'] in stopids],
        'calendar.txt':[r for r in complete['calendar.txt'] if r['service_id'] in serviceids],
        'calendar_dates.txt':[r for r in complete['calendar_dates.txt'] if r['service_id'] in serviceids],
        'agency.txt':complete['agency.txt'],'feed_info.txt':complete['feed_info.txt']}
    if set(selected)!=set(fixture['files']) or any(selected[n]!=rows(fixture['files'][n]) for n in selected):
        raise ValueError('committed subset differs from exact source row selection')


def run(args):
    git=lambda *parts:subprocess.run(['git','-C',str(ROOT),*parts],check=True,capture_output=True,text=True).stdout.strip()
    def source_status():
        records=git('status','--porcelain','--untracked-files=all','--','api','scripts').splitlines()
        return [r for r in records if not (r.startswith('?? ') and '/__pycache__/' in r and r.endswith('.pyc'))]
    head=git('rev-parse','HEAD')
    if head!=args.expected_sha or git('branch','--show-current')!='main':
        raise ValueError('expected main SHA mismatch')
    if source_status():
        raise ValueError('audit source has uncommitted changes')
    if not args.accept_experimental_transfer_model:
        raise ValueError('explicit experimental transfer-model acknowledgment required')
    before=inputs(args)
    bus=load_sendai_dataset(args.bus_gtfs_dir,expected_service_date=args.expected_service_date)
    subway,raw_subway=load_reviewed_subway(args.subway_published,args.subway_review)
    review=json.loads(args.municipal_review.read_text(encoding='utf-8'))
    fixture=json.loads(args.bus_subset.read_text(encoding='utf-8'))
    verify_subset(args.bus_gtfs_dir,fixture,review)
    net=build_reviewed_municipal_model(subway,bus,review,accept_experimental_bus_transfers=True)
    matrix=json.loads(args.cases.read_text(encoding='utf-8'))
    params=NetworkSearchParameters(**matrix['parameters'])
    if params.max_candidates!=1:raise ValueError('gate covers one earliest route only')
    categories={c['category'] for c in matrix['cases']}
    if categories!={'bus_only','subway_only','bus_rail','rail_bus'}:
        raise ValueError('all four fixed route categories required')
    raw_bus={name:(args.bus_gtfs_dir/name).read_text(encoding='utf-8-sig') for name in ('trips.txt','stop_times.txt','calendar.txt','calendar_dates.txt')}
    kinds={e.day:e.kind for e in subway.operating_days.entries if e.kind is not None}
    for i,case in enumerate(matrix['cases'],1):
        day=date.fromisoformat(case['civil_date'])
        rr=runs(raw_bus,raw_subway,kinds,day,review)
        expected=optimum(rr,review,case['origin'],case['destination'],case['departure_minute'],max_boardings=params.max_boardings,max_minutes=params.max_travel_minutes)
        # Fixed sample: errors/missing category/mismatch stop; never try another OD.
        with contextlib.redirect_stdout(io.StringIO()):
            result=search_practical_subway(net,case['origin'],case['destination'],civil_date=day,departure_minute=case['departure_minute'],parameters=params)
        if not result or expected is None:raise AssertionError(f'fixed case unavailable: category={case["category"]} attempt={i}')
        j=result[0];actual=(j.arrival_estimate.day-day).days*1440+j.arrival_estimate.minute
        if actual!=expected or expected!=case['expected_arrival_minute']:
            raise AssertionError(f'fixed arrival mismatch: category={case["category"]} attempt={i}')
        validate(j,rr,review,day,case['origin'],case['destination'],case['departure_minute'])
        modes=[e.source.mode for e in j.events if isinstance(e,PracticalRide)]
        required={'bus_only':['bus'],'subway_only':['rail'],'bus_rail':['bus','rail'],'rail_bus':['rail','bus']}[case['category']]
        if modes!=required:raise AssertionError(f'fixed mode witness mismatch: category={case["category"]} attempt={i}')
        print(json.dumps({'category':case['category'],'mode':'time','attempt':i,'status':'ok'},ensure_ascii=False),flush=True)
    if inputs(args)!=before or git('rev-parse','HEAD')!=head or source_status():
        raise AssertionError('inputs or audit source changed during gate')
    print(json.dumps({'sha':head,'input_hashes':before,'fixed_cases':len(matrix['cases']),
        'bus_version':bus.metadata.version,'subway_version':subway.dataset.metadata.version,
        'scope':'reviewed 20/R20 + two subway lines; finite normal dates; planning assumptions',
        'exact_arrival_verified':False,'transfer_time_measured':False,'actual_connection_guaranteed':False,
        'true_top_k_verified':False},ensure_ascii=False))
    print('READ_ONLY_SENDAI_PRACTICAL_MUNICIPAL_MODEL_OK')


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('bus-gtfs-dir','subway-published','subway-review','municipal-review','cases','bus-subset'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--expected-service-date',required=True);p.add_argument('--expected-sha',required=True)
    p.add_argument('--accept-experimental-transfer-model',action='store_true')
    return p


if __name__=='__main__':run(parser().parse_args())
