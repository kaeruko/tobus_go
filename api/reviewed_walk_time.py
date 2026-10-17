"""Shared, explicit walking-time evidence for transit network transfer edges.

Only exact stop/entrance identifiers may receive a reviewed override. A
geometric estimate is not independently verified, and an official standard
walking-time quote is not a wheelchair-accessible travel-time guarantee.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from urllib.parse import urlsplit
from typing import Mapping, Any
from walking_access import walking_elapsed_minutes, walking_minutes


def validate_reviewed_walk_timing(meters: int, minutes: int) -> None:
    if type(meters) is not int or meters < 0:
        raise ValueError("reviewed walking meters must be a nonnegative integer")
    if type(minutes) is not int or minutes < 0:
        raise ValueError("reviewed walking minutes must be a nonnegative integer")
    if minutes < walking_minutes(meters):
        raise ValueError("reviewed walking minutes less than the distance minimum")


def walk_edge_elapsed_minutes(edge: Mapping[str, Any], *, speed_m_per_min: float = 80.0) -> float:
    """Return a graph walking edge's elapsed minutes, not its weighted cost.

    Existing unreviewed edges retain the exact legacy distance/speed formula
    (including the 1m fallback for zero-length links). A reviewed override,
    if present, changes routing time and must match the physical distance.
    """
    if isinstance(speed_m_per_min, bool) or not isinstance(speed_m_per_min, (int, float)):
        raise ValueError("walking speed must be positive and finite")
    if not math.isfinite(speed_m_per_min) or speed_m_per_min <= 0:
        raise ValueError("walking speed must be positive and finite")
    meters = edge.get("meters", 0)
    if isinstance(meters, bool) or not isinstance(meters, (int, float)):
        raise ValueError("walking meters must be nonnegative and finite")
    if not math.isfinite(meters):
        raise ValueError("walking meters must be finite")
    if "reviewed_walk_minutes" not in edge:
        # Preserve Tokyo's legacy 1-meter fallback for 0 or negative
        # synthetic/virtual walk edges. Only reviewed walking overrides
        # require actual nonnegative measured distance.
        return walking_elapsed_minutes(meters if meters > 0 else 1.0, speed_m_per_min=speed_m_per_min)
    if meters < 0:
        raise ValueError("reviewed walking meters must be nonnegative")
    minutes = edge["reviewed_walk_minutes"]
    if type(minutes) is not int or minutes < 0:
        raise ValueError("reviewed walk minutes must be nonnegative integer")
    if minutes < walking_minutes(meters, speed_m_per_min=speed_m_per_min):
        raise ValueError("reviewed walk minutes shorter than distance minimum")
    return float(minutes)


@dataclass(frozen=True, slots=True)
class ReviewedWalkingLink:
    """Directed official link. Station-to-platform access must be reviewed.

    A reverse direction requires its own link and source evidence. These links
    are not assembled from proximity, matching names or bus-pole suffixes.
    """
    from_stop_id: str
    to_stop_id: str
    walk_meters: int
    walk_minutes: int
    official_evidence_url: str
    includes_station_access: bool

    def __post_init__(self) -> None:
        if (not isinstance(self.from_stop_id, str) or not self.from_stop_id.strip()
                or not isinstance(self.to_stop_id, str) or not self.to_stop_id.strip()
                or self.from_stop_id == self.to_stop_id):
            raise ValueError("reviewed walk requires distinct exact stop IDs")
        validate_reviewed_walk_timing(self.walk_meters, self.walk_minutes)
        if self.includes_station_access is not True:
            raise ValueError("reviewed transfer requires station/platform access check")
        if not isinstance(self.official_evidence_url, str):
            raise ValueError("reviewed walk requires official HTTPS evidence")
        parsed = urlsplit(self.official_evidence_url)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password or parsed.fragment
                or not (parsed.hostname.endswith(".lg.jp")
                        or parsed.hostname.endswith(".tokyo.jp")
                        or parsed.hostname in {"www.city.sendai.jp", "www.kotsu.city.sendai.jp",
                                               "www.navi.kotsu.city.sendai.jp"})):
            raise ValueError("reviewed walk requires official government HTTPS evidence")
