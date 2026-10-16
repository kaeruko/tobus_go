"""New profile regressions and real published CSV model routes, not old gates."""
import base64
import contextlib
import csv
from dataclasses import replace
from datetime import date, datetime, timezone, timedelta
import hashlib
import io
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from sendai_shared_network import FreeSegmentReview
from sendai_practical_network import (
    SendaiStandardTransferReview, PracticalRide, PracticalTransfer,
    build_practical_subway_network, search_practical_subway,
)
from transit_adapters.sendai_subway import Evidence, FILES, STATIONS, StationReview, SendaiSubwayAdapter
from transit_adapters.sendai_subway_practical import (
    PROFILE, GUIDE_URI, GUIDE_SHA256, DayClassification, FiniteOperatingDays,
    PracticalTableReview, SendaiSubwayPracticalAdapter,
)
from transit_network import NetworkCosts
from transit_timetable_choices import NetworkSearchParameters
from tests.sendai_practical_oracle import earliest, raw_runs, validate_witness

FIXTURE=Path(__file__).parent/'fixtures'/'sendai_subway'
DAY=date(2026,10,16)
PARAMS=NetworkSearchParameters(max_candidates=1,max_boardings=2,max_travel_minutes=120)
E=Evidence('https://www.city.sendai.jp/synthetic-practical-review','a'*64)


def inputs(real=False, *, base=600, east_base=610):
    review=json.loads((FIXTURE/'practical_review_20261016.json').read_text(encoding='utf-8'))
    def evidence(value): return Evidence(**value)
    calendar=FiniteOperatingDays(tuple(DayClassification(date.fromisoformat(e['day']),e['kind'],e['reason'])
        for e in review['days']), (evidence(review['day_source']),), DAY,
        review['holiday_source_uri'],review['holiday_source_sha256'])
    coords={name:StationReview(*value,evidence(review['coordinate_source'])) for name,value in review['stations'].items()}
    source=json.loads((FIXTURE/'published_20230701.json').read_text(encoding='utf-8'))
    files={name:base64.b64decode(value['cp932_base64'],validate=True) for name,value in source.items()}
    if not real:
        files={}
        for filename in FILES:
            line,_,direction,_=filename.split('_');names=STATIONS[line]
            if direction in ('north','west'): names=tuple(reversed(names))
            first=base if line=='namboku' else east_base
            output=io.StringIO(newline='');w=csv.writer(output)
            w.writerow(['行先','始発',*names]);w.writerow([names[-1],names[0],
                *(f'{(first+i)//60%24}:{(first+i)%60:02d}' for i in range(len(names)))])
            files[filename]=output.getvalue().encode('cp932')
    reviews={name:PracticalTableReview(hashlib.sha256(files[name]).hexdigest(),
        tuple(evidence(e) for e in value['current_departure_evidence']) if real else (E,),
        value['source_comparison_record_sha256'],'nonterminal_departure_multisets_only',
        evidence(review['license_source']),'CC-BY-4.0') for name,value in review['tables'].items()}
    return files,reviews,coords,calendar


def load(args):
    files,reviews,coords,calendar=args
    return SendaiSubwayPracticalAdapter().load(files,reviews=reviews,stations=coords,
        operating_days=calendar,fetched_at=datetime(2026,10,16,tzinfo=timezone.utc),profile=PROFILE)


def free_reviews(source):
    rows={t:[] for t in source.dataset.trips}
    for r in source.dataset.stop_times: rows[r.trip_id].append(r)
    return tuple(FreeSegmentReview(t,source.dataset.metadata.version,a.sequence,b.sequence,
        a.stop_id,b.stop_id,'SendaiMunicipal','local','04100',Evidence(GUIDE_URI,GUIDE_SHA256))
        for t,rr in rows.items() for a,b in zip(rr,rr[1:]))


def build(source, *, margin=2, connections=True, reviews=None):
    transfer=SendaiStandardTransferReview(margin,
        frozenset(e.day for e in source.operating_days.entries if e.kind),GUIDE_URI,GUIDE_SHA256) if connections else None
    return build_practical_subway_network(source,segment_reviews=free_reviews(source) if reviews is None else reviews,
        transfers=transfer,costs=NetworkCosts())


def query(net,a,b,*,day=DAY,start=600,params=PARAMS,**kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return search_practical_subway(net,'sendai_subway:'+a,'sendai_subway:'+b,
            civil_date=day,departure_minute=start,parameters=params,**kwargs)


class PracticalProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.args=inputs();cls.source=load(cls.args);cls.net=build(cls.source)

    def test_typed_departure_and_arrival_proxy_never_source_seconds(self):
        d=self.source.dataset
        self.assertEqual(d.metadata.clock_profile,PROFILE)
        for r in d.stop_times:
            self.assertIsNone(r.arrival_service_seconds);self.assertIsNone(r.departure_service_seconds)
            self.assertTrue(r.arrival_provenance.is_estimate)
            if r.departure_minute is not None: self.assertFalse(r.departure_provenance.is_estimate)
        journey=query(self.net,'namboku/泉中央','namboku/富沢')[0]
        self.assertEqual(len(journey.events),1)  # No repeated boarding/transfer margin in one train.
        self.assertEqual(journey.arrival_estimate.minute,616)
        self.assertEqual(journey.events[0].source.to_sequence,16)
        self.assertEqual(journey.events[0].source.arrival_provenance.precision_minutes,1)
        self.assertFalse(journey.actual_connection_guaranteed)

    def test_missing_provenance_exact_seconds_or_false_source_profile_rejected(self):
        d=self.source.dataset;r=d.stop_times[0]
        for bad in (replace(r,arrival_provenance=None),replace(r,arrival_service_seconds=36000),
                    replace(r,arrival_minute=r.arrival_minute+1440)):
            with self.assertRaises(ValueError): replace(d,stop_times=(bad,*d.stop_times[1:]))
        with self.assertRaises(ValueError): replace(d,metadata=replace(d.metadata,clock_profile='source'))

    def test_explicit_profile_and_realtime_required(self):
        files,reviews,coords,days=self.args
        for kwargs in ({'profile':'source'},{'profile':PROFILE,'realtime':True}):
            with self.assertRaises(ValueError):
                SendaiSubwayPracticalAdapter().load(files,reviews=reviews,stations=coords,
                    operating_days=days,fetched_at=datetime.now(timezone.utc),**kwargs)
        with self.assertRaisesRegex(ValueError,'static only'):
            query(self.net,'namboku/泉中央','namboku/仙台',realtime=True)
        # New profile is never invoked as a fallback from the unchanged strict adapter.
        with self.assertRaises(ValueError):
            SendaiSubwayAdapter().load(files,reviews=reviews,stations=coords,fetched_at=datetime.now(timezone.utc))

    def test_hash_license_and_comparison_scope_fail_fast(self):
        files,reviews,coords,days=self.args;name=FILES[0]
        for change in ({'csv_sha256':'b'*64},{'current_departure_evidence':()},
                       {'comparison_scope':'all_exact_arrivals'},{'license_id':'unknown'}):
            with self.assertRaises(ValueError):load((files,{**reviews,name:replace(reviews[name],**change)},coords,days))

    def test_calendar_holiday_and_exclusions_are_explicit(self):
        days=self.source.operating_days
        self.assertEqual(days.kind_on(date(2026,10,12)),'h')  # Monday, Sports Day.
        self.assertEqual(days.kind_on(DAY),'w')
        self.assertEqual(days.kind_on(date(2026,10,17)),'h')
        with self.assertRaisesRegex(ValueError,'year-end special'):days.kind_on(date(2026,12,31))
        with self.assertRaisesRegex(ValueError,'not in finite'):days.kind_on(date(2027,1,1))
        with self.assertRaisesRegex(ValueError,'year-end special'):
            query(self.net,'namboku/泉中央','namboku/仙台',day=date(2026,12,31))
        with self.assertRaises(ValueError):replace(days,entries=days.entries+(days.entries[0],))

    def test_transfer_ready_boundary_no_implicit_walk_or_double_buffer(self):
        # 10:09 arrival proxy + official 5 + experimental 2 = 10:16 eastbound.
        for start,expected in ((599,True),(600,True),(601,False)):
            result=query(self.net,'namboku/泉中央','tozai/荒井',start=start)
            self.assertEqual(bool(result),expected)
        result=query(self.net,'namboku/泉中央','tozai/荒井')[0]
        transfer=next(e for e in result.events if isinstance(e,PracticalTransfer))
        self.assertEqual((transfer.standard_minutes,transfer.margin_minutes),(5,2))
        self.assertEqual(transfer.ready_estimate.minute,616)
        self.assertIsNone(transfer.physical_walk_meters);self.assertFalse(transfer.walking_time_measured)
        self.assertEqual(transfer.margin_status,'experimental_unvalidated')
        self.assertFalse(result.experimental_margin_formally_adopted)
        self.assertFalse(query(build(self.source,margin=3),'namboku/泉中央','tozai/荒井'))
        self.assertTrue(query(build(self.source,margin=1),'namboku/泉中央','tozai/荒井'))
        self.assertFalse(query(build(self.source,connections=False),'namboku/泉中央','tozai/荒井'))
        with self.assertRaisesRegex(ValueError,'implicit boarding'):
            query(self.net,'namboku/泉中央','tozai/荒井',params=replace(PARAMS,rail_boarding_minutes=1))

    def test_transfer_source_and_date_are_pinned(self):
        with self.assertRaises(ValueError):replace(self.net.transfers,source_sha256='b'*64)
        limited=replace(self.net,transfers=replace(self.net.transfers,valid_days=frozenset({date(2026,10,15)})))
        with self.assertRaisesRegex(ValueError,'standard transfer is not reviewed'):
            query(limited,'namboku/泉中央','tozai/荒井')

    def test_free_scope_is_applied_before_search(self):
        rr=free_reviews(self.source)
        allowed=tuple(r for r in rr if r.trip_id.startswith('sendai_subway:namboku_'))
        net=build(self.source,reviews=allowed)
        self.assertFalse(query(net,'tozai/八木山動物公園','tozai/荒井',start=610))
        self.assertEqual(query(net,'namboku/泉中央','namboku/富沢')[0].fare_quote.pay_now_yen,0)
        for kwargs in ({'entire_path_municipality':'04209'},{'feed_version':'wrong'},{'operator_id':'MiyagiKotsu'}):
            with self.assertRaises(ValueError):build(self.source,reviews=(replace(rr[0],**kwargs),))

    def test_previous_weekday_24_clock_on_current_holiday(self):
        source=load(inputs(base=1430,east_base=1430));net=build(source)
        result=query(net,'namboku/五橋','namboku/富沢',day=date(2026,10,17),start=0)[0]
        event=result.events[0]
        self.assertEqual(event.source.service_date,DAY)
        self.assertIn('_w_south_',event.source.source_trip_id)
        self.assertEqual(event.departure.day,date(2026,10,17));self.assertEqual(event.departure.minute,0)
        self.assertEqual(event.source.departure_minute,1440)
        self.assertEqual(result.arrival_estimate.minute,6)

    def test_current_service_crossing_midnight_and_missing_previous_rejected(self):
        source=load(inputs(base=1430,east_base=1430));net=build(source)
        result=query(net,'namboku/泉中央','namboku/富沢',start=1430)[0]
        self.assertEqual(result.events[0].source.service_date,DAY)
        self.assertEqual(result.arrival_estimate.day,date(2026,10,17))
        entries=tuple(replace(e,kind=None,reason='unverified special day') if e.day==DAY else e for e in source.operating_days.entries)
        blocked=load((*inputs(base=1430,east_base=1430)[:3],replace(source.operating_days,entries=entries)))
        with self.assertRaisesRegex(ValueError,'unverified special day'):
            query(build(blocked),'namboku/五橋','namboku/富沢',day=date(2026,10,17),start=0)

    def test_calendar_changes_invalidate_dataset_version(self):
        files,reviews,coords,days=self.args
        altered=replace(days,entries=tuple(replace(e,kind='h') if e.day==DAY else e for e in days.entries))
        self.assertNotEqual(load((files,reviews,coords,altered)).dataset.metadata.version,self.source.dataset.metadata.version)

    def test_search_exception_identity_is_preserved(self):
        error=RuntimeError('independent injected core failure')
        with patch('sendai_practical_network.search_network',side_effect=error):
            with self.assertRaises(RuntimeError) as caught:query(self.net,'namboku/泉中央','namboku/富沢')
        self.assertIs(caught.exception,error)

    def test_real_core_limit_is_not_partial_success(self):
        from route_engine import RouteSearchLimitError
        with self.assertRaises(RouteSearchLimitError):
            query(self.net,'namboku/泉中央','namboku/富沢',params=replace(PARAMS,max_visited=1))

    def test_independent_generated_boundary_counterexample_search(self):
        for seed in range(12):
            offset=random.Random(seed).randint(-4,4)
            args=inputs(east_base=610+offset);source=load(args);net=build(source)
            days={e.day:e.kind for e in source.operating_days.entries if e.kind}
            expected=earliest(args[0],days,'sendai_subway:namboku/泉中央','sendai_subway:tozai/荒井',
                DAY,600,max_boardings=2,max_minutes=120,transfer_minutes=7)
            results=query(net,'namboku/泉中央','tozai/荒井')
            self.assertEqual(None if not results else results[0].arrival_estimate.minute,expected)


class PublishedCsvRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.args=inputs(real=True);cls.source=load(cls.args);cls.net=build(cls.source)

    def test_real_published_routes_against_independent_minute_oracle(self):
        cases=[(DAY,'namboku/泉中央','namboku/仙台',600),
               (DAY,'namboku/富沢','namboku/広瀬通',600),
               (DAY,'tozai/八木山動物公園','tozai/仙台',600),
               (DAY,'tozai/荒井','tozai/青葉通一番町',600),
               (DAY,'namboku/広瀬通','tozai/宮城野通',600),
               (DAY,'tozai/青葉通一番町','namboku/五橋',600),
               (date(2026,10,12),'namboku/泉中央','namboku/仙台',600),
               (date(2026,10,17),'tozai/八木山動物公園','tozai/荒井',600),
               (DAY,'namboku/仙台','namboku/富沢',1430),
               (date(2026,10,17),'namboku/五橋','namboku/富沢',0)]
        days={e.day:e.kind for e in self.source.operating_days.entries if e.kind}
        allowed={(f,n) for f,n,_,_,_ in raw_runs(self.args[0])}
        self.assertEqual(len(allowed),1046)
        for day,a,b,start in cases:
            with self.subTest(day=day,a=a,b=b,start=start):
                expected=earliest(self.args[0],days,'sendai_subway:'+a,'sendai_subway:'+b,day,start,
                    max_boardings=2,max_minutes=120,transfer_minutes=7,allowed=allowed)
                self.assertIsNotNone(expected,'fixed real source sample must have a complete witness')
                results=query(self.net,a,b,day=day,start=start);self.assertTrue(results)
                result=results[0]
                self.assertEqual((result.arrival_estimate.day-day).days*1440+result.arrival_estimate.minute,expected)
                validate_witness(self.args[0],result,day,transfer_minutes=7,day_kinds=days,allowed=allowed)
                if a.split('/')[0]!=b.split('/')[0]:
                    self.assertTrue(any(isinstance(e,PracticalTransfer) for e in result.events))
