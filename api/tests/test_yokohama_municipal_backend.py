"""Current municipal v2 contract; obsolete two-stage/estimate tests removed."""
import asyncio
from dataclasses import asdict, replace
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from reviewed_walk_time import ReviewedWalkingLink
from transit_network import DirectedWalkLink
from route_engine import GeoPoint, RouteInputError, RoutePreference, RouteSearchRequest, serialize_route_result
from route_fare_scope import search_with_fare_scope
from fare_policy import decorate_route_result_with_fare
from test_yokohama_municipal_transfer import _feed
from yokohama_municipal_backend import YokohamaMunicipalRouteBackend, load_reviewed_transfer_links

WELFARE='yokohama_welfare_special_pass'
SENIOR='yokohama_senior_special_pass'


def _request(origin=(35.4700,139.6200),destination=(35.4500,139.6300),*,hour=9,minute=0,
             bus_only=False,preference=RoutePreference.FASTEST):
    return RouteSearchRequest(GeoPoint(*origin),GeoPoint(*destination),
        datetime(2026,10,14,hour,minute,tzinfo=ZoneInfo('Asia/Tokyo')),preference,bus_only=bus_only)


def directed_links(bus,rail):
    a,b='yokohama_bus:B','yokohama_subway:S'
    return tuple(DirectedWalkLink(ReviewedWalkingLink(x,y,120,3,
        'https://www.city.yokohama.lg.jp/kotsu/',True),v,w)
        for x,y,v,w in ((a,b,bus.dataset.metadata.version,rail.dataset.metadata.version),
                        (b,a,rail.dataset.metadata.version,bus.dataset.metadata.version)))


class MunicipalBackendContractTests(unittest.TestCase):
    def setUp(self):
        b=tempfile.TemporaryDirectory();r=tempfile.TemporaryDirectory()
        self.addCleanup(b.cleanup);self.addCleanup(r.cleanup)
        self.bus=_feed(Path(b.name),rail=False);self.rail=_feed(Path(r.name),rail=True)
        self.links=directed_links(self.bus,self.rail)

    def search(self,request,*,links=None,policy=WELFARE):
        engine=YokohamaMunicipalRouteBackend(self.bus,self.rail,
            transfer_links=self.links if links is None else links)
        result=search_with_fare_scope(engine,request,policy)
        payload=serialize_route_result(result)
        decorate_route_result_with_fare(city_key='yokohama',result=payload,policy_id=policy)
        return payload

    def test_both_directions_and_both_passes_delegate_to_shared_v2(self):
        import transit_timetable_choices as choices
        for policy in (WELFARE,SENIOR):
            for request in (_request(),_request(origin=(35.4500,139.6300),destination=(35.4700,139.6200),hour=9,minute=55)):
                with self.subTest(policy=policy,origin=request.origin):
                    with patch('transit_timetable_choices.search_labels',wraps=choices.search_labels) as core:
                        payload=self.search(request,policy=policy)
                    self.assertTrue(core.called)
                    candidate=payload['candidates'][0]
                    self.assertEqual(candidate['fare']['payNowYen'],0)
                    self.assertEqual(candidate['boards'],2)
                    walks=[s for s in candidate['steps'] if s['kind']=='walk']
                    self.assertTrue(any(w.get('walking_connection_verified') for w in walks))
                    self.assertEqual(payload['meta']['walking_transfer_basis'],'reviewed_links_only')

    def test_no_implicit_link_reverse_or_legacy_bidirectional_conversion(self):
        self.assertFalse(self.search(_request(),links=())['candidates'])
        reverse=_request(origin=(35.4500,139.6300),destination=(35.4700,139.6200),hour=9,minute=55)
        self.assertFalse(self.search(reverse,links=self.links[:1])['candidates'])
        with self.assertRaisesRegex(ValueError,'directed'):
            YokohamaMunicipalRouteBackend(self.bus,self.rail,transfer_links=(
                {'bus_stop_id':'yokohama_bus:B','subway_stop_id':'yokohama_subway:S'},))

    def test_bus_only_filters_before_network_search(self):
        result=self.search(_request(destination=(35.4650,139.6250),bus_only=True))
        self.assertTrue(result['candidates'])
        self.assertTrue(all(s['kind']!='rail' for s in result['candidates'][0]['steps']))

    def test_scope_required_and_bad_versions_fail(self):
        engine=YokohamaMunicipalRouteBackend(self.bus,self.rail)
        with self.assertRaisesRegex(RouteInputError,'fare policy scope'):engine.search(_request())
        with self.assertRaisesRegex(ValueError,'version mismatch'):
            YokohamaMunicipalRouteBackend(self.bus,self.rail,transfer_links=(replace(self.links[0],from_feed_version='old'),))

    def test_old_estimate_setting_is_rejected_before_data_io(self):
        from app.yokohama_runtime import setup_yokohama_on_startup
        with patch.dict(os.environ,{'YOKOHAMA_TRANSFER_WALK_MODE':'estimate_dev'}):
            with self.assertRaisesRegex(RuntimeError,'was removed'):
                asyncio.run(setup_yokohama_on_startup(SimpleNamespace(state=SimpleNamespace()),'local'))

    def test_directed_review_schema_is_version_pinned_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'links.json'
            raw={'schema_version':2,'feed_versions':{'yokohama_bus':self.bus.dataset.metadata.version,
                'yokohama_subway':self.rail.dataset.metadata.version},'links':[asdict(x.link) for x in self.links]}
            path.write_text(json.dumps(raw));before=path.read_bytes()
            self.assertEqual(load_reviewed_transfer_links(path,self.bus,self.rail),self.links)
            self.assertEqual(before,path.read_bytes())
            for change in ({'schema_version':1},{'feed_versions':{}}):
                path.write_text(json.dumps({**raw,**change}))
                with self.assertRaises(ValueError):load_reviewed_transfer_links(path,self.bus,self.rail)
