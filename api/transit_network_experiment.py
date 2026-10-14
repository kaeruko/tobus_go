"""Experimental, OFFLINE multi-feed scheduled rides + reviewed walking.

Not used by public Tokyo/Yokohama route runtimes. Never infer transfers from
coordinates or mark a trip free: an explicit, externally reviewed trip-ID
allowlist and version-pinned, directed walk links are mandatory.
"""
from __future__ import annotations

import bisect
import heapq
from dataclasses import dataclass
from datetime import date
from time import perf_counter
from typing import Iterable, Sequence

from reviewed_walk_time import ReviewedWalkingLink
from route_engine import RouteSearchLimitError
from transit_adapters.unified import TransitFeedSource
from transit_dataset import TransitDataset, TransitStopTime
from transit_engine import SearchLimits, SearchPreference, TransitLeg


@dataclass(frozen=True, slots=True)
class PinnedWalkLink:
    link: ReviewedWalkingLink
    from_feed_version: str
    to_feed_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.link, ReviewedWalkingLink):
            raise ValueError("transfer must be an explicitly reviewed walking link")
        if not isinstance(self.from_feed_version, str) or not self.from_feed_version:
            raise ValueError("source feed version is required")
        if not isinstance(self.to_feed_version, str) or not self.to_feed_version:
            raise ValueError("destination feed version is required")


@dataclass(frozen=True, slots=True)
class WalkLeg:
    from_stop_id: str
    to_stop_id: str
    departure_minute: int
    arrival_minute: int
    meters: int
    official_evidence_url: str


@dataclass(frozen=True, slots=True)
class ExperimentalJourney:
    departure_minute: int
    arrival_minute: int
    events: tuple[TransitLeg | WalkLeg, ...]

    @property
    def rides(self) -> int:
        return sum(isinstance(e, TransitLeg) for e in self.events)

    @property
    def transfers(self) -> int:
        return max(0, self.rides - 1)

    @property
    def walking_minutes(self) -> int:
        return sum(e.arrival_minute - e.departure_minute
                   for e in self.events if isinstance(e, WalkLeg))


class ExperimentalMultiFeedSearch:
    """Static prototype for exact stop IDs, fastest/fewest only.

    This deliberately does not claim Tokyo comfort-mode, realtime, top-K,
    accessibility or production fares. Search one GTFS service day, including
    24:xx times belonging to that service day. No automatic station walking.
    """

    @classmethod
    def from_sources(
        cls,
        sources: Sequence[TransitFeedSource],
        *,
        allowed_trip_ids: Iterable[str],
        walking_links: Iterable[PinnedWalkLink] = (),
    ) -> ExperimentalMultiFeedSearch:
        if not sources:
            raise ValueError("at least one transit source is required")
        return cls(
            tuple(source.load() for source in sources),
            allowed_trip_ids=allowed_trip_ids,
            walking_links=walking_links,
        )

    def __init__(
        self,
        datasets: Sequence[TransitDataset],
        *,
        allowed_trip_ids: Iterable[str],
        walking_links: Iterable[PinnedWalkLink] = (),
    ) -> None:
        if not datasets:
            raise ValueError("at least one dataset is required")
        self.datasets = tuple(datasets)
        feeds: dict[str, TransitDataset] = {}
        stops = {}
        trips = {}
        routes = {}
        stop_times: dict[str, list[TransitStopTime]] = {}
        for dataset in self.datasets:
            feed_id = dataset.metadata.feed_id
            if feed_id in feeds:
                raise ValueError(f"duplicate feed id: {feed_id}")
            feeds[feed_id] = dataset
            for name, current, incoming in (
                ("stop", stops, dataset.stops),
                ("trip", trips, dataset.trips),
                ("route", routes, dataset.routes),
            ):
                collision = set(current).intersection(incoming)
                if collision:
                    raise ValueError(f"duplicate {name} id: {sorted(collision)[0]}")
                current.update(incoming)
            for row in dataset.stop_times:
                stop_times.setdefault(row.trip_id, []).append(row)

        if allowed_trip_ids is None:
            raise ValueError("an explicit reviewed trip allowlist is required")
        self.allowed_trip_ids = frozenset(allowed_trip_ids)
        if not self.allowed_trip_ids.issubset(trips):
            raise ValueError("trip allowlist contains unknown trip ID")
        self.feeds = feeds
        self.stops = stops
        self.trips = trips
        self.routes = routes
        self.rows_by_trip: dict[str, tuple[TransitStopTime, ...]] = {}
        departures: dict[str, list[tuple[int, str, int]]] = {}

        for trip_id in sorted(self.allowed_trip_ids):
            rows = tuple(sorted(stop_times[trip_id], key=lambda s: s.sequence))
            if len(rows) < 2:
                raise ValueError(f"allowed trip lacks two stops: {trip_id}")
            last_sequence = -1
            last_clock = -1
            for index, row in enumerate(rows):
                if row.sequence <= last_sequence:
                    raise ValueError(f"duplicate/out-of-order stop sequence: {trip_id}")
                event_time = (row.departure_minute if row.departure_minute is not None
                              else row.arrival_minute)
                if event_time is not None and event_time < last_clock:
                    raise ValueError(f"trip goes backwards in time: {trip_id}")
                last_sequence = row.sequence
                if event_time is not None:
                    last_clock = event_time
                if index < len(rows) - 1 and row.departure_minute is not None:
                    departures.setdefault(row.stop_id, []).append(
                        (row.departure_minute, trip_id, index)
                    )
            self.rows_by_trip[trip_id] = rows
        self.departures = {stop: tuple(sorted(items))
                           for stop, items in departures.items()}

        links_by_from: dict[str, list[PinnedWalkLink]] = {}
        seen = set()
        for pinned in walking_links:
            if not isinstance(pinned, PinnedWalkLink):
                raise ValueError("walking links must be version-pinned and reviewed")
            link = pinned.link
            if link.from_stop_id not in stops or link.to_stop_id not in stops:
                raise ValueError("walking link refers to an unknown stop")
            source_feed = link.from_stop_id.split(":", 1)[0]
            dest_feed = link.to_stop_id.split(":", 1)[0]
            if (source_feed not in feeds or dest_feed not in feeds
                    or pinned.from_feed_version != feeds[source_feed].metadata.version
                    or pinned.to_feed_version != feeds[dest_feed].metadata.version):
                raise ValueError("walking link feed version mismatch")
            pair = (link.from_stop_id, link.to_stop_id)
            if pair in seen:
                raise ValueError("duplicate directed walking link")
            seen.add(pair)
            links_by_from.setdefault(link.from_stop_id, []).append(pinned)
        self.links_by_from = {s: tuple(sorted(p, key=lambda x: x.link.to_stop_id))
                              for s, p in links_by_from.items()}

    def search(
        self,
        origin_stop_id: str,
        destination_stop_id: str,
        *,
        service_date: date,
        departure_minute: int,
        preference: SearchPreference = "fastest",
        max_rides: int = 6,
        limits: SearchLimits | None = None,
    ) -> ExperimentalJourney | None:
        if origin_stop_id not in self.stops or destination_stop_id not in self.stops:
            raise KeyError("unknown origin or destination stop")
        if type(service_date) is not date:
            raise ValueError("service_date must be a date")
        if type(departure_minute) is not int or departure_minute < 0:
            raise ValueError("departure_minute must be a nonnegative int")
        if preference not in ("fastest", "fewest_transfers"):
            raise ValueError("experiment supports fastest/fewest_transfers only")
        if type(max_rides) is not int or max_rides < 1:
            raise ValueError("max_rides must be a positive int")
        limits = limits or SearchLimits()

        active: set[str] = set()
        for dataset in self.datasets:
            active.update(dataset.active_service_ids(service_date))
        starts = (origin_stop_id, 0)
        best = {starts: departure_minute}
        parent: dict[tuple[str, int], tuple[tuple[str, int], TransitLeg | WalkLeg]] = {}
        serial = 0
        generated = 0
        visited = 0
        started_at = perf_counter()
        def rank(t: int, rides: int) -> tuple[int, int]:
            return (t, rides) if preference == "fastest" else (rides, t)
        queue = [(rank(departure_minute, 0), serial, starts)]
        while queue:
            if perf_counter() - started_at > limits.time_limit_seconds:
                raise RouteSearchLimitError("experimental search time limit exceeded")
            if len(queue) > limits.max_queue_size:
                raise RouteSearchLimitError("experimental search queue limit exceeded")
            queued_priority, _, state = heapq.heappop(queue)
            current = best[state]
            if rank(current, state[1]) != queued_priority:
                continue
            visited += 1
            if visited > limits.max_visited_states:
                raise RouteSearchLimitError("experimental search state limit exceeded")
            stop_id, used = state
            if stop_id == destination_stop_id:
                events = []
                while state in parent:
                    prev, event = parent[state]
                    events.append(event)
                    state = prev
                events.reverse()
                return ExperimentalJourney(
                    departure_minute, current, tuple(events)
                )

            def offer(to_stop: str, next_rides: int, arrival: int,
                      event: TransitLeg | WalkLeg) -> None:
                nonlocal serial, generated
                key = (to_stop, next_rides)
                if key in best and best[key] <= arrival:
                    return
                best[key] = arrival
                parent[key] = ((stop_id, used), event)
                serial += 1
                generated += 1
                if generated > limits.max_generated_labels:
                    raise RouteSearchLimitError("experimental search labels limit exceeded")
                heapq.heappush(queue, (rank(arrival, next_rides), serial, key))
                if len(queue) > limits.max_queue_size:
                    raise RouteSearchLimitError("experimental search queue limit exceeded")

            # Explicitly validated, direction-specific walking: no reverse
            # edge, geospatial guess, unknown station entrance, or implicit fare.
            for pinned in self.links_by_from.get(stop_id, ()):
                walk = pinned.link
                arrived = current + walk.walk_minutes
                offer(walk.to_stop_id, used, arrived, WalkLeg(
                    stop_id, walk.to_stop_id, current, arrived,
                    walk.walk_meters, walk.official_evidence_url,
                ))

            if used >= max_rides:
                continue
            departures = self.departures.get(stop_id, ())
            start = bisect.bisect_left(departures, (current, "", -1))
            for leave, trip_id, index in departures[start:]:
                trip = self.trips[trip_id]
                if trip.service_id not in active:
                    continue
                rows = self.rows_by_trip[trip_id]
                traversed = [stop_id]
                for row in rows[index + 1:]:
                    traversed.append(row.stop_id)
                    if row.arrival_minute is None or row.arrival_minute < leave:
                        continue
                    event = TransitLeg(
                        trip_id=trip_id, route_id=trip.route_id,
                        mode=self.routes[trip.route_id].mode,
                        from_stop_id=stop_id, to_stop_id=row.stop_id,
                        departure_minute=leave, arrival_minute=row.arrival_minute,
                        stop_ids=tuple(traversed),
                    )
                    offer(row.stop_id, used + 1, row.arrival_minute, event)
        return None
