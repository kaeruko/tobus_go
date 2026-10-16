"""Explicit local-only server for the Sendai reviewed scheduled test profile."""
import argparse
import sys
from pathlib import Path
import json
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'api'))
from app.sendai_practical_routes import create_sendai_practical_test_app
from sendai_practical_bundle import load_reviewed_subway,build_reviewed_municipal_model
from sendai_transit import load_sendai_dataset
from transit_timetable_choices import NetworkSearchParameters


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('bus-gtfs-dir','subway-published','subway-review','municipal-review'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--expected-service-date',required=True)
    p.add_argument('--accept-experimental-transfer-model',action='store_true')
    p.add_argument('--port',type=int,default=8000)
    args=p.parse_args()
    if not args.accept_experimental_transfer_model:raise ValueError('explicit test model selection required')
    bus=load_sendai_dataset(args.bus_gtfs_dir,expected_service_date=args.expected_service_date)
    subway,_=load_reviewed_subway(args.subway_published,args.subway_review)
    review=json.loads(args.municipal_review.read_text(encoding='utf-8'))
    net=build_reviewed_municipal_model(subway,bus,review,accept_experimental_bus_transfers=True)
    # Existing shared v2 default safety limits; one earliest result, no top-k claim.
    params=NetworkSearchParameters(max_candidates=1,max_boardings=3,max_travel_minutes=180)
    app=create_sendai_practical_test_app(net,environment='test',parameters=params)
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=args.port)


if __name__=='__main__':main()
