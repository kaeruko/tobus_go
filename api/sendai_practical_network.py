"""Opt-in municipal scheduled model over the shared v2 network.

Civil requests explicitly materialize each reviewed service day. No alternate
search, pruning, candidate sorting, realtime or implicit calendar is introduced.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from fractions import Fraction
from types import MappingProxyType
from time import monotonic

from route_engine import RouteSearchLimitError

from sendai_shared_network import SendaiFureaiPassPolicy, SendaiFreeNetwork, build_sendai_free_network
from fare_policy import FareQuote
from transit_adapters.sendai_subway_practical import (
    PROFILE, GUIDE_URI, GUIDE_SHA256, PracticalSubwayDataset, _digest,
)
from transit_dataset import ServiceCalendar, ServiceException, TransitDataset
from transit_network import NetworkCosts, StandardTransferLink, build_transit_network
from transit_timetable_choices import (
    NetworkRideEvent, NetworkStandardTransferEvent, NetworkWalkEvent, NetworkSearchParameters, search_network,
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
    time_basis: str = "official_standard"
    path_description: str | None = None


@dataclass(frozen=True)
class PracticalWalk:
    source: NetworkWalkEvent
    departure: CivilMinute
    ready: CivilMinute


@dataclass(frozen=True)
class BusSubwayTransferReview:
    """Exact pole -> platform direction. Map evidence does not measure time.

    These are opt-in experimental planning assumptions until numeric official
    evidence or measurements have been independently reviewed. No default link.
    """
    link: StandardTransferLink
    valid_days: frozenset[date]
    bus_bay: str
    subway_entrance: str
    path_description: str
    map_evidence: tuple
    time_basis: str = "experimental_planning_assumption"

    def __post_init__(self):
        from urllib.parse import urlsplit
        from transit_adapters.sendai_subway import Evidence
        if (not isinstance(self.link, StandardTransferLink)
                or {self.link.from_stop_id.split(':')[0], self.link.to_stop_id.split(':')[0]}
                    != {"sendai_bus", "sendai_subway"}
                or not self.valid_days or any(type(d) is not date for d in self.valid_days)
                or not all(isinstance(x, str) and x.strip() for x in
                    (self.bus_bay, self.subway_entrance, self.path_description))
                or self.time_basis != "experimental_planning_assumption"
                or not self.map_evidence or any(not isinstance(e, Evidence) or
                    urlsplit(e.uri).hostname not in ("www.city.sendai.jp", "www.kotsu.city.sendai.jp")
                    for e in self.map_evidence)):
            raise ValueError("explicit directional municipal pole/entrance map and experimental time review required")


@dataclass(frozen=True)
class PracticalJourney:
    departure: CivilMinute
    arrival_estimate: CivilMinute
    events: tuple[PracticalRide | PracticalTransfer | PracticalWalk, ...]
    fare_quote: FareQuote
    profile: str
    input_version: str
    normal_timetable_only: bool = True
    exact_arrival_verified: bool = False
    actual_connection_guaranteed: bool = False
    experimental_margin_formally_adopted: bool = False
    planning_cost: float = 0.0  # Original v2 cost; not part of the practical wire schema.


@dataclass(frozen=True)
class PracticalFreeNetwork:
    source: PracticalSubwayDataset
    free_scope: SendaiFreeNetwork
    transfers: SendaiStandardTransferReview | None
    bus_transfers: tuple[BusSubwayTransferReview, ...] = ()
    walking_links: tuple = ()
    bus_reviewed_days: frozenset[date] = frozenset()


def build_practical_subway_network(source, *, segment_reviews, transfers, costs,
                                    bus_dataset=None, walking_links=(), bus_transfers=(),
                                    use_experimental_bus_transfers=False, bus_reviewed_days=frozenset()):
    if not isinstance(source, PracticalSubwayDataset) or source.dataset.metadata.clock_profile != PROFILE:
        raise ValueError("explicit practical subway dataset required")
    if transfers is not None and not isinstance(transfers, SendaiStandardTransferReview):
        raise ValueError("explicit standard transfer review required")
    days = frozenset(e.day for e in source.operating_days.entries if e.kind is not None)
    if transfers is not None and not transfers.valid_days <= days:
        raise ValueError("standard transfer days exceed reviewed operating-day table")
    walking_links = tuple(walking_links)
    datasets = (source.dataset,) if bus_dataset is None else (source.dataset, bus_dataset)
    if bus_dataset is not None and (bus_dataset.metadata.feed_id != "sendai_bus"
            or bus_dataset.metadata.clock_profile != "source"):
        raise ValueError("explicit static municipal bus dataset required")
    if bus_dataset is not None and (not bus_reviewed_days or not bus_reviewed_days <= days):
        raise ValueError("explicit finite bus operating-date review required")
    bus_transfers = tuple(bus_transfers)
    if bus_transfers and use_experimental_bus_transfers is not True:
        raise ValueError("experimental bus transfer model must be explicitly selected")
    versions = {d.metadata.feed_id: d.metadata.version for d in datasets}
    stops = {key for d in datasets for key in d.stops}
    pairs = set()
    for review in bus_transfers:
        if not isinstance(review, BusSubwayTransferReview) or not review.valid_days <= days:
            raise ValueError("bus transfer days exceed reviewed scope")
        link = review.link
        pair = link.from_stop_id, link.to_stop_id
        if pair in pairs or any(stop not in stops for stop in pair):
            raise ValueError("duplicate or unknown bus transfer direction")
        pairs.add(pair)
        if (link.from_feed_version != versions[link.from_stop_id.split(':')[0]]
                or link.to_feed_version != versions[link.to_stop_id.split(':')[0]]):
            raise ValueError("bus transfer feed version mismatch")
    scope = build_sendai_free_network(datasets, segment_reviews=segment_reviews,
        reviewed_days=days, walking_links=tuple(walking_links), costs=costs)
    return PracticalFreeNetwork(source, scope, transfers, bus_transfers, tuple(walking_links), frozenset(bus_reviewed_days))


def _civil(anchor, minute):
    offset = minute // 1440
    return CivilMinute(anchor + timedelta(days=int(offset)), minute - offset * 1440)


def _latest_source_minute(network):
    return max(r.arrival_minute or r.departure_minute or 0
               for d in network.free_scope.snapshot.datasets for r in d.stop_times)


def _practical_input_version(network):
    return _digest({
        "feeds": dict(network.free_scope.snapshot.feed_versions),
        "bus_reviewed_days": sorted(network.bus_reviewed_days),
        "transfers": [repr(r) for r in network.bus_transfers],
        "subway_transfer": repr(network.transfers),
        "walks": [repr(w) for w in network.walking_links],
        "allowed": sorted(network.free_scope.allowed_trip_ids)})


def _materialize_practical_days(network, civil_date, days, bus_only):
    """One request-local immutable network with unchanged service-day clocks."""
    originals = network.free_scope.snapshot.datasets
    anchor = civil_date - timedelta(days=1)
    identities, materialized, versions = {}, [], {}
    for original in originals:
        feed = original.metadata.feed_id
        if not (network.free_scope.allowed_trip_ids & original.trips.keys()):
            # A transport-mode filter can legitimately remove this feed. Do
            # not manufacture an invalid empty TransitDataset for that mode.
            continue
        trips, times, calendars, exceptions = {}, [], {}, []
        rows = {}
        for row in original.stop_times:
            rows.setdefault(row.trip_id, []).append(row)
        for day in days:
            offset = (day - anchor).days * 1440
            active = original.active_service_ids(day)
            for trip_id in sorted(network.free_scope.allowed_trip_ids & original.trips.keys()):
                trip = original.trips[trip_id]
                if trip.service_id not in active:
                    continue
                source_id = trip.source_id + "/service-" + day.isoformat()
                clone = feed + ":" + source_id
                # Exception-only GTFS services need not have a calendar row.
                service_source = trip.service_id.split(':', 1)[1] + "/service-" + day.isoformat()
                service_id = feed + ":" + service_source
                trips[clone] = replace(trip, id=clone, source_id=source_id, service_id=service_id)
                identities[clone] = original, trip_id, day, offset
                if service_id not in calendars:
                    calendars[service_id] = ServiceCalendar(service_id, service_source, (False,) * 7, anchor, anchor)
                    exceptions.append(ServiceException(service_id, anchor, 1))
                for row in rows[trip_id]:
                    times.append(replace(row, trip_id=clone,
                        model_day_offset_minutes=offset if original.metadata.clock_profile == PROFILE else 0,
                        arrival_minute=None if row.arrival_minute is None else row.arrival_minute + offset,
                        departure_minute=None if row.departure_minute is None else row.departure_minute + offset,
                        arrival_service_seconds=None if row.arrival_service_seconds is None else row.arrival_service_seconds + offset*60,
                        departure_service_seconds=None if row.departure_service_seconds is None else row.departure_service_seconds + offset*60))
        version = _digest({"input": original.metadata.version, "anchor": anchor, "days": days})
        versions[feed] = version
        materialized.append(TransitDataset(replace(original.metadata, version=version), original.stops,
            original.routes, MappingProxyType(trips), tuple(times), MappingProxyType(calendars), tuple(exceptions)))
    if not identities:
        return None, identities, anchor
    def reversion(link):
        endpoints = link.link if hasattr(link, "link") else link
        return replace(link, from_feed_version=versions[endpoints.from_stop_id.split(':')[0]],
                       to_feed_version=versions[endpoints.to_stop_id.split(':')[0]])
    links = list(() if network.transfers is None or "sendai_subway" not in versions
                 else network.transfers.links(versions["sendai_subway"]))
    links.extend(reversion(review.link) for review in network.bus_transfers
                 if {review.link.from_stop_id.split(':')[0], review.link.to_stop_id.split(':')[0]} <= versions.keys())
    walks = tuple(reversion(link) for link in network.walking_links)
    # Filtering allowed vehicle runs keeps the original station vertices and
    # reviewed walking paths. Removing a rail Dataset would incorrectly remove
    # its concourse access even when no train is boarded.
    allowed = {key for key,(original,tid,day,offset) in identities.items()
               if not bus_only or original.routes[original.trips[tid].route_id].mode.value == "bus"}
    snapshot = build_transit_network(tuple(materialized), allowed_trip_ids=allowed, walking_links=walks,
        costs=network.free_scope.snapshot.costs, standard_transfers=tuple(links))
    return snapshot, identities, anchor


def search_practical_subway(network, origin, destination, *, civil_date,
                             departure_minute, parameters, realtime=False, mode="time", bus_only=False,
                             _request_materializations=None, _request_deadline=None, _request_metadata=None):
    if realtime is not False:
        raise ValueError("practical subway search is static only")
    if mode not in ("time", "fewTransfers"):
        raise ValueError("practical profile supports time or fewTransfers")
    if type(bus_only) is not bool:
        raise ValueError("explicit boolean bus_only required")
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
    if origin not in network.free_scope.snapshot.stops or destination not in network.free_scope.snapshot.stops:
        raise ValueError("unknown practical origin/destination")
    originals = network.free_scope.snapshot.datasets
    finish = Fraction(departure_minute) + Fraction(str(parameters.max_travel_minutes))
    # Both values depend only on this immutable source network. Reuse the
    # SAME calculations within one coordinate request, never across requests,
    # instead of scanning every original stop-time row for each endpoint pair.
    metadata = {} if _request_metadata is None else _request_metadata.setdefault(id(network), {})
    if "latest_source_minute" not in metadata:
        metadata["latest_source_minute"] = _latest_source_minute(network)
    latest = metadata["latest_source_minute"]
    first = -1 if departure_minute <= latest - 1440 else 0
    last = int(finish // 1440)
    days = tuple(civil_date + timedelta(days=i) for i in range(first, last + 1))
    for day in days:
        source.operating_days.kind_on(day)
        if network.transfers is not None and day not in network.transfers.valid_days:
            raise ValueError(f"standard transfer is not reviewed for operating day {day}")
        if any(day not in r.valid_days for r in network.bus_transfers):
            raise ValueError(f"bus transfer is not reviewed for operating day {day}")
        for dataset in originals:
            if dataset.metadata.feed_id == "sendai_bus":
                # Finite approval dates are independent of the subway w/h table.
                # Every materialized bus day must be explicitly reviewed too.
                if day not in network.bus_reviewed_days:
                    raise ValueError(f"bus service date is outside reviewed scope: {day}")
    key = (id(network), civil_date, days, bus_only)
    if _request_materializations is None:
        prepared = _materialize_practical_days(network, civil_date, days, bus_only)
    else:
        if key not in _request_materializations:
            _request_materializations[key] = _materialize_practical_days(network, civil_date, days, bus_only)
        prepared = _request_materializations[key]
    snapshot, identities, anchor = prepared
    if not identities:
        return ()
    if _request_deadline is not None:
        remaining = _request_deadline - monotonic()
        if remaining <= 0:
            raise RouteSearchLimitError("Sendai coordinate request deadline exceeded during materialization",
                                       reason="time_limit")
        parameters = replace(parameters, time_limit_seconds=min(parameters.time_limit_seconds, remaining))
    start = 1440 + departure_minute
    journeys = search_network(snapshot, origin, destination, service_date=anchor,
        departure_minute=start, mode=mode, parameters=parameters)
    result = []
    for journey in journeys:
        events, quoted_rides = [], []
        for event in journey.events:
            if isinstance(event, NetworkRideEvent):
                original, trip_id, day, offset = identities[event.trip_id]
                trip = original.trips[trip_id]
                restored = replace(event, trip_id=trip_id, source_trip_id=trip.source_id,
                    service_date=day, feed_version=original.metadata.version,
                    departure_minute=event.departure_minute - offset,
                    arrival_minute=event.arrival_minute - offset)
                source_rows = network.free_scope.snapshot.rows_by_trip[trip_id]
                by_sequence = {row.sequence: row.source for row in source_rows}
                if original.metadata.clock_profile == PROFILE and (restored.departure_provenance is None or restored.arrival_provenance is None
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
                review = next((r for r in network.bus_transfers if
                    (r.link.from_stop_id, r.link.to_stop_id) == (link.from_stop_id, link.to_stop_id)), None)
                events.append(PracticalTransfer(link.standard_minutes, link.margin_minutes,
                    link.margin_status, link.from_stop_id, link.to_stop_id,
                    _civil(anchor, event.departure_minute), _civil(anchor, event.arrival_minute),
                    link.source_uri, link.source_sha256,
                    time_basis="official_standard" if review is None else review.time_basis,
                    path_description=None if review is None else review.path_description))
            elif isinstance(event, NetworkWalkEvent):
                events.append(PracticalWalk(event, _civil(anchor, event.departure_minute),
                    _civil(anchor, event.arrival_minute)))
            else:
                raise ValueError("unreviewed practical event type")
        quote = SendaiFureaiPassPolicy().quote(network.free_scope, replace(journey, events=tuple(quoted_rides)))
        if "input_version" not in metadata:
            metadata["input_version"] = _practical_input_version(network)
        result.append(PracticalJourney(CivilMinute(civil_date, Fraction(departure_minute)),
            _civil(anchor, journey.arrival_minute), tuple(events), quote, PROFILE,
            metadata["input_version"], planning_cost=journey.cost))
    return tuple(result)
