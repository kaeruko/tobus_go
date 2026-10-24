from __future__ import annotations

from collections.abc import Iterable

from route_engine import RouteInputError


TOEI_BUS = "toei_bus"
TOEI_SUBWAY = "toei_subway"
TOKYO_METRO = "tokyo_metro"
ALL_TRANSPORTS = frozenset((TOEI_BUS, TOEI_SUBWAY, TOKYO_METRO))
LEGACY_DEFAULT_SCOPE = frozenset((TOEI_BUS, TOEI_SUBWAY))


def normalize_transport_scope(
    values: Iterable[str] | None,
    *,
    bus_only: bool,
) -> frozenset[str]:
    """Resolve the explicit scope while preserving legacy ``bus_only`` calls."""

    if values is None:
        return frozenset((TOEI_BUS,)) if bus_only else LEGACY_DEFAULT_SCOPE
    if isinstance(values, (str, bytes)):
        raise RouteInputError("transport_scope must be a list")
    normalized = []
    for value in values:
        if not isinstance(value, str):
            raise RouteInputError("transport_scope entries must be strings")
        if value not in ALL_TRANSPORTS:
            raise RouteInputError(f"unsupported transport_scope entry: {value!r}")
        normalized.append(value)
    if not normalized:
        raise RouteInputError("transport_scope must select at least one transport")
    if len(normalized) != len(set(normalized)):
        raise RouteInputError("transport_scope must not contain duplicates")
    scope = frozenset(normalized)
    if bus_only and scope != frozenset((TOEI_BUS,)):
        raise RouteInputError(
            "bus_only=true conflicts with the explicit transport_scope"
        )
    return scope


def transport_for_line_node(node: tuple, data: dict) -> str | None:
    explicit = data.get("transport_service")
    if explicit in ALL_TRANSPORTS:
        return explicit
    if data.get("mode") == "bus":
        return TOEI_BUS
    line_id = str(data.get("line") or (node[2] if len(node) > 2 else ""))
    if "TokyoMetro" in line_id:
        return TOKYO_METRO
    if data.get("mode") == "rail":
        return TOEI_SUBWAY
    return None


def physical_transports(graph, node: tuple) -> frozenset[str]:
    explicit = graph.nodes[node].get("transport_services")
    if explicit:
        return frozenset(explicit)
    services = set()
    for neighbor in set(graph.predecessors(node)) | set(graph.successors(node)):
        if not isinstance(neighbor, tuple) or not neighbor or neighbor[0] != "line":
            continue
        service = transport_for_line_node(neighbor, graph.nodes[neighbor])
        if service:
            services.add(service)
    return frozenset(services)
