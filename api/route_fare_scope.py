from __future__ import annotations

from route_engine import RouteInputError, RouteSearchRequest


def search_with_fare_scope(engine, request: RouteSearchRequest, policy_id: str):
    """Ask a city adapter for its explicit search scope; never rewrite the core."""
    if not isinstance(policy_id, str) or not policy_id or policy_id.strip() != policy_id:
        raise RouteInputError(f"invalid route fare policy id: {policy_id!r}")
    if policy_id == "normal":
        scoped_engine = engine
    else:
        select = getattr(engine, "for_fare_policy", None)
        if not callable(select):
            raise RouteInputError(f"route fare scope is unsupported: {policy_id!r}")
        scoped_engine = select(policy_id)
    return scoped_engine.search(request)
