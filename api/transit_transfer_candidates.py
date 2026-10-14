"""Shared, read-only GTFS-coordinate proximity pairs for inter-feed triage.

A matching pair is only a straight-line *candidate*. This helper never
certifies a walkable path, station entrance, fare policy or transfer duration.
Cities supply already-vetted service-day stop identities and fare coverage.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping

from gtfs_route_backend import _haversine_m
from transit_dataset import TransitStop


def iter_nearby_stop_pairs(
    left_stops: Mapping[str, TransitStop],
    right_stops: Mapping[str, TransitStop],
    *,
    left_ids: Iterable[str],
    right_ids: Iterable[str],
    radius_m: float,
) -> Iterator[tuple[float, str, str]]:
    """Yield (straight_line_m, left_stop_id, right_stop_id), sorted by IDs.

    Both live search and offline audit call the same geometry. Missing stop
    IDs raise immediately; duplicates collapse only for input enumeration.
    Results are *not* ordered by distance, so callers may sort if needed.
    """
    if isinstance(radius_m, bool) or not isinstance(radius_m, (int, float)) or (
        not math.isfinite(radius_m) or radius_m <= 0
    ):
        raise ValueError("radius_m must be a positive finite number")
    for left_id in sorted(set(left_ids)):
        a = left_stops[left_id]
        for right_id in sorted(set(right_ids)):
            b = right_stops[right_id]
            distance = _haversine_m(a.lat, a.lon, b.lat, b.lon)
            if math.isfinite(distance) and distance <= radius_m:
                yield distance, left_id, right_id
