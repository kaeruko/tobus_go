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
    # A GTFS route can contain both directions (and other driven paths).
    # Match the whole ordered path as well as the concrete trip whitelist.
    patterns={}
    for p in review['bus_patterns']:
        key=(p['route_id'].split(':',1)[1],tuple(p['stop_ids']))
        if key in patterns:raise ValueError('duplicate raw oracle reviewed pattern')
        patterns[key]=p
    reviewed_routes={route_id for route_id,_ in patterns}
    tt={}
    for r in rows(bus_files['stop_times.txt']):tt.setdefault(r['trip_id'],[]).append(r)
    for day,kind in day_kinds.items():
        shift=(day-civil_day).days*1440
        active=raw_services(bus_files,day)
        for trip in rows(bus_files['trips.txt']):
            if trip['service_id'] not in active or trip['route_id'] not in reviewed_routes:continue
            rr=sorted(tt[trip['trip_id']],key=lambda r:int(r['stop_sequence']))
            p=patterns.get((trip['route_id'],tuple('sendai_bus:'+r['stop_id'] for r in rr)))
            if p is None or 'sendai_bus:'+trip['trip_id'] not in p['trip_ids']:continue
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


def arrivals(raw_runs,review,origin,start,*,max_boardings,max_minutes):
    """The same bounded raw scan, retaining all destination arrival values.

    Bulk coverage needs one scan per origin, rather than repeating the exact
    same layers for thousands of destinations. No production code is called.
    Count>=1 still requires a ride, excluding bare transfer walks.
    """
    layer={origin:Fraction(start)};best={}
    for count in range(max_boardings+1):
        # Positive directed connection closure, independent of shared graph.
        for _ in range(len(links(review))+1):
            changed=False
            for a,b,minutes in links(review):
                if a in layer and layer[a]+minutes<layer.get(b,Fraction(10**12)):
                    layer[b]=layer[a]+minutes;changed=True
            if not changed:break
        if count:
            for destination,minute in layer.items():
                if minute<=start+max_minutes:
                    best[destination]=min(best.get(destination,Fraction(10**12)),minute)
        next_layer={}
        for run in raw_runs:
            for i,a in enumerate(run['stops'][:-1]):
                if a not in layer or run['pickup'][i]!='0' or run['deps'][i]<layer[a]:continue
                for j in range(i+1,len(run['stops'])):
                    if run['dropoff'][j]!='0' or run['arrs'][j]>start+max_minutes:continue
                    b=run['stops'][j];next_layer[b]=min(next_layer.get(b,Fraction(10**12)),run['arrs'][j])
        layer=next_layer
    return best


def optimum(raw_runs,review,origin,destination,start,*,max_boardings,max_minutes):
    return arrivals(raw_runs,review,origin,start,max_boardings=max_boardings,max_minutes=max_minutes).get(destination)


def few_transfer_arrivals(raw_runs,review,origin,start,*,max_boardings,max_minutes,
                          destination_walk_minutes=None):
    """Test-only finite raw-row scan, retaining clock/cost Pareto alternatives.

    Costs are independent integer tenths: boarding=50, each travelled row=8,
    reviewed connection minute=15. Waiting and endpoint walks do not enter the
    established planning-cost objective. No production search/ranker is used.
    The witness records original trip, sequences, clocks and connection rows.
    """
    deadline=Fraction(start)+max_minutes
    def add(layer,stop,clock,cost,witness):
        if clock>deadline:return False
        current=layer.setdefault(stop,[])
        if any(t<=clock and c<=cost for t,c,_ in current):return False
        current[:]=[(t,c,w) for t,c,w in current if not (clock<=t and cost<=c)]
        current.append((clock,cost,witness));return True
    layer={origin:[(Fraction(start),0,())]};best={}
    for count in range(max_boardings+1):
        for _ in range(len(links(review))+1):
            changed=False
            for a,b,minutes in links(review):
                for clock,cost,witness in tuple(layer.get(a,())):
                    changed=add(layer,b,clock+minutes,cost+15*minutes,
                        witness+(('walk',a,b,minutes),)) or changed
            if not changed:break
        if count:
            for stop,values in layer.items():
                if stop not in best:
                    walk=(destination_walk_minutes or {}).get(stop,0)
                    feasible=[v for v in values if v[0]+walk<=deadline]
                    if not feasible:continue
                    clock,cost,witness=min(feasible,key=lambda v:(v[1],v[0]))
                    best[stop]=(count,cost,clock,witness)
        if count==max_boardings:break
        following={}
        for run in raw_runs:
            for i,a in enumerate(run['stops'][:-1]):
                if run['pickup'][i]!='0':continue
                ready=[v for v in layer.get(a,()) if v[0]<=run['deps'][i]]
                if not ready:continue
                # Every available prefix boards the SAME concrete departure;
                # its arrival thereafter is identical. Keep the cheapest.
                clock,cost,witness=min(ready,key=lambda v:(v[1],v[0]))
                for j in range(i+1,len(run['stops'])):
                    if run['dropoff'][j]!='0':continue
                    add(following,run['stops'][j],run['arrs'][j],cost+50+8*(j-i),
                        witness+(('ride',run['trip'],run['seq'][i],run['seq'][j],
                            str(run['deps'][i]),str(run['arrs'][j])),))
        layer=following
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
