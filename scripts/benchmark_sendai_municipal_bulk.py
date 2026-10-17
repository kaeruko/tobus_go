"""Separate-process before/after scope measurement, same input/core/queries."""
import argparse
import contextlib
from datetime import date
import io
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'api')]
from sendai_transit import load_sendai_dataset
from sendai_operating_period import OperatingPeriodReview
from sendai_practical_bundle import build_reviewed_municipal_model,load_reviewed_subway
from sendai_practical_network import search_practical_subway
from transit_timetable_choices import NetworkSearchParameters


def measure(directory,profile):
    f=ROOT/'api/tests/fixtures/sendai_subway'
    review=json.loads((f/('municipal_review_20261017_'+profile+'.json')).read_text())
    started=time.perf_counter();bus=load_sendai_dataset(directory,expected_service_date='2026-10-16');loaded=time.perf_counter()
    sub,_=load_reviewed_subway(f/'published_20230701.json',f/'practical_review_20261016.json',operating_period=OperatingPeriodReview.from_mapping(review['operating_period']))
    net=build_reviewed_municipal_model(sub,bus,review,accept_experimental_bus_transfers=True);built=time.perf_counter()
    params=NetworkSearchParameters(max_candidates=1,max_boardings=3,max_travel_minutes=180)
    conditions=[('sendai_bus:7605_50','sendai_subway:namboku/泉中央'),('sendai_subway:namboku/泉中央','sendai_bus:7605_10'),('sendai_bus:4015_10','sendai_bus:7253_10')]
    queries=[]
    for origin,dest in conditions:
        times=[];arrivals=[]
        for repeat in range(3):
            t=time.perf_counter()
            with contextlib.redirect_stdout(io.StringIO()):result=search_practical_subway(net,origin,dest,civil_date=date(2026,11,19),departure_minute=540,parameters=params)
            times.append(round(time.perf_counter()-t,6))
            if not result:raise AssertionError('fixed performance query has no route')
            arrivals.append(str(result[0].arrival_estimate.minute))
        queries.append(dict(origin=origin,destination=dest,seconds=times,arrivals=arrivals))
    return dict(profile=profile,load_seconds=round(loaded-started,6),network_build_seconds=round(built-loaded,6),startup_seconds=round(built-started,6),peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,queries=queries)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bus-gtfs-dir',type=Path,required=True);p.add_argument('--profile',choices=('stage8','bulk'));a=p.parse_args()
    if a.profile:print(json.dumps(measure(a.bus_gtfs_dir,a.profile),ensure_ascii=False));return
    results=[]
    for profile in ('stage8','bulk'):
        r=subprocess.run([sys.executable,'-B',__file__,'--bus-gtfs-dir',str(a.bus_gtfs_dir),'--profile',profile],capture_output=True,text=True,check=True)
        results.append(json.loads(r.stdout))
    print(json.dumps(dict(platform=sys.platform,python=sys.version,measurement='independent fresh processes, same source and unchanged SearchCore; maxrss is process high-water mark, not retained heap',results=results),ensure_ascii=False,indent=2))
    print('SENDAI_BULK_PERFORMANCE_MEASURED')


if __name__=='__main__':main()
