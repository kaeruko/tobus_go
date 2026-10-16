"""Explicit retained-source reviews for the isolated Sendai scheduled model.

No download, credentials, old dataset retry or automatic pole matching here.
A bus pattern review covers its complete driven path, not endpoint coordinates.
"""
import base64
from datetime import date, datetime, timezone
import json
from pathlib import Path

from sendai_practical_network import BusSubwayTransferReview, SendaiStandardTransferReview, build_practical_subway_network
from sendai_shared_network import FreeSegmentReview
from transit_adapters.sendai_subway import Evidence, StationReview
from transit_adapters.sendai_subway_practical import (
    PROFILE, GUIDE_URI, GUIDE_SHA256, DayClassification, FiniteOperatingDays,
    PracticalTableReview, SendaiSubwayPracticalAdapter,
)
from transit_network import NetworkCosts, StandardTransferLink


def load_reviewed_subway(published_path, review_path, *, operating_period=None):
    published = json.loads(Path(published_path).read_text(encoding="utf-8"))
    review = json.loads(Path(review_path).read_text(encoding="utf-8"))
    files = {name: base64.b64decode(value["cp932_base64"], validate=True) for name,value in published.items()}
    if review["profile"] != PROFILE:
        raise ValueError("explicit practical profile review required")
    evidence = lambda x: Evidence(**x)
    days = FiniteOperatingDays(tuple(DayClassification(date.fromisoformat(e["day"]),e["kind"],e["reason"])
        for e in review["days"]), (evidence(review["day_source"]),),date.fromisoformat(review["reviewed_at"]),review["holiday_source_uri"],review["holiday_source_sha256"])
    if operating_period is not None:
        from sendai_operating_period import OperatingPeriodReview
        if not isinstance(operating_period, OperatingPeriodReview):
            raise ValueError("explicit operating-period review required")
        days = operating_period.operating_days()
    stations = {key: StationReview(*value,evidence(review["coordinate_source"])) for key,value in review["stations"].items()}
    tables = {name: PracticalTableReview(value["csv_sha256"],tuple(evidence(e) for e in value["current_departure_evidence"]),
        value["source_comparison_record_sha256"],value["comparison_scope"],evidence(review["license_source"]),"CC-BY-4.0")
        for name,value in review["tables"].items()}
    source = SendaiSubwayPracticalAdapter().load(files,reviews=tables,stations=stations,operating_days=days,
        fetched_at=datetime(2026,10,16,tzinfo=timezone.utc),profile=PROFILE)
    return source, files


def _validate_expanded_period(subway, bus, review, days):
    """Bind the new finite review, bus exclusions and actual feed coverage."""
    from sendai_operating_period import OperatingPeriodReview
    if review.get("stage_profile") not in {"sendai_municipal_stage1", "sendai_municipal_stage2", "sendai_municipal_stage3"}:
        raise ValueError("explicit supported municipal stage profile required")
    period = OperatingPeriodReview.from_mapping(review["operating_period"])
    table = period.operating_days()
    if table != subway.operating_days:
        raise ValueError("municipal period does not match loaded subway operating days")
    values = review["reviewed_days"]
    if (not isinstance(values, list) or len(values) != len(days)
            or any(date.fromisoformat(value).isoformat() != value for value in values)):
        raise ValueError("unique canonical reviewed bus dates required")
    rows = review["bus_excluded_days"]
    if not isinstance(rows, list):
        raise ValueError("explicit bus excluded-day review list required")
    excluded = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"day", "reason", "evidence"}
                or not isinstance(row["reason"], str) or not row["reason"].strip()):
            raise ValueError("bus excluded day requires an exact date, reason and evidence")
        day = date.fromisoformat(row["day"])
        if (day.isoformat() != row["day"] or day in excluded
                or not period.coverage_start <= day <= period.coverage_end):
            raise ValueError("unique bus exclusion within reviewed coverage required")
        Evidence(**row["evidence"])
        excluded.add(day)
    expected = {entry.day for entry in table.entries if entry.kind is not None} - excluded
    if days != expected:
        raise ValueError("reviewed bus dates contradict finite period or explicit exclusions")
    bounds = [day for calendar in bus.calendars.values() for day in (calendar.start_date, calendar.end_date)]
    bounds.extend(exception.day for exception in bus.service_exceptions)
    if (not bounds or period.coverage_start < min(bounds) or period.coverage_end > max(bounds)):
        raise ValueError("municipal operating period exceeds explicit GTFS coverage")


def build_reviewed_municipal_model(subway, bus, review, *, accept_experimental_bus_transfers):
    if review["schema_version"] != 1 or review["bus_feed_version"] != bus.metadata.version:
        raise ValueError("municipal bus review does not match this exact feed version")
    if review["bus_source_uri"] != bus.metadata.source_uri:
        raise ValueError("municipal bus review source URI mismatch")
    days = frozenset(date.fromisoformat(d) for d in review["reviewed_days"])
    if "operating_period" in review:
        _validate_expanded_period(subway, bus, review, days)
    rows = {}
    for row in bus.stop_times: rows.setdefault(row.trip_id,[]).append(row)
    segments = []
    for pattern in review["bus_patterns"]:
        if pattern["entire_driven_path_municipality"] != "04100" or pattern["service_kind"] != "local":
            raise ValueError("bus pattern is outside or not verified free municipal scope")
        evidence = Evidence(**pattern["map_evidence"])
        matched = []
        for trip in bus.trips.values():
            rr = sorted(rows[trip.id],key=lambda r:r.sequence)
            if trip.route_id != pattern["route_id"]: continue
            if tuple(r.stop_id for r in rr) != tuple(pattern["stop_ids"]):
                # Different patterns on the route are excluded, never inferred free.
                continue
            if tuple(bus.stops[r.stop_id].name for r in rr) != tuple(pattern["stop_names"]):
                raise ValueError("reviewed bus pattern stop names changed")
            matched.append(trip.id)
            segments.extend(FreeSegmentReview(trip.id,bus.metadata.version,a.sequence,b.sequence,a.stop_id,b.stop_id,
                "SendaiMunicipal","local","04100",evidence) for a,b in zip(rr,rr[1:]))
        if not matched or sorted(matched) != sorted(pattern["trip_ids"]):
            raise ValueError("exact reviewed bus concrete-trip set mismatch")
    # Two city subway lines have an independently retained complete-path review.
    subway_rows = {}
    for row in subway.dataset.stop_times: subway_rows.setdefault(row.trip_id,[]).append(row)
    if review["subway_feed_version"] != subway.dataset.metadata.version:
        raise ValueError("subway free scope review version mismatch")
    subway_evidence = Evidence(**review["subway_free_path_evidence"])
    for tid,rr in subway_rows.items():
        segments.extend(FreeSegmentReview(tid,subway.dataset.metadata.version,a.sequence,b.sequence,a.stop_id,b.stop_id,
            "SendaiMunicipal","local","04100",subway_evidence) for a,b in zip(rr,rr[1:]))
    links=[]
    versions={"sendai_bus":bus.metadata.version,"sendai_subway":subway.dataset.metadata.version}
    for row in review["bus_subway_transfers"]:
        link=StandardTransferLink(row["from_stop_id"],row["to_stop_id"],
            versions[row["from_stop_id"].split(':')[0]],versions[row["to_stop_id"].split(':')[0]],
            row["standard_minutes"],row["margin_minutes"],row["map_evidence"][0]["uri"],
            row["map_evidence"][0]["sha256"],PROFILE)
        links.append(BusSubwayTransferReview(link,days,row["bus_bay"],row["subway_entrance"],
            row["path_description"],tuple(Evidence(**e) for e in row["map_evidence"]),row["time_basis"]))
    transfer=SendaiStandardTransferReview(review["subway_transfer_margin_minutes"],days,GUIDE_URI,GUIDE_SHA256)
    return build_practical_subway_network(subway,segment_reviews=segments,transfers=transfer,costs=NetworkCosts(),
        bus_dataset=bus,bus_reviewed_days=days,bus_transfers=tuple(links),
        use_experimental_bus_transfers=accept_experimental_bus_transfers)
