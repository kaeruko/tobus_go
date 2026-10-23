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
from urllib.parse import urlparse

from transport_scope import TOEI_BUS, TOEI_SUBWAY, TOKYO_METRO, transport_for_line_node
from walking_access import walking_elapsed_minutes
from reviewed_walk_time import validate_reviewed_walk_timing
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
TRANSFER_SCHEMA = "tokyo_metro_reviewed_transfer/v1"
_TRANSFER_EVIDENCE_HOSTS = frozenset((
    "tokyometro.jp", "www.tokyometro.jp",
    "kotsu.metro.tokyo.jp", "www.kotsu.metro.tokyo.jp",
    "odpt.org", "www.odpt.org", "developer.odpt.org", "ckan.odpt.org",
))


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


def _reviewed_transfers(path: str | None) -> dict[frozenset[str], dict]:
    """Load explicit path distance/time evidence, or fail closed with none."""
    if path is None:
        return {}
    payload = _json(path)
    if not isinstance(payload, dict) or set(payload) != {"schema", "transfers"}:
        raise ValueError("Tokyo Metro reviewed transfer manifest has an invalid envelope")
    if payload["schema"] != TRANSFER_SCHEMA or not isinstance(payload["transfers"], list):
        raise ValueError("Tokyo Metro reviewed transfer manifest has an unsupported schema")
    result = {}
    required = {
        "from_station_id", "to_station_id", "minimum_minutes",
        "walking_distance_meters", "evidence_urls", "reviewed_at",
    }
    for index, item in enumerate(payload["transfers"]):
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError(f"Tokyo Metro reviewed transfer #{index} has invalid fields")
        first, second = item["from_station_id"], item["to_station_id"]
        if not all(isinstance(value, str) and value.startswith("odpt.Station:")
                   for value in (first, second)) or first == second:
            raise ValueError(f"Tokyo Metro reviewed transfer #{index} has invalid station IDs")
        minutes, meters = item["minimum_minutes"], item["walking_distance_meters"]
        if type(minutes) is not int or minutes < 1:
            raise ValueError(f"Tokyo Metro reviewed transfer #{index} has invalid minutes")
        if type(meters) not in (int, float) or not math.isfinite(meters) or not 0 < meters <= 600:
            raise ValueError(f"Tokyo Metro reviewed transfer #{index} has invalid walking distance")
        validate_reviewed_walk_timing(meters, minutes)
        urls = item["evidence_urls"]
        if not isinstance(urls, list) or not urls or any(
            not isinstance(url, str) or urlparse(url).scheme != "https"
            or urlparse(url).hostname not in _TRANSFER_EVIDENCE_HOSTS
            for url in urls
        ):
            raise ValueError(f"Tokyo Metro reviewed transfer #{index} lacks official evidence")
        try:
            reviewed_at = dt.date.fromisoformat(item["reviewed_at"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"Tokyo Metro reviewed transfer #{index} has invalid review date") from error
        pair = frozenset((first, second))
        if pair in result:
            raise ValueError(f"Tokyo Metro reviewed transfer #{index} duplicates a station pair")
        result[pair] = {
            "minutes": minutes,
            "meters": float(meters),
            "evidence_urls": tuple(urls),
            "reviewed_at": reviewed_at.isoformat(),
        }
    return result


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
    reviewed_transfers_path: str | None = None,
    walk_radius: int = 300,
) -> TokyoMetroFeedInfo:
    """Atomically validate inputs, then add Metro nodes, runs and allowed walks."""

    info = inspect_tokyo_metro_feed(gtfs_dir)
    reviewed_transfers = _reviewed_transfers(reviewed_transfers_path)
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

    # Rail transfers require both an official ODPT connectingStation relation
    # and reviewed path distance/time evidence. A relation alone verifies only
    # topology; station-coordinate distance is not a platform/gate walk.
    mapped_station_ids = set(stop_to_station.values())
    official_pairs = set()
    for station_id in mapped_station_ids:
        station = station_by_id[station_id]
        connections = station.get("odpt:connectingStation") or ()
        if isinstance(connections, str):
            connections = (connections,)
        for target_id in connections:
            official_pairs.add(frozenset((station_id, target_id)))

    added_transfer_pairs = set()
    for pair, review in reviewed_transfers.items():
        if pair not in official_pairs:
            raise ValueError(
                "Tokyo Metro reviewed transfer lacks an official connectingStation relation: "
                f"{sorted(pair)!r}"
            )
        first_id, second_id = sorted(pair)
        source, target = ("phys", first_id), ("phys", second_id)
        if source not in graph or target not in graph:
            raise ValueError(f"Tokyo Metro reviewed transfer references an unloaded station: {sorted(pair)!r}")
        services = (
            set(graph.nodes[source].get("transport_services") or ()),
            set(graph.nodes[target].get("transport_services") or ()),
        )
        if not all(value.intersection((TOKYO_METRO, TOEI_SUBWAY)) for value in services) \
                or TOKYO_METRO not in services[0] | services[1]:
            raise ValueError(f"Tokyo Metro reviewed transfer has invalid operators: {sorted(pair)!r}")
        edge = {
            "w": WALK_COST * review["minutes"],
            "etype": "walk",
            "meters": review["meters"],
            "reviewed_walk_minutes": review["minutes"],
            "evidence_urls": review["evidence_urls"],
            "reviewed_at": review["reviewed_at"],
            "official_connection": True,
            "transfer_time_basis": "reviewed_station_path",
        }
        graph.add_edge(source, target, **edge)
        graph.add_edge(target, source, **edge)
        added_transfer_pairs.add(pair)

    # Every reviewed entry must have been applied; unreviewed official
    # connections deliberately remain absent from the search graph.
    if added_transfer_pairs != set(reviewed_transfers):
        raise RuntimeError("Tokyo Metro reviewed transfer application is incomplete")

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
