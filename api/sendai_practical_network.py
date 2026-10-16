"""Opt-in municipal subway model over the shared v2 network, never public UI.

Civil requests explicitly materialize each reviewed service day. No alternate
search, pruning, candidate sorting, realtime or implicit calendar is introduced.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from fractions import Fraction
from types import MappingProxyType

from sendai_shared_network import SendaiFureaiPassPolicy, SendaiFreeNetwork, build_sendai_free_network
from fare_policy import FareQuote
from transit_adapters.sendai_subway_practical import (
    PROFILE, GUIDE_URI, GUIDE_SHA256, PracticalSubwayDataset, _digest,
)
from transit_dataset import ServiceCalendar, ServiceException, TransitDataset
from transit_network import NetworkCosts, StandardTransferLink, build_transit_network
from transit_timetable_choices import (
    NetworkRideEvent, NetworkStandardTransferEvent, NetworkSearchParameters, search_network,
)


@dataclass(frozen=True)
class SendaiStandardTransferReview:
    """Both directions adopt the official planning rule, not measured walks."""
    margin_minutes: int
    valid_days: frozenset[date]
    source_uri: str
    source_sha256: str
    margin_status: str = "experimental_unvalidated"

    def __post_init__(self):
        if (type(self.margin_minutes) is not int or self.margin_minutes < 0
                or type(self.valid_days) is not frozenset or not self.valid_days
                or any(type(d) is not date for d in self.valid_days)
                or self.source_uri != GUIDE_URI or self.source_sha256 != GUIDE_SHA256
                or self.margin_status != "experimental_unvalidated"):
            raise ValueError("explicit official Sendai standard and experimental margin required")

    def links(self, version):
        a, b = "sendai_subway:namboku/仙台", "sendai_subway:tozai/仙台"
        return tuple(StandardTransferLink(x, y, version, version, 5, self.margin_minutes,
            self.source_uri, self.source_sha256, PROFILE) for x, y in ((a, b), (b, a)))


@dataclass(frozen=True)
class CivilMinute:
    day: date
    minute: Fraction


@dataclass(frozen=True)
class PracticalRide:
    source: NetworkRideEvent  # Original trip, service date and source-day clocks.
    departure: CivilMinute
    arrival_estimate: CivilMinute


@dataclass(frozen=True)
class PracticalTransfer:
    standard_minutes: int
    margin_minutes: int
    margin_status: str
    from_stop_id: str
    to_stop_id: str
    departure_estimate: CivilMinute
    ready_estimate: CivilMinute
    source_uri: str
    source_sha256: str
    physical_walk_meters: None = None
    walking_time_measured: bool = False
    connection_guaranteed: bool = False


@dataclass(frozen=True)
class PracticalJourney:
    departure: CivilMinute
    arrival_estimate: CivilMinute
    events: tuple[PracticalRide | PracticalTransfer, ...]
    fare_quote: FareQuote
    profile: str
    input_version: str
    normal_timetable_only: bool = True
    exact_arrival_verified: bool = False
    actual_connection_guaranteed: bool = False
    experimental_margin_formally_adopted: bool = False


@dataclass(frozen=True)
class PracticalFreeNetwork:
    source: PracticalSubwayDataset
    free_scope: SendaiFreeNetwork
    transfers: SendaiStandardTransferReview | None


def build_practical_subway_network(source, *, segment_reviews, transfers, costs):
    if not isinstance(source, PracticalSubwayDataset) or source.dataset.metadata.clock_profile != PROFILE:
        raise ValueError("explicit practical subway dataset required")
    if transfers is not None and not isinstance(transfers, SendaiStandardTransferReview):
        raise ValueError("explicit standard transfer review required")
    days = frozenset(e.day for e in source.operating_days.entries if e.kind is not None)
    if transfers is not None and not transfers.valid_days <= days:
        raise ValueError("standard transfer days exceed reviewed operating-day table")
    scope = build_sendai_free_network((source.dataset,), segment_reviews=segment_reviews,
        reviewed_days=days, walking_links=(), costs=costs)
    return PracticalFreeNetwork(source, scope, transfers)


def _civil(anchor, minute):
    offset = minute // 1440
    return CivilMinute(anchor + timedelta(days=int(offset)), minute - offset * 1440)


def search_practical_subway(network, origin, destination, *, civil_date,
                             departure_minute, parameters, realtime=False):
    if realtime is not False:
        raise ValueError("practical subway search is static only")
    if (not isinstance(network, PracticalFreeNetwork) or type(civil_date) is not date
            or type(departure_minute) is not int or not 0 <= departure_minute < 1440
            or not isinstance(parameters, NetworkSearchParameters)):
        raise ValueError("explicit civil date/minute and network parameters required")
    # Standard transfers already include all declared connection time. Avoid an
    # implicit extra rail buffer, whose meaning would differ from this profile.
    if (parameters.rail_boarding_minutes != 0 or parameters.rail_alighting_minutes != 0
            or parameters.bus_alighting_minutes != 0):
        raise ValueError("practical profile requires zero additional implicit boarding/alighting buffers")
    source = network.source
    if origin not in source.dataset.stops or destination not in source.dataset.stops:
        raise ValueError("unknown practical origin/destination")
    original = source.dataset
    finish = Fraction(departure_minute) + Fraction(str(parameters.max_travel_minutes))
    latest = max(r.arrival_minute for r in original.stop_times)
    first = -1 if departure_minute <= latest - 1440 else 0
    last = int(finish // 1440)
    days = tuple(civil_date + timedelta(days=i) for i in range(first, last + 1))
    for day in days:
        source.operating_days.kind_on(day)  # reasoned failure; never partial coverage.
        if network.transfers is not None and day not in network.transfers.valid_days:
            raise ValueError(f"standard transfer is not reviewed for operating day {day}")
    anchor = civil_date - timedelta(days=1)
    trips, times, calendars, exceptions, identities = {}, [], {}, [], {}
    rows = {}
    for row in original.stop_times:
        rows.setdefault(row.trip_id, []).append(row)
    for day in days:
        offset = (day - anchor).days * 1440
        active = original.active_service_ids(day)
        for trip_id in sorted(network.free_scope.allowed_trip_ids):
            trip = original.trips[trip_id]
            if trip.service_id not in active:
                continue
            source_id = trip.source_id + "/service-" + day.isoformat()
            clone = "sendai_subway:" + source_id
            service_source = original.calendars[trip.service_id].source_id + "/service-" + day.isoformat()
            service_id = "sendai_subway:" + service_source
            trips[clone] = replace(trip, id=clone, source_id=source_id, service_id=service_id)
            identities[clone] = trip_id, day, offset
            if service_id not in calendars:
                calendars[service_id] = ServiceCalendar(service_id, service_source, (False,) * 7, anchor, anchor)
                exceptions.append(ServiceException(service_id, anchor, 1))
            for row in rows[trip_id]:
                times.append(replace(row, trip_id=clone, model_day_offset_minutes=offset,
                    arrival_minute=row.arrival_minute + offset,
                    departure_minute=None if row.departure_minute is None else row.departure_minute + offset))
    if not trips:
        return ()
    version = _digest({"input": original.metadata.version, "anchor": anchor,
        "days": days, "transfers": None if network.transfers is None else {
            "margin": network.transfers.margin_minutes, "days": sorted(network.transfers.valid_days),
            "source": network.transfers.source_sha256}})
    materialized = TransitDataset(replace(original.metadata, version=version), original.stops,
        original.routes, MappingProxyType(trips), tuple(times), MappingProxyType(calendars), tuple(exceptions))
    links = () if network.transfers is None else network.transfers.links(version)
    snapshot = build_transit_network((materialized,), allowed_trip_ids=trips, walking_links=(),
        costs=network.free_scope.snapshot.costs, standard_transfers=links)
    start = 1440 + departure_minute
    journeys = search_network(snapshot, origin, destination, service_date=anchor,
        departure_minute=start, mode="time", parameters=parameters)
    result = []
    for journey in journeys:
        events, quoted_rides = [], []
        for event in journey.events:
            if isinstance(event, NetworkRideEvent):
                trip_id, day, offset = identities[event.trip_id]
                trip = original.trips[trip_id]
                restored = replace(event, trip_id=trip_id, source_trip_id=trip.source_id,
                    service_date=day, feed_version=original.metadata.version,
                    departure_minute=event.departure_minute - offset,
                    arrival_minute=event.arrival_minute - offset)
                source_rows = network.free_scope.snapshot.rows_by_trip[trip_id]
                by_sequence = {row.sequence: row.source for row in source_rows}
                if (restored.departure_provenance is None or restored.arrival_provenance is None
                        or not restored.arrival_provenance.is_estimate
                        or restored.from_sequence not in by_sequence or restored.to_sequence not in by_sequence
                        or restored.departure_provenance != by_sequence[restored.from_sequence].departure_provenance
                        or restored.arrival_provenance != by_sequence[restored.to_sequence].arrival_provenance):
                    raise ValueError("practical result lost required clock provenance")
                quoted_rides.append(restored)
                events.append(PracticalRide(restored, _civil(anchor, event.departure_minute),
                    _civil(anchor, event.arrival_minute)))
            elif isinstance(event, NetworkStandardTransferEvent):
                link = event.standard
                events.append(PracticalTransfer(link.standard_minutes, link.margin_minutes,
                    link.margin_status, link.from_stop_id, link.to_stop_id,
                    _civil(anchor, event.departure_minute), _civil(anchor, event.arrival_minute),
                    link.source_uri, link.source_sha256))
            else:
                raise ValueError("unreviewed practical event type")
        quote = SendaiFureaiPassPolicy().quote(network.free_scope, replace(journey, events=tuple(quoted_rides)))
        result.append(PracticalJourney(CivilMinute(civil_date, Fraction(departure_minute)),
            _civil(anchor, journey.arrival_minute), tuple(events), quote, PROFILE, original.metadata.version))
    return tuple(result)
