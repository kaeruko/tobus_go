"""Read-only scheduled network input for the shared Python label core.

Not selected by either city's production runtime. The explicit trip scope and
directed, version-pinned walking links must be supplied by the city adapter.
Line nodes share an ordered stopping pattern, not one graph per vehicle trip.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
import math
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

import networkx as nx

from reviewed_walk_time import ReviewedWalkingLink
from transit_dataset import TransitDataset, TransitMode, TransitRoute, TransitStop, TransitStopTime, TransitTrip, namespace_id


@dataclass(frozen=True, slots=True)
class DirectedWalkLink:
    link: ReviewedWalkingLink
    from_feed_version: str
    to_feed_version: str

    def __post_init__(self):
        if not isinstance(self.link, ReviewedWalkingLink):
            raise ValueError("walking link requires directed reviewed evidence")
        for value in (self.from_feed_version, self.to_feed_version):
            if not isinstance(value, str) or not value or value.strip() != value:
                raise ValueError("walking link requires exact feed versions")


@dataclass(frozen=True, slots=True)
class NetworkCosts:
    boarding: float = 5.0
    bus_ride: float = 0.8
    rail_ride: float = 0.8
    walking_per_minute: float = 1.5

    def __post_init__(self):
        for name in ("boarding", "bus_ride", "rail_ride", "walking_per_minute"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"network cost must be positive and finite: {name}")


class _Attributes(dict):
    """NetworkX attribute dictionary sealed after network construction."""
    sealed = False

    def _check(self):
        if self.sealed:
            raise TypeError("network snapshot attributes are read-only")

    def __setitem__(self, key, value):
        self._check()
        return super().__setitem__(key, value)

    def __delitem__(self, key):
        self._check()
        return super().__delitem__(key)

    def update(self, *args, **kwargs):
        self._check()
        return super().update(*args, **kwargs)

    def clear(self):
        self._check()
        return super().clear()

    def pop(self, *args):
        self._check()
        return super().pop(*args)

    def popitem(self):
        self._check()
        return super().popitem()

    def setdefault(self, *args):
        self._check()
        return super().setdefault(*args)

    def __ior__(self, other):
        self.update(other)
        return self


class _Graph(nx.DiGraph):
    node_attr_dict_factory = _Attributes
    edge_attr_dict_factory = _Attributes
    graph_attr_dict_factory = _Attributes


@dataclass(frozen=True, slots=True)
class TransitNetworkSnapshot:
    graph: nx.DiGraph
    datasets: tuple[TransitDataset, ...]
    feed_versions: Mapping[str, str]
    stops: Mapping[str, TransitStop]
    routes: Mapping[str, TransitRoute]
    trips: Mapping[str, TransitTrip]
    rows_by_trip: Mapping[str, tuple[TransitStopTime, ...]]
    trip_patterns: Mapping[str, int]
    departures: Mapping[tuple, tuple[tuple[int, str, int], ...]]
    allowed_trip_ids: frozenset[str]
    costs: NetworkCosts


def physical_node(stop_id: str):
    return "phys", stop_id


def line_node(pattern: int, position: int):
    return "line", pattern, position


def _freeze_dataset(dataset):
    return replace(dataset, **{
        name: MappingProxyType(dict(getattr(dataset, name)))
        for name in ("stops", "routes", "trips", "calendars")
    }, stop_times=tuple(dataset.stop_times), service_exceptions=tuple(dataset.service_exceptions))


def build_transit_network(
    datasets: Sequence[TransitDataset], *, allowed_trip_ids: Iterable[str],
    walking_links: Iterable[DirectedWalkLink], costs: NetworkCosts,
) -> TransitNetworkSnapshot:
    if not datasets or not isinstance(costs, NetworkCosts):
        raise ValueError("datasets and explicit NetworkCosts are required")
    if allowed_trip_ids is None or isinstance(allowed_trip_ids, (str, bytes)):
        raise ValueError("explicit trip-ID scope is required")
    frozen = tuple(_freeze_dataset(dataset) for dataset in datasets)
    feeds, stops, routes, all_trips = {}, {}, {}, {}
    all_rows = defaultdict(list)
    for dataset in frozen:
        metadata = dataset.metadata
        if any(not isinstance(value, str) or not value for value in
               (metadata.feed_id, metadata.version, metadata.source_type, metadata.source_uri)):
            raise ValueError("network feed metadata requires immutable string identities")
        if metadata.feed_id in feeds:
            raise ValueError(f"duplicate feed id: {metadata.feed_id}")
        feeds[metadata.feed_id] = metadata.version
        for target, collection in ((stops, dataset.stops), (routes, dataset.routes),
                                   (all_trips, dataset.trips)):
            for key, record in collection.items():
                if key != namespace_id(metadata.feed_id, record.source_id):
                    raise ValueError(f"source/internal ID mismatch: {key}")
                if key in target:
                    raise ValueError(f"duplicate network ID: {key}")
                target[key] = record
        for stop in dataset.stops.values():
            if not isinstance(stop.name, str):
                raise ValueError(f"invalid stop name: {stop.id}")
            if (type(stop.lat) not in (int, float) or type(stop.lon) not in (int, float)
                    or not math.isfinite(stop.lat) or not math.isfinite(stop.lon)
                    or not -90 <= stop.lat <= 90 or not -180 <= stop.lon <= 180):
                raise ValueError(f"invalid stop coordinates: {stop.id}")
        exceptions = set()
        service_ids = set(dataset.calendars)
        for calendar in dataset.calendars.values():
            if (calendar.id != namespace_id(metadata.feed_id, calendar.source_id)
                    or type(calendar.start_date) is not date or type(calendar.end_date) is not date
                    or type(calendar.weekdays) is not tuple or len(calendar.weekdays) != 7
                    or any(type(value) is not bool for value in calendar.weekdays)):
                raise ValueError(f"invalid service calendar: {calendar.id}")
        for route in dataset.routes.values():
            if (not isinstance(route.mode, TransitMode)
                    or not isinstance(route.short_name, str) or not isinstance(route.long_name, str)):
                raise ValueError(f"invalid route mode: {route.id}")
        for exception in dataset.service_exceptions:
            if type(exception.day) is not date or type(exception.exception_type) is not int:
                raise ValueError(f"invalid service exception day: {exception.service_id}")
            key = exception.service_id, exception.day
            if key in exceptions:
                raise ValueError(f"duplicate service exception: {key}")
            exceptions.add(key)
            service_ids.add(exception.service_id)
        for trip in dataset.trips.values():
            if (not isinstance(trip.headsign, str)
                    or (trip.direction_id is not None and not isinstance(trip.direction_id, str))):
                raise ValueError(f"invalid immutable trip metadata: {trip.id}")
            if trip.service_id not in service_ids:
                raise ValueError(f"trip references unknown service: {trip.id}")
        for row in dataset.stop_times:
            all_rows[row.trip_id].append(row)
    allowed = frozenset(allowed_trip_ids)
    if not allowed <= all_trips.keys():
        raise ValueError(f"unknown allowed trip IDs: {sorted(allowed - all_trips.keys())!r}")
    # Validate source clocks, including dwell, before constructing any graph.
    validated = {}
    for trip_id in all_trips:
        rows = tuple(sorted(all_rows[trip_id], key=lambda row: row.sequence))
        if len(rows) < 2:
            raise ValueError(f"trip requires at least two timed stops: {trip_id}")
        previous_departure = None
        for index, row in enumerate(rows):
            if type(row.sequence) is not int or row.sequence < 0:
                raise ValueError(f"invalid sequence: {trip_id} {row.sequence!r}")
            for clock in (row.arrival_minute, row.departure_minute):
                if clock is not None and (type(clock) is not int or clock < 0):
                    raise ValueError(f"invalid service-day clock: {trip_id} sequence={row.sequence}")
            for minute, second in ((row.arrival_minute, row.arrival_service_seconds),
                                   (row.departure_minute, row.departure_service_seconds)):
                if second is not None:
                    if minute != second // 60 + (1 if second % 60 >= 30 else 0):
                        raise ValueError(f"source seconds/minutes mismatch: {trip_id} sequence={row.sequence}")
                    if second % 60:
                        raise ValueError(f"subminute source clock requires an exact-clock v2 contract: "
                                         f"{trip_id} sequence={row.sequence} seconds={second}")
            if index > 0 and row.arrival_minute is None:
                raise ValueError(f"missing arrival: {trip_id} sequence={row.sequence}")
            if index < len(rows) - 1 and row.departure_minute is None:
                raise ValueError(f"missing departure: {trip_id} sequence={row.sequence}")
            if (row.arrival_minute is not None and row.departure_minute is not None
                    and row.arrival_minute > row.departure_minute):
                raise ValueError(f"arrival after departure: {trip_id} sequence={row.sequence}")
            if previous_departure is not None and row.arrival_minute < previous_departure:
                raise ValueError(f"trip goes backwards: {trip_id} sequence={row.sequence}")
            previous_departure = row.departure_minute
        if trip_id in allowed:
            validated[trip_id] = rows
    graph = _Graph()
    for stop_id, stop in sorted(stops.items()):
        graph.add_node(physical_node(stop_id), stop_id=stop_id, lat=stop.lat, lon=stop.lon)
    patterns, trip_patterns, departures = {}, {}, defaultdict(list)
    for trip_id in sorted(allowed):
        trip = all_trips[trip_id]
        rows = validated[trip_id]
        route = routes[trip.route_id]
        key = trip.route_id, tuple((r.stop_id, r.pickup_type, r.drop_off_type) for r in rows)
        pattern = patterns.get(key)
        if pattern is None:
            pattern = len(patterns)
            patterns[key] = pattern
            for index, row in enumerate(rows):
                node = line_node(pattern, index)
                graph.add_node(node, mode=route.mode.value, stop_id=row.stop_id,
                               route_id=trip.route_id, position=index)
                if index < len(rows) - 1 and row.pickup_type == 0:
                    graph.add_edge(physical_node(row.stop_id), node, etype="board", w=costs.boarding)
                if index > 0 and row.drop_off_type == 0:
                    graph.add_edge(node, physical_node(row.stop_id), etype="alight", w=0.0)
                if index > 0:
                    weight = costs.bus_ride if route.mode.value == "bus" else costs.rail_ride
                    graph.add_edge(line_node(pattern, index - 1), node, etype="ride", w=weight)
        trip_patterns[trip_id] = pattern
        for index, row in enumerate(rows[:-1]):
            if row.pickup_type == 0:
                departures[(physical_node(row.stop_id), line_node(pattern, index))].append(
                    (row.departure_minute, trip_id, index))
    seen = set()
    for pinned in walking_links:
        if not isinstance(pinned, DirectedWalkLink):
            raise ValueError("only version-pinned directed reviewed links are accepted")
        link = pinned.link
        if link.from_stop_id not in stops or link.to_stop_id not in stops:
            raise ValueError("walking link references an unknown stop")
        pair = link.from_stop_id, link.to_stop_id
        if pair in seen:
            raise ValueError("duplicate directed walking link")
        seen.add(pair)
        if (feeds[link.from_stop_id.split(":", 1)[0]] != pinned.from_feed_version
                or feeds[link.to_stop_id.split(":", 1)[0]] != pinned.to_feed_version):
            raise ValueError("walking link feed version mismatch")
        a, b = stops[link.from_stop_id], stops[link.to_stop_id]
        dlat, dlon = math.radians(b.lat - a.lat), math.radians(b.lon - a.lon)
        hav = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(a.lat))
               * math.cos(math.radians(b.lat)) * math.sin(dlon / 2) ** 2)
        minimum = 2 * 6_371_000 * math.asin(min(1.0, math.sqrt(hav)))
        if link.walk_meters < minimum:
            raise ValueError("reviewed walking distance is shorter than endpoint distance")
        graph.add_edge(physical_node(pair[0]), physical_node(pair[1]), etype="walk",
                       meters=link.walk_meters, reviewed_walk_minutes=link.walk_minutes,
                       w=costs.walking_per_minute * link.walk_minutes, reviewed_link=pinned)
    nx.freeze(graph)
    graph.graph.sealed = True
    for attributes in graph.nodes.values():
        attributes.sealed = True
    for _, _, attributes in graph.edges(data=True):
        attributes.sealed = True
    return TransitNetworkSnapshot(
        graph, frozen, MappingProxyType(feeds), MappingProxyType(stops),
        MappingProxyType(routes), MappingProxyType({key: all_trips[key] for key in sorted(allowed)}),
        MappingProxyType(validated), MappingProxyType(trip_patterns),
        MappingProxyType({key: tuple(sorted(rows)) for key, rows in departures.items()}), allowed, costs,
    )
