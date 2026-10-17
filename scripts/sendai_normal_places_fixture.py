"""CI-only Google Places upstream response fixture. Never imported by runtime.

Own /autocomplete and /details endpoints, bilingual parsing, HTTP transport to
the local app, /route, Policy, GTFS, calendar and SearchCore remain real. These
responses prove client/server contracts, not live Google geocoding accuracy.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'api'))


def install():
    from app import route_only_places as places
    fixture = json.loads((Path(__file__).resolve().parents[1]/
        'api/tests/fixtures/sendai_subway/normal_coordinate_cases_20261017.json').read_text(encoding='utf-8'))
    entries = {}
    for case in fixture['cases']:
        for role in ('origin','destination'):
            key = case['name'] + '-' + role
            entries[key] = dict(label=case[role+'_label'], coordinate=case[role])
    async def autocomplete(query,language):
        places._require_language(language)
        matches = [(key,value) for key,value in entries.items() if value['label']==query]
        # Only the external response is fixed. The existing converter still
        # turns Places v1 suggestions into the app's legacy prediction contract.
        if not matches:
            raise ValueError('CI Places fixture has no declared query: '+query)
        key,value=matches[0]
        return {'suggestions':[{'placePrediction':{'placeId':key,'text':{'text':value['label']}}}]}
    async def details(place_id,language):
        places._require_language(language)
        if place_id not in entries:
            raise ValueError('CI Places fixture has no declared place: '+place_id)
        value=entries[place_id];lat,lon=value['coordinate']
        return {'id':place_id,'displayName':{'text':value['label'] if language=='ja' else 'CI place '+place_id},
                'formattedAddress':value['label'],'location':{'latitude':lat,'longitude':lon}}
    places._request_autocomplete=autocomplete
    places._request_details=details


if __name__=='__main__':
    install()
    from serve_sendai_normal_local import main
    main()
