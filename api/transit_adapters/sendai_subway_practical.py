"""Explicit Sendai minute timetable model; never an exact-arrival fallback."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import hashlib
import json
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

from transit_adapters.sendai_subway import (
    Evidence, FEED, FILES, SOURCE_BASE, STATIONS, StationReview, PublishedTable, inspect_csv,
)
from transit_dataset import (
    FeedMetadata, PublishedMinuteProvenance, ServiceCalendar, ServiceException,
    TransitDataset, TransitMode, TransitRoute, TransitStop, TransitStopTime,
    TransitTrip, namespace_id,
)

PROFILE = "sendai_published_minute_v1"
GUIDE_URI = "https://www.kotsu.city.sendai.jp/images/guide2026.pdf"
GUIDE_SHA256 = "2154d455ad80d5b8c33b16122352b444a1b97d39b7290efa211cb54c9df76921"


@dataclass(frozen=True)
class DayClassification:
    """Explicit finite normal-timetable model, not exhaustive service assurance."""
    day: date
    kind: str | None
    reason: str

    def __post_init__(self):
        if type(self.day) is not date or self.kind not in (None, "w", "h") or not self.reason.strip():
            raise ValueError("day requires w/h or an excluded reason")


@dataclass(frozen=True)
class FiniteOperatingDays:
    entries: tuple[DayClassification, ...]
    evidence: tuple[Evidence, ...]
    reviewed_at: date
    holiday_source_uri: str
    holiday_source_sha256: str

    def __post_init__(self):
        if (type(self.entries) is not tuple or not self.entries
                or any(not isinstance(e, DayClassification) for e in self.entries)
                or len({e.day for e in self.entries}) != len(self.entries)
                or not self.evidence or any(not isinstance(e, Evidence) for e in self.evidence)
                or type(self.reviewed_at) is not date):
            raise ValueError("explicit unique operating-day review required")
        host = urlsplit(self.holiday_source_uri)
        if (host.scheme != "https" or host.hostname != "www8.cao.go.jp"
                or host.username or host.password or host.fragment
                or len(self.holiday_source_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.holiday_source_sha256)):
            raise ValueError("holiday classification requires retained Cabinet Office evidence")

    def kind_on(self, day):
        if type(day) is not date:
            raise ValueError("operating day must be an explicit date")
        entry = next((e for e in self.entries if e.day == day), None)
        if entry is None:
            raise ValueError(f"unsupported operating day {day}: not in finite reviewed table")
        if entry.kind is None:
            raise ValueError(f"excluded operating day {day}: {entry.reason}")
        return entry.kind


@dataclass(frozen=True)
class PracticalTableReview:
    csv_sha256: str
    # Reuse a previously passed, exact-source-bound comparison; no HTTP rerun.
    current_departure_evidence: tuple[Evidence, ...]
    source_comparison_record_sha256: str
    comparison_scope: str
    license_evidence: Evidence
    license_id: str


@dataclass(frozen=True)
class PracticalSubwayDataset:
    dataset: TransitDataset
    operating_days: FiniteOperatingDays
    tables: Mapping[str, PublishedTable]
    attribution: str = "仙台市 / CC BY 4.0; 到着は公開時計の代理値（目安）"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        default=lambda v: v.isoformat() if isinstance(v, (date, datetime)) else str(v)).encode()).hexdigest()


class SendaiSubwayPracticalAdapter:
    def load(self, raw_files, *, reviews, stations, operating_days, fetched_at,
             profile, realtime=False):
        if profile != PROFILE:
            raise ValueError("explicit Sendai practical minute profile required")
        if realtime is not False:
            raise ValueError("practical subway model is static only")
        if not isinstance(operating_days, FiniteOperatingDays):
            raise ValueError("finite operating-day table required")
        if set(raw_files) != set(FILES) or set(reviews) != set(FILES):
            raise ValueError("all eight source files and practical reviews required")
        names = {f"{line}/{station}" for line, seq in STATIONS.items() for station in seq}
        if set(stations) != names or any(not isinstance(r, StationReview) for r in stations.values()):
            raise ValueError("exact 30 line-specific reviewed station coordinates required")
        kinds = {e.kind for e in operating_days.entries if e.kind is not None}
        if kinds != {"w", "h"}:
            raise ValueError("finite review must cover both normal timetable types")
        tables = {name: inspect_csv(name, raw_files[name]) for name in FILES}
        routes, trips, calendars, times, exceptions = {}, {}, {}, [], []
        for filename, table in tables.items():
            review = reviews[filename]
            if (not isinstance(review, PracticalTableReview) or review.csv_sha256 != table.sha256
                    or review.comparison_scope != "nonterminal_departure_multisets_only"
                    or len(review.source_comparison_record_sha256) != 64
                    or any(c not in "0123456789abcdef" for c in review.source_comparison_record_sha256)
                    or not review.current_departure_evidence
                    or any(not isinstance(e, Evidence) for e in review.current_departure_evidence)
                    or not isinstance(review.license_evidence, Evidence)
                    or review.license_id != "CC-BY-4.0"):
                raise ValueError(f"{filename}: practical review/hash/license mismatch")
            line, kind, direction, _ = filename.split("_")
            route = namespace_id(FEED, line)
            service = namespace_id(FEED, filename)
            dates = tuple(e.day for e in operating_days.entries if e.kind == kind)
            calendars[service] = ServiceCalendar(service, filename, (False,) * 7, min(dates), max(dates))
            exceptions.extend(ServiceException(service, d, 1) for d in dates)
            routes[route] = TransitRoute(route, line, line, line, TransitMode.RAIL)
            for run in table.runs:
                source_id = f"{filename}/{table.sha256}/row-{run.row_number}"
                trip_id = namespace_id(FEED, source_id)
                trips[trip_id] = TransitTrip(trip_id, source_id, route, service, run.destination,
                    direction, source_operator_id="SendaiMunicipal")
                for i, (station, clock, seconds) in enumerate(zip(table.stations, run.clocks, run.service_seconds)):
                    minute = seconds // 60
                    def provenance(basis):
                        return PublishedMinuteProvenance(basis, SOURCE_BASE + filename, table.sha256,
                            run.row_number, i + 3, clock, minute)
                    terminal = i == len(table.stations) - 1
                    times.append(TransitStopTime(trip_id, namespace_id(FEED, f"{line}/{station}"),
                        i, minute, None if terminal else minute,
                        pickup_type=1 if terminal else 0, drop_off_type=1 if i == 0 else 0,
                        arrival_provenance=provenance("published_clock_arrival_proxy"),
                        departure_provenance=None if terminal else provenance("published_departure_minute")))
        version = _digest({"profile": profile,
            "sources": {name: t.sha256 for name, t in tables.items()},
            "reviews": {name: asdict(r) for name, r in reviews.items()},
            "stations": {name: asdict(r) for name, r in stations.items()},
            "days": asdict(operating_days)})
        dataset = TransitDataset(FeedMetadata(FEED, "sendai_subway_practical_csv", SOURCE_BASE,
            version, fetched_at, clock_profile=PROFILE),
            MappingProxyType({namespace_id(FEED, name): TransitStop(namespace_id(FEED, name),
                name, name, r.latitude, r.longitude) for name, r in stations.items()}),
            MappingProxyType(routes), MappingProxyType(trips), tuple(times),
            MappingProxyType(calendars), tuple(exceptions))
        return PracticalSubwayDataset(dataset, operating_days, MappingProxyType(tables))
