"""Municipal fare/coordinate connection layer over the shared v2 network.

No two-stage city search, geometric transfer generation or v1 backend selection.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from datetime import timedelta

from gtfs_route_backend import GtfsRouteEngine
from reviewed_walk_time import ReviewedWalkingLink
from route_engine import RouteInputError, RouteSearchResult
from transit_network import DirectedWalkLink, NetworkCosts, build_transit_network
from yokohama_shared_network import build_shared_municipal_network

PASS_IDS = frozenset({"yokohama_welfare_special_pass", "yokohama_senior_special_pass"})


def load_reviewed_transfer_links(path, bus_coverage, subway_coverage):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = {c.dataset.metadata.feed_id: c.dataset.metadata.version
                for c in (bus_coverage, subway_coverage)}
    if (not isinstance(raw, dict) or set(raw) != {"schema_version", "feed_versions", "links"}
            or type(raw["schema_version"]) is not int or raw["schema_version"] != 2
            or raw["feed_versions"] != expected or not isinstance(raw["links"], list)):
        raise ValueError("directed municipal transfer review schema/version mismatch; v1 is not accepted")
    links = []
    for row in raw["links"]:
        link = ReviewedWalkingLink(**row)
        links.append(DirectedWalkLink(link, expected[link.from_stop_id.split(":", 1)[0]],
                                     expected[link.to_stop_id.split(":", 1)[0]]))
    return tuple(links)


class _MunicipalNetworkEngine(GtfsRouteEngine):
    def __init__(self, context, *, snapshot, **kwargs):
        self.context = context
        super().__init__(None, network_snapshot=snapshot, **kwargs)

    def _ride_step(self, leg, index):
        step = super()._ride_step(leg, index)
        coverage = self.context.coverages[leg.trip_id.split(":", 1)[0]]
        step["fare_context"] = coverage.context_for_step(step)
        step["timetable_only"] = True
        return step


class YokohamaMunicipalRouteBackend:
    def __init__(self, bus_coverage, subway_coverage, *, transfer_links=(), **kwargs):
        self.bus_coverage, self.subway_coverage = bus_coverage, subway_coverage
        self.transfer_links = tuple(transfer_links)
        if any(not isinstance(link, DirectedWalkLink) for link in self.transfer_links):
            raise ValueError("municipal v2 requires separately reviewed directed walking links")
        self.context = build_shared_municipal_network(bus_coverage, subway_coverage,
            policy_id="yokohama_welfare_special_pass", walking_links=self.transfer_links, costs=NetworkCosts())
        self.kwargs = kwargs
        self.policy_id = None

    def for_fare_policy(self, policy_id):
        if policy_id not in PASS_IDS:
            raise RouteInputError(f"unsupported Yokohama route fare policy: {policy_id!r}")
        scoped = copy.copy(self)
        scoped.policy_id = policy_id
        return scoped

    def search(self, request):
        if self.policy_id not in PASS_IDS:
            raise RouteInputError("municipal search requires explicit fare policy scope")
        if request.departure_at.utcoffset() != timedelta(hours=9):
            raise RouteInputError("municipal search requires Asia/Tokyo local time")
        snapshot = self.context.snapshot
        if request.bus_only:
            bus = snapshot.datasets[0]
            allowed = {key for key in snapshot.allowed_trip_ids if key in bus.trips}
            snapshot = build_transit_network((bus,), allowed_trip_ids=allowed,
                walking_links=(), costs=snapshot.costs)
        engine = _MunicipalNetworkEngine(self.context, snapshot=snapshot, **self.kwargs)
        result = engine.search(request)
        return RouteSearchResult(result.candidates, {**result.meta,
            "search_scope": self.policy_id, "timetable_only": True,
            "covered_modes": ["bus"] if request.bus_only else ["bus", "rail"],
            "unreviewed_transport_excluded": True,
            "unverified_walking_transfers_excluded": True,
            "reviewed_transfer_links": len(self.transfer_links),
            "walking_transfer_basis": "reviewed_links_only",
            "coverage_notice": "無料区間・方向別徒歩接続の確認済み範囲のみ検索します。"})
