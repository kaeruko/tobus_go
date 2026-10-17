"""Same three OD/time/budget searches in fresh processes; Linux peak RSS.

Stops/date/expected arrivals are fixed before each profile. Startup includes
the exact approved source loader, subway and reviewed network construction.
No routing algorithm, source subset or candidate budget is changed.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'api')]


def one(profile, directory):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.route_endpoint import register_route_endpoint
    from app.route_only_routes import SharedNetworkApiRouteRequest
    from app.sendai_practical_routes import create_sendai_practical_test_app
    from sendai_transit import load_sendai_dataset,SendaiRouteBackend
    from sendai_practical_bundle import load_reviewed_subway,build_reviewed_municipal_model
    from sendai_operating_period import OperatingPeriodReview
    from sendai_coordinate_routes import SendaiCoordinateScope
    from transit_timetable_choices import NetworkSearchParameters
    f=ROOT/'api/tests/fixtures/sendai_subway'
    started=time.perf_counter()
    bus=load_sendai_dataset(directory,expected_service_date='2026-10-16')
    review=json.loads((f/'municipal_review_20261017_bulk.json').read_text(encoding='utf-8'))
    period=OperatingPeriodReview.from_mapping(review['operating_period'])
    subway,_=load_reviewed_subway(f/'published_20230701.json',f/'practical_review_20261016.json',operating_period=period)
    network=build_reviewed_municipal_model(subway,bus,review,accept_experimental_bus_transfers=True)
    params=NetworkSearchParameters(max_candidates=1,max_boardings=3,max_travel_minutes=180)
    if profile=='stop-id':
        app=create_sendai_practical_test_app(network,environment='test',parameters=params,operating_period=period)
    else:
        engine=SendaiCoordinateScope(None,network,period,environment='development',
            normal_backend_factory=lambda:SendaiRouteBackend(bus))
        app=FastAPI();app.state.loading_status='ready';app.state.city_key='sendai';app.state.route_engine=engine
        register_route_endpoint(app,warmup_message='starting',request_model=SharedNetworkApiRouteRequest)
    startup=time.perf_counter()-started
    cases=json.loads((f/'normal_coordinate_cases_20261017.json').read_text(encoding='utf-8'))['cases'][1:4]
    report=[]
    with TestClient(app) as client:
        for case in cases:
            values=[]
            for _ in range(3):
                started=time.perf_counter()
                if profile=='stop-id':
                    result=client.post('/test/sendai/route',json=dict(origin_stop_id=case['origin_stop_id'],
                        destination_stop_id=case['destination_stop_id'],civil_date=case['civil_date'],departure_minute=540,
                        fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True))
                else:
                    result=client.post('/route',json=dict(alat=case['origin'][0],alon=case['origin'][1],
                        blat=case['destination'][0],blon=case['destination'][1],start_time='09:00',
                        target_date_str=case['civil_date'],pref='time',fare_policy_id='sendai_fureai_pass',
                        accept_experimental_transfer_model=True))
                result.raise_for_status();values.append(time.perf_counter()-started)
                value=result.json()['candidates'][0]
                arrival=value['arrival']['time'] if profile=='stop-id' else value['arrival_time']
                expected=f"{case['arrival_minute']//60:02d}:{case['arrival_minute']%60:02d}"
                assert arrival==expected,(case,arrival)
            report.append(dict(case=case['name'],seconds=values,median_seconds=statistics.median(values),arrival=arrival))
    return dict(profile=profile,startup_seconds=startup,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                queries=report)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bus-gtfs-dir',required=True)
    p.add_argument('--profile',choices=('stop-id','normal'));args=p.parse_args()
    if args.profile:
        with contextlib.redirect_stdout(io.StringIO()):
            result=one(args.profile,args.bus_gtfs_dir)
        print(json.dumps(result));return
    results=[]
    for profile in ('stop-id','normal'):
        completed=subprocess.run([sys.executable,__file__,'--bus-gtfs-dir',args.bus_gtfs_dir,'--profile',profile],
            check=True,capture_output=True,text=True)
        results.append(json.loads(completed.stdout))
    print(json.dumps(dict(scope='same three OD, 09:00 Nov19, 3 boards/180min, 3 repetitions; Linux peak RSS',
        profiles=results),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
