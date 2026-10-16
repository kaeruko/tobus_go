"""New hub and finite-date/API regressions for the reviewed stage1 model."""
import contextlib
from dataclasses import replace
from datetime import date
import io
import json
from pathlib import Path
import unittest

from fastapi.testclient import TestClient
from app.sendai_practical_routes import create_sendai_practical_test_app
from sendai_operating_period import OperatingPeriodReview
from sendai_practical_bundle import load_reviewed_subway, build_reviewed_municipal_model
from sendai_practical_network import PracticalRide, PracticalTransfer, search_practical_subway
from transit_timetable_choices import NetworkSearchParameters
from tests.test_sendai_arai21_practical import load_bus
from tests.sendai_municipal_oracle import runs, optimum, validate


FIXTURE=Path(__file__).parent/'fixtures/sendai_subway'


class SendaiStage1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=json.loads((FIXTURE/'municipal_bus_subset_20261006_stage1.json').read_text(encoding='utf-8'))
        cls.review=json.loads((FIXTURE/'municipal_review_20261016_stage1.json').read_text(encoding='utf-8'))
        cls.period=OperatingPeriodReview.from_mapping(cls.review['operating_period'])
        cls.bus=load_bus(cls.source,cls.review)
        cls.subway,cls.raw=load_reviewed_subway(FIXTURE/'published_20230701.json',FIXTURE/'practical_review_20261016.json',operating_period=cls.period)
        cls.network=build_reviewed_municipal_model(cls.subway,cls.bus,cls.review,accept_experimental_bus_transfers=True)
        cls.matrix=json.loads((FIXTURE/'municipal_fixed_cases_20261016_stage1.json').read_text(encoding='utf-8'))
        cls.params=NetworkSearchParameters(**cls.matrix['parameters'])
        cls.client=TestClient(create_sendai_practical_test_app(cls.network,environment='test',parameters=cls.params,
            operating_period=cls.period,coverage_label=cls.review['coverage_label']))

    def body(self,day='2026-10-19',minute=600):
        return dict(origin_stop_id='sendai_subway:tozai/仙台',destination_stop_id='sendai_subway:tozai/荒井',
            civil_date=day,departure_minute=minute,fare_policy_id='sendai_fureai_pass',accept_experimental_transfer_model=True)

    def post(self,body):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.client.post('/test/sendai/route',json=body)

    def test_new_izumi_hub_three_categories_and_two_subway_lines_match_independent_raw_model(self):
        # Import the raw classifier, not the production calendar/adapter output.
        import sys
        root=Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:sys.path.insert(0,str(root))
        from scripts.check_sendai_expansion import raw_day_kinds
        kinds=raw_day_kinds(self.review['operating_period'])
        for case in self.matrix['cases']:
            if not case['category'].startswith('izumi_') and case['category']!='rail_izumi_21':continue
            with self.subTest(category=case['category']):
                day=date.fromisoformat(case['civil_date'])
                rr=runs(self.source['files'],self.raw,kinds,day,self.review)
                expected=optimum(rr,self.review,case['origin'],case['destination'],case['departure_minute'],max_boardings=3,max_minutes=180)
                self.assertEqual(expected,case['expected_arrival_minute'])
                with contextlib.redirect_stdout(io.StringIO()):
                    result=search_practical_subway(self.network,case['origin'],case['destination'],civil_date=day,
                        departure_minute=case['departure_minute'],parameters=self.params)[0]
                self.assertEqual(result.arrival_estimate.minute,expected)
                validate(result,rr,self.review,day,case['origin'],case['destination'],case['departure_minute'])
                rides=[e.source for e in result.events if isinstance(e,PracticalRide)]
                self.assertEqual([r.mode for r in rides],case['modes'])
                self.assertIn('sendai_bus:10038',{self.bus.trips[r.trip_id].route_id for r in rides if r.mode=='bus'})
                transfers=[e for e in result.events if isinstance(e,PracticalTransfer)]
                if len(rides)>1:
                    izumi=next(e for e in transfers if '泉中央' in e.from_stop_id or '泉中央' in e.to_stop_id)
                    self.assertEqual((izumi.standard_minutes,izumi.margin_minutes),(8,2))
                    self.assertEqual(izumi.time_basis,'experimental_planning_assumption')

    def test_extended_dates_exclude_known_bus_change_but_keep_normal_query_times(self):
        caps=self.client.get('/test/sendai/capabilities').json()
        self.assertEqual(caps['operating_dates'][0],'2026-10-12')
        self.assertEqual(caps['operating_dates'][-1],'2026-10-31')
        self.assertIn('2026-10-19',caps['operating_dates'])
        self.assertNotIn('2026-10-25',caps['operating_dates'])
        self.assertEqual(len(caps['operating_dates']),19)
        self.assertIn('泉中央21',caps['coverage_label'])
        self.assertIn('日付境界',caps['date_boundary_notice'])
        self.assertFalse(caps['special_timetables_verified'])
        for day in ('2026-10-19','2026-10-24','2026-10-26','2026-10-31'):
            with self.subTest(day=day):self.assertEqual(self.post(self.body(day)).status_code,200)
        for day in ('2026-10-11','2026-10-25','2026-11-01','2026-12-01'):
            with self.subTest(day=day):self.assertEqual(self.post(self.body(day)).status_code,422)

    def test_previous_and_next_excluded_service_day_do_not_become_partial_results(self):
        for day,minute in (('2026-10-24',1439),('2026-10-26',0)):
            response=self.post(self.body(day,minute))
            self.assertEqual(response.status_code,422,response.text)
            self.assertIn('2026-10-25',response.text)

    def test_directional_new_hub_links_and_legacy_arai_assumptions_remain_distinct(self):
        links=self.review['bus_subway_transfers']
        self.assertEqual({(r['from_stop_id'],r['to_stop_id']) for r in links if '1085' in r['from_stop_id'] or '1085' in r['to_stop_id']},
            {('sendai_bus:1085_0','sendai_subway:namboku/泉中央'),('sendai_subway:namboku/泉中央','sendai_bus:1085_12')})
        old=json.loads((FIXTURE/'municipal_review_20261016.json').read_text(encoding='utf-8'))
        self.assertEqual(links[:2],old['bus_subway_transfers'])
        self.assertEqual(self.period.operating_days().kind_on(date(2026,10,25)),'h')
        self.assertNotIn(date(2026,10,25),self.network.bus_reviewed_days)

    def test_date_review_version_mismatch_and_non_test_environment_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'exact loaded subway'):
            create_sendai_practical_test_app(self.network,environment='test',parameters=self.params,
                operating_period=replace(self.period,coverage_end=date(2026,10,31),query_end=date(2026,10,30)))
        with self.assertRaises(ValueError):
            create_sendai_practical_test_app(self.network,environment='production',parameters=self.params,operating_period=self.period)
        self.assertEqual(self.post({**self.body(),'fare_policy_id':'normal'}).status_code,422)
        self.assertEqual(self.post({**self.body(),'fare_policy_id':'sendai_keiro_pass'}).status_code,422)


if __name__=='__main__':unittest.main()
