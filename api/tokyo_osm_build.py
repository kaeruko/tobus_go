"""Build Tokyo's offline ground walking network from one pinned Geofabrik PBF.

Install osmium==4.3.2 in the build environment. The API has no osmium dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle
import re
import tempfile
import zlib
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from tokyo_osm_walk import (
    CREDIT,
    CREDIT_URL,
    RECORD,
    SCHEMA,
    Anchor,
    cell,
    cells_between,
    inside,
    routes,
    snap,
    unpack_tile,
    walk_edge,
)

_ALLOWED = {"yes", "designated", "permissive", "official"}
_ROADS = {
    "pedestrian",
    "footway",
    "path",
    "steps",
    "living_street",
    "residential",
    "unclassified",
    "service",
    "track",
    "tertiary",
    "secondary",
    "primary",
    "tertiary_link",
    "secondary_link",
    "primary_link",
}
_BLOCKED = {
    "motorway",
    "motorway_link",
    "construction",
    "proposed",
    "abandoned",
    "razed",
    "platform",
    "raceway",
    "bus_guideway",
    "corridor",
    "elevator",
}


def _access(tags):
    if any(
        k in tags
        for k in (
            "access:conditional",
            "foot:conditional",
            "opening_hours",
            "oneway:foot:conditional",
            "foot:forward:conditional",
            "foot:backward:conditional",
        )
    ):
        return False
    return tags.get("foot", tags.get("access", "yes")) in _ALLOWED


def way_profile(tags):
    road = tags.get("highway")
    if (
        not road
        or road in _BLOCKED
        or (road not in _ROADS and tags.get("foot") not in _ALLOWED)
        or not _access(tags)
        or tags.get("area") == "yes"
        or tags.get("indoor", "no") != "no"
        or tags.get("railway") == "platform"
        or tags.get("motorroad") == "yes"
        or tags.get("crossing") == "no"
    ):
        return None
    if any(
        tags.get(k) == "separate"
        for k in ("sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both")
    ):
        return None
    direction = {"yes": 1, "1": 1, "true": 1, "-1": 2, "no": 3, "0": 3}.get(
        tags.get("oneway:foot", "no"), 0
    )
    # Escalator direction and pedestrian one-way restrictions both apply.
    direction &= {"no": 3, "both": 3, "forward": 1, "backward": 2}.get(
        tags.get("conveying", "no"), 0
    )
    if tags.get("foot:forward", "yes") not in _ALLOWED:
        direction &= 2
    if tags.get("foot:backward", "yes") not in _ALLOWED:
        direction &= 1
    if not direction:
        return None
    ground = (
        tags.get("bridge", "no") == "no"
        and tags.get("tunnel", "no") == "no"
        and tags.get("layer", "0") == "0"
        and tags.get("level", "0") == "0"
        and tags.get("location", "surface")
        not in {"underground", "overground", "overhead"}
    )
    return direction, ground


def _blocked_node(tags):
    return (
        not _access(tags)
        or tags.get("locked") == "yes"
        or tags.get("crossing") == "no"
        or tags.get("barrier", "no")
        not in {"no", "bollard", "cycle_barrier", "kerb", "entrance"}
    )


def load_config(path):
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {"pbf", "source_url", "source_date", "sha256", "bounds"}
    if set(config) - required - {"station_nodes"} or not required <= set(config):
        raise ValueError(f"invalid OSM config keys in {path}: {sorted(config)}")
    if (
        not isinstance(config["source_url"], str)
        or not urlsplit(config["source_url"]).hostname
        or urlsplit(config["source_url"]).scheme != "https"
    ):
        raise ValueError("OSM source_url must be an HTTPS URL")
    date.fromisoformat(config["source_date"])
    if not re.fullmatch(r"[0-9a-f]{64}", config["sha256"]):
        raise ValueError("OSM sha256 must be 64 lower-case hexadecimal digits")
    bounds = config["bounds"]
    if (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or any(type(n) not in {float, int} or not math.isfinite(n) for n in bounds)
    ):
        raise ValueError(
            "OSM bounds require finite west, south, east, north coordinates"
        )
    w, s, e, n = bounds
    if not -180 <= w < e <= 180 or not -85 <= s < n <= 85:
        raise ValueError(f"invalid OSM bounds: {bounds}")
    stations = config.get("station_nodes", {})
    if not isinstance(stations, dict):
        raise TypeError("OSM station_nodes must map station IDs to reviewed nodes")
    for sid, review in stations.items():
        if (
            not sid.startswith("odpt.Station:")
            or not isinstance(review, dict)
            or set(review) != {"node", "evidence_url"}
            or type(review["node"]) is not int
            or review["node"] <= 0
            or not isinstance(review["evidence_url"], str)
            or not urlsplit(review["evidence_url"]).hostname
            or urlsplit(review["evidence_url"]).scheme != "https"
        ):
            raise ValueError(f"invalid reviewed OSM station node: {sid!r}")
    config["pbf"] = (path.parent / config["pbf"]).resolve()
    with config["pbf"].open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != config["sha256"]:
        raise ValueError(
            f"OSM SHA-256 mismatch for {config['pbf']}: expected {config['sha256']}, found {digest}"
        )
    return config


def compile_network(config):
    import osmium

    path, bounds = config["pbf"], config["bounds"]
    blocked_nodes, blocked_ways = set(), set()
    for relation in osmium.FileProcessor(path, osmium.osm.RELATION).with_filter(
        osmium.filter.KeyFilter("restriction:foot", "restriction:foot:conditional")
    ):
        for member in relation.members:
            if member.role == "via":
                if member.type == "n":
                    blocked_nodes.add(member.ref)
                elif member.type == "w":
                    blocked_ways.add(member.ref)
    for node in osmium.FileProcessor(path, osmium.osm.NODE).with_filter(
        osmium.filter.KeyFilter(
            "barrier",
            "foot",
            "access",
            "locked",
            "crossing",
            "foot:conditional",
            "access:conditional",
            "opening_hours",
        )
    ):
        if inside(bounds, (node.location.lat, node.location.lon)) and _blocked_node(
            node.tags
        ):
            blocked_nodes.add(node.id)

    # Merge coincident links only when their OSM endpoints are the same IDs.
    segments = {}
    ways = (
        osmium.FileProcessor(path, osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.KeyFilter("highway"))
    )
    for way in ways:
        if way.id in blocked_ways:
            continue
        profile = way_profile(way.tags)
        if profile is None:
            continue
        previous = None
        for node in way.nodes:
            if not node.location.valid():
                raise ValueError(
                    f"missing OSM location on way {way.id} at node {node.ref}"
                )
            pos = node.location.lat, node.location.lon
            current = (
                (node.ref, pos)
                if inside(bounds, pos) and node.ref not in blocked_nodes
                else None
            )
            if (
                previous
                and current
                and previous[0] != current[0]
                and previous[1] != pos
            ):
                (u, a), (v, b) = sorted((previous, current))
                direction, ground = profile
                if previous[0] != u:
                    direction = ((direction & 1) << 1) | ((direction & 2) >> 1)
                old = segments.get((u, v))
                if old:
                    direction |= old[2]
                    ground |= old[3]
                segments[u, v] = a, b, direction, ground
            previous = current
    if not segments:
        raise ValueError(f"no eligible pedestrian segments inside OSM bounds {bounds}")

    bins = defaultdict(bytearray)
    requested = {r["node"] for r in config.get("station_nodes", {}).values()}
    station_positions = {}
    for (u, v), (a, b, direction, ground) in segments.items():
        if u in requested:
            station_positions[u] = a
        if v in requested:
            station_positions[v] = b
        row = RECORD.pack(u, v, *(round(c * 1e7) for c in (*a, *b)), direction, ground)
        for key in cells_between(a, b):
            bins[key].extend(row)
    missing = requested - station_positions.keys()
    if missing:
        raise ValueError(
            f"reviewed OSM station nodes missing from walk network: {sorted(missing)}"
        )
    return {
        "schema": SCHEMA,
        "bounds": bounds,
        "source": {
            **{k: config[k] for k in ("source_url", "source_date", "sha256")},
            "attribution": CREDIT,
            "license": "ODbL-1.0",
            "license_url": CREDIT_URL,
        },
        "tiles": {k: zlib.compress(v) for k, v in bins.items()},
        "station_nodes": config.get("station_nodes", {}),
        "station_positions": station_positions,
    }


def bind_network(graph, network, walk_radius):
    from toei_engine import MAX_WALK_SEG_M

    if "tokyo_osm_walk" in graph.graph:
        raise ValueError("Tokyo transit graph already has an OSM walking network")
    if not 0 < walk_radius <= MAX_WALK_SEG_M:
        raise ValueError(f"invalid walk radius {walk_radius}")
    anchors, stop_cells = {}, defaultdict(list)
    for sid in network["station_nodes"]:
        if ("phys", sid) not in graph:
            raise ValueError(f"reviewed OSM station missing from transit graph: {sid}")
    for node, data in graph.nodes(data=True):
        if node[0] != "phys":
            continue
        if node[1] in network["station_nodes"]:
            osm_id = network["station_nodes"][node[1]]["node"]
            point = network["station_positions"][osm_id]
            seg = next(
                s
                for s in unpack_tile(network["tiles"][cell(point)])[0]
                if osm_id in (s.u, s.v)
            )
            anchor = Anchor(point, point, 0, seg, float(seg.v == osm_id))
        elif node[1].startswith("odpt.BusstopPole:"):
            anchor = snap(network, (data["lat"], data["lon"]))
        else:
            continue
        if anchor:
            anchors[node] = anchor
            stop_cells[cell(anchor.point)].append(node)

    remove, replace = [], []
    for source, edges in graph.adjacency():
        targets = {}
        for target, edge in edges.items():
            if (
                edge.get("etype") != "walk"
                or "reviewed_walk_minutes" in edge
                or edge.get("walking_connection_verified")
            ):
                continue
            if source in anchors and target in anchors:
                targets[target] = anchors[target]
            else:
                remove.append((source, target))
        if targets:
            limits = {
                target: (
                    MAX_WALK_SEG_M
                    if edges[target].get("official_connection")
                    or edges[target].get("connecting_station")
                    else walk_radius
                )
                for target in targets
            }
            paths = routes(network, anchors[source], targets, max(limits.values()))
            for target in targets:
                if target in paths and paths[target][0] <= limits[target]:
                    updated = walk_edge(paths[target])
                    if edges[target].get("official_connection"):
                        updated.update(
                            transfer_time_basis="osm_ground_network",
                            transfer_time_confidence="network_estimate",
                            physical_walk_distance_known=True,
                        )
                    replace.append((source, target, updated))
                else:
                    remove.append((source, target))
    graph.remove_edges_from(remove)
    graph.add_edges_from(replace)
    graph.graph["tokyo_osm_walk"] = dict(
        network, anchors=anchors, stop_cells=dict(stop_cells)
    )
    return {
        "matched_stops": len(anchors),
        "routed_walks": len(replace),
        "excluded_walks": len(remove),
    }


def write_prebuilt(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
    try:
        with temp.open("wb") as stream:
            pickle.dump(data, stream, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--base",
        type=Path,
        required=True,
        help="trusted transit prebuilt produced by this version",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.base.resolve() == args.output.resolve():
        parser.error("--output must differ from --base")
    network = compile_network(load_config(args.config))
    with args.base.open("rb") as stream:
        data = pickle.load(stream)
    summary = bind_network(data["G"], network, data["WALK_RAD"])
    write_prebuilt(data, args.output)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
