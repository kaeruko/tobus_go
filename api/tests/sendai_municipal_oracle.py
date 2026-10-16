"""Independent raw GTFS/CP932 finite oracle, including a full witness check.

Test/audit only. No Dataset, network, calendar implementation, provider,
frontier, priority or production search code is used for the optimum.
"""
import csv
import io
import hashlib
from datetime import date
from fractions import Fraction

from tests.sendai_practical_oracle import raw_runs


def rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def seconds(clock):
    h,m,s=map(int,clock.split(':'))
    return Fraction(h*3600+m*60+s,60)


def raw_services(files,day):
    result=set()
    key=day.strftime('%Y%m%d')
    for r in rows(files.get('calendar.txt','')):
        if r['start_date']<=key<=r['end_date'] and r[('monday','tuesday','wednesday','thursday','friday','saturday','sunday')[day.weekday()]]=='1': result.add(r['service_id'])
    for r in rows(files.get('calendar_dates.txt','')):
        if r['date']==key:
            if r['exception_type']=='1':result.add(r['service_id'])
            elif r['exception_type']=='2':result.discard(r['service_id'])
            else:raise ValueError('unknown raw GTFS exception')
    return result


def runs(bus_files,subway_files,day_kinds,civil_day,review):
    result=[]
    patterns={p['route_id'].split(':',1)[1]:p for p in review['bus_patterns']}
    tt={}
    for r in rows(bus_files['stop_times.txt']):tt.setdefault(r['trip_id'],[]).append(r)
    for day,kind in day_kinds.items():
        shift=(day-civil_day).days*1440
        active=raw_services(bus_files,day)
        for trip in rows(bus_files['trips.txt']):
            if trip['service_id'] not in active or trip['route_id'] not in patterns:continue
            rr=sorted(tt[trip['trip_id']],key=lambda r:int(r['stop_sequence']))
            p=patterns[trip['route_id']]
            if ['sendai_bus:'+r['stop_id'] for r in rr]!=p['stop_ids'] or 'sendai_bus:'+trip['trip_id'] not in p['trip_ids']:continue
            result.append(dict(trip='sendai_bus:'+trip['trip_id'],day=day,mode='bus',
                stops=tuple('sendai_bus:'+r['stop_id'] for r in rr),seq=tuple(int(r['stop_sequence']) for r in rr),
                deps=tuple(seconds(r['departure_time'])+shift for r in rr),arrs=tuple(seconds(r['arrival_time'])+shift for r in rr),
                pickup=tuple(r.get('pickup_type','') or '0' for r in rr),dropoff=tuple(r.get('drop_off_type','') or '0' for r in rr)))
        for filename,number,k,stops,clocks in raw_runs(subway_files):
            if k!=kind:continue
            result.append(dict(trip=f'{filename}/{hashlib.sha256(subway_files[filename]).hexdigest()}/row-{number}',day=day,mode='rail',stops=stops,seq=tuple(range(len(stops))),
                deps=tuple(c+shift for c in clocks),arrs=tuple(c+shift for c in clocks),
                pickup=tuple('1' if i==len(stops)-1 else '0' for i in range(len(stops))),
                dropoff=tuple('1' if i==0 else '0' for i in range(len(stops)))))
    return result


def links(review):
    a,b='sendai_subway:namboku/仙台','sendai_subway:tozai/仙台'
    return [(a,b,5+review['subway_transfer_margin_minutes']),(b,a,5+review['subway_transfer_margin_minutes'])]+[
        (r['from_stop_id'],r['to_stop_id'],r['standard_minutes']+r['margin_minutes']) for r in review['bus_subway_transfers']]


def optimum(raw_runs,review,origin,destination,start,*,max_boardings,max_minutes):
    layer={origin:Fraction(start)};best=None
    for count in range(max_boardings+1):
        # Positive directed connection closure, independent of shared graph.
        for _ in range(len(links(review))+1):
            changed=False
            for a,b,minutes in links(review):
                if a in layer and layer[a]+minutes<layer.get(b,Fraction(10**12)):
                    layer[b]=layer[a]+minutes;changed=True
            if not changed:break
        if count and destination in layer and layer[destination]<=start+max_minutes:
            best=layer[destination] if best is None else min(best,layer[destination])
        next_layer={}
        for run in raw_runs:
            for i,a in enumerate(run['stops'][:-1]):
                if a not in layer or run['pickup'][i]!='0' or run['deps'][i]<layer[a]:continue
                for j in range(i+1,len(run['stops'])):
                    if run['dropoff'][j]!='0' or run['arrs'][j]>start+max_minutes:continue
                    b=run['stops'][j];next_layer[b]=min(next_layer.get(b,Fraction(10**12)),run['arrs'][j])
        layer=next_layer
    return best


def validate(result,raw_runs,review,civil_day,origin,destination,start):
    from sendai_practical_network import PracticalRide,PracticalTransfer
    ready=Fraction(start);at=origin;boards=0
    def absolute(c):return (c.day-civil_day).days*1440+c.minute
    for e in result.events:
        if isinstance(e,PracticalTransfer):
            assert (at,e.to_stop_id,e.standard_minutes+e.margin_minutes) in links(review)
            assert e.from_stop_id==at and absolute(e.departure_estimate)==ready
            ready+=e.standard_minutes+e.margin_minutes;assert absolute(e.ready_estimate)==ready;at=e.to_stop_id
        elif isinstance(e,PracticalRide):
            r=e.source;boards+=1
            candidates=[x for x in raw_runs if x['day']==r.service_date and
                (x['trip']==r.trip_id if x['mode']=='bus' else x['trip']==r.source_trip_id)]
            assert len(candidates)==1
            run=candidates[0];i=run['seq'].index(r.from_sequence);j=run['seq'].index(r.to_sequence)
            assert i<j and run['stops'][i]==at and run['stops'][i:j+1]==r.stop_ids
            assert run['pickup'][i]=='0' and run['dropoff'][j]=='0'
            assert run['deps'][i]>=ready and absolute(e.departure)==run['deps'][i]
            assert absolute(e.arrival_estimate)==run['arrs'][j]
            ready=run['arrs'][j];at=run['stops'][j]
        else:raise AssertionError('unreviewed witness event')
    assert boards and at==destination and absolute(result.arrival_estimate)==ready
    assert result.fare_quote.pay_now_yen==0
