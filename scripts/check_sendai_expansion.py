"""Read-only new-stage real-source gate; does not invoke previous audit gates."""
from __future__ import annotations
import argparse
import base64
import contextlib
from datetime import date, timedelta
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'api'))
from fastapi.testclient import TestClient
from app.sendai_practical_routes import create_sendai_practical_test_app
from sendai_operating_period import OperatingPeriodReview
from sendai_practical_bundle import load_reviewed_subway, build_reviewed_municipal_model
from sendai_practical_network import search_practical_subway, PracticalRide
from sendai_transit import load_sendai_dataset
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_municipal_oracle import runs, optimum, validate
from scripts.check_sendai_practical_local import verify_subset


def raw_day_kinds(period):
    # Independent calendar expansion from the retained review JSON. Do not
    # obtain oracle dates from the production calendar or adapter output.
    holidays = {date.fromisoformat(h['day']) for h in period['holiday_review']['holidays']}
    excluded = {date.fromisoformat(e['day']) for e in period['exclusions']}
    first, last = (date.fromisoformat(period[k]) for k in ('coverage_start', 'coverage_end'))
    return {day: ('h' if day.weekday() >= 5 or day in holidays else 'w')
            for day in (first + timedelta(days=i) for i in range((last-first).days+1))
            if day not in excluded}


def verify_model(bus, source_files, raw_subway, subway, review, matrix, *, profile):
    period = OperatingPeriodReview.from_mapping(review['operating_period'])
    network = build_reviewed_municipal_model(subway, bus, review, accept_experimental_bus_transfers=True)
    parameters = NetworkSearchParameters(**matrix['parameters'])
    if parameters.max_candidates != 1 or parameters.max_boardings != 3:
        raise ValueError('stage1 verifies one earliest result with up to three boardings')
    app = TestClient(create_sendai_practical_test_app(network, environment='test', parameters=parameters,
        operating_period=period, coverage_label=review['coverage_label']))
    caps = app.get('/test/sendai/capabilities').json()
    if profile == 'stage3':
        required = {'2026-10-19', '2026-11-03', '2026-11-19', '2026-11-23', '2026-11-30'}
        forbidden = {'2026-10-25', '2026-11-22', '2026-12-01'}
        if (not required <= set(caps['operating_dates']) or forbidden & set(caps['operating_dates'])
                or len(caps['operating_dates']) != 48):
            raise AssertionError('stage3 November finite-day coverage or exclusions differ')
    elif ('2026-10-19' not in caps['operating_dates'] or '2026-10-31' not in caps['operating_dates']
            or '2026-10-25' in caps['operating_dates'] or '2026-11-01' in caps['operating_dates']):
        raise AssertionError('finite period/excluded bus day was not preserved by the API')
    kinds = raw_day_kinds(review['operating_period'])
    for case in matrix['cases']:
        day = date.fromisoformat(case['civil_date'])
        rr = runs(source_files, raw_subway, kinds, day, review)
        expected = optimum(rr, review, case['origin'], case['destination'], case['departure_minute'],
            max_boardings=parameters.max_boardings, max_minutes=parameters.max_travel_minutes)
        if expected is None or (case['expected_arrival_minute'] is not None and expected != case['expected_arrival_minute']):
            raise AssertionError('fixed raw expectation differs: ' + case['category'])
        with contextlib.redirect_stdout(io.StringIO()):
            result = search_practical_subway(network, case['origin'], case['destination'], civil_date=day,
                departure_minute=case['departure_minute'], parameters=parameters)
        if not result:
            raise AssertionError('fixed new route is missing: ' + case['category'])
        journey = result[0]
        actual = (journey.arrival_estimate.day-day).days*1440 + journey.arrival_estimate.minute
        if actual != expected:
            raise AssertionError('model differs from independent raw optimum: ' + case['category'])
        validate(journey, rr, review, day, case['origin'], case['destination'], case['departure_minute'])
        rides = [e.source for e in journey.events if isinstance(e, PracticalRide)]
        if ([r.mode for r in rides] != case['modes'] or
                ('required_route_id' in case and
                case['required_route_id'] not in {bus.trips[r.trip_id].route_id for r in rides if r.mode=='bus'})):
            raise AssertionError('new exact route/mode witness differs: ' + case['category'])
        body = dict(origin_stop_id=case['origin'], destination_stop_id=case['destination'],
            civil_date=case['civil_date'], departure_minute=case['departure_minute'],
            fare_policy_id='sendai_fureai_pass', accept_experimental_transfer_model=True)
        with contextlib.redirect_stdout(io.StringIO()):
            response = app.post('/test/sendai/route', json=body)
        if response.status_code != 200:
            raise AssertionError(f'new route API failed: {case["category"]}: {response.text}')
        candidate = response.json()['candidates'][0]
        arrival = candidate['arrival']
        if arrival['minute'] != {'numerator': int(expected), 'denominator': 1}:
            raise AssertionError('API scheduled arrival differs from independent raw model')
        if candidate['fare']['additional_payment_yen'] != 0 or candidate['fare']['normal_fare_yen'] is not None:
            raise AssertionError('free-pass quote or unknown normal fare was changed')
        print(json.dumps({'category':case['category'], 'date':case['civil_date'],
            'arrival_minute':int(expected), 'modes':case['modes'], 'status':'ok'}, ensure_ascii=False), flush=True)
    return network, app


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bus-gtfs-dir', type=Path, required=True)
    p.add_argument('--expected-sha', required=True)
    p.add_argument('--profile', choices=('stage1','stage2','stage3'), default='stage1',
        help='Explicit reviewed scope; never select another profile on failure')
    args=p.parse_args()
    git=lambda *parts: subprocess.run(['git','-C',str(ROOT),*parts],check=True,capture_output=True,text=True).stdout.strip()
    if git('rev-parse','HEAD') != args.expected_sha or git('branch','--show-current') != 'main':
        raise ValueError('explicit current main SHA required')
    fixture=ROOT/'api/tests/fixtures/sendai_subway'
    profile=args.profile
    review_name=f'municipal_review_{"20261017" if profile == "stage3" else "20261016"}_{profile}.json'
    subset_name=f'municipal_bus_subset_20261006_{"stage2" if profile == "stage3" else profile}.json'
    cases_name=f'municipal_fixed_cases_{"20261017" if profile == "stage3" else "20261016"}_{profile}.json'
    paths=list(args.bus_gtfs_dir.glob('*.txt')) + [args.bus_gtfs_dir/'sendai_gtfs_manifest.json',
        args.bus_gtfs_dir/'sendai_gtfs_source.zip'] + [fixture/name for name in (
        'published_20230701.json','practical_review_20261016.json',review_name,subset_name,cases_name)]
    digests=lambda: {str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    before=digests()
    source=json.loads((fixture/subset_name).read_text(encoding='utf-8'))
    review=json.loads((fixture/review_name).read_text(encoding='utf-8'))
    matrix=json.loads((fixture/cases_name).read_text(encoding='utf-8'))
    if review['stage_profile'] != f'sendai_municipal_{profile}' or len(matrix['cases']) != {'stage1':7,'stage2':6,'stage3':7}[profile]:
        raise ValueError('Explicit review profile and complete fixed case matrix required')
    verify_subset(args.bus_gtfs_dir,source,review)
    bus=load_sendai_dataset(args.bus_gtfs_dir,expected_service_date='2026-10-16')
    subway,raw=load_reviewed_subway(fixture/'published_20230701.json',fixture/'practical_review_20261016.json',
        operating_period=OperatingPeriodReview.from_mapping(review['operating_period']))
    full_files={name:(args.bus_gtfs_dir/name).read_text(encoding='utf-8-sig') for name in source['files']}
    verify_model(bus,full_files,raw,subway,review,matrix,profile=profile)
    if before != digests() or git('rev-parse','HEAD') != args.expected_sha:
        raise AssertionError('source or input bytes changed during the new-stage read-only gate')
    print({'stage1':'READ_ONLY_SENDAI_STAGE1_NEW_SEVEN_OK',
           'stage2':'READ_ONLY_SENDAI_STAGE2_NEW_SIX_OK',
           'stage3':'READ_ONLY_SENDAI_STAGE3_NOVEMBER_OK'}[profile])


if __name__=='__main__':
    main()
