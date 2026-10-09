"""User-visible Tokyo itineraries, independent of destination walk variants."""

from route_engine import RouteContractError


def _line_identity(graph, node):
    data = graph.nodes[node]
    identity = (data.get("line") or data.get("route_id")
                or (node[2] if len(node) > 2 else None) or data.get("disp"))
    return str(identity) if identity is not None else None


def transit_path_signature(graph, path, *, transit_only=False, collapse_final_alight=True):
    """Keep transfers and direction, omitting only the final alighting stop.

    A later departure on the same itinerary is not an extra route choice.
    Selected vehicle runs and clocks remain on the path used for validation.
    ``transit_only`` also supports abstract non-transit board/alight edges in
    the label search; response paths retain the strict shape checks.
    """
    legs = []
    active = None
    boarded_line_identity = None
    first_ride_stop = None
    for u, v in zip(path, path[1:]):
        edge = graph.get_edge_data(u, v)
        if edge is None:
            continue
        etype = edge.get("etype")
        if etype == "board":
            data = graph.nodes[v]
            if transit_only and data.get("mode") not in ("bus", "rail"):
                continue
            if active is not None:
                raise RouteContractError(
                    f"nested board edge in route path: active={active!r}, u={u!r}, v={v!r}"
                )
            if u[0] != "phys" or v[0] != "line":
                raise RouteContractError(f"invalid board edge shape: u={u!r}, v={v!r}")
            boarded_line_identity = _line_identity(graph, v)
            active = (data.get("mode"), boarded_line_identity or str(v), str(u[1]))
            first_ride_stop = None
        elif etype == "ride" and active is not None and first_ride_stop is None:
            # Railway nodes are shared by both directions. Bus line IDs also
            # retain their route pattern, even when display titles match.
            first_ride_stop = str(v[1])
        elif etype == "alight":
            if (transit_only and active is None
                    and graph.nodes[u].get("mode") not in ("bus", "rail")):
                continue
            if active is None:
                raise RouteContractError(
                    f"alight without active ride in route path: u={u!r}, v={v!r}"
                )
            if u[0] != "line" or v[0] != "phys":
                raise RouteContractError(f"invalid alight edge shape: u={u!r}, v={v!r}")
            alighted_line_identity = _line_identity(graph, u)
            identity = alighted_line_identity or str(u)
            # Older abstract graph fixtures do not declare line identities.
            # An explicit line change remains invalid in every caller.
            missing_identity = boarded_line_identity is None or alighted_line_identity is None
            if identity != active[1] and not (transit_only and missing_identity):
                raise RouteContractError(
                    "ride line changed without a transfer: "
                    f"boarded={active[1]!r}, alighted={identity!r}"
                )
            legs.append((*active, first_ride_stop, str(v[1])))
            active = None
    if active is not None:
        raise RouteContractError(f"route path ended before alighting: active={active!r}")
    if legs and collapse_final_alight:
        legs[-1] = legs[-1][:-1]
    return tuple(legs)
