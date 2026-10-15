"""Independent opt-in Sendai free-segment scope over the existing shared core.

No production registration, endpoint-only city inference, realtime or implicit
walking. Unknown segments are excluded before boarding patterns are constructed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fare_policy import FareQuote, SettlementType
from transit_adapters.sendai_subway import Evidence
from transit_dataset import TransitMode
from transit_network import NetworkCosts, build_transit_network
from transit_timetable_choices import NetworkRideEvent, search_network

FUREAI_SOURCE = "https://www.city.sendai.jp/servicekanri/kurashi/kenkotofukushi/shogai/shakaisanka/waribiki/fureai.html"
SUPPORTED = {"sendai_bus": TransitMode.BUS, "sendai_subway": TransitMode.RAIL}


@dataclass(frozen=True)
class FreeSegmentReview:
    """A review of the entire driven segment, not merely its endpoints.

    Outside and unknown paths must not receive this record. Sequence numbers
    identify occurrences on circular runs. Exact-version binding is mandatory.
    """
    trip_id: str
    feed_version: str
    from_sequence: int
    to_sequence: int
    from_stop_id: str
    to_stop_id: str
    operator_id: str
    service_kind: str
    entire_path_municipality: str
    evidence: Evidence


@dataclass(frozen=True)
class SendaiFureaiPassPolicy:
    """Only a pre-scoped reviewed network can issue this opt-in quote.

    This policy is intentionally absent from the public/UI registry until real
    data and independent routing gates pass. User entitlement is not inferred.
    """
    city_key: str = "sendai"
    policy_id: str = "sendai_fureai_pass"
    display_name: str = "仙台市 ふれあい乗車証（確認済み市内無料区間）"
    settlement_type: SettlementType = SettlementType.FREE_PASS
    source_uri: str = FUREAI_SOURCE

    def quote(self, network, journey):
        rides = [event for event in journey.events if isinstance(event, NetworkRideEvent)]
        if not rides:
            raise ValueError("free-pass quote requires at least one covered ride")
        for event in rides:
            if (event.trip_id not in network.allowed_trip_ids
                    or event.feed_version != network.snapshot.feed_versions[event.trip_id.split(':', 1)[0]]):
                raise ValueError("ride is not in the reviewed Sendai free scope")
            trip = network.snapshot.trips[event.trip_id]
            route = network.snapshot.routes[trip.route_id]
            if (event.service_date not in network.reviewed_days or event.route_id != trip.route_id
                    or event.mode != route.mode.value
                    or not any(trip.service_id in dataset.active_service_ids(event.service_date)
                               for dataset in network.snapshot.datasets)):
                raise ValueError("ride identity/calendar does not match the reviewed scope")
            rows = network.snapshot.rows_by_trip[event.trip_id]
            indices = {row.sequence: i for i, row in enumerate(rows)}
            if event.from_sequence not in indices or event.to_sequence not in indices:
                raise ValueError("ride occurrence is outside the reviewed scope")
            start, end = indices[event.from_sequence], indices[event.to_sequence]
            if (start >= end or event.stop_ids != tuple(row.stop_id for row in rows[start:end + 1])
                    or event.from_stop_id != rows[start].stop_id or event.to_stop_id != rows[end].stop_id):
                raise ValueError("ride stop sequence does not match the reviewed scope")
            if (event.departure_minute != rows[start].departure_minute
                    or event.arrival_minute != rows[end].arrival_minute):
                raise ValueError("ride clock does not match the reviewed source run")
        return FareQuote(None, 0, 0, self.policy_id, self.settlement_type)


@dataclass(frozen=True)
class SendaiFreeNetwork:
    snapshot: object
    allowed_trip_ids: frozenset[str]
    reviewed_days: frozenset[date]


def build_sendai_free_network(datasets, *, segment_reviews, reviewed_days,
                              walking_links, costs: NetworkCosts):
    """Conservative whole-run inclusion; partly reviewed runs remain excluded.

    This deliberately does not split a concrete vehicle into invented services.
    Valid in-city subrides on an otherwise unreviewed run are an explicit gap.
    """
    datasets = tuple(datasets)
    days = frozenset(reviewed_days)
    if not days or any(type(d) is not date for d in days):
        raise ValueError("explicit reviewed civil service dates are required")
    feeds = {d.metadata.feed_id: d for d in datasets}
    if len(feeds) != len(datasets) or not feeds or not set(feeds) <= set(SUPPORTED):
        raise ValueError("only distinct reviewed Sendai municipal feeds are supported; Miyagi is unsupported")
    for feed, dataset in feeds.items():
        if any(route.mode != SUPPORTED[feed] for route in dataset.routes.values()):
            raise ValueError("Sendai feed/mode mismatch")
    # Generic builder validates source clocks/calendars even on excluded trips.
    all_trips = {key: (dataset, trip) for dataset in datasets for key, trip in dataset.trips.items()}
    rows = {key: [] for key in all_trips}
    for dataset in datasets:
        for row in dataset.stop_times:
            rows[row.trip_id].append(row)
    rows = {key: sorted(value, key=lambda r: r.sequence) for key, value in rows.items()}
    reviewed = set()
    for review in segment_reviews:
        if not isinstance(review, FreeSegmentReview) or review.trip_id not in all_trips:
            raise ValueError("segment review references an unknown trip")
        dataset, trip = all_trips[review.trip_id]
        if (review.feed_version != dataset.metadata.version or review.operator_id != "SendaiMunicipal"
                or review.service_kind != "local" or review.entire_path_municipality != "04100"
                or not isinstance(review.evidence, Evidence)):
            raise ValueError("segment is unverified, outside Sendai or unsupported")
        pair = (review.from_sequence, review.to_sequence, review.from_stop_id, review.to_stop_id)
        source_pairs = {(a.sequence, b.sequence, a.stop_id, b.stop_id)
                        for a, b in zip(rows[trip.id], rows[trip.id][1:])}
        key = review.trip_id, pair
        if pair not in source_pairs or key in reviewed:
            raise ValueError("duplicate or non-adjacent concrete segment review")
        reviewed.add(key)
    allowed = frozenset(key for key, trip_rows in rows.items() if len(trip_rows) >= 2
        and all((key, (a.sequence, b.sequence, a.stop_id, b.stop_id)) in reviewed
                for a, b in zip(trip_rows, trip_rows[1:])))
    if not allowed:
        raise ValueError("no completely verified free municipal runs")
    snapshot = build_transit_network(datasets, allowed_trip_ids=allowed,
        walking_links=tuple(walking_links), costs=costs)
    return SendaiFreeNetwork(snapshot, allowed, days)


def search_sendai_free_network(network, origin_stop, destination_stop, *, service_date,
                               departure_minute, parameters, realtime=False):
    if realtime is not False:
        raise ValueError("Sendai common free search is static only; realtime is not accepted")
    if service_date not in network.reviewed_days:
        raise ValueError("service date is outside the explicitly reviewed Sendai scope")
    journeys = search_network(network.snapshot, origin_stop, destination_stop,
        service_date=service_date, departure_minute=departure_minute, mode="time",
        parameters=parameters)
    policy = SendaiFureaiPassPolicy()
    return tuple((journey, policy.quote(network, journey)) for journey in journeys)
