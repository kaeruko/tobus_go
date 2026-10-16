"""Connection-layer records for shared v2. No route-search implementation."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Literal
from transit_dataset import TransitMode

SearchPreference = Literal["fastest", "fewest_transfers"]
@dataclass(frozen=True, slots=True)
class TransitLeg:
    trip_id: str
    route_id: str
    mode: TransitMode
    from_stop_id: str
    to_stop_id: str
    departure_minute: int | Fraction
    arrival_minute: int | Fraction
    stop_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransitItinerary:
    departure_minute: int | Fraction
    arrival_minute: int | Fraction
    legs: tuple[TransitLeg, ...]

    @property
    def rides(self) -> int:
        return len(self.legs)

    @property
    def transfers(self) -> int:
        return max(0, self.rides - 1)

    @property
    def total_minutes(self) -> int | Fraction:
        return self.arrival_minute - self.departure_minute


@dataclass(frozen=True, slots=True)
class SearchDiagnostics:
    preference: SearchPreference
    elapsed_seconds: float
    route_found: bool
    visited_states: int = 0
    queue_peak: int = 0
    generated_labels: int = 0
    origin_searches: int = 0
    termination_reason: str = "completed"


@dataclass(frozen=True, slots=True)
class SearchEndpoint:
    stop_id: str
    walk_minutes: int = 0
    walk_meters: float = 0.0
    rank: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.stop_id, str) or not self.stop_id:
            raise ValueError("stop_id is required")
        if (
            isinstance(self.walk_minutes, bool)
            or not isinstance(self.walk_minutes, int)
            or self.walk_minutes < 0
        ):
            raise ValueError("walk_minutes must be an integer >= 0")
        if (
            isinstance(self.walk_meters, bool)
            or not isinstance(self.walk_meters, (int, float))
            or not math.isfinite(self.walk_meters)
            or self.walk_meters < 0
        ):
            raise ValueError("walk_meters must be finite and >= 0")
        if (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank < 0
        ):
            raise ValueError("rank must be an integer >= 0")


@dataclass(frozen=True, slots=True)
class BatchSearchRequest:
    service_date: date
    departure_minute: int
    origins: tuple[SearchEndpoint, ...]
    destinations: tuple[SearchEndpoint, ...]
    preference: SearchPreference
    max_rides: int = 6

    def __post_init__(self) -> None:
        if not isinstance(self.service_date, date):
            raise ValueError("service_date must be a date")
        if (
            isinstance(self.departure_minute, bool)
            or not isinstance(self.departure_minute, int)
            or self.departure_minute < 0
        ):
            raise ValueError("departure_minute must be an integer >= 0")
        if not self.origins:
            raise ValueError("origins must not be empty")
        if not self.destinations:
            raise ValueError("destinations must not be empty")
        if self.preference not in ("fastest", "fewest_transfers"):
            raise ValueError(f"unsupported search preference: {self.preference!r}")
        if isinstance(self.max_rides, bool) or not isinstance(self.max_rides, int):
            raise ValueError("max_rides must be an integer")
        if self.max_rides < 1:
            raise ValueError("max_rides must be >= 1")


