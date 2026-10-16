"""Tiny finite exhaustive schedule oracle for adapter fixtures only.

Independent boarding-count relaxation. No heap, A*, shared graph, production
provider, dominance code or v1 implementation. Not importable by app startup.
"""
from datetime import date
from fractions import Fraction
from transit_search_dto import TransitItinerary, TransitLeg


def earliest(dataset, origin, destination, day, start, *, max_rides=6, fewest=False):
    active = {c.id for c in dataset.calendars.values() if c.start_date <= day <= c.end_date and c.weekdays[day.weekday()]}
    for e in dataset.service_exceptions:
        if e.day == day:
            if e.exception_type == 1: active.add(e.service_id)
            else: active.discard(e.service_id)
    runs = {}
    for row in dataset.stop_times:
        if dataset.trips[row.trip_id].service_id in active:
            runs.setdefault(row.trip_id, []).append(row)
    def clock(row, field):
        seconds=getattr(row, field+'_service_seconds')
        return Fraction(seconds,60) if seconds is not None else getattr(row,field+'_minute')
    layer = {origin:(Fraction(start),())}; goals=[]
    for count in range(max_rides+1):
        if destination in layer:
            at,legs=layer[destination]
            goals.append(TransitItinerary(start,at,legs))
            if fewest: break
        following={}
        for tid,unsorted in runs.items():
            rows=sorted(unsorted,key=lambda r:r.sequence)
            trip=dataset.trips[tid]
            for i,row in enumerate(rows[:-1]):
                dep=clock(row,'departure')
                if row.pickup_type or dep is None or row.stop_id not in layer or layer[row.stop_id][0]>dep: continue
                for end in rows[i+1:]:
                    arr=clock(end,'arrival')
                    if end.drop_off_type or arr is None:continue
                    leg=TransitLeg(tid,trip.route_id,dataset.routes[trip.route_id].mode,row.stop_id,end.stop_id,dep,arr,
                        tuple(r.stop_id for r in rows[i:] if r.sequence<=end.sequence))
                    if end.stop_id not in following or arr<following[end.stop_id][0]:
                        following[end.stop_id]=(arr,layer[row.stop_id][1]+(leg,))
        layer=following
    return min(goals,key=lambda j:(j.arrival_minute,j.rides)) if goals else None


class FixtureScheduleOracle:
    def __init__(self,dataset): self.dataset=dataset
    def search_fastest(self,origin,destination,*,departure):
        return earliest(self.dataset,origin,destination,departure.date(),departure.hour*60+departure.minute)
    def search_fewest_transfers(self,origin,destination,*,departure):
        return earliest(self.dataset,origin,destination,departure.date(),departure.hour*60+departure.minute,fewest=True)
    def search(self,request):
        from types import SimpleNamespace
        pairs=[]
        for i,o in enumerate(request.origins):
            for j,d in enumerate(request.destinations):
                result=earliest(self.dataset,o.stop_id,d.stop_id,request.service_date,
                    request.departure_minute+o.walk_minutes,max_rides=request.max_rides,
                    fewest=request.preference=='fewest_transfers')
                if result is not None: pairs.append(SimpleNamespace(origin_index=i,destination_index=j,itinerary=result))
        return SimpleNamespace(pairs=tuple(pairs))
