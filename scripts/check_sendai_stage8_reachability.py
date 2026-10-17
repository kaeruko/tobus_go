"""Stage8 fixed new-area evidence, reusing the stage7 raw-oracle counter."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'api')]
from scripts.check_sendai_stage7_reachability import compute

F=ROOT/'api/tests/fixtures/sendai_subway'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--print-candidate',action='store_true')
    args=p.parse_args()
    read=lambda n:json.loads((F/n).read_text(encoding='utf-8'))
    result=compute(read('municipal_bus_subset_20261006_stage8.json'),read('municipal_review_20261017_stage8.json'),
        read('municipal_review_20261017_stage7.json'),read('published_20230701.json'),
        scope=read('municipal_reachability_scope_20261017_stage8.json'))
    # Sendai has separate Namboku/Tozai vertices. Count physical station
    # names for reporting only; never merge routing nodes or OD hashes.
    result['rail_station_names']=len({s.split('/',1)[1] for s in result['bus_to_rail']['by_rail_vertex']})
    for direction in ('bus_to_rail','rail_to_bus'):
        result[direction]['served_rail_station_names']=len({s.split('/',1)[1] for s,n in result[direction]['by_rail_vertex'].items() if n})
    if not args.print_candidate and result!=read('municipal_reachability_20261017_stage8.json'):
        raise AssertionError('Fixed stage8 independent reachability or arrival evidence changed')
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2),flush=True)
    if not args.print_candidate:print('SENDAI_STAGE8_NEW_AREA_REACHABILITY_OK')


if __name__=='__main__':main()
