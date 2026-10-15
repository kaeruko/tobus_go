"""Strict inspection and evidence-gated normalization of Sendai's row-per-run CSV.

Never selected by startup. A 20230701 filename is not a current service calendar.
The single source clock is retained as a published clock, not an invented arrival.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from types import MappingProxyType
from urllib.parse import urlsplit

from transit_dataset import (
    FeedMetadata, ServiceCalendar, ServiceException, TransitDataset, TransitMode,
    TransitRoute, TransitStop, TransitStopTime, TransitTrip, namespace_id,
)

FEED = "sendai_subway"
SOURCE_BASE = "https://www.city.sendai.jp/joho-kikaku/shise/security/kokai/documents/"
STATIONS = {
    "namboku": tuple("泉中央 八乙女 黒松 旭ヶ丘 台原 北仙台 北四番丁 勾当台公園 広瀬通 仙台 五橋 愛宕橋 河原町 長町一丁目 長町 長町南 富沢".split()),
    "tozai": tuple("八木山動物公園 青葉山 川内 国際センター 大町西公園 青葉通一番町 仙台 宮城野通 連坊 薬師堂 卸町 六丁の目 荒井".split()),
}
FILES = tuple(f"{line}_{day}_{direction}_20230701.csv"
              for line, directions in (("namboku", ("south", "north")),
                                       ("tozai", ("east", "west")))
              for day in ("w", "h") for direction in directions)


def official_url(value: str) -> None:
    p = urlsplit(value)
    if (p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment
            or not (p.hostname == "www.city.sendai.jp"
                    or p.hostname.endswith(".kotsu.city.sendai.jp")
                    or p.hostname == "www.kotsu.city.sendai.jp"
                    or p.hostname == "www2.wagmap.jp")):
        raise ValueError("Sendai review requires an explicit official HTTPS source")


@dataclass(frozen=True)
class Evidence:
    """Reference to retained source bytes; assertions still require human review."""
    uri: str
    sha256: str

    def __post_init__(self):
        official_url(self.uri)
        if re.fullmatch(r"[a-f0-9]{64}", self.sha256) is None:
            raise ValueError("evidence requires an exact SHA-256")


@dataclass(frozen=True)
class PublishedRun:
    row_number: int
    destination: str
    origin: str
    clocks: tuple[str, ...]
    service_seconds: tuple[int, ...]


@dataclass(frozen=True)
class PublishedTable:
    filename: str
    sha256: str
    stations: tuple[str, ...]
    runs: tuple[PublishedRun, ...]


def inspect_csv(filename: str, raw: bytes) -> PublishedTable:
    if filename not in FILES:
        raise ValueError("unknown Sendai subway source filename")
    line, _, direction, _ = filename.split("_")
    stations = STATIONS[line]
    if direction in ("north", "west"):
        stations = tuple(reversed(stations))
    rows = list(csv.reader(io.StringIO(raw.decode("cp932", errors="strict"))))
    if not rows or rows[0] != ["行先", "始発", *stations]:
        raise ValueError(f"{filename}: station header/order mismatch")
    runs = []
    for number, row in enumerate(rows[1:], 2):
        if len(row) != len(stations) + 2 or row[:2] != [stations[-1], stations[0]]:
            raise ValueError(f"{filename}: row {number}: unsupported partial run/width/terminus")
        seconds = []
        offset = 0
        previous = None
        for clock in row[2:]:
            if re.fullmatch(r"(?:[0-9]|1[0-9]|2[0-3]):[0-5][0-9]", clock) is None:
                raise ValueError(f"{filename}: row {number}: invalid source clock")
            hour, minute = map(int, clock.split(":"))
            civil = hour * 3600 + minute * 60
            if previous is not None and civil < previous:
                # Explicit contract: exactly one observed 23:xx -> 0:xx wrap.
                if offset or previous < 23 * 3600 or civil >= 3600:
                    raise ValueError(f"{filename}: row {number}: non-midnight clock decrease")
                offset = 86400
            seconds.append(civil + offset)
            previous = civil
        runs.append(PublishedRun(number, row[0], row[1], tuple(row[2:]), tuple(seconds)))
    if not runs:
        raise ValueError(f"{filename}: empty timetable")
    return PublishedTable(filename, hashlib.sha256(raw).hexdigest(), stations, tuple(runs))


@dataclass(frozen=True)
class StationReview:
    latitude: float
    longitude: float
    evidence: Evidence

    def __post_init__(self):
        if not isinstance(self.evidence, Evidence):
            raise ValueError("station coordinates require source evidence")
        if (type(self.latitude) not in (float, int) or type(self.longitude) not in (float, int)
                or not math.isfinite(self.latitude) or not math.isfinite(self.longitude)
                or not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180):
            raise ValueError("station requires reviewed finite WGS84 coordinates")


@dataclass(frozen=True)
class TableReview:
    csv_sha256: str
    # Exact concrete-run arrival clocks independently established from source.
    arrivals_by_row: dict[int, tuple[int, ...]]
    # Full station departure multiset from current official timetable evidence.
    departures_by_station: dict[str, tuple[int, ...]]
    current_timetable_evidence: Evidence
    arrival_clock_evidence: Evidence
    operating_day_evidence: Evidence
    license_evidence: Evidence
    # Explicit dates, including holidays/year-end; no weekday-name inference.
    operating_days: frozenset[date]
    license_id: str


class SendaiSubwayAdapter:
    """Opt-in only. Missing evidence is an error, never a historical fallback."""

    def load(self, raw_files: dict[str, bytes], *, reviews: dict[str, TableReview],
             stations: dict[str, StationReview], fetched_at: datetime) -> TransitDataset:
        if set(raw_files) != set(FILES) or set(reviews) != set(FILES):
            raise ValueError("all eight source files and reviews are required")
        if set(stations) != {f"{line}/{station}" for line, names in STATIONS.items() for station in names}:
            raise ValueError("exact official station coordinate mapping is required")
        tables = {name: inspect_csv(name, raw) for name, raw in raw_files.items()}
        routes, trips, times, calendars, exceptions = {}, {}, [], {}, []
        day_sets = {}
        for filename, table in sorted(tables.items()):
            review = reviews[filename]
            if not isinstance(review, TableReview) or review.csv_sha256 != table.sha256:
                raise ValueError(f"{filename}: review/source hash mismatch")
            for item in (review.current_timetable_evidence, review.arrival_clock_evidence,
                         review.operating_day_evidence, review.license_evidence):
                if not isinstance(item, Evidence):
                    raise ValueError(f"{filename}: missing source evidence")
            if not review.operating_days or any(type(d) is not date for d in review.operating_days):
                raise ValueError(f"{filename}: explicit verified operating dates required")
            if review.license_id != "CC-BY-4.0":
                raise ValueError(f"{filename}: unsupported/unreviewed reuse license")
            if set(review.arrivals_by_row) != {r.row_number for r in table.runs}:
                raise ValueError(f"{filename}: incomplete concrete-run arrival mapping")
            if set(review.departures_by_station) != set(table.stations[:-1]):
                raise ValueError(f"{filename}: incomplete current timetable comparison")
            for i, station in enumerate(table.stations[:-1]):
                if sorted(review.departures_by_station[station]) != sorted(r.service_seconds[i] for r in table.runs):
                    raise ValueError(f"{filename}: current departure mismatch at column {i + 2}")
            line, kind, direction, _ = filename.split("_")
            day_sets[line, direction, kind] = review.operating_days
            route_id = namespace_id(FEED, line)
            routes[route_id] = TransitRoute(route_id, line, line, line, TransitMode.RAIL)
            service = namespace_id(FEED, filename)
            calendars[service] = ServiceCalendar(service, filename, (False,) * 7,
                min(review.operating_days), max(review.operating_days))
            exceptions.extend(ServiceException(service, day, 1) for day in sorted(review.operating_days))
            for run in table.runs:
                arrivals = review.arrivals_by_row[run.row_number]
                if len(arrivals) != len(table.stations):
                    raise ValueError(f"{filename}: arrival mapping width mismatch")
                source_id = f"{filename}/{table.sha256}/row-{run.row_number}"
                trip_id = namespace_id(FEED, source_id)
                trips[trip_id] = TransitTrip(trip_id, source_id, route_id, service,
                    run.destination, direction, source_operator_id="SendaiMunicipal")
                if arrivals[-1] != run.service_seconds[-1]:
                    raise ValueError(f"{filename}: terminal arrival/source clock mismatch")
                previous_departure = -1
                for i, (station, arrival, departure) in enumerate(zip(table.stations, arrivals, run.service_seconds)):
                    if type(arrival) is not int or not previous_departure <= arrival <= departure:
                        raise ValueError(f"{filename}: nonmonotone/invalid exact arrival at row {run.row_number}")
                    times.append(TransitStopTime(trip_id, namespace_id(FEED, f"{line}/{station}"), i,
                        arrival // 60 + (arrival % 60 >= 30), departure // 60 + (departure % 60 >= 30), arrival_service_seconds=arrival,
                        departure_service_seconds=departure))
                    previous_departure = departure
        # The two day types cannot both apply on one date; directions/lines agree.
        reference = None
        for line, directions in (("namboku", ("south", "north")), ("tozai", ("east", "west"))):
            for direction in directions:
                pair = tuple(day_sets[line, direction, kind] for kind in ("w", "h"))
                if pair[0] & pair[1] or (reference is not None and pair != reference):
                    raise ValueError("inconsistent/overlapping subway operating date classifications")
                reference = pair
        version_material = {
            "sources": {name: table.sha256 for name, table in tables.items()},
            "reviews": {name: asdict(review) for name, review in reviews.items()},
            "stations": {name: asdict(review) for name, review in stations.items()},
        }
        version = hashlib.sha256(json.dumps(version_material, sort_keys=True,
            default=lambda value: sorted(str(v) for v in value) if isinstance(value, frozenset)
            else str(value), ensure_ascii=False).encode()).hexdigest()
        return TransitDataset(FeedMetadata(FEED, "sendai_subway_csv", SOURCE_BASE, version, fetched_at),
            MappingProxyType({namespace_id(FEED, name): TransitStop(namespace_id(FEED, name), name, name,
                review.latitude, review.longitude) for name, review in stations.items()}),
            MappingProxyType(routes), MappingProxyType(trips), tuple(times),
            MappingProxyType(calendars), tuple(exceptions))
