"""Finite subway day tables from explicit, bounded normal-timetable reviews.

This module does not fetch evidence, infer a bus calendar, certify special
services, or extend a review according to today's date. A human must review the
retained sources and the complete holiday list for the declared coverage.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re
from urllib.parse import urlsplit

from transit_adapters.sendai_subway import Evidence
from transit_adapters.sendai_subway_practical import DayClassification, FiniteOperatingDays


NORMAL_RULE = "weekday_w_weekend_and_official_holiday_h"


def _date(value):
    if not isinstance(value, str):
        raise ValueError("review dates must be explicit ISO strings")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("review dates must use YYYY-MM-DD")
    return parsed


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"{label}: exact review fields required")


def _days(start, end):
    return tuple(start + timedelta(days=i) for i in range((end - start).days + 1))


@dataclass(frozen=True)
class HolidayPeriodReview:
    """Complete official holidays, including substitute/citizens' holidays.

    No holiday is calculated from a name, weekday or recurrence rule. An empty
    list asserts that the retained official source lists none in this interval.
    """

    start: date
    end: date
    source_uri: str
    source_sha256: str
    holidays: tuple[tuple[date, str], ...]

    def __post_init__(self):
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise ValueError("explicit ordered holiday coverage required")
        p = urlsplit(self.source_uri)
        if (p.scheme != "https" or p.netloc != "www8.cao.go.jp"
                or p.username or p.password or p.fragment
                or not isinstance(self.source_sha256, str)
                or re.fullmatch(r"[a-f0-9]{64}", self.source_sha256) is None):
            raise ValueError("retained Cabinet Office holiday source/hash required")
        if (type(self.holidays) is not tuple
                or any(type(item) is not tuple or len(item) != 2
                       or type(item[0]) is not date or not self.start <= item[0] <= self.end
                       or not isinstance(item[1], str) or not item[1].strip()
                       for item in self.holidays)
                or len({item[0] for item in self.holidays}) != len(self.holidays)):
            raise ValueError("unique named official holiday dates within coverage required")


@dataclass(frozen=True)
class OperatingPeriodReview:
    """Subway-only normal-day assumption, separate from query display bounds.

    Sources and the assumption note are review assertions, not automatic proof
    that no later announcement or special service exists. Bus availability and
    each transfer's valid days must be supplied independently by the caller.
    """

    coverage_start: date
    coverage_end: date
    query_start: date
    query_end: date
    reviewed_at: date
    normal_timetable_sources: tuple[Evidence, ...]
    change_notice_sources: tuple[Evidence, ...]
    holiday_review: HolidayPeriodReview
    exclusions: tuple[DayClassification, ...]
    assumption_note: str

    def __post_init__(self):
        if (any(type(d) is not date for d in (self.coverage_start, self.coverage_end,
                                             self.query_start, self.query_end, self.reviewed_at))
                or not self.coverage_start <= self.query_start <= self.query_end <= self.coverage_end):
            raise ValueError("ordered query bounds within explicit internal coverage required")
        for sources in (self.normal_timetable_sources, self.change_notice_sources):
            if type(sources) is not tuple or not sources or any(not isinstance(e, Evidence) for e in sources):
                raise ValueError("normal timetable and change-notice source reviews required")
        h = self.holiday_review
        if (not isinstance(h, HolidayPeriodReview) or h.start > self.coverage_start
                or h.end < self.coverage_end):
            raise ValueError("holiday evidence must cover all internal service days")
        if (type(self.exclusions) is not tuple
                or any(not isinstance(e, DayClassification) or e.kind is not None
                       or not self.coverage_start <= e.day <= self.coverage_end
                       for e in self.exclusions)
                or len({e.day for e in self.exclusions}) != len(self.exclusions)):
            raise ValueError("unique explicit excluded subway days within coverage required")
        if not isinstance(self.assumption_note, str) or not self.assumption_note.strip():
            raise ValueError("explicit normal-timetable assumption/limitations note required")

    @classmethod
    def from_mapping(cls, value):
        _keys(value, ("schema_version", "feed_id", "normal_timetable_rule",
                      "normal_timetable_only", "special_timetables_verified", "coverage_start",
                      "coverage_end", "query_start", "query_end", "reviewed_at",
                      "normal_timetable_sources", "change_notice_sources", "holiday_review",
                      "exclusions", "assumption_note"), "operating period")
        if (type(value["schema_version"]) is not int or value["schema_version"] != 1
                or value["feed_id"] != "sendai_subway"
                or value["normal_timetable_rule"] != NORMAL_RULE
                or value["normal_timetable_only"] is not True
                or value["special_timetables_verified"] is not False):
            raise ValueError("explicit subway normal-timetable model schema required")
        h = value["holiday_review"]
        _keys(h, ("start", "end", "source_uri", "source_sha256", "holidays"), "holiday review")
        if not isinstance(h["holidays"], list) or not isinstance(value["exclusions"], list):
            raise ValueError("explicit holiday and exclusion lists required")
        holidays = []
        for row in h["holidays"]:
            _keys(row, ("day", "name"), "holiday")
            holidays.append((_date(row["day"]), row["name"]))
        exclusions = []
        for row in value["exclusions"]:
            _keys(row, ("day", "reason"), "exclusion")
            if not isinstance(row["reason"], str) or not row["reason"].strip():
                raise ValueError("excluded day requires a reason")
            exclusions.append(DayClassification(_date(row["day"]), None, row["reason"]))

        def sources(field):
            if not isinstance(value[field], list):
                raise ValueError("explicit source list required")
            result = []
            for source in value[field]:
                _keys(source, ("uri", "sha256"), field)
                result.append(Evidence(**source))
            return tuple(result)

        return cls(*(_date(value[k]) for k in ("coverage_start", "coverage_end", "query_start",
                                               "query_end", "reviewed_at")),
                   sources("normal_timetable_sources"), sources("change_notice_sources"),
                   HolidayPeriodReview(_date(h["start"]), _date(h["end"]), h["source_uri"],
                                       h["source_sha256"], tuple(holidays)),
                   tuple(exclusions), value["assumption_note"])

    def to_mapping(self):
        """Return a fresh JSON-ready record; no filesystem/network side effects."""
        h = self.holiday_review
        evidence = lambda rows: [{"uri": e.uri, "sha256": e.sha256} for e in rows]
        return {
            "schema_version": 1, "feed_id": "sendai_subway", "normal_timetable_rule": NORMAL_RULE,
            "normal_timetable_only": True, "special_timetables_verified": False,
            "coverage_start": self.coverage_start.isoformat(), "coverage_end": self.coverage_end.isoformat(),
            "query_start": self.query_start.isoformat(), "query_end": self.query_end.isoformat(),
            "reviewed_at": self.reviewed_at.isoformat(),
            "normal_timetable_sources": evidence(self.normal_timetable_sources),
            "change_notice_sources": evidence(self.change_notice_sources),
            "holiday_review": {"start": h.start.isoformat(), "end": h.end.isoformat(),
                "source_uri": h.source_uri, "source_sha256": h.source_sha256,
                "holidays": [{"day": d.isoformat(), "name": name} for d, name in sorted(h.holidays)]},
            "exclusions": [{"day": e.day.isoformat(), "reason": e.reason}
                           for e in sorted(self.exclusions, key=lambda e: e.day)],
            "assumption_note": self.assumption_note,
        }

    def operating_days(self):
        """Generate only the bounded internal table; exclusions take precedence."""
        holidays = dict(self.holiday_review.holidays)
        excluded = {e.day: e for e in self.exclusions}
        entries = []
        for day in _days(self.coverage_start, self.coverage_end):
            if day in excluded:
                entries.append(excluded[day])
            elif day in holidays:
                entries.append(DayClassification(day, "h", "official holiday: " + holidays[day]))
            elif day.weekday() >= 5:
                entries.append(DayClassification(day, "h", "reviewed normal Saturday/Sunday model"))
            else:
                entries.append(DayClassification(day, "w", "reviewed normal weekday model"))
        return FiniteOperatingDays(tuple(entries), self.normal_timetable_sources + self.change_notice_sources,
                                   self.reviewed_at, self.holiday_review.source_uri,
                                   self.holiday_review.source_sha256)

    def require_query_days(self, civil_date, required_service_days, *, additional_reviewed_days=()):
        """Validate the caller's exact dependency days; never return a partial set.

        The caller obtains dependencies from its existing materialization rules.
        Additional sets represent independently reviewed bus/transfer days, not
        GTFS weekday classifications. Bus active services still come from GTFS.
        """
        if type(civil_date) is not date or not self.query_start <= civil_date <= self.query_end:
            raise ValueError("civil query date is outside advertised review bounds")
        if (type(required_service_days) is not tuple or not required_service_days
                or any(type(d) is not date for d in required_service_days)
                or len(set(required_service_days)) != len(required_service_days)
                or civil_date not in required_service_days):
            raise ValueError("explicit unique service dependencies including query day required")
        _validate_additional_days(additional_reviewed_days)
        table = self.operating_days()
        for day in required_service_days:
            table.kind_on(day)
            if any(day not in days for days in additional_reviewed_days):
                raise ValueError(f"independent bus/transfer review missing service day {day}")
        return required_service_days

    def advertised_dates(self, *, service_day_offsets, additional_reviewed_days=()):
        """Conservative display dates for an explicitly declared dependency envelope.

        For a profile requiring at most the previous/current/next service day,
        pass (-1, 0, 1). A wider search horizon must supply a wider envelope.
        This does not establish that an OD has a route or an active bus service.
        """
        if (type(service_day_offsets) is not tuple or not service_day_offsets
                or any(type(i) is not int for i in service_day_offsets)
                or len(set(service_day_offsets)) != len(service_day_offsets)
                or 0 not in service_day_offsets):
            raise ValueError("explicit unique dependency offsets including zero required")
        _validate_additional_days(additional_reviewed_days)
        valid = {e.day for e in self.operating_days().entries if e.kind is not None}
        for days in additional_reviewed_days:
            valid.intersection_update(days)
        return tuple(day for day in _days(self.query_start, self.query_end)
                     if all(day + timedelta(days=i) in valid for i in service_day_offsets))


def _validate_additional_days(value):
    if (type(value) is not tuple or any(type(days) is not frozenset
            or any(type(day) is not date for day in days) for days in value)):
        raise ValueError("independent review dates require an explicit tuple of frozensets")
