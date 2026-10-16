"""Independent raw-CSV minute oracle. Never imported by application code.

No Dataset adapter, network graph, shared labels, priority or dominance. The
finite reference relaxes all board/alight pairs by boarding count; earlier
arrival at a physical stop can wait for any later raw departure in this model.
"""
import csv
import io
from datetime import timedelta


def raw_runs(files):
    result = []
    for filename, raw in files.items():
        line, kind, _, _ = filename.split('_')
        rows = list(csv.reader(io.StringIO(raw.decode('cp932', errors='strict'))))
        for number, row in enumerate(rows[1:], 2):
            clock, previous, offset = [], -1, 0
            for text in row[2:]:
                h, m = map(int, text.split(':')); value = 60*h+m
                if value < previous: offset += 1440
                clock.append(value+offset); previous=value
            result.append((filename, number, kind,
                tuple('sendai_subway:'+line+'/'+name for name in rows[0][2:]), tuple(clock)))
    return result


def earliest(files, day_kinds, origin, destination, civil_day, start, *,
             max_boardings, max_minutes, transfer_minutes=None, allowed=None):
    runs = []
    for filename, number, kind, stops, clocks in raw_runs(files):
        if allowed is not None and (filename, number) not in allowed: continue
        for day, day_kind in day_kinds.items():
            if day_kind == kind:
                shift = (day-civil_day).days*1440
                runs.append((stops, tuple(t+shift for t in clocks)))
    labels = {origin: start}
    best = None
    a,b='sendai_subway:namboku/仙台','sendai_subway:tozai/仙台'
    for count in range(max_boardings+1):
        if transfer_minutes is not None:
            # Two physical line stations, one positive standard link each way.
            for u,v in ((a,b),(b,a)):
                if u in labels:
                    labels[v]=min(labels.get(v,10**9),labels[u]+transfer_minutes)
        if count and destination in labels:
            value=labels[destination]
            if value <= start+max_minutes: best=value if best is None else min(best,value)
        if count==max_boardings: break
        following={}
        for stops, clocks in runs:
            for i,stop in enumerate(stops[:-1]):
                if stop not in labels or clocks[i]<labels[stop]: continue
                for j in range(i+1,len(stops)):
                    if clocks[j]<=start+max_minutes:
                        following[stops[j]]=min(following.get(stops[j],10**9),clocks[j])
        labels=following
    return best


def validate_witness(files, result, civil_day, *, transfer_minutes, day_kinds, allowed):
    # Local imports are result type checks only; source clock validation above
    # does not invoke any application transformation or calendar implementation.
    from sendai_practical_network import PracticalRide, PracticalTransfer
    rows={(f,n):(k,s,c) for f,n,k,s,c in raw_runs(files)}
    ready=result.departure.minute
    previous=None
    for event in result.events:
        if isinstance(event,PracticalTransfer):
            assert event.standard_minutes+event.margin_minutes==transfer_minutes
            dep=(event.departure_estimate.day-civil_day).days*1440+event.departure_estimate.minute
            end=(event.ready_estimate.day-civil_day).days*1440+event.ready_estimate.minute
            assert dep==ready and end==ready+transfer_minutes
            assert previous is None or event.from_stop_id==previous
            ready=end;previous=event.to_stop_id
        elif isinstance(event,PracticalRide):
            source=event.source
            filename,_,number=source.source_trip_id.split('/')
            number=int(number.removeprefix('row-'))
            assert (filename,number) in allowed
            kind,stops,clocks=rows[filename,number]
            assert day_kinds[source.service_date]==kind
            i,j=source.from_sequence,source.to_sequence
            assert i<j and source.stop_ids==stops[i:j+1]
            assert previous is None or source.from_stop_id==previous
            assert source.departure_minute==clocks[i] and source.arrival_minute==clocks[j]
            assert source.departure_provenance.published_clock.split(':')==[
                str(clocks[i]//60%24),f'{clocks[i]%60:02d}']
            assert source.arrival_provenance.is_estimate
            dep=(event.departure.day-civil_day).days*1440+event.departure.minute
            end=(event.arrival_estimate.day-civil_day).days*1440+event.arrival_estimate.minute
            assert dep>=ready and end>=dep
            ready=end;previous=source.to_stop_id
        else: raise AssertionError('unknown result event')
    assert (result.arrival_estimate.day-civil_day).days*1440+result.arrival_estimate.minute==ready
    assert result.fare_quote.pay_now_yen==0 and result.exact_arrival_verified is False
