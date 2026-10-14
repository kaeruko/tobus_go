"""Uniform, source-only access to GTFS-JP and ODPT schedule datasets.

Loading returns TransitDataset without merging feeds, granting fare rights,
creating pedestrian connections, or changing existing city runtimes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence, runtime_checkable

from transit_dataset import FeedMetadata, TransitDataset

from .gtfs import GtfsTransitAdapter
from .odpt import OdptCalendarRule, OdptTransitAdapter


@runtime_checkable
class TransitFeedSource(Protocol):
    """One versioned source yielding a validated, feed-namespaced dataset."""

    def load(self) -> TransitDataset: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class GtfsFeedSource:
    directory: str | Path
    metadata: FeedMetadata
    skip_untimed_intermediate_stops: bool = False

    def load(self) -> TransitDataset:
        return GtfsTransitAdapter.load(
            self.directory,
            metadata=self.metadata,
            skip_untimed_intermediate_stops=self.skip_untimed_intermediate_stops,
        )


OdptRecord = Mapping[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class OdptFeedSource:
    metadata: FeedMetadata
    # ODPT does not contain sufficient universally applicable calendar rules.
    # Callers must supply authoritative rules explicitly, never infer them.
    calendar_rules: Mapping[str, OdptCalendarRule]
    busstop_poles: Sequence[OdptRecord] = ()
    busroute_patterns: Sequence[OdptRecord] = ()
    bus_timetables: Sequence[OdptRecord] = ()
    stations: Sequence[OdptRecord] = ()
    railways: Sequence[OdptRecord] = ()
    train_timetables: Sequence[OdptRecord] = ()

    def load(self) -> TransitDataset:
        return OdptTransitAdapter.build(
            metadata=self.metadata,
            busstop_poles=self.busstop_poles,
            busroute_patterns=self.busroute_patterns,
            bus_timetables=self.bus_timetables,
            stations=self.stations,
            railways=self.railways,
            train_timetables=self.train_timetables,
            calendar_rules=self.calendar_rules,
        )
