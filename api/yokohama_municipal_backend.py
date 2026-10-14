"""Municipal feed coordination; timetable search stays in the shared SearchCore.

Public inter-feed transfers require explicitly reviewed walking links. Nearby
GTFS coordinates alone are not evidence of a usable pedestrian connection.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from datetime import timedelta

from gtfs_route_backend import GtfsRouteBackend, _haversine_m
from route_engine import (RouteCandidate, RouteInputError, RoutePreference,
                          RouteSearchLimitError, RouteSearchResult)
from yokohama_municipal_transfer import (
    ExplicitTransferLink, GeometricTransferEstimate, _reviewed,
)
from yokohama_transit import _yokohama_service_clock

PASS_IDS = frozenset({"yokohama_welfare_special_pass", "yokohama_senior_special_pass"})


def load_reviewed_transfer_links(path, bus_coverage, subway_coverage):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "feed_versions", "links"}:
        raise ValueError("municipal transfer review schema mismatch")
    expected = {c.dataset.metadata.feed_id: c.dataset.metadata.version
                for c in (bus_coverage, subway_coverage)}
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1 or raw["feed_versions"] != expected:
        raise ValueError("municipal transfer review edition mismatch")
    if not isinstance(raw["links"], list):
        raise ValueError("municipal transfer links must be a list")
    return tuple(ExplicitTransferLink(**row) for row in raw["links"])


class _CoveredFeedBackend(GtfsRouteBackend):
    def __init__(self, coverage, **kwargs):
        self.coverage = coverage
        self.active_stops = frozenset(row.stop_id for row in coverage.dataset.stop_times)
        super().__init__(coverage.dataset, **kwargs)

    def _nearby(self, lat, lon):
        # Excluded routes' poles must not consume the endpoint candidate budget.
        rows = [(stop, _haversine_m(lat, lon, stop.lat, stop.lon))
                for key, stop in self.dataset.stops.items() if key in self.active_stops]
        return sorted((row for row in rows if row[1] <= self.walk_radius_m),
                      key=lambda row: (row[1], row[0].id))[:self.endpoint_candidate_limit]

    def _ride_step(self, leg, index):
        step = super()._ride_step(leg, index)
        step.update(
            fare_context=self.coverage.context_for_step(step),
            headsign=self.dataset.trips[leg.trip_id].headsign,
            boarding_minutes=leg.departure_minute,
            departure_time=_yokohama_service_clock(leg.departure_minute),
            arrival_time=_yokohama_service_clock(leg.arrival_minute),
            timetable_only=True,
        )
        return step

    def _serialize(self, *args, **kwargs):
        itinerary = args[0]
        if itinerary.arrival_minute >= 1440:
            raise RouteInputError("municipal integration does not yet support cross-midnight journeys")
        payload = super()._serialize(*args, **kwargs)
        for step in payload["steps"]:
            if step["kind"] == "walk":
                step.update(title="徒歩（直線距離による推定）", distance_basis="straight_line",
                            walking_connection_verified=False)
        return payload


class YokohamaMunicipalRouteBackend:
    """Search both covered feeds and at most one reviewed inter-feed connection.

    Source IDs, calendars and configured Python/Rust core remain per-feed.
    A missing walking review excludes connections, never enables proximity
    estimates. Bus-only searches select the bus feed before any search runs.
    """
    def __init__(
        self, bus_coverage, subway_coverage, *, transfer_links=(),
        estimated_transfer_mode=False, estimated_radius_m=300,
        estimated_candidate_limit=100, **kwargs,
    ):
        if type(estimated_transfer_mode) is not bool:
            raise ValueError("estimated_transfer_mode must be bool")
        if type(estimated_radius_m) is not int or not 1 <= estimated_radius_m <= 600:
            raise ValueError("estimated_radius_m must be 1..600")
        if type(estimated_candidate_limit) is not int or not 1 <= estimated_candidate_limit <= 100:
            raise ValueError("estimated_candidate_limit must be 1..100")
        self.estimated_transfer_mode = estimated_transfer_mode
        self.estimated_radius_m = estimated_radius_m
        self.estimated_candidate_limit = estimated_candidate_limit
        bus = _reviewed(bus_coverage, "yokohama_bus", "yokohama_municipal_bus")
        rail = _reviewed(subway_coverage, "yokohama_subway", "yokohama_municipal_subway")
        self.backends = {
            key: None if coverage is None else _CoveredFeedBackend(coverage, **kwargs)
            for key, coverage in (("bus", bus), ("rail", rail))
        }
        self.transfer_links = tuple(transfer_links)
        if len(self.transfer_links) > 100:
            raise ValueError("municipal reviewed transfer limit exceeded")
        seen = set()
        for link in self.transfer_links:
            if not isinstance(link, ExplicitTransferLink):
                raise ValueError("public municipal transfers require reviewed ExplicitTransferLink")
            key = (link.bus_stop_id, link.subway_stop_id)
            if key in seen:
                raise ValueError("duplicate municipal transfer link")
            seen.add(key)
            a = bus_coverage.dataset.stops[link.bus_stop_id]
            b = subway_coverage.dataset.stops[link.subway_stop_id]
            distance = _haversine_m(a.lat, a.lon, b.lat, b.lon)
            if distance > 600 or link.walk_meters < distance:
                raise ValueError("municipal walking link distance is invalid")
        self.policy_id = None

    def for_fare_policy(self, policy_id):
        if policy_id not in PASS_IDS:
            raise RouteInputError(f"unsupported Yokohama route fare policy: {policy_id!r}")
        scoped = copy.copy(self)
        scoped.policy_id = policy_id
        return scoped

    @staticmethod
    def _payload(backend, best, request, departure, origin, destination, preference):
        return backend._serialize(
            *best, alat=origin.lat, alon=origin.lon, blat=destination.lat,
            blon=destination.lon, departure=departure, preference=preference,
        )

    def _candidate_transfer_links(self):
        """Keep reviewed evidence separate from provisional GTFS proximity.

        This is an explicit development-only switch; public default stays
        reviewed links only. Every mode preserves direction-specific pole IDs.
        """
        if not self.estimated_transfer_mode:
            return self.transfer_links
        bus = self.backends["bus"]
        rail = self.backends["rail"]
        if bus is None or rail is None:
            return self.transfer_links
        reviewed_pairs = {(x.bus_stop_id, x.subway_stop_id) for x in self.transfer_links}
        estimated = []
        for bus_id in sorted(bus.active_stops):
            a = bus.dataset.stops[bus_id]
            for rail_id in sorted(rail.active_stops):
                if (bus_id, rail_id) in reviewed_pairs:
                    continue
                b = rail.dataset.stops[rail_id]
                distance = _haversine_m(a.lat, a.lon, b.lat, b.lon)
                if math.isfinite(distance) and distance <= self.estimated_radius_m:
                    meters = math.ceil(distance * 1.5)
                    estimated.append(GeometricTransferEstimate(
                        bus_stop_id=bus_id,
                        subway_stop_id=rail_id,
                        straight_line_distance_m=distance,
                        walk_meters=meters,
                        walk_minutes=math.ceil(meters / 80) + 2,
                    ))
                    if len(estimated) > self.estimated_candidate_limit:
                        raise RouteSearchLimitError(
                            "too many provisional Yokohama walking links; "
                            "reduce estimated_radius_m, no truncated routes"
                        )
        return self.transfer_links + tuple(estimated)

    def _connections(self, request, preference):
        for link in self._candidate_transfer_links():
            for first_mode, second_mode in (("bus", "rail"), ("rail", "bus")):
                first, second = self.backends[first_mode], self.backends[second_mode]
                if first is None or second is None:
                    continue
                ids = {"bus": link.bus_stop_id, "rail": link.subway_stop_id}
                if ids[first_mode] not in first.active_stops or ids[second_mode] not in second.active_stops:
                    continue
                a, b = first.dataset.stops[ids[first_mode]], second.dataset.stops[ids[second_mode]]
                origins = first._nearby(request.origin.lat, request.origin.lon)
                destinations = second._nearby(request.destination.lat, request.destination.lon)
                if not origins or not destinations:
                    continue
                # Earliest arrival for every ride budget preserves the tradeoff
                # between arrival time and transfer count at the connection.
                for budget in range(1, first.max_rides):
                    left = copy.copy(first)
                    left.max_rides = budget
                    best = left._find_best(origins, [(a, 0)], departure=request.departure_at,
                                           preference="time")
                    if best is None or not best[0].legs:
                        continue
                    ready = best[0].arrival_minute + link.walk_minutes
                    if ready >= 1440:
                        raise RouteInputError("municipal transfer crosses the service-day boundary")
                    departure = request.departure_at.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=ready)
                    right = copy.copy(second)
                    right.max_rides = first.max_rides - best[0].rides
                    onward = right._find_best([(b, 0)], destinations, departure=departure,
                                              preference=preference)
                    if onward is None or not onward[0].legs:
                        continue
                    p = self._payload(left, best, request, request.departure_at, request.origin, a, preference)
                    q = self._payload(right, onward, request, departure, b, request.destination, preference)
                    is_reviewed = isinstance(link, ExplicitTransferLink)
                    walk = dict(
                        kind="walk",
                        title="徒歩乗換" if is_reviewed else "徒歩乗換（座標から推定）",
                        from_=a.name, to=b.name, minutes=link.walk_minutes,
                        meters=link.walk_meters, stops=[],
                        departureStopId=a.id, arrivalPoleId=b.id,
                        walking_connection_verified=is_reviewed,
                    )
                    if is_reviewed:
                        walk["evidence_url"] = link.official_evidence_url
                    else:
                        walk["distance_basis"] = "straight_line_estimate"
                        walk["walking_route_confirmed"] = False
                    steps = p["steps"] + [walk] + q["steps"]
                    for index, step in enumerate(steps):
                        step["step_id"] = f"municipal-{index}"
                    total = p["total_time"] + link.walk_minutes + q["total_time"]
                    p.update(id=p["id"] + "|" + q["id"], steps=steps,
                             total=total, total_time=total, arrival_time=q["arrival_time"],
                             destination_coords=q["destination_coords"],
                             lines=list(dict.fromkeys(p["lines"] + q["lines"])),
                             points=p["points"] + q["points"],
                             boards=p["boards"] + q["boards"], rides=p["rides"] + q["rides"],
                             transfers=p["transfers"] + q["transfers"] + 1,
                             walking_distance_meters=p["walking_distance_meters"] + link.walk_meters + q["walking_distance_meters"],
                             walking_segment_count=p["walking_segment_count"] + 1 + q["walking_segment_count"])
                    yield RouteCandidate.from_mapping(p)

    def search(self, request):
        if self.policy_id not in PASS_IDS:
            raise RouteInputError("municipal search requires explicit fare policy scope")
        if request.departure_at.utcoffset() != timedelta(hours=9):
            raise RouteInputError("municipal search requires Asia/Tokyo local time")
        modes = ("bus",) if request.bus_only else ("bus", "rail")
        results = []
        reachable = False
        for mode in modes:
            backend = self.backends[mode]
            if backend is None:
                continue
            dates = [d for c in backend.dataset.calendars.values() for d in (c.start_date, c.end_date)]
            dates.extend(e.day for e in backend.dataset.service_exceptions)
            if not dates or not min(dates) <= request.departure_at.date() <= max(dates):
                raise RouteInputError(f"municipal {mode} search date outside installed calendar coverage")
            result = backend.search(request)
            reachable |= result.meta["destination_reachable"]
            results.extend(result.candidates)
        preference = "time" if request.preference is RoutePreference.FASTEST else "fewTransfers"
        if not request.bus_only:
            results.extend(self._connections(request, preference))
        unique = {candidate.id: candidate for candidate in results}
        ranked = sorted(unique.values(), key=lambda c: (
            (c.total_time, c.transfers, c.id) if preference == "time"
            else (c.transfers, c.total_time, c.id)))[:request.limit]
        return RouteSearchResult(candidates=ranked, meta={
            "destination_reachable": bool(ranked) or reachable,
            "search_scope": self.policy_id, "timetable_only": True,
            "covered_modes": list(modes), "max_inter_feed_transfers": 1,
            "unreviewed_transport_excluded": True,
            "unverified_walking_transfers_excluded": not self.estimated_transfer_mode,
            "reviewed_transfer_links": len(self.transfer_links),
            "walking_transfer_basis": (
                "provisional_gtfs_proximity" if self.estimated_transfer_mode
                else "reviewed_links_only"
            ),
            "coverage_notice": (
                "未対応・無料の確認未了の路線は検索対象外です。"
                "徒歩乗換はGTFSの位置情報からの推定で、歩行経路・駅入口は未検証です。"
                if self.estimated_transfer_mode
                else "未対応・無料の確認未了の路線と、徒歩接続未確認の乗換は検索対象外です。"
            ),
        })
