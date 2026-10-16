"""Estimate-aware wire contract for the isolated Sendai test service.

This schema is intentionally distinct from Tokyo's public route contract.
"""
from dataclasses import asdict
from fractions import Fraction

from sendai_practical_network import PracticalRide, PracticalTransfer, PracticalWalk

SCHEMA = "sendai_practical_route_v1"


def civil_clock(value, *, basis):
    minute = Fraction(value.minute)
    stamp = f"{int(minute)//60:02d}:{int(minute)%60:02d}"
    remainder = (minute - int(minute)) * 60
    if remainder:
        if remainder.denominator != 1:
            raise ValueError("wire clock requires an exact source second or published minute")
        stamp += f":{int(remainder):02d}"
    return {"date": value.day.isoformat(), "time": stamp,
            "minute": {"numerator": minute.numerator, "denominator": minute.denominator},
            "basis": basis, "actual_arrival_verified": False}


def serialize_practical_journey(journey):
    events = []
    for event in journey.events:
        if isinstance(event, PracticalRide):
            ride = event.source
            published = ride.departure_provenance
            proxy = ride.arrival_provenance
            if ride.mode == "rail" and (published is None or proxy is None or not proxy.is_estimate):
                raise ValueError("subway result lacks published/proxy provenance")
            events.append({"kind": "ride", "mode": ride.mode, "trip_id": ride.trip_id,
                "source_trip_id": ride.source_trip_id, "service_date": ride.service_date.isoformat(),
                "route_id": ride.route_id, "feed_version": ride.feed_version,
                "from_stop_id": ride.from_stop_id, "to_stop_id": ride.to_stop_id,
                "from_sequence": ride.from_sequence, "to_sequence": ride.to_sequence,
                "stop_ids": list(ride.stop_ids),
                "departure": civil_clock(event.departure, basis="published_departure_minute" if published else "gtfs_scheduled_departure"),
                "arrival": civil_clock(event.arrival_estimate, basis="published_clock_arrival_proxy" if proxy else "gtfs_scheduled_arrival"),
                "departure_provenance": None if published is None else asdict(published),
                "arrival_provenance": None if proxy is None else asdict(proxy)})
        elif isinstance(event, PracticalTransfer):
            events.append({"kind": "standard_transfer", "from_stop_id": event.from_stop_id,
                "to_stop_id": event.to_stop_id, "standard_minutes": event.standard_minutes,
                "margin_minutes": event.margin_minutes, "margin_status": event.margin_status,
                "time_basis": event.time_basis, "path_description": event.path_description,
                "departure": civil_clock(event.departure_estimate, basis="connection_model"),
                "ready": civil_clock(event.ready_estimate, basis="connection_model"),
                "source_uri": event.source_uri, "source_sha256": event.source_sha256,
                "physical_walk_meters": None, "walking_time_measured": False,
                "connection_guaranteed": False})
        elif isinstance(event, PracticalWalk):
            link = event.source.pinned_link.link
            events.append({"kind": "reviewed_walk", "from_stop_id": link.from_stop_id,
                "to_stop_id": link.to_stop_id, "physical_walk_meters": link.walk_meters,
                "departure": civil_clock(event.departure, basis="reviewed_walk_model"),
                "ready": civil_clock(event.ready, basis="reviewed_walk_model")})
        else:
            raise ValueError("unsupported practical event type")
    quote = journey.fare_quote
    if quote.policy_id != "sendai_fureai_pass" or quote.pay_now_yen != 0:
        raise ValueError("only pre-scoped free-pass results may use this serializer")
    return {"schema": SCHEMA, "profile": journey.profile, "input_version": journey.input_version,
        "departure": civil_clock(journey.departure, basis="request"),
        "arrival": civil_clock(journey.arrival_estimate, basis="journey_arrival_estimate"),
        "events": events, "fare": {"policy_id": quote.policy_id, "additional_payment_yen": 0,
            "normal_fare_yen": None, "entitlement_assumed": True},
        "normal_timetable_only": True, "exact_arrival_verified": False,
        "actual_connection_guaranteed": False, "experimental_margin_formally_adopted": False}
