"""New bulk-scope full-row and fixed-route gate; no previous audit replay."""
from __future__ import annotations
import argparse
from collections import defaultdict
import contextlib
from datetime import date
import io
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'api')]
from fastapi.testclient import TestClient
from app.sendai_practical_routes import create_sendai_practical_test_app
from sendai_operating_period import OperatingPeriodReview
from sendai_practical_bundle import build_reviewed_municipal_model,load_reviewed_subway
from sendai_practical_network import PracticalRide,search_practical_subway
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_municipal_oracle import rows,raw_services,runs,optimum,seconds,validate
from scripts.review_sendai_municipal_bulk import source_from_directory,compile_review,digest
from scripts.check_sendai_expansion import raw_day_kinds

F=ROOT/'api/tests/fixtures/sendai_subway'
read=lambda name:json.loads((F/name).read_text(encoding='utf-8'))


def verify_all_rows(bus,source,review):
    approved={t for p in review['bus_patterns'] for t in p['trip_ids']}
    raw_trips={r['trip_id']:r for r in rows(source['files']['trips.txt'])}
    by=defaultdict(list)
    for r in rows(source['files']['stop_times.txt']):
        by['sendai_bus:'+r['trip_id']].append(r)
    actual=defaultdict(list)
    for r in bus.stop_times:
        actual[r.trip_id].append(r)
    if len(bus.trips)!=8231 or len(bus.routes)!=339 or len(approved)!=8142:
        raise AssertionError('complete operator/approval totals differ')
    count=0
    for tid in sorted(approved):
        trip=bus.trips[tid];raw=raw_trips[trip.source_id]
        if (trip.route_id,trip.service_id)!=('sendai_bus:'+raw['route_id'],'sendai_bus:'+raw['service_id']):
            raise AssertionError('raw trip route/service differs: '+tid)
        a=sorted(actual[tid],key=lambda r:r.sequence)
        b=sorted(by[tid],key=lambda r:int(r['stop_sequence']))
        if len(a)!=len(b):raise AssertionError('missing source occurrence: '+tid)
        for value,r in zip(a,b):
            expected=(int(r['stop_sequence']),'sendai_bus:'+r['stop_id'],
                int(seconds(r['arrival_time'])*60),int(seconds(r['departure_time'])*60),
                int(r.get('pickup_type','') or '0'),int(r.get('drop_off_type','') or '0'))
            observed=(value.sequence,value.stop_id,value.arrival_service_seconds,value.departure_service_seconds,
                      value.pickup_type,value.drop_off_type)
            if observed!=expected:raise AssertionError('raw occurrence/clock/pickup/dropoff differs: '+tid)
            count+=1
    for ds in review['reviewed_days']:
        day=date.fromisoformat(ds)
        if bus.active_service_ids(day)!={'sendai_bus:'+s for s in raw_services(source['files'],day)}:
            raise AssertionError('raw service applicability differs: '+ds)
    return dict(approved_trips=len(approved),approved_stop_times=count,reviewed_dates=len(review['reviewed_days']))


def fixed_routes(bus,source,subway,raw_subway,review,matrix):
    net=build_reviewed_municipal_model(subway,bus,review,accept_experimental_bus_transfers=True)
    period=OperatingPeriodReview.from_mapping(review['operating_period'])
    params=NetworkSearchParameters(**matrix['parameters'])
    client=TestClient(create_sendai_practical_test_app(net,environment='test',parameters=params,
        operating_period=period,coverage_label=review['coverage_label']))
    previous={t for p in read('municipal_review_20261017_stage8.json')['bus_patterns'] for t in p['trip_ids']}
    kinds=raw_day_kinds(review['operating_period']);reports=[]
    # All declared conditions finish within their civil day. Prove that no
    # previous-day >24h run can intersect any of them before using one raw day.
    latest=max(seconds(r['arrival_time']) for r in rows(source['files']['stop_times.txt']))
    if latest>=1440 or any(c['departure_minute']+params.max_travel_minutes>=1440 for c in matrix['cases']):
        raise ValueError('fixed single-day oracle window proof no longer applies')
    try:
        for ds in sorted({c['civil_date'] for c in matrix['cases']}):
            day=date.fromisoformat(ds)
            rr=runs(source['files'],raw_subway,{day:kinds[day]},day,review)
            first=min(c['departure_minute'] for c in matrix['cases'] if c['civil_date']==ds)
            if any(max(r['arrs'])>=1440+first for r in rr):
                raise ValueError('previous-day subway run may intersect the fixed window')
            for c in [c for c in matrix['cases'] if c['civil_date']==ds]:
                expected=optimum(rr,review,c['origin'],c['destination'],c['departure_minute'],max_boardings=params.max_boardings,max_minutes=params.max_travel_minutes)
                if expected!=c['expected_arrival_minute']:
                    raise AssertionError('fixed raw expectation differs: '+c['category'])
                start=time.perf_counter()
                with contextlib.redirect_stdout(io.StringIO()):
                    result=search_practical_subway(net,c['origin'],c['destination'],civil_date=day,departure_minute=c['departure_minute'],parameters=params)
                elapsed=time.perf_counter()-start
                if expected is None:
                    if result:raise AssertionError('fixed disconnected condition unexpectedly has a route')
                    response=client.post('/test/sendai/route',json=dict(origin_stop_id=c['origin'],destination_stop_id=c['destination'],civil_date=ds,departure_minute=c['departure_minute'],fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True))
                    if response.status_code!=200 or response.json()['candidates']:
                        raise AssertionError('disconnected condition API differs: '+response.text)
                    reports.append(dict(category=c['category'],arrival_minute=None,status='confirmed_no_route'))
                    print(json.dumps(reports[-1]),flush=True)
                    continue
                if not result or result[0].arrival_estimate.day!=day or result[0].arrival_estimate.minute!=expected:
                    raise AssertionError('common SearchCore differs from independent raw optimum: '+c['category'])
                validate(result[0],rr,review,day,c['origin'],c['destination'],c['departure_minute'])
                rides=[e.source for e in result[0].events if isinstance(e,PracticalRide)]
                if not any(r.mode=='bus' and r.trip_id not in previous for r in rides):
                    raise AssertionError('condition does not witness newly registered concrete service: '+c['category'])
                with contextlib.redirect_stdout(io.StringIO()):
                    response=client.post('/test/sendai/route',json=dict(origin_stop_id=c['origin'],destination_stop_id=c['destination'],civil_date=ds,departure_minute=c['departure_minute'],fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True))
                if response.status_code!=200:raise AssertionError(response.text)
                candidate=response.json()['candidates'][0]
                if candidate['arrival']['minute']!={'numerator':int(expected),'denominator':1} or candidate['fare']['additional_payment_yen']!=0 or candidate['fare']['normal_fare_yen'] is not None:
                    raise AssertionError('API arrival/free quote/unknown normal fare differs')
                report=dict(category=c['category'],civil_date=ds,arrival_minute=int(expected),modes=[r.mode for r in rides],route_ids=[r.route_id for r in rides],query_seconds=round(elapsed,4))
                reports.append(report);print(json.dumps(report,ensure_ascii=False),flush=True)
            del rr
    finally:
        client.close()
    return net,reports


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bus-gtfs-dir',type=Path,required=True)
    p.add_argument('--expected-sha',required=True)
    args=p.parse_args()
    git=lambda *a:subprocess.run(['git','-C',str(ROOT),*a],check=True,capture_output=True,text=True).stdout.strip()
    if git('rev-parse','HEAD')!=args.expected_sha or git('branch','--show-current')!='main':
        raise ValueError('explicit current main required')
    review=read('municipal_review_20261017_bulk.json');scope=read('municipal_bulk_scope_20261017.json')
    previous=read('municipal_review_20261017_stage8.json')
    bus,source=source_from_directory(args.bus_gtfs_dir)
    before=digest(source)
    generated,report=compile_review(source,previous,scope)
    if generated!=review or report!=read('municipal_bulk_inventory_20261017.json'):
        raise AssertionError('all-pattern compiler differs from retained review/report')
    print(json.dumps(verify_all_rows(bus,source,review),sort_keys=True),flush=True)
    sub,raw=load_reviewed_subway(F/'published_20230701.json',F/'practical_review_20261016.json',operating_period=OperatingPeriodReview.from_mapping(review['operating_period']))
    fixed_routes(bus,source,sub,raw,review,read('municipal_fixed_cases_20261017_bulk.json'))
    # Revalidate the very same original source and manifest after the gate.
    _,after=source_from_directory(args.bus_gtfs_dir)
    if digest(after)!=before or git('rev-parse','HEAD')!=args.expected_sha:
        raise AssertionError('raw source or main changed during read-only bulk gate')
    print('READ_ONLY_SENDAI_MUNICIPAL_BULK_OK',flush=True)


if __name__=='__main__':main()
