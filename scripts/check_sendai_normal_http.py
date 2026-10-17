"""Focused real normal HTTP contract and old stop-ID comparison; no bulk audit."""
import argparse
import json
from pathlib import Path
import time

import httpx


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url',required=True)
    args=p.parse_args()
    cases=json.loads((Path(__file__).resolve().parents[1]/
        'api/tests/fixtures/sendai_subway/normal_coordinate_cases_20261017.json').read_text(encoding='utf-8'))['cases']
    with httpx.Client(base_url=args.base_url,headers={'X-App-City':'sendai'},timeout=60) as client:
        for case in cases:
            body=dict(alat=case['origin'][0],alon=case['origin'][1],blat=case['destination'][0],blon=case['destination'][1],
                pref='time',bus_only=case['bus_only'],target_date_str=case['civil_date'],start_time='09:00',
                fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True)
            started=time.perf_counter();response=client.post('/route',json=body);response.raise_for_status()
            candidate=response.json()['candidates'][0]
            expected=f"{case['arrival_minute']//60:02d}:{case['arrival_minute']%60:02d}"
            assert candidate['arrival_time']==expected,(case,response.text)
            assert candidate['fare']['normalFareYen'] is None and candidate['fare']['payNowYen']==0
            if case['name']!='surface_access':
                comparison=client.post('/test/sendai/route',json=dict(origin_stop_id=case['origin_stop_id'],
                    destination_stop_id=case['destination_stop_id'],civil_date=case['civil_date'],departure_minute=540,
                    fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True))
                comparison.raise_for_status()
                assert candidate['planning_journey']==comparison.json()['candidates'][0],case['name']
            print(json.dumps(dict(case=case['name'],arrival=expected,
                elapsed_including_stop_id_comparison=time.perf_counter()-started,
                trips=[s['trip_id'] for s in candidate['steps'] if s['kind'] in ('bus','rail')]),ensure_ascii=False))
        base=dict(alat=cases[0]['origin'][0],alon=cases[0]['origin'][1],blat=cases[0]['destination'][0],blon=cases[0]['destination'][1],
            pref='time',target_date_str='2026-11-19',start_time='09:00',fare_policy_id='sendai_fureai_pass',
            accept_experimental_transfer_model=True)
        for change in ({'accept_experimental_transfer_model':False},{'fare_policy_id':'sendai_keiro_pass'},
                       {'target_date_str':'2026-10-25'},{'target_date_str':'2026-11-22'},
                       {'target_date_str':'2026-12-01'},{'alat':base['alat']+.00005}):
            response=client.post('/route',json={**base,**change})
            assert response.status_code==422,(change,response.text)
        result=client.post('/route',json={**base,'target_date_str':'2026-11-30'})
        result.raise_for_status();assert result.json()['candidates'][0]['arrival_time']=='09:38'
    print('NORMAL_SENDAI_REAL_HTTP_OK')


if __name__=='__main__':main()
