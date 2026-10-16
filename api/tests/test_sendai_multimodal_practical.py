"""New mixed real-source model regressions; no old successful audit is rerun."""
import contextlib
from dataclasses import replace
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.sendai_practical_routes import create_sendai_practical_test_app
from route_engine import RouteSearchLimitError
from sendai_practical_bundle import build_reviewed_municipal_model,load_reviewed_subway
from sendai_practical_network import PracticalRide,PracticalTransfer,search_practical_subway
from sendai_practical_serializer import serialize_practical_journey,civil_clock
from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_municipal_oracle import runs,optimum,validate
from tests.test_sendai_practical import FIXTURE,DAY


def fixture_bus():
    source=json.loads((FIXTURE/'municipal_bus_subset_20261006.json').read_text(encoding='utf-8'))
    review=json.loads((FIXTURE/'municipal_review_20261016.json').read_text(encoding='utf-8'))
    from datetime import datetime,timezone
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        for name,text in source['files'].items(): (root/name).write_text(text,encoding='utf-8',newline='')
        bus=GtfsTransitAdapter.load(root,metadata=FeedMetadata('sendai_bus','gtfs-jp',source['source_url'],
            review['bus_feed_version'],datetime(2026,10,16,tzinfo=timezone.utc)))
    return bus,source,review


class SendaiMunicipalPracticalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bus,cls.fixture,cls.review=fixture_bus()
        cls.subway,cls.raw=load_reviewed_subway(FIXTURE/'published_20230701.json',FIXTURE/'practical_review_20261016.json')
        cls.net=build_reviewed_municipal_model(cls.subway,cls.bus,cls.review,accept_experimental_bus_transfers=True)
        cls.fixed=json.loads((FIXTURE/'municipal_fixed_cases_20261016.json').read_text(encoding='utf-8'))
        cls.params=NetworkSearchParameters(**cls.fixed['parameters'])
        cls.days={e.day:e.kind for e in cls.subway.operating_days.entries if e.kind}

    def query(self,case,**kw):
        values=dict(civil_date=date.fromisoformat(case['civil_date']),departure_minute=case['departure_minute'],parameters=self.params)
        values.update(kw)
        with contextlib.redirect_stdout(io.StringIO()):
            return search_practical_subway(self.net,case['origin'],case['destination'],**values)

    def test_four_fixed_real_source_categories_match_raw_oracle_and_concrete_witness(self):
        seen=set()
        for case in self.fixed['cases']:
            with self.subTest(category=case['category']):
                seen.add(case['category']);day=date.fromisoformat(case['civil_date'])
                rr=runs(self.fixture['files'],self.raw,self.days,day,self.review)
                expected=optimum(rr,self.review,case['origin'],case['destination'],case['departure_minute'],max_boardings=3,max_minutes=180)
                result=self.query(case)
                self.assertEqual(result[0].arrival_estimate.minute,expected)
                self.assertEqual(expected,case['expected_arrival_minute'])
                validate(result[0],rr,self.review,day,case['origin'],case['destination'],case['departure_minute'])
                modes=[e.source.mode for e in result[0].events if isinstance(e,PracticalRide)]
                required={'bus_only':['bus'],'subway_only':['rail'],'bus_rail':['bus','rail'],'rail_bus':['rail','bus']}[case['category']]
                self.assertEqual(modes,required)
        self.assertEqual(seen,{'bus_only','subway_only','bus_rail','rail_bus'})

    def test_official_clocks_proxies_and_experimental_bus_transfer_are_distinct_on_wire(self):
        result=self.query(next(c for c in self.fixed['cases'] if c['category']=='bus_rail'))[0]
        payload=serialize_practical_journey(result);bus,transfer,rail=payload['events']
        self.assertEqual(bus['arrival']['basis'],'gtfs_scheduled_arrival')
        self.assertEqual(rail['departure']['basis'],'published_departure_minute')
        self.assertEqual(rail['arrival']['basis'],'published_clock_arrival_proxy')
        self.assertEqual(transfer['time_basis'],'experimental_planning_assumption')
        self.assertIsNone(transfer['physical_walk_meters'])
        self.assertFalse(transfer['walking_time_measured']);self.assertFalse(payload['actual_connection_guaranteed'])
        self.assertEqual(payload['fare']['additional_payment_yen'],0)
        self.assertIsNone(payload['fare']['normal_fare_yen'])

    def test_bus_days_exact_version_and_explicit_experimental_selection_fail_fast(self):
        for review in ({**self.review,'bus_feed_version':'wrong'},{**self.review,'bus_source_uri':'https://example.test/past.zip'}):
            with self.assertRaises(ValueError):build_reviewed_municipal_model(self.subway,self.bus,review,accept_experimental_bus_transfers=True)
        with self.assertRaisesRegex(ValueError,'explicitly selected'):
            build_reviewed_municipal_model(self.subway,self.bus,self.review,accept_experimental_bus_transfers=False)
        net=replace(self.net,bus_reviewed_days=frozenset({date(2026,10,15)}))
        with self.assertRaisesRegex(ValueError,'bus service date'):
            search_practical_subway(net,'sendai_bus:5099_10','sendai_subway:tozai/仙台',civil_date=DAY,departure_minute=660,parameters=self.params)

    def test_unreviewed_direction_and_free_pattern_do_not_get_implicit_links(self):
        case=next(c for c in self.fixed['cases'] if c['category']=='bus_rail')
        net=replace(self.net,bus_transfers=tuple(r for r in self.net.bus_transfers if not r.link.from_stop_id.startswith('sendai_bus:')))
        with contextlib.redirect_stdout(io.StringIO()):
            result=search_practical_subway(net,case['origin'],case['destination'],civil_date=DAY,departure_minute=660,parameters=self.params)
        self.assertEqual(result,())
        # Unknown other municipal patterns are excluded before building boarding edges.
        self.assertEqual({self.bus.trips[t].route_id for t in self.net.free_scope.allowed_trip_ids if t.startswith('sendai_bus:')}, {'sendai_bus:10033','sendai_bus:10255'})

    def test_real_holiday_calendar_independently_selects_correct_bus_service(self):
        case={**self.fixed['cases'][0],'civil_date':'2026-10-12'}
        result=self.query(case)[0]
        bus=next(e for e in result.events if isinstance(e,PracticalRide))
        self.assertIn('_3_',bus.source.source_trip_id)
        rr=runs(self.fixture['files'],self.raw,self.days,date(2026,10,12),self.review)
        validate(result,rr,self.review,date(2026,10,12),case['origin'],case['destination'],case['departure_minute'])

    def test_original_search_error_propagates_and_partial_result_is_not_success(self):
        error=RouteSearchLimitError('fixed limit',reason='max_visited_states')
        with patch('sendai_practical_network.search_network',side_effect=error):
            with self.assertRaises(RouteSearchLimitError) as caught:self.query(self.fixed['cases'][0])
        self.assertIs(caught.exception,error)

    def test_isolated_api_requires_pass_and_preserves_unsupported_scope(self):
        client=TestClient(create_sendai_practical_test_app(self.net,environment='test',parameters=self.params))
        caps=client.get('/test/sendai/capabilities').json()
        self.assertEqual(caps['supported_modes'],['bus','rail']);self.assertIn('miyagi_kotsu',caps['unsupported'])
        self.assertEqual(client.post('/route',json={}).status_code,404)
        case=self.fixed['cases'][0]
        body=dict(origin_stop_id=case['origin'],destination_stop_id=case['destination'],civil_date=case['civil_date'],departure_minute=case['departure_minute'],fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True)
        with contextlib.redirect_stdout(io.StringIO()):response=client.post('/test/sendai/route',json=body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['candidates'][0]['fare']['additional_payment_yen'],0)
        self.assertEqual(client.post('/test/sendai/route',json={**body,'fare_policy_id':'normal'}).status_code,422)
        self.assertEqual(client.post('/test/sendai/route',json={**body,'accept_experimental_transfer_model':False}).status_code,422)
        self.assertEqual(client.post('/test/sendai/route',json={**body,'civil_date':'2026-12-31'}).status_code,422)
        with patch('sendai_practical_network.search_network',side_effect=RouteSearchLimitError('fixed',reason='queue_size')):
            self.assertEqual(client.post('/test/sendai/route',json=body).status_code,503)
        with self.assertRaises(ValueError):create_sendai_practical_test_app(self.net,environment='production',parameters=self.params)

class SendaiBundleIntegrityTests(unittest.TestCase):
    def install(self,root):
        from tests.test_sendai_transit import _write_feed,_write_manifest,SERVICE_DATE
        _write_feed(root);_write_manifest(root)
        return SERVICE_DATE

    def test_manifest_checks_archive_each_file_inventory_dates_and_published_version(self):
        from sendai_transit import load_sendai_dataset,SENDAI_MANIFEST_FILENAME,SOURCE_ARCHIVE
        for change in ('zip','file','inventory','coverage','legacy','version'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);day=self.install(root)
                if change=='zip':(root/SOURCE_ARCHIVE).write_bytes(b'altered')
                elif change=='file':
                    p=root/'stop_times.txt';p.write_bytes(p.read_bytes().replace(b'10:10:00',b'10:11:00'))
                else:
                    path=root/SENDAI_MANIFEST_FILENAME;manifest=json.loads(path.read_text())
                    if change=='inventory':manifest['file_sha256'].pop('calendar_dates.txt')
                    elif change=='coverage':manifest['valid_until']='2026-12-30'
                    elif change=='legacy':manifest.pop('schema_version')
                    elif change=='version':manifest['published_version']='unverified-2027'
                    path.write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):load_sendai_dataset(root,expected_service_date=day)

    def test_explicit_public_resource_never_retries_other_source_and_checks_sha(self):
        from sendai_transit import fetch_sendai_gtfs
        from tests.test_sendai_transit import _FakeClient,_zip_bytes,SERVICE_DATE
        import hashlib
        url='https://api-public.odpt.org/api/v4/files/odpt/SendaiMunicipal/bus_realtime_information.zip?date=20261006'
        raw=_zip_bytes();client=_FakeClient(raw)
        with tempfile.TemporaryDirectory() as directory:
            manifest=fetch_sendai_gtfs(Path(directory)/'feed',expected_service_date=SERVICE_DATE,source_url=url,
                expected_sha256=hashlib.sha256(raw).hexdigest(),client=client)
            self.assertEqual(client.calls,[(url,None)]);self.assertEqual(manifest.schema_version,2)
            self.assertEqual(manifest.sha256,hashlib.sha256(raw).hexdigest())
        client=_FakeClient(raw)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'SHA-256 mismatch'):
                fetch_sendai_gtfs(Path(directory)/'feed',expected_service_date=SERVICE_DATE,source_url=url,
                    expected_sha256='0'*64,client=client)
            self.assertFalse((Path(directory)/'feed').exists());self.assertEqual(len(client.calls),1)
        with self.assertRaisesRegex(ValueError,'official Sendai'):
            fetch_sendai_gtfs('unused',expected_service_date=SERVICE_DATE,source_url='https://example.test/old.zip',client=client)

    def test_subsecond_loss_is_not_silently_displayed_as_published_minute(self):
        from fractions import Fraction
        from sendai_practical_network import CivilMinute
        value=civil_clock(CivilMinute(DAY,Fraction(1201,2)),basis='gtfs_scheduled_arrival')
        self.assertEqual(value['time'],'10:00:30');self.assertEqual(value['minute'],{'numerator':1201,'denominator':2})

    def test_actual_extracted_subset_tampering_is_detected_by_read_only_derivation(self):
        # The full-source gate owns this check; the local fixture is never used
        # as an alternate operational installation.
        import importlib.util
        spec=importlib.util.spec_from_file_location('sendai_model_gate',Path(__file__).resolve().parents[2]/'scripts/check_sendai_practical_local.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);day=self.install(root)
            raw=json.loads((root/'sendai_gtfs_manifest.json').read_text())
            from tests.test_sendai_transit import _files
            fixture={'source_zip_sha256':raw['sha256'],'source_member_sha256':raw['file_sha256'],
                     'files':_files()}
            with self.assertRaises((ValueError,KeyError)):
                module.verify_subset(root,fixture,{'bus_source_sha256':'0'*64})


class SendaiMixedCivilClockTests(unittest.TestCase):
    def test_previous_bus_service_24xx_and_half_minute_survive_common_core_and_quote(self):
        # Deliberately synthetic clock mutation of a known complete pattern.
        # This is a civil materialization regression, not real midnight service.
        import csv
        from fractions import Fraction
        from tests.sendai_municipal_oracle import seconds
        bus,fixture,review=fixture_bus()
        subway,subway_files=load_reviewed_subway(FIXTURE/'published_20230701.json',FIXTURE/'practical_review_20261016.json')
        tid='sendai_bus:20_1_12002220';offset=738*60+30
        shifted=[]
        for row in bus.stop_times:
            if row.trip_id==tid:
                row=replace(row,arrival_minute=row.arrival_minute+739,departure_minute=row.departure_minute+739,
                    arrival_service_seconds=row.arrival_service_seconds+offset,
                    departure_service_seconds=row.departure_service_seconds+offset)
            shifted.append(row)
        bus=replace(bus,metadata=replace(bus.metadata,version='synthetic-midnight-v1',source_type='synthetic'),stop_times=tuple(shifted))
        review={**review,'bus_feed_version':bus.metadata.version}
        net=build_reviewed_municipal_model(subway,bus,review,accept_experimental_bus_transfers=True)
        original=next(r for r in shifted if r.trip_id==tid and r.sequence==13)
        day=date(2026,10,17);params=NetworkSearchParameters(max_candidates=1,max_boardings=2,max_travel_minutes=120)
        with contextlib.redirect_stdout(io.StringIO()):
            result=search_practical_subway(net,original.stop_id,'sendai_bus:5181_0',civil_date=day,departure_minute=0,parameters=params)[0]
        ride=next(e for e in result.events if isinstance(e,PracticalRide))
        self.assertEqual(ride.source.service_date,date(2026,10,16))
        self.assertEqual(ride.source.trip_id,tid);self.assertEqual(result.arrival_estimate.minute,Fraction(19,2))
        self.assertEqual(serialize_practical_journey(result)['events'][0]['arrival']['time'],'00:09:30')
        raw_bus={**fixture['files']}
        input_rows=list(csv.DictReader(io.StringIO(raw_bus['stop_times.txt'])))
        for row in input_rows:
            if row['trip_id']==tid.split(':',1)[1]:
                for field in ('arrival_time','departure_time'):
                    ss=int(seconds(row[field])*60)+offset
                    row[field]=f'{ss//3600:02d}:{ss//60%60:02d}:{ss%60:02d}'
        out=io.StringIO();writer=csv.DictWriter(out,fieldnames=input_rows[0].keys());writer.writeheader();writer.writerows(input_rows)
        raw_bus['stop_times.txt']=out.getvalue()
        kinds={e.day:e.kind for e in subway.operating_days.entries if e.kind}
        rr=runs(raw_bus,subway_files,kinds,day,review)
        self.assertEqual(optimum(rr,review,original.stop_id,'sendai_bus:5181_0',0,max_boardings=2,max_minutes=120),Fraction(19,2))
        validate(result,rr,review,day,original.stop_id,'sendai_bus:5181_0',0)
