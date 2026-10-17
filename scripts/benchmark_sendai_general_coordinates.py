"""Pinned-before/after, fresh processes, same real GTFS, queries and limits.

No routing response is substituted. The old code must still reject the newly
supported general coordinates; those 422 timings are not route-performance
baselines. Linux peak RSS includes startup and every measured query.
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
import tarfile
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
BASELINE='744b8c9a893d969c31ce8e4436d524949f89cf30'


def worker(api_root,directory,profile):
    sys.path.insert(0,str(api_root))
    from unittest.mock import patch
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.route_endpoint import register_route_endpoint
    from app.route_only_routes import SharedNetworkApiRouteRequest
    from sendai_transit import load_sendai_dataset,SendaiRouteBackend
    from sendai_operating_period import OperatingPeriodReview
    from sendai_practical_bundle import load_reviewed_subway,build_reviewed_municipal_model
    from sendai_coordinate_routes import SendaiCoordinateScope
    import sendai_practical_network as practical
    f=ROOT/'api/tests/fixtures/sendai_subway'
    started=time.perf_counter()
    bus=load_sendai_dataset(directory,expected_service_date='2026-10-16')
    review=json.loads((f/'municipal_review_20261017_bulk.json').read_text(encoding='utf-8'))
    period=OperatingPeriodReview.from_mapping(review['operating_period'])
    subway,_=load_reviewed_subway(f/'published_20230701.json',f/'practical_review_20261016.json',operating_period=period)
    network=build_reviewed_municipal_model(subway,bus,review,accept_experimental_bus_transfers=True)
    engine=SendaiCoordinateScope(None,network,period,environment='development',normal_backend_factory=lambda:SendaiRouteBackend(bus))
    app=FastAPI();app.state.loading_status='ready';app.state.city_key='sendai';app.state.route_engine=engine
    register_route_endpoint(app,warmup_message='starting',request_model=SharedNetworkApiRouteRequest)
    startup=time.perf_counter()-started
    fixed=json.loads((f/'normal_coordinate_cases_20261017.json').read_text(encoding='utf-8'))['cases'][1:4]
    general=json.loads((f/'general_coordinate_cases_20261018.json').read_text(encoding='utf-8'))['cases']
    report=[]
    with TestClient(app) as client:
        for case in fixed+general:
            samples=[]
            for _ in range(3):
                core_seconds=[]
                original_search=practical.search_network
                def traced(*args,**kwargs):
                    begin=time.perf_counter();result=original_search(*args,**kwargs)
                    core_seconds.append(time.perf_counter()-begin);return result
                with patch.object(practical,'build_transit_network',wraps=practical.build_transit_network) as builds, \
                     patch.object(practical,'search_network',side_effect=traced):
                    begin=time.perf_counter()
                    response=client.post('/route',json=dict(alat=case['origin'][0],alon=case['origin'][1],
                        blat=case['destination'][0],blon=case['destination'][1],target_date_str=case['civil_date'],
                        start_time='09:00',pref='time',bus_only=case['bus_only'],fare_policy_id='sendai_fureai_pass',
                        accept_experimental_transfer_model=True))
                    elapsed=time.perf_counter()-begin
                if profile=='before' and case in general:
                    assert response.status_code==422,response.text
                    assert 'unreviewed_coordinate_access' in response.text,response.text
                    assert not core_seconds and builds.call_count==0
                else:
                    response.raise_for_status()
                    assert response.json()['candidates'][0]['arrival_time']==f"{case['arrival_minute']//60:02d}:{case['arrival_minute']%60:02d}",response.text
                diagnostic=response.json().get('meta',{}).get('coordinate_access')
                samples.append(dict(http_seconds=elapsed,search_seconds=sum(core_seconds),searches=len(core_seconds),
                    network_builds=builds.call_count,status=response.status_code,diagnostics=diagnostic))
            report.append(dict(name=case['name'],samples=samples,median_seconds=statistics.median(v['http_seconds'] for v in samples)))
    return dict(profile=profile,startup_seconds=startup,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,queries=report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bus-gtfs-dir',required=True,type=Path)
    parser.add_argument('--baseline-ref',default=BASELINE)
    parser.add_argument('--worker',choices=('before','after'))
    parser.add_argument('--api-root',type=Path)
    args=parser.parse_args()
    if args.worker:
        if args.api_root is None:parser.error('--worker requires --api-root')
        with contextlib.redirect_stdout(sys.stderr):
            value=worker(args.api_root,args.bus_gtfs_dir,args.worker)
        print(json.dumps(value,ensure_ascii=False));return
    with tempfile.TemporaryDirectory(prefix='sendai-before-') as directory:
        # Materialize the exact old repository API, without changing main or
        # carrying any changed module into the before worker.
        archive=subprocess.run(['git','archive','--format=tar',args.baseline_ref,'api'],cwd=ROOT,
            check=True,stdout=subprocess.PIPE)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
            bundle.extractall(directory,filter='data')
        results=[]
        for profile,api_root in (('before',Path(directory)/'api'),('after',ROOT/'api')):
            completed=subprocess.run([sys.executable,__file__,'--worker',profile,'--api-root',str(api_root),
                '--bus-gtfs-dir',str(args.bus_gtfs_dir.resolve())],check=True,stdout=subprocess.PIPE,text=True)
            results.append(json.loads(completed.stdout))
        print(json.dumps(dict(baseline=args.baseline_ref,scope='same runner, 3 fixed + 3 general OD, Nov19 09:00, 3 boards/180min, 3 repetitions; ASGI HTTP conversion, not internet latency',profiles=results),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
