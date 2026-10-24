"""Validated static Tokyo Metro GTFS integration for the Tokyo graph.

The source archive is intentionally not vendored: ODPT's Basic License allows
application use but not redistribution of a reusable copy of the dataset.
"""

from __future__ import annotations

import csv
import copy
import datetime as dt
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass

from transport_scope import TOEI_BUS, TOEI_SUBWAY, TOKYO_METRO, transport_for_line_node
from walking_access import walking_elapsed_minutes
from tokyo_metro_transfer_model import (
    LEGACY_SCHEMA,
    POLICY_SCHEMA,
    automatic_path_class,
    load_transfer_policy,
    relevant_connection,
)
from toei_engine import WALK_COST


REQUIRED_FILES = (
    "agency.txt",
    "calendar.txt",
    "calendar_dates.txt",
    "feed_info.txt",
    "routes.txt",
    "stop_times.txt",
    "stops.txt",
    "translations.txt",
    "trips.txt",
)
TRANSFER_SCHEMA = LEGACY_SCHEMA
TRANSFER_POLICY_SCHEMA = POLICY_SCHEMA


@dataclass(frozen=True, slots=True)
class TokyoMetroFeedInfo:
    version: str
    start_date: dt.date
    end_date: dt.date
    trip_count: int
    stop_count: int
    route_count: int


def _rows(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def _json(path: str):
    with open(path, encoding="utf-8") as source:
        return json.load(source)


def _date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y%m%d").date()


def _minute(value: str) -> int:
    hour, minute, second = (int(part) for part in value.split(":"))
    if second != 0:
        raise ValueError(f"Tokyo Metro GTFS requires whole-minute times: {value!r}")
    return hour * 60 + minute


def _id(value: dict) -> str | None:
    result = value.get("owl:sameAs") or value.get("@id")
    return str(result) if result else None


def _distance_m(first: dict, second: dict) -> float:
    lat1, lon1 = math.radians(first["lat"]), math.radians(first["lon"])
    lat2, lon2 = math.radians(second["lat"]), math.radians(second["lon"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _transfer_policy(path: str | None):
    """Load the common model and its small reviewed-override layer."""
    if path is None:
        return load_transfer_policy({"schema": LEGACY_SCHEMA, "transfers": []})
    return load_transfer_policy(_json(path))


def _reviewed_transfers(path: str | None) -> dict[frozenset[str], dict]:
    """Backward-compatible test/helper view of reviewed overrides."""
    return _transfer_policy(path).overrides


def inspect_tokyo_metro_feed(gtfs_dir: str) -> TokyoMetroFeedInfo:
    root = os.path.realpath(gtfs_dir)
    missing = [name for name in REQUIRED_FILES if not os.path.isfile(os.path.join(root, name))]
    if missing:
        raise FileNotFoundError(f"Tokyo Metro GTFS is missing: {', '.join(missing)}")
    agencies = _rows(os.path.join(root, "agency.txt"))
    if len(agencies) != 1 or agencies[0].get("agency_id") != "tokyometro":
        raise ValueError("Tokyo Metro GTFS agency_id must be exactly 'tokyometro'")
    routes = _rows(os.path.join(root, "routes.txt"))
    if not routes or any(row.get("agency_id") != "tokyometro" or row.get("route_type") != "1" for row in routes):
        raise ValueError("Tokyo Metro GTFS must contain only Tokyo Metro subway routes")
    info_rows = _rows(os.path.join(root, "feed_info.txt"))
    if len(info_rows) != 1 or info_rows[0].get("feed_publisher_name") != "東京メトロ":
        raise ValueError("Tokyo Metro GTFS feed_info publisher is invalid")
    info = info_rows[0]
    start, end = _date(info["feed_start_date"]), _date(info["feed_end_date"])
    if end < start:
        raise ValueError("Tokyo Metro GTFS effective period is inverted")
    return TokyoMetroFeedInfo(
        version=info["feed_version"],
        start_date=start,
        end_date=end,
        trip_count=len(_rows(os.path.join(root, "trips.txt"))),
        stop_count=len(_rows(os.path.join(root, "stops.txt"))),
        route_count=len(routes),
    )


def add_tokyo_metro_to_graph(
    graph,
    timetable_manager,
    *,
    gtfs_dir: str,
    stations_path: str,
    railways_path: str,
    counterpart_stations_path: str | None = None,
    reviewed_transfers_path: str | None = None,
    walk_radius: int = 300,
) -> TokyoMetroFeedInfo:
    """Atomically validate inputs, then add Metro nodes, runs and allowed walks."""

    info = inspect_tokyo_metro_feed(gtfs_dir)
    transfer_policy = _transfer_policy(reviewed_transfers_path)
    reviewed_transfers = transfer_policy.overrides
    def qualified(source_id: str) -> str:
        return f"tokyo_metro:{source_id}"

    stop_rows = _rows(os.path.join(gtfs_dir, "stops.txt"))
    route_rows = _rows(os.path.join(gtfs_dir, "routes.txt"))
    trip_rows = _rows(os.path.join(gtfs_dir, "trips.txt"))
    stops = {row["stop_id"]: row for row in stop_rows}
    routes = {row["route_id"]: row for row in route_rows}
    trips = {row["trip_id"]: row for row in trip_rows}
    service_calendar = {}
    for row in _rows(os.path.join(gtfs_dir, "calendar.txt")):
        service_calendar[row["service_id"]] = {
            "weekdays": tuple(
                row[name] == "1" for name in
                ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
            ),
            "start_date": row["start_date"],
            "end_date": row["end_date"],
        }
    service_exceptions = defaultdict(dict)
    for row in _rows(os.path.join(gtfs_dir, "calendar_dates.txt")):
        service_exceptions[row["date"]][row["service_id"]] = int(row["exception_type"])
    stop_times = defaultdict(list)
    for row in _rows(os.path.join(gtfs_dir, "stop_times.txt")):
        trip_id, stop_id = row["trip_id"], row["stop_id"]
        if trip_id not in trips or stop_id not in stops:
            raise ValueError(f"Tokyo Metro stop_time has an unknown trip/stop: {trip_id}/{stop_id}")
        if not row.get("arrival_time") or not row.get("departure_time"):
            # Non-stopping pass-through records are not boardable and do not
            # assert an invented clock. Adjacent timed calls remain one run.
            continue
        pickup_type = int(row.get("pickup_type") or "0")
        drop_off_type = int(row.get("drop_off_type") or "0")
        if pickup_type not in (0, 1) or drop_off_type not in (0, 1):
            raise ValueError(
                "Tokyo Metro GTFS has an unsupported conditional pickup/drop-off: "
                f"{trip_id}/{stop_id}"
            )
        stop_times[trip_id].append((
            int(row["stop_sequence"]), stop_id,
            _minute(row["arrival_time"]), _minute(row["departure_time"]),
            pickup_type, drop_off_type,
        ))
    stations = _json(stations_path)
    railways = _json(railways_path)
    if not isinstance(stations, list) or not isinstance(railways, list):
        raise ValueError("Tokyo Metro ODPT station and railway masters must be lists")

    station_by_code = {}
    station_by_id = {}
    for station in stations:
        if station.get("odpt:operator") != "odpt.Operator:TokyoMetro":
            raise ValueError("Tokyo Metro station master contains another operator")
        station_id = _id(station)
        code = str(station.get("odpt:stationCode") or "").strip()
        titles = station.get("odpt:stationTitle") or {}
        if not station_id or not code or not all(titles.get(key) for key in ("ja", "en", "ko", "zh-Hans", "zh-Hant")):
            raise ValueError(f"Tokyo Metro station lacks identity or translations: {station_id!r}")
        previous = station_by_code.get(code)
        if previous is not None:
            previous_id = _id(previous) or ""
            # The official GTFS intentionally represents main/branch M06 as
            # one stop. Prefer the non-branch ODPT identity for that stop.
            if "Branch" not in previous_id and "Branch" in station_id:
                station_by_id[station_id] = station
                continue
            if "Branch" in previous_id and "Branch" not in station_id:
                station_by_code[code] = station
            else:
                raise ValueError(f"ambiguous duplicate Tokyo Metro station code: {code}")
        else:
            station_by_code[code] = station
        station_by_id[station_id] = station

    railway_by_title = {}
    for railway in railways:
        if railway.get("odpt:operator") != "odpt.Operator:TokyoMetro":
            raise ValueError("Tokyo Metro railway master contains another operator")
        railway_id = _id(railway)
        titles = railway.get("odpt:railwayTitle") or {}
        if not railway_id or not titles.get("ja") or not titles.get("en"):
            raise ValueError("Tokyo Metro railway lacks official bilingual titles")
        railway_by_title[titles["ja"]] = (railway_id, titles)

    stop_to_station = {}
    for stop_id, raw in stops.items():
        code = raw.get("stop_code", "").strip()
        station = station_by_code.get(code)
        if station is None:
            raise ValueError(f"GTFS stop has no matching official ODPT station code: {stop_id}/{code}")
        station_id = _id(station)
        stop_to_station[stop_id] = station_id
    qualified_stop_ids = {
        stop_id: qualified(stop_id) for stop_id in stop_to_station
    }

    # Tag the legacy graph before adding a third service.
    for node, data in graph.nodes(data=True):
        if node[0] == "line":
            service = transport_for_line_node(node, data)
            if service:
                data["transport_service"] = service
    for node, data in graph.nodes(data=True):
        if node[0] != "phys":
            continue
        services = set(data.get("transport_services") or ())
        for neighbor in set(graph.predecessors(node)) | set(graph.successors(node)):
            if neighbor[0] == "line":
                service = graph.nodes[neighbor].get("transport_service")
                if service:
                    services.add(service)
        data["transport_services"] = frozenset(services)

    for stop_id, station_id in stop_to_station.items():
        station = station_by_id[station_id]
        titles = station["odpt:stationTitle"]
        node = ("phys", station_id)
        values = {
            "lat": float(station["geo:lat"]),
            "lon": float(station["geo:long"]),
            "name": titles["ja"],
            "name_en": titles["en"],
            "name_ko": titles["ko"],
            "name_zh_hans": titles["zh-Hans"],
            "name_zh_hant": titles["zh-Hant"],
            "station_code": station["odpt:stationCode"],
            "gtfs_stop_id": qualified(stop_id),
            "kind": "phys",
            "transport_services": frozenset((TOKYO_METRO,)),
        }
        if node in graph:
            raise ValueError(f"Tokyo Metro station collides with existing graph node: {station_id}")
        graph.add_node(node, **values)

    route_map = {}
    for raw_route_id, route in routes.items():
        title = str(route.get("route_long_name") or "").strip()
        official = railway_by_title.get(title)
        if official is None:
            raise ValueError(f"GTFS route has no matching ODPT railway: {raw_route_id}/{title}")
        route_map[raw_route_id] = official

    def line_node(station_id: str, raw_route_id: str):
        railway_id, titles = route_map[raw_route_id]
        node = ("line", station_id, railway_id)
        if node not in graph:
            base = graph.nodes[("phys", station_id)]
            graph.add_node(
                node,
                lat=base["lat"], lon=base["lon"],
                name=f'{base["name"]}@{titles["ja"]}',
                name_en=f'{base["name_en"]}@{titles["en"]}',
                line=railway_id, kind="line", disp=titles["ja"],
                disp_en=titles["en"], mode="rail",
                route_id=qualified(raw_route_id),
                operator_id="tokyo_metro", transport_service=TOKYO_METRO,
            )
            graph.add_edge(("phys", station_id), node, w=5.0, etype="board")
            graph.add_edge(node, ("phys", station_id), w=0, etype="alight")
        return node

    trip_meta = {row["trip_id"]: row for row in trip_rows}
    patterns_by_service = defaultdict(list)
    run_metadata = {}
    for trip_id, occurrences in stop_times.items():
        trip = trip_meta[trip_id]
        raw_route_id = trip["route_id"]
        service_id = trip["service_id"]
        usable = sorted(occurrences)
        if any(item[4] != 0 for item in usable[1:-1]):
            raise ValueError(
                f"Tokyo Metro GTFS has an interior no-pickup occurrence: {trip_id}"
            )
        if any(item[5] != 0 for item in usable[1:-1]):
            raise ValueError(
                f"Tokyo Metro GTFS has an interior no-drop-off occurrence: {trip_id}"
            )
        # The current reviewed rail transition has no per-occurrence pickup
        # flag. The official feed uses restrictions only at the first/last
        # timed call, which can be represented exactly by excluding that
        # boundary segment. Any future interior restriction fails above.
        if usable and usable[0][4] == 1:
            usable = usable[1:]
        if usable and usable[-1][5] == 1:
            usable = usable[:-1]
        qualified_trip_id = qualified(trip_id)
        qualified_route_id = qualified(raw_route_id)
        run_segments = []
        for timed_sequence, (first, second) in enumerate(zip(usable, usable[1:])):
            sequence, stop_id, _arrival, departure, _pickup, _drop_off = first
            _, next_stop_id, next_arrival, _, _next_pickup, _next_drop_off = second
            station_id = stop_to_station[stop_id]
            next_station_id = stop_to_station[next_stop_id]
            u = line_node(station_id, raw_route_id)
            v = line_node(next_station_id, raw_route_id)
            if not graph.has_edge(u, v):
                graph.add_edge(u, v, w=2.0, etype="ride", line=u[2], mode="rail")
            record = {
                "dep": departure,
                "arr": next_arrival,
                "origin_id": station_id,
                "next_sta": next_station_id,
                "train_num": trip_id,
                "run_key": qualified_trip_id,
                "stop_sequence": timed_sequence,
                "service_id": service_id,
                "trip_id": qualified_trip_id,
                "route_id": qualified_route_id,
                # Exact GTFS service activation is applied before these
                # records reach TimetableChoices.  An empty legacy calendar
                # marker therefore means "already filtered for this date"
                # and lets immutable source records be shared per query.
                "calendar": "",
                "operator_id": "tokyo_metro",
                "origin_gtfs_stop_id": qualified_stop_ids[stop_id],
                "next_gtfs_stop_id": qualified_stop_ids[next_stop_id],
            }
            patterns_by_service[service_id].append(record)
            run_segments.append(record)
            calendar = service_calendar.get(service_id)
            if calendar is None:
                raise ValueError(f"Tokyo Metro trip references unknown service_id: {service_id}")
        run_metadata[qualified_trip_id] = {
            "trip_id": qualified_trip_id,
            "route_id": qualified_route_id,
            "service_id": service_id,
            "segments": tuple(run_segments),
        }

    timetable_manager.tokyo_metro_service_calendar = service_calendar
    timetable_manager.tokyo_metro_service_exceptions = dict(service_exceptions)
    timetable_manager.tokyo_metro_patterns_by_service = {
        service_id: tuple(records)
        for service_id, records in patterns_by_service.items()
    }
    timetable_manager.tokyo_metro_run_metadata = run_metadata
    timetable_manager.tokyo_metro_feed_version = info.version
    timetable_manager.tokyo_metro_feed_start_date = info.start_date.isoformat()
    timetable_manager.tokyo_metro_feed_end_date = info.end_date.isoformat()
    timetable_manager.tokyo_metro_data_obtained_at = (
        dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    )

    # ODPT connectingStation is the only automatic topology source.  Automatic
    # links additionally require the relation in both source records.  The
    # common model consumes the full existing per-segment walking budget
    # without pretending that it measured a 600 m physical path.  Different-
    # station links remain fail-closed unless they have a reviewed override.
    mapped_station_ids = set(stop_to_station.values())
    connection_station_by_id = dict(station_by_id)
    if counterpart_stations_path is not None:
        counterpart_stations = _json(counterpart_stations_path)
        if not isinstance(counterpart_stations, list):
            raise ValueError("Tokyo counterpart ODPT station master must be a list")
        for station in counterpart_stations:
            station_id = _id(station)
            if station_id and relevant_connection(station_id):
                connection_station_by_id[station_id] = station

    directed_official_pairs = set()
    official_pairs = set()
    for station_id, station in connection_station_by_id.items():
        connections = station.get("odpt:connectingStation") or ()
        if isinstance(connections, str):
            connections = (connections,)
        for target_id in connections:
            target_id = str(target_id)
            if relevant_connection(target_id) and station_id != target_id:
                directed_official_pairs.add((station_id, target_id))
                official_pairs.add(frozenset((station_id, target_id)))

    unknown_reviews = set(reviewed_transfers) - official_pairs
    if unknown_reviews:
        raise ValueError(
            "Tokyo Metro reviewed transfer lacks an official connectingStation relation: "
            f"{sorted(map(sorted, unknown_reviews))!r}"
        )
    unknown_exceptions = set(transfer_policy.exceptions) - official_pairs
    if unknown_exceptions:
        raise ValueError(
            "Tokyo Metro transfer exception lacks an official connectingStation relation: "
            f"{sorted(map(sorted, unknown_exceptions))!r}"
        )

    def canonical_station(station_id: str):
        direct = ("phys", station_id)
        if direct in graph:
            return direct
        station = station_by_id.get(station_id)
        if station is not None:
            canonical = station_by_code.get(str(station.get("odpt:stationCode") or ""))
            if canonical is not None:
                candidate = ("phys", _id(canonical))
                if candidate in graph:
                    return candidate
        return None

    counts = defaultdict(int)
    details = []
    canonical_pairs = {}
    added_transfer_pairs = set()
    for pair in sorted(official_pairs, key=lambda value: tuple(sorted(value))):
        counts["official_pairs"] += 1
        first_id, second_id = sorted(pair)
        source, target = canonical_station(first_id), canonical_station(second_id)
        if source is None or target is None:
            counts["unloaded_station"] += 1
            details.append({"pair": tuple(sorted(pair)), "status": "unloaded_station"})
            continue
        if source == target:
            counts["same_physical_node"] += 1
            details.append({"pair": tuple(sorted(pair)), "status": "same_physical_node"})
            continue
        canonical_pair = frozenset((source, target))
        if canonical_pair in canonical_pairs:
            counts["duplicate_canonical_pair"] += 1
            details.append({
                "pair": tuple(sorted(pair)), "status": "duplicate_canonical_pair",
                "canonical_of": canonical_pairs[canonical_pair],
            })
            continue
        services = (
            set(graph.nodes[source].get("transport_services") or ()),
            set(graph.nodes[target].get("transport_services") or ()),
        )
        if not all(value.intersection((TOKYO_METRO, TOEI_SUBWAY)) for value in services) \
                or TOKYO_METRO not in services[0] | services[1]:
            counts["invalid_operators"] += 1
            details.append({"pair": tuple(sorted(pair)), "status": "invalid_operators"})
            continue

        review = reviewed_transfers.get(pair)
        path_class = automatic_path_class(first_id, second_id)
        reciprocal = (
            (first_id, second_id) in directed_official_pairs
            and (second_id, first_id) in directed_official_pairs
        )
        if review is not None:
            edge = {
                "w": WALK_COST * review["minutes"],
                "etype": "walk",
                "meters": review["meters"],
                "reviewed_walk_minutes": review["minutes"],
                "evidence_urls": review["evidence_urls"],
                "reviewed_at": review["reviewed_at"],
                "official_connection": True,
                "transfer_path_class": review["path_class"],
                "transfer_time_basis": "reviewed_station_path",
                "transfer_time_estimated": False,
                "physical_walk_distance_known": True,
            }
            status = "reviewed_override"
        elif transfer_policy.automatic_enabled and path_class is not None:
            if not reciprocal:
                counts["nonreciprocal_official_relation"] += 1
                details.append({
                    "pair": tuple(sorted(pair)),
                    "status": "nonreciprocal_official_relation",
                    "reason": "automatic bidirectional transfer requires reciprocal ODPT records",
                })
                continue
            straight_line_lower_bound = _distance_m(
                graph.nodes[source], graph.nodes[target]
            )
            if straight_line_lower_bound > transfer_policy.automatic_resource_meters:
                counts["straight_line_exceeds_walk_limit"] += 1
                details.append({
                    "pair": tuple(sorted(pair)),
                    "status": "straight_line_exceeds_walk_limit",
                    "straight_line_lower_bound_meters": straight_line_lower_bound,
                })
                continue
            if math.ceil(straight_line_lower_bound / 80.0) > transfer_policy.automatic_minutes:
                raise ValueError(
                    "Tokyo Metro automatic transfer allowance is shorter than "
                    f"its straight-line time floor: {sorted(pair)!r}"
                )
            edge = {
                "w": WALK_COST * transfer_policy.automatic_minutes,
                "etype": "walk",
                # Unknown is not serialized as an invented physical distance.
                "meters": 0.0,
                "walk_resource_meters": transfer_policy.automatic_resource_meters,
                "reviewed_walk_minutes": transfer_policy.automatic_minutes,
                "official_connection": True,
                "transfer_path_class": path_class,
                "transfer_time_basis": "app_conservative_allowance",
                "transfer_time_estimated": True,
                "transfer_time_confidence": "unverified_conservative",
                "physical_walk_distance_known": False,
                "physical_walk_distance_lower_bound_meters": straight_line_lower_bound,
                "walk_constraint_verified": False,
                "official_relation_reciprocal": True,
                "transfer_model_schema": transfer_policy.schema,
            }
            status = "automatic_same_station"
        else:
            counts["unsupported_different_station"] += 1
            details.append({
                "pair": tuple(sorted(pair)),
                "status": "unsupported_different_station",
                "reason": "official relation has different station identities and no reviewed path override",
            })
            continue
        canonical_pairs[canonical_pair] = tuple(sorted(pair))
        exception = transfer_policy.exceptions.get(pair)
        added_directions = []
        for from_id, to_id, from_node, to_node in (
            (first_id, second_id, source, target),
            (second_id, first_id, target, source),
        ):
            if exception is not None:
                direction_name = (
                    "from_to"
                    if from_id == exception["from_station_id"]
                    else "to_from"
                )
                if exception["directions"] not in ("both", direction_name):
                    continue
            directed_edge = dict(edge)
            if exception is not None:
                directed_edge["transfer_available_windows"] = exception["available_windows"]
                directed_edge["transfer_availability_evidence_urls"] = exception["evidence_urls"]
                directed_edge["transfer_availability_reason"] = exception["reason"]
                directed_edge["transfer_direction_evidence"] = exception["directions"]
            graph.add_edge(from_node, to_node, **directed_edge)
            added_directions.append((from_id, to_id))
        if not added_directions:
            raise ValueError(f"Tokyo Metro transfer exception disables every direction: {sorted(pair)!r}")
        added_transfer_pairs.add(pair)
        counts[status] += 1
        details.append({
            "pair": tuple(sorted(pair)), "status": status,
            "canonical_nodes": (source, target),
            "added_directions": tuple(added_directions),
        })

    # Every reviewed override must have been applied.  Automatically unsupported
    # relations remain explicitly reported rather than silently receiving a
    # guessed path or distance.
    if not set(reviewed_transfers).issubset(added_transfer_pairs):
        raise RuntimeError("Tokyo Metro reviewed transfer application is incomplete")
    timetable_manager.tokyo_metro_transfer_model_report = {
        **dict(counts),
        "searchable_raw_pairs": (
            counts["reviewed_override"] + counts["automatic_same_station"]
            + counts["same_physical_node"] + counts["duplicate_canonical_pair"]
        ),
        "added_unique_walk_pairs": len(added_transfer_pairs),
        "policy_schema": transfer_policy.schema,
        "details": tuple(details),
    }

    # Bus access is a pedestrian connection between official coordinates; it
    # does not create an unreviewed rail-to-rail interchange.
    metro_nodes = [("phys", station_id) for station_id in mapped_station_ids]
    bus_nodes = [
        node for node, data in graph.nodes(data=True)
        if node[0] == "phys" and TOEI_BUS in set(data.get("transport_services") or ())
    ]
    for metro_node in metro_nodes:
        for bus_node in bus_nodes:
            distance = _distance_m(graph.nodes[metro_node], graph.nodes[bus_node])
            if distance > walk_radius:
                continue
            minutes = max(1.0, walking_elapsed_minutes(distance, speed_m_per_min=80.0))
            edge = {"w": WALK_COST * minutes, "etype": "walk", "meters": distance}
            graph.add_edge(metro_node, bus_node, **edge)
            graph.add_edge(bus_node, metro_node, **edge)

    return info


def metro_service_is_active(manager, service_id: str, service_date: dt.date) -> bool:
    exceptions = getattr(manager, "tokyo_metro_service_exceptions", {})
    exception = exceptions.get(service_date.strftime("%Y%m%d"), {}).get(service_id)
    if exception is not None:
        return exception == 1
    calendar = getattr(manager, "tokyo_metro_service_calendar", {}).get(service_id)
    if calendar is None:
        return False
    compact = service_date.strftime("%Y%m%d")
    return (
        calendar["start_date"] <= compact <= calendar["end_date"]
        and calendar["weekdays"][service_date.weekday()]
    )


def scoped_timetable_manager(manager, graph, scope, day_type):
    """Return a cheap query-local timetable containing only selected services.

    The reviewed ``TimetableChoices`` transition implementation remains
    unchanged.  Scope and exact GTFS calendar-date filtering happen before it
    sees the records, so unchecked Metro data adds neither choices nor work.
    """

    if not getattr(manager, "tokyo_metro_feed_version", None):
        if TOKYO_METRO in scope:
            from route_engine import RouteEngineUnavailableError
            raise RouteEngineUnavailableError("Tokyo Metro static data is not loaded")
        return manager

    scoped = copy.copy(manager)
    selected_attribute = (
        "train_patterns_weekday" if str(day_type) == "weekday"
        else "train_patterns_weekend"
    )
    source = getattr(manager, selected_attribute, {})
    allowed_stations = {
        node[1] for node in graph.nodes
        if isinstance(node, tuple) and len(node) >= 2 and node[0] == "phys"
    }
    selected = {}
    for station_id, records in source.items():
        if station_id not in allowed_stations:
            continue
        retained = [
            record for record in records
            if record.get("operator_id") != "tokyo_metro"
        ]
        if retained:
            selected[station_id] = retained

    if TOKYO_METRO in scope:
        service_date = getattr(day_type, "service_date", None)
        if not isinstance(service_date, dt.date):
            raise ValueError("Tokyo Metro search requires an exact service date")
        feed_start = dt.date.fromisoformat(manager.tokyo_metro_feed_start_date)
        feed_end = dt.date.fromisoformat(manager.tokyo_metro_feed_end_date)
        if not feed_start <= service_date <= feed_end:
            from route_engine import RouteInputError
            raise RouteInputError(
                "Tokyo Metro service date is outside the loaded GTFS period: "
                f"{feed_start.isoformat()}..{feed_end.isoformat()}"
            )
        if str(day_type) not in {"weekday", "saturday", "holiday"}:
            raise ValueError(f"unsupported Tokyo Metro day type: {day_type!r}")
        by_service = getattr(manager, "tokyo_metro_patterns_by_service", {})
        for service_id, records in by_service.items():
            if not metro_service_is_active(manager, str(service_id), service_date):
                continue
            for source_record in records:
                origin_id = source_record["origin_id"]
                if origin_id not in allowed_stations:
                    continue
                selected.setdefault(origin_id, []).append(source_record)

    for records in selected.values():
        records.sort(key=lambda row: (row["dep"], row.get("run_key", ""), row.get("stop_sequence", -1)))
    # TimetableChoices reads exactly one of these based on day_type. Keeping
    # the other empty makes accidental cross-calendar use fail closed.
    scoped.train_patterns_weekday = selected if selected_attribute.endswith("weekday") else {}
    scoped.train_patterns_weekend = selected if selected_attribute.endswith("weekend") else {}
    return scoped


def enrich_selected_metro_run(manager, selected_run: dict) -> dict:
    """Verify and attach immutable GTFS identity to a selected Metro run."""

    run_key = selected_run.get("run_key")
    metadata = getattr(manager, "tokyo_metro_run_metadata", {}).get(run_key)
    if metadata is None:
        raise ValueError(f"Tokyo Metro selected run is unknown: {run_key!r}")
    records = selected_run.get("segment_records")
    if not isinstance(records, list) or not records:
        raise ValueError("Tokyo Metro selected run has no segments")
    source_segments = {item["stop_sequence"]: item for item in metadata["segments"]}
    decorated = []
    for record in records:
        sequence = record.get("stop_sequence")
        source = source_segments.get(sequence)
        if source is None or any(
            record.get(key) != source[key]
            for key in ("origin_id", "next_sta", "dep", "arr")
        ):
            raise ValueError(
                f"Tokyo Metro selected segment disagrees with GTFS: {run_key!r}/{sequence!r}"
            )
        decorated.append({
            **record,
            "trip_id": metadata["trip_id"],
            "route_id": metadata["route_id"],
            "service_id": metadata["service_id"],
            "origin_gtfs_stop_id": source["origin_gtfs_stop_id"],
            "next_gtfs_stop_id": source["next_gtfs_stop_id"],
        })
    return {
        **selected_run,
        "trip_id": metadata["trip_id"],
        "route_id": metadata["route_id"],
        "service_id": metadata["service_id"],
        "origin_gtfs_stop_id": decorated[0]["origin_gtfs_stop_id"],
        "destination_gtfs_stop_id": decorated[-1]["next_gtfs_stop_id"],
        "segment_records": decorated,
    }
