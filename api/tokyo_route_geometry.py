"""Draw Tokyo route legs by search edge type, without fabricating streets.

These stop-to-stop lines are schematic. Only explicit 'walk' and 'ride' edges
produce geometry; boarding, alighting, and waiting never invent a connection.
"""

import math

from route_engine import RouteContractError


def _node_point(graph, node):
    if isinstance(node, tuple) and len(node) == 2 and (
        node[0] == "phys" and str(node[1]).startswith("dest:")
    ):
        parts = str(node[1])[5:].split(",")
        if len(parts) != 2:
            raise RouteContractError(f"invalid virtual destination coordinate: {node!r}")
        try:
            point = [float(parts[0]), float(parts[1])]
        except ValueError as error:
            raise RouteContractError(
                f"invalid virtual destination coordinate: {node!r}"
            ) from error
    else:
        if node not in graph:
            raise RouteContractError(f"route geometry node is absent: {node!r}")
        data = graph.nodes[node]
        try:
            point = [float(data["lat"]), float(data["lon"])]
        except (KeyError, TypeError, ValueError) as error:
            raise RouteContractError(
                f"route geometry node has invalid coordinates: {node!r}"
            ) from error

    lat, lon = point
    if (not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180
            or (lat == 0 and lon == 0)):
        raise RouteContractError(
            f"route geometry node has unusable coordinates: {node!r}, {point!r}"
        )
    return point


def path_to_route_geometry(graph, path, *, virtual_dest_connections=None):
    """Return consecutive transit/walk polylines of the selected Tokyo path.

    'points' on the existing candidate remains unchanged for old clients.
    The final synthetic destination edge is only accepted when its exact
    connection is present in the explicit virtual destination input.
    """
    segments = []
    virtual_origins = {node for node, _, _ in (virtual_dest_connections or ())}
    for source, destination in zip(path, path[1:]):
        edge = graph.get_edge_data(source, destination)
        if edge is None:
            if (source in virtual_origins
                    and isinstance(destination, tuple)
                    and len(destination) == 2
                    and destination[0] == "phys"
                    and str(destination[1]).startswith("dest:")):
                edge = {"etype": "walk"}
            else:
                raise RouteContractError(
                    f"route geometry edge is absent: {source!r} -> {destination!r}"
                )

        etype = edge.get("etype")
        if etype in ("board", "alight", "xfer"):
            continue
        if etype == "walk":
            kind = "walk"
        elif etype == "ride":
            # The Tokyo graph stores the vehicle mode on its line node.
            # Some ride edges repeat that metadata; both must agree if set.
            edge_mode = edge.get("mode")
            node_mode = graph.nodes[source].get("mode")
            if (edge_mode is not None and node_mode is not None
                    and edge_mode != node_mode):
                raise RouteContractError(
                    f"route geometry ride mode disagrees with node: "
                    f"{source!r} edge={edge_mode!r} node={node_mode!r}"
                )
            kind = edge_mode if edge_mode is not None else node_mode
            if kind not in ("bus", "rail"):
                raise RouteContractError(
                    f"route geometry ride has invalid mode: "
                    f"{source!r} -> {destination!r}, mode={kind!r}"
                )
        else:
            raise RouteContractError(
                f"route geometry has unsupported edge type: "
                f"{source!r} -> {destination!r}, etype={etype!r}"
            )

        a, b = _node_point(graph, source), _node_point(graph, destination)
        if segments and segments[-1]["kind"] == kind and segments[-1]["points"][-1] == a:
            if a != b:
                segments[-1]["points"].append(b)
        else:
            segments.append({"kind": kind, "points": [a, b]})
    return segments
