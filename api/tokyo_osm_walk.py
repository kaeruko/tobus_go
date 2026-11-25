"""Local, directed pedestrian routing on a versioned, offline OSM extract."""

from __future__ import annotations

import heapq
import math
import os
import struct
import zlib
from collections import ChainMap, defaultdict
from dataclasses import dataclass
from functools import lru_cache

import networkx as nx
from walking_access import haversine_m

SCHEMA = "tokyo_osm_walk/v1"
CELL = 0.002
SNAP_M = 15.0
CREDIT = "© OpenStreetMap contributors"
CREDIT_URL = "https://www.openstreetmap.org/copyright"
# OSM IDs, E7 latitude/longitude of each endpoint, direction bits, ground access.
RECORD = struct.Struct("<qqiiiiBB")


def network_required():
    value = os.getenv("REQUIRE_TOKYO_OSM_WALK", "0")
    if value not in {"0", "1"}:
        raise ValueError(f"REQUIRE_TOKYO_OSM_WALK must be 0 or 1, got {value!r}")
    return value == "1" or "TOKYO_OSM_WALK_CONFIG" in os.environ


def loaded_network(graph, *, required=False):
    metadata = getattr(graph, "graph", {})
    if "tokyo_osm_walk" not in metadata:
        if required:
            raise ValueError(
                "prebuilt transit graph has no required OSM walking network"
            )
        return None
    net = metadata["tokyo_osm_walk"]
    if (
        not isinstance(net, dict)
        or net.get("schema") != SCHEMA
        or not {"bounds", "source", "tiles", "anchors", "stop_cells"} <= net.keys()
    ):
        raise ValueError("invalid or incompatible prebuilt OSM walking network")
    return net


def cell(point):
    return math.floor(point[0] / CELL), math.floor(point[1] / CELL)


def cells_between(a, b):
    y0, x0 = cell(a)
    y1, x1 = cell(b)
    for y in range(min(y0, y1), max(y0, y1) + 1):
        for x in range(min(x0, x1), max(x0, x1) + 1):
            yield y, x


def nearby_cells(point, meters):
    dy = meters / 110_000
    dx = dy / math.cos(math.radians(abs(point[0]) + dy))
    return cells_between((point[0] - dy, point[1] - dx), (point[0] + dy, point[1] + dx))


def inside(bounds, point):
    west, south, east, north = bounds
    return south <= point[0] <= north and west <= point[1] <= east


@dataclass(frozen=True, slots=True)
class Segment:
    u: int
    v: int
    a: tuple
    b: tuple
    directions: int
    ground: bool
    meters: float


@lru_cache(maxsize=192)
def unpack_tile(payload):
    segments = []
    adjacency = defaultdict(list)
    for u, v, ay, ax, by, bx, direction, ground in RECORD.iter_unpack(
        zlib.decompress(payload)
    ):
        a, b = (ay / 1e7, ax / 1e7), (by / 1e7, bx / 1e7)
        length = haversine_m(*a, *b)
        segment = Segment(u, v, a, b, direction, bool(ground), length)
        segments.append(segment)
        adjacency[u].append((v, b, length, direction))
        adjacency[v].append(
            (u, a, length, ((direction & 1) << 1) | ((direction & 2) >> 1))
        )
    return segments, adjacency


@dataclass(frozen=True, slots=True)
class Anchor:
    point: tuple
    foot: tuple
    offset: float
    segment: Segment
    fraction: float

    def ends(self, reverse):
        seg = self.segment
        # At a mapped intersection all incident legal ways are available.
        if self.fraction == 0:
            yield seg.u, seg.a, self.offset
        elif self.fraction == 1:
            yield seg.v, seg.b, self.offset
        else:
            if seg.directions & (1 if reverse else 2):
                yield seg.u, seg.a, self.offset + self.fraction * seg.meters
            if seg.directions & (2 if reverse else 1):
                yield seg.v, seg.b, self.offset + (1 - self.fraction) * seg.meters


def project(point, segment):
    lat, lon = point
    a, b = segment.a, segment.b
    scale = math.cos(math.radians(lat))
    dx, dy = (b[1] - a[1]) * scale, b[0] - a[0]
    fraction = ((lon - a[1]) * scale * dx + (lat - a[0]) * dy) / (dx * dx + dy * dy)
    fraction = min(1.0, max(0.0, fraction))
    foot = (a[0] + fraction * dy, a[1] + fraction * (b[1] - a[1]))
    return Anchor(point, foot, haversine_m(*point, *foot), segment, fraction)


def _snap_identity(anchor):
    if anchor.fraction == 0:
        return (anchor.segment.u,)
    if anchor.fraction == 1:
        return (anchor.segment.v,)
    return anchor.segment.u, anchor.segment.v


def snap(network, point):
    if not inside(network["bounds"], point):
        return None
    best = {}
    for key in nearby_cells(point, SNAP_M):
        payload = network["tiles"].get(key)
        if payload is None:
            continue
        for seg in unpack_tile(payload)[0]:
            if seg.ground:
                anchor = project(point, seg)
                if anchor.offset <= SNAP_M:
                    best[_snap_identity(anchor)] = anchor
    ranked = sorted(best.values(), key=lambda a: (a.offset, a.segment.u, a.segment.v))
    if not ranked or (len(ranked) > 1 and ranked[1].offset - ranked[0].offset <= 0.01):
        return None
    return ranked[0]


def _unique_points(points):
    result = []
    for point in points:
        if not result or point != result[-1]:
            result.append(point)
    if len(result) == 1:
        result.append(result[0])
    return tuple(result)


def routes(network, start, targets, limit, *, reverse=False):
    """One cutoff Dijkstra for all targets. Reversing answers stop-to-coordinate."""
    if not targets:
        return {}
    bit = 2 if reverse else 1
    opposite_bit = 1 if reverse else 2
    queue, distance, via, positions = [], {}, {}, {}

    def offer(node, pos, total, parent):
        if total <= limit and total < distance.get(node, math.inf):
            distance[node], positions[node], via[node] = total, pos, parent
            heapq.heappush(queue, (total, node))

    for node, pos, length in start.ends(reverse):
        offer(node, pos, length, None)
    while queue:
        total, node = heapq.heappop(queue)
        if total != distance[node]:
            continue
        adjacent = unpack_tile(network["tiles"][cell(positions[node])])[1][node]
        for neighbor, pos, length, directions in adjacent:
            if directions & bit:
                offer(neighbor, pos, total + length, node)

    result = {}
    for key, end in targets.items():
        best = math.inf
        path = None
        if _snap_identity(start) == _snap_identity(end) and start.point == end.point:
            best, path = 0.0, (start.point, end.point)
        elif (start.segment.u, start.segment.v) == (end.segment.u, end.segment.v):
            delta = end.fraction - start.fraction
            if delta == 0 or start.segment.directions & (
                bit if delta > 0 else opposite_bit
            ):
                best = start.offset + abs(delta) * start.segment.meters + end.offset
                path = (start.point, start.foot, end.foot, end.point)
        for node, _, tail in end.ends(not reverse):
            total = distance.get(node, math.inf) + tail
            if total > limit or total >= best:
                continue
            best = total
            chain = []
            while node is not None:
                chain.append(positions[node])
                node = via[node]
            path = (start.point, start.foot, *reversed(chain), end.foot, end.point)
        if best <= limit:
            result[key] = best, _unique_points(reversed(path) if reverse else path)
    return result


def coordinate_routes(network, graph, point, limit, *, reverse=False):
    if not inside(network["bounds"], point):
        return {}, "outside_coverage"
    start = snap(network, point)
    if start is None:
        return {}, "no_ground_match"
    targets = {}
    for grid in nearby_cells(point, limit):
        for node in network["stop_cells"].get(grid, ()):
            anchor = network["anchors"][node]
            if node in graph and haversine_m(*point, *anchor.point) <= limit:
                targets[node] = anchor
    if not targets:
        return {}, "no_scoped_stop_in_range"
    found = routes(network, start, targets, limit, reverse=reverse)
    return found, "connected" if found else "no_walkable_connection"


def walk_edge(route):
    from toei_engine import WALK_COST, WALK_SPEED_M_PER_MIN

    meters, points = route
    cost = WALK_COST * max(1.0, meters / WALK_SPEED_M_PER_MIN) if meters else 0.0
    return {"etype": "walk", "meters": meters, "w": cost, "osm_points": points}


def endpoint_graph(graph, origin, destination, access, egress):
    """Overlay only affected adjacency maps. The shared scoped graph stays immutable."""
    start, finish = ("phys", "osm:origin"), ("phys", "osm:destination")
    if start in graph or finish in graph:
        raise ValueError("reserved OSM query node already exists")
    view = nx.graphviews.generic_graph_view(graph)
    nodes = {
        start: {
            "lat": origin[0],
            "lon": origin[1],
            "name": "現在地",
            "name_en": "Current location",
        },
        finish: {
            "lat": destination[0],
            "lon": destination[1],
            "name": "目的地",
            "name_en": "Destination",
        },
    }
    succ, pred = {start: {}, finish: {}}, {start: {}, finish: {}}
    for node, route in access.items():
        edge = walk_edge(route)
        succ[start][node] = edge
        pred[node] = ChainMap({start: edge}, graph.pred[node])
    for node, route in egress.items():
        edge = walk_edge(route)
        pred[finish][node] = edge
        succ[node] = ChainMap({finish: edge}, graph.succ[node])
    view._node = ChainMap(nodes, graph._node)
    view._succ = ChainMap(succ, graph._succ)
    view._pred = ChainMap(pred, graph._pred)
    return view, start, finish
