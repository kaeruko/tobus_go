"""Shared coordinate-access mechanics, separate from permission to transfer.

Distance candidates do not certify a sidewalk, entrance or station connection.
Callers supply their existing candidate source/order and access rules; reviewed
network transfer links remain the responsibility of the network loader.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from route_engine import RouteInputError


def haversine_m(lat1, lon1, lat2, lon2):
    radius = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * radius * math.asin(math.sqrt(a))


def distance_candidates(points, lat, lon, *, radius_m=None, distance=haversine_m):
    """Yield (identity, metres) in source order, with an inclusive radius.

    A point is an (identity, latitude, longitude) tuple. Keeping the original
    order matters for legacy nearest-node ties and spatial-index results.
    """
    for identity, point_lat, point_lon in points:
        meters = distance(lat, lon, point_lat, point_lon)
        if radius_m is None or meters <= radius_m:
            yield identity, meters


def nearest_candidate(points, lat, lon, *, distance=haversine_m):
    """Preserve the legacy first-on-tie rule and empty-result sentinel."""
    best, best_distance = None, 1e30
    for identity, meters in distance_candidates(points, lat, lon, distance=distance):
        if meters < best_distance:
            best, best_distance = identity, meters
    return best, best_distance


def nearby_stops(stops, lat, lon, *, radius_m, candidate_limit):
    """Distance/ID ordered candidates only, without approving access."""
    points = ((stop, stop.lat, stop.lon) for stop in stops.values())
    candidates = list(distance_candidates(points, lat, lon, radius_m=radius_m))
    candidates.sort(key=lambda item: (item[1], item[0].id))
    return candidates[:candidate_limit]


def walking_elapsed_minutes(meters, *, speed_m_per_min=80.0, minimum_minutes=0):
    """Distance estimate only; explicit reviewed durations are not recomputed."""
    elapsed = meters / speed_m_per_min
    return elapsed if minimum_minutes == 0 else max(minimum_minutes, elapsed)


def walking_minutes(meters, *, speed_m_per_min=80.0):
    return math.ceil(walking_elapsed_minutes(meters, speed_m_per_min=speed_m_per_min))


def walking_display_meters(meters):
    """The existing GTFS/WalkStep integer distance contract."""
    return int(round(meters))


def walking_metrics(steps):
    """Aggregate the existing integer WalkStep display contract."""
    walks = [step for step in steps if step.get("kind") == "walk"]
    return {"walking_distance_meters": sum(step["meters"] for step in walks),
            "walking_segment_count": len(walks)}


@dataclass(frozen=True)
class ReviewedCoordinateAccessRules:
    candidate_radius_m: float
    same_position_tolerance_m: float


@dataclass(frozen=True)
class ReviewedPoleAccess:
    """Directional, version-pinned footprint; never a proximity permission."""
    role: str
    stop_id: str
    feed_version: str
    polygon: tuple
    path_description: str
    evidence: object
    minutes: int
    meters: int
    label: str

    def matches(self, point, role):
        if role != self.role:
            return False
        signs = []
        for a, b in zip(self.polygon, self.polygon[1:] + self.polygon[:1]):
            signs.append((b[0] - a[0]) * (point.lon - a[1])
                         - (b[1] - a[1]) * (point.lat - a[0]))
        return all(x >= -1e-15 for x in signs) or all(x <= 1e-15 for x in signs)

    def endpoint(self):
        return {"stop_id": self.stop_id, "minutes": self.minutes, "meters": self.meters,
                "basis": "reviewed_surface_planning_assumption", "label": self.label,
                "path_description": self.path_description, "source_uri": self.evidence.uri,
                "source_sha256": self.evidence.sha256, "walking_time_measured": False,
                "walking_distance_measured": False}


def reviewed_coordinate_endpoint(point, role, *, stops, boarding_stops, reviews, rules,
                                 require_explicit=True):
    """Resolve one exact pole or one directional review, failing on ambiguity.

    Source-defined boarding/alighting-only poles can resolve a coincident
    terminal. This never creates an alias, a curb crossing or a reverse link.
    """
    candidates = nearby_stops(stops, point.lat, point.lon,
                             radius_m=rules.candidate_radius_m, candidate_limit=len(stops))
    exact = [stop for stop, meters in candidates if meters <= rules.same_position_tolerance_m]
    if role == "origin" and len(exact) > 1:
        boarding = [stop for stop in exact if stop.id in boarding_stops]
        if len(boarding) == 1:
            exact = boarding
    if role == "destination" and len(exact) > 1:
        dedicated = [stop for stop in exact if stop.id not in boarding_stops]
        if len(dedicated) == 1:
            exact = dedicated
    if len(exact) == 1:
        return {"stop_id": exact[0].id, "minutes": 0, "meters": 0,
                "basis": "gtfs_pole_position_only", "label": exact[0].name,
                "path_description": "GTFS具体標柱と同一地点。周辺からの徒歩は未承認。"}
    matches = [review for review in reviews if review.matches(point, role)]
    if len(matches) == 1:
        return matches[0].endpoint()
    # Optional resolution is an explicit input classification, never recovery
    # from an exception. Ambiguous exact poles/reviews must still fail closed.
    if not require_explicit and not exact and not matches:
        return None
    raise RouteInputError(f"unreviewed_coordinate_access: {role} {point.lat},{point.lon}; "
                         "徒歩経路・出入口を確認できない地点です。近い標柱や反対側へ自動接続しません。")
