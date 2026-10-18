"""Opt-in Sendai coordinate/result adapter over the unchanged practical v2 clock.

Exact poles and directional reviews take precedence. General coordinates use
explicitly unverified geometric access to concrete bus poles only. Such access
never creates a public-transport transfer or approves a subway entrance.
"""
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction
import hashlib
import math
from time import monotonic

from route_engine import RouteCandidate, RouteInputError, RoutePreference, RouteSearchLimitError, RouteSearchResult, WalkStep
from sendai_coordinate_access import COORDINATE_ACCESS_RULES
from sendai_practical_network import CivilMinute, PracticalRide, search_practical_subway
from sendai_practical_serializer import civil_clock, serialize_practical_journey
from transit_timetable_choices import NetworkSearchParameters
from transit_network_core import coordinate_pair_objective
from walking_access import nearby_stops, reviewed_coordinate_endpoint, walking_minutes, walking_display_meters, walking_metrics

# Initial evaluation scope, inherited from the common GTFS coordinate backend;
# neither a Sendai optimum nor evidence that any point is physically walkable.
GENERAL_RADIUS_M = 600
GENERAL_CANDIDATE_LIMIT = 6

POLICY = "sendai_fureai_pass"
KEIRO_POLICY = "sendai_keiro_pass"
NOTICE = ("仙台・開発検証用。地下鉄は公式発車時刻と到着目安、バスはGTFS予定時刻です。"
          "徒歩・乗換時間と余裕は未実測の計画仮定で、接続・到着を保証しません。"
          "通常運賃は不明。本人の有効なふれあい乗車証所持・明示選択が前提です。"
          "地図の線は停車点を結ぶ概略線で、実歩行経路ではありません。")
KEIRO_NOTICE = ("敬老乗車証はチャージ残高から運賃が引かれます。実際の引落額は未計算です。"
                "検索対象はレビュー済みの市営バス・地下鉄の区間に限定しています。")


class SendaiCoordinateScope:
    """Connection adapter implementing the existing RouteEngine boundary."""
    verified_quote_policy_ids = frozenset({POLICY})

    def __init__(self, normal_backend, network, operating_period, *, environment, access_reviews=(),
                 normal_backend_factory=None):
        if environment not in ("development", "lambda"):
            raise ValueError("Sendai coordinate scope requires an explicit reviewed runtime")
        self.environment = environment
        if normal_backend is None and not callable(normal_backend_factory):
            raise ValueError("explicit original normal backend or factory required")
        self._normal_backend = normal_backend
        self._normal_backend_factory = normal_backend_factory
        self.network = network
        self.period = operating_period
        self.access_reviews = tuple(access_reviews)
        snapshot = network.free_scope.snapshot
        served = {r.stop_id for t in network.free_scope.allowed_trip_ids
                  for r in snapshot.rows_by_trip[t] if t.startswith("sendai_bus:")}
        self.bus_stops = {key: snapshot.stops[key] for key in served}
        rows = [r.source for t in network.free_scope.allowed_trip_ids if t.startswith('sendai_bus:')
                for r in snapshot.rows_by_trip[t]]
        self.boarding_stops = {r.stop_id for r in rows if r.pickup_type == 0}
        self.alighting_stops = {r.stop_id for r in rows if r.drop_off_type == 0}

    @property
    def normal_backend(self):
        if self._normal_backend is None:
            # The opt-in scope does not need a second graph for every loaded
            # bus. Construct the unchanged normal backend on explicit demand.
            # Exceptions propagate; no alternate backend/source is attempted.
            self._normal_backend = self._normal_backend_factory()
        return self._normal_backend

    def search(self, request):
        # No pass selection keeps the original normal-fare coordinate backend.
        return self.normal_backend.search(request)

    def for_fare_policy(self, policy_id):
        if policy_id not in (POLICY, KEIRO_POLICY):
            raise RouteInputError(f"unsupported Sendai reviewed fare scope: {policy_id!r}")
        return _SelectedScope(self, policy_id)

    def endpoint(self, point, role):
        return reviewed_coordinate_endpoint(point, role, stops=self.bus_stops,
            boarding_stops=self.boarding_stops, reviews=self.access_reviews,
            rules=COORDINATE_ACCESS_RULES)


    def endpoint_candidates(self, point, role):
        if role not in ("origin", "destination"):
            raise RouteInputError("coordinate role must be origin or destination")
        explicit = reviewed_coordinate_endpoint(point, role, stops=self.bus_stops,
            boarding_stops=self.boarding_stops, reviews=self.access_reviews,
            rules=COORDINATE_ACCESS_RULES, require_explicit=False)
        permitted = self.boarding_stops if role == "origin" else self.alighting_stops
        if explicit is not None:
            # Preserve the explicit pole/transfer contract. A boarding-only
            # bay can also be the endpoint of an already reviewed rail access;
            # the shared graph still enforces each actual bus ride's flags.
            values = (explicit,)
            return values, {"scope": "explicit", "eligible_count": len(values), "omitted_stop_ids": []}
        role_stops = {key: stop for key, stop in self.bus_stops.items() if key in permitted}
        nearby = nearby_stops(role_stops, point.lat, point.lon,
            radius_m=GENERAL_RADIUS_M, candidate_limit=len(role_stops))
        values = tuple({"stop_id": stop.id, "minutes": walking_minutes(meters),
            "meters": walking_display_meters(meters), "geometric_distance_meters": meters,
            "basis": "haversine_80m_per_minute_estimate", "label": stop.name,
            "source_stop_id": stop.id, "feed_version": self.network.free_scope.snapshot.feed_versions["sendai_bus"],
            "path_description": "一般地点とGTFS具体標柱間の直線距離を80m/分で換算。道路・横断・河川・建物出口の通行可能性は未確認",
            "physical_walk_meters": None, "walking_time_measured": False,
            "walking_distance_measured": False, "connection_guaranteed": False,
            "walking_connection_verified": False}
            for stop, meters in nearby[:GENERAL_CANDIDATE_LIMIT])
        return values, {"scope": "geometric_estimate", "radius_m": GENERAL_RADIUS_M,
            "candidate_limit": GENERAL_CANDIDATE_LIMIT, "eligible_count": len(nearby),
            "selected_stop_ids": [v["stop_id"] for v in values],
            "omitted_stop_ids": [stop.id for stop, _ in nearby[GENERAL_CANDIDATE_LIMIT:]],
            "outside_radius_compared": False, "physical_walkability_verified": False}


class _SelectedScope:
    def __init__(self, adapter, policy_id):
        self.adapter = adapter
        self.policy_id = policy_id

    def search(self, request):
        a = self.adapter
        if request.accept_experimental_transfer_model is not True:
            raise RouteInputError("explicit experimental access/transfer-model consent required")
        if request.preference not in (RoutePreference.FASTEST, RoutePreference.FEWEST_TRANSFERS):
            raise RouteInputError("Sendai reviewed scope supports time or fewTransfers")
        day = request.departure_at.date()
        mode = "time" if request.preference == RoutePreference.FASTEST else "fewTransfers"
        parameters = NetworkSearchParameters(max_candidates=1, max_boardings=3, max_travel_minutes=180)
        started = monotonic()
        deadline = started + parameters.time_limit_seconds
        materializations = {}  # Immutable date windows, released at request end.
        source_metadata = {}  # One source range/version calculation per request.
        timetable_choices = {}  # At most one existing same-condition provider.
        diagnostic = {"comparison_complete": False, "completed_pairs": 0,
                      "minimum_transit_boardings": 1, "pair_boarding_limits": [],
                      "pair_transit_arrival_ceilings": [],
                      "arrival_bound_basis": "completed_incumbent_final_arrival"
                          if mode == "time" else "unchanged_maximum",
                      "boarding_bound_basis": "completed_incumbent_primary_objective"
                          if mode == "fewTransfers" else "unchanged_maximum"}
        try:
            a.period.require_query_days(day, (day,), additional_reviewed_days=(a.network.bus_reviewed_days,))
            origins, origin_scope = a.endpoint_candidates(request.origin, "origin")
            destinations, destination_scope = a.endpoint_candidates(request.destination, "destination")
            pairs = [(i, j, origin, destination) for i, origin in enumerate(origins)
                     for j, destination in enumerate(destinations)]
            diagnostic.update(origin=origin_scope, destination=destination_scope, total_pairs=len(pairs))
            start = request.departure_at.hour * 60 + request.departure_at.minute
            if any(start + origin["minutes"] >= 1440 for origin in origins):
                raise RouteInputError("access walk crosses an unreviewed civil-day boundary")
            best = None
            for i, j, origin, destination in pairs:
                # Since every accepted journey travels at least one ride,
                # transfers = boardings - 1. In fewTransfers ONLY, a larger
                # boarding count cannot beat a completed incumbent, regardless
                # of cost/arrival. Keep ALL pairs and every equal/lower count;
                # reuse the core's existing hard bound, never discard a pair.
                boarding_limit=parameters.max_boardings
                if mode == "fewTransfers" and best is not None:
                    boarding_limit=min(boarding_limit,
                        sum(isinstance(e,PracticalRide) for e in best[1].events))
                diagnostic["pair_boarding_limits"].append(boarding_limit)
                # time's first completed objective already includes the final
                # walk. Retain equal arrivals (including cheaper ties), using
                # the existing travel-time bound only after original day-scope
                # validation/materialization in the practical connection.
                arrival_ceiling=None
                if mode == "time" and best is not None:
                    arrival_ceiling=best[0][0]-day.toordinal()*1440-destination["minutes"]
                diagnostic["pair_transit_arrival_ceilings"].append(
                    None if arrival_ceiling is None else str(arrival_ceiling))
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise RouteSearchLimitError("Sendai coordinate request deadline exceeded", reason="time_limit")
                journeys = search_practical_subway(a.network, origin["stop_id"], destination["stop_id"],
                    civil_date=day, departure_minute=start + origin["minutes"],
                    parameters=replace(parameters, time_limit_seconds=remaining,
                        max_boardings=boarding_limit,
                        max_travel_minutes=180 - origin["minutes"] - destination["minutes"]),
                    mode=mode, bus_only=request.bus_only,
                    _request_arrival_ceiling=arrival_ceiling,
                    _request_materializations=materializations, _request_deadline=deadline,
                    _request_metadata=source_metadata, _request_choices=timetable_choices)
                if monotonic() > deadline:
                    raise RouteSearchLimitError("Sendai coordinate request deadline exceeded", reason="time_limit")
                for journey in journeys:
                    final_day = _add(journey.arrival_estimate, destination["minutes"]).day
                    dependency_days = (day,) if final_day == day else (day, final_day)
                    a.period.require_query_days(day, dependency_days,
                        additional_reviewed_days=(a.network.bus_reviewed_days,))
                    boards = sum(isinstance(e, PracticalRide) for e in journey.events)
                    objective = coordinate_pair_objective(preference=mode,
                        arrival_minute=_absolute(journey.arrival_estimate),
                        destination_walk_minutes=destination["minutes"], planning_cost=journey.planning_cost,
                        transfers=max(0, boards-1), origin_rank=i, destination_rank=j)
                    if best is None or objective < best[0]:
                        best = objective, journey, origin, destination
                diagnostic["completed_pairs"] += 1
        except RouteSearchLimitError as error:
            diagnostic.update(network_builds=len(materializations),
                timetable_preparations=timetable_choices.get("preparations", 0),
                timetable_reuse_hits=timetable_choices.get("reuse_hits", 0),
                uncompared_pairs=[[o["stop_id"], d["stop_id"]]
                    for _, _, o, d in pairs[diagnostic["completed_pairs"]:]],
                elapsed_seconds=monotonic()-started)
            error.diagnostics["coordinate_access"] = diagnostic
            raise  # Same exception, reason and original core diagnostic.
        except ValueError as error:
            if isinstance(error, RouteInputError):
                raise
            raise RouteInputError(str(error)) from error
        candidates = [] if best is None else [_candidate(a.network, best[1], request, best[2], best[3],
            fare_policy_id=self.policy_id)]
        diagnostic.update(comparison_complete=True, uncompared_pairs=[], network_builds=len(materializations),
            timetable_preparations=timetable_choices.get("preparations", 0),
            timetable_reuse_hits=timetable_choices.get("reuse_hits", 0),
            elapsed_seconds=monotonic()-started, optimality_scope="selected_endpoint_pairs_only",
            all_geographic_candidates_compared=False)
        return RouteSearchResult(candidates, {"destination_reachable": bool(candidates),
            "destination_label": "目的地", "development_only": a.environment == "development",
            "planning_notice": NOTICE if self.policy_id == POLICY else KEIRO_NOTICE,
            "access_scope": "explicit_access_first_then_unverified_geometric_bus_poles",
            "coordinate_access": diagnostic,
            "actual_connection_guaranteed": False, "normal_fare_known": False})


def _absolute(value):
    return value.day.toordinal() * 1440 + value.minute


def _add(value, minutes):
    minute = value.minute + minutes
    days = minute // 1440
    return CivilMinute(value.day + timedelta(days=int(days)), minute - days * 1440)


def _candidate(network, journey, request, origin, destination, *, fare_policy_id=POLICY):
    wire = serialize_practical_journey(journey, fare_policy_id=fare_policy_id)
    snapshot = network.free_scope.snapshot
    steps, lines = [], []
    clock = CivilMinute(request.departure_at.date(), Fraction(request.departure_at.hour*60 + request.departure_at.minute))
    start = clock
    def add(kind, title, from_name, to_name, departure, arrival, *, meters=0, details=None, **extra):
        duration = _absolute(arrival) - _absolute(departure)
        if duration < 0:
            raise ValueError("coordinate serialization reversed scheduled time")
        extra = {
            "departure_time": civil_clock(departure, basis="display")["time"],
            "arrival_time": civil_clock(arrival, basis="display")["time"],
            "planning_details": details, **extra}
        if kind == "walk":
            steps.append(WalkStep(title, from_name, to_name, math.ceil(duration), meters,
                step_id=f"sendai-{len(steps)}", extra=extra).to_mapping())
        else:
            steps.append({"step_id": f"sendai-{len(steps)}", "kind": kind, "title": title,
                "from_": from_name, "to": to_name, "minutes": math.ceil(duration), "meters": meters, **extra})
    def access(endpoint, before):
        nonlocal clock
        if not endpoint["minutes"]:
            return
        end = _add(clock, endpoint["minutes"])
        add("walk", "地点からの徒歩（推定）" if before else "目的地までの徒歩（推定）",
            "現在地" if before else snapshot.stops[endpoint["stop_id"]].name,
            snapshot.stops[endpoint["stop_id"]].name if before else "目的地", clock, end,
            meters=endpoint["meters"], details={**endpoint, "notice": endpoint["path_description"] + "。時間・距離は推定、未実測・未保証。"})
        clock = end
    access(origin, True)
    first_ride = next(i for i,e in enumerate(journey.events) if isinstance(e, PracticalRide))
    last_ride = max(i for i,e in enumerate(journey.events) if isinstance(e, PracticalRide))
    for index, (event, raw) in enumerate(zip(journey.events, wire["events"])):
        if isinstance(event, PracticalRide):
            ride = event.source
            route = snapshot.routes[ride.route_id]
            title = route.short_name or route.long_name
            if _absolute(event.departure) > _absolute(clock):
                add("wait", "発車待ち", snapshot.stops[ride.from_stop_id].name,
                    snapshot.stops[ride.from_stop_id].name, clock, event.departure,
                    details={"notice": "予定発車時刻までの待機。運行保証ではありません。"})
            points = [{"id": s, "name": snapshot.stops[s].name,
                       "lat": snapshot.stops[s].lat, "lon": snapshot.stops[s].lon} for s in ride.stop_ids]
            notice = ("公式発車時刻 → 到着目安（公開発車時計による推定）。到着・接続保証なし。"
                      if ride.mode == "rail" else "GTFS予定発車・予定到着。遅延・到着保証なし。")
            add(ride.mode, title, points[0]["name"], points[-1]["name"], event.departure,
                event.arrival_estimate, details={**raw, "notice": notice}, trip_id=ride.trip_id,
                route_id=ride.route_id, departureStopId=ride.from_stop_id, arrivalPoleId=ride.to_stop_id,
                boarding_minutes=0, stops=points, edges=len(points)-1)
            lines.append(title)
            clock = event.arrival_estimate
        elif raw["kind"] == "standard_transfer":
            ready = event.ready_estimate
            notice = (f"乗換の計画仮定 {event.standard_minutes}分＋余裕{event.margin_minutes}分。"
                      "実歩行距離不明・時間未実測・接続保証なし。" + (event.path_description or ""))
            role = "origin_access" if index < first_ride else "destination_access" if index > last_ride else "transfer"
            add("walk", "駅アクセス（推定・未保証）" if role != "transfer" else "乗換（推定・未保証）", snapshot.stops[event.from_stop_id].name,
                snapshot.stops[event.to_stop_id].name, event.departure_estimate, ready,
                details={**raw, "role": role, "notice": notice})
            clock = ready
        else:
            raise ValueError("coordinate serializer needs an explicit reviewed-walk conversion")
    access(destination, False)
    arrival = clock
    # Details retain original service-day clocks/provenance, exact sequences,
    # and quote from the same concrete-run scope. UI integers are display only.
    # No fictitious free fare for prepaid senior-card riders. Reuse the
    # exact reviewed journey and the shared city fare-policy contract.
    if fare_policy_id == POLICY:
        fare_quote = journey.fare_quote
    else:
        from fare_policy import evaluate_candidate_fare
        fare_quote = evaluate_candidate_fare(
            city_key="sendai", candidate={"steps": steps},
            policy_id=fare_policy_id, normal_fare_yen=None)
    raw = {"id": "sendai-" + hashlib.sha256(repr((wire,origin,destination)).encode()).hexdigest()[:20],
        "lines": lines, "rides": len(lines), "boards": len(lines), "transfers": max(0,len(lines)-1),
        "total_time": math.ceil(_absolute(arrival)-_absolute(start)),
        **walking_metrics(steps), "steps": steps,
        "points": [[p["lat"],p["lon"]] for s in steps for p in s.get("stops",[])],
        "arrival_time": civil_clock(arrival,basis="arrival_estimate")["time"],
        "departure_date": request.departure_at.isoformat(), "preference": request.preference.api_value,
        "origin_coords": request.origin.to_list(), "destination_coords": request.destination.to_list(),
        "fare": fare_quote.to_api_dict(),
        "planning_notice": NOTICE if fare_policy_id == POLICY else KEIRO_NOTICE,
        "planning_journey": wire, "access": {"origin": origin,"destination": destination},
        "arrival_is_estimate": True}
    return RouteCandidate.from_mapping(raw)
