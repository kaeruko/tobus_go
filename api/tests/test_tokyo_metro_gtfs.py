from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import networkx as nx

from app.services.train_realtime import StaticTrainGtfs
from app.services.train_route_identity import enrich_route_result_train_trip_ids
from route_engine import RouteInputError
from toei_engine import MAX_TRAVEL_MIN, SpatialIndex, TimetableManager
from tokyo_metro_gtfs import (
    _reviewed_transfers,
    _transfer_policy,
    add_tokyo_metro_to_graph,
    inspect_tokyo_metro_feed,
    metro_service_is_active,
    enrich_selected_metro_run,
    scoped_timetable_manager,
)
from tokyo_metro_transfer_model import POLICY_SCHEMA
from transport_scope import TOEI_BUS, TOEI_SUBWAY, TOKYO_METRO
from tokyo_route_engine import TokyoRouteEngine


def _write(path, name, content):
    (path / name).write_text(content, encoding="utf-8")


def _station(line, slug, code, title, connections=()):
    return {
        "owl:sameAs": f"odpt.Station:TokyoMetro.{line}.{slug}",
        "odpt:operator": "odpt.Operator:TokyoMetro",
        "odpt:stationCode": code,
        "odpt:stationTitle": {
            "ja": title,
            "en": f"{title} EN",
            "ko": f"{title} KO",
            "zh-Hans": f"{title} ZH",
            "zh-Hant": f"{title} ZHT",
        },
        "geo:lat": 35.68 + int(code[-1]) / 1000,
        "geo:long": 139.76 + int(code[-1]) / 1000,
        "odpt:connectingStation": list(connections),
    }


def _fixture(tmp_path):
    gtfs = tmp_path / "gtfs"
    gtfs.mkdir()
    _write(gtfs, "agency.txt", "agency_id,agency_name,agency_url,agency_timezone\ntokyometro,東京メトロ,https://www.tokyometro.jp/,Asia/Tokyo\n")
    _write(gtfs, "feed_info.txt", "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version\n東京メトロ,https://www.tokyometro.jp/,ja,20260919,20270312,test-v1\n")
    _write(gtfs, "routes.txt", "route_id,agency_id,route_short_name,route_long_name,route_type\n1,tokyometro,,銀座線,1\n2,tokyometro,,半蔵門線,1\n")
    _write(gtfs, "stops.txt", "stop_id,stop_code,stop_name,stop_lat,stop_lon\n101,G01,A,35.681,139.761\n102,G02,B,35.682,139.762\n201,Z01,C,35.683,139.763\n202,Z02,D,35.684,139.764\n")
    _write(gtfs, "trips.txt", "route_id,service_id,trip_id,trip_headsign,direction_id\n"
           "1,0,g-late,B,0\n"
           "2,0,z-too-early,D,0\n"
           "2,0,z-after-transfer,D,0\n"
           "2,1,z-holiday,D,0\n")
    _write(gtfs, "stop_times.txt", "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type\n"
           "g-late,23:55:00,23:55:00,101,1,0,0\ng-late,24:05:00,24:05:00,102,2,0,0\n"
           "z-too-early,24:10:00,24:10:00,201,1,0,0\nz-too-early,24:14:00,24:14:00,202,2,0,0\n"
           "z-after-transfer,24:12:00,24:12:00,201,1,0,0\nz-after-transfer,24:16:00,24:16:00,202,2,0,0\n"
           "z-holiday,10:00:00,10:00:00,201,1,0,0\nz-holiday,10:04:00,10:04:00,202,2,0,0\n")
    _write(gtfs, "calendar.txt", "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n0,1,1,1,1,1,0,0,20260919,20270312\n1,0,0,0,0,0,1,1,20260919,20270312\n")
    _write(gtfs, "calendar_dates.txt", "service_id,date,exception_type\n0,20260921,2\n1,20260921,1\n")
    _write(gtfs, "translations.txt", "table_name,field_name,field_value,language,translation\n")
    stations = [
        _station("Ginza", "A", "G01", "A"),
        _station("Ginza", "B", "G02", "B", ("odpt.Station:TokyoMetro.Hanzomon.C",)),
        _station("Hanzomon", "C", "Z01", "C", ("odpt.Station:TokyoMetro.Ginza.B",)),
        _station("Hanzomon", "D", "Z02", "D"),
    ]
    station_path = tmp_path / "stations.json"
    station_path.write_text(json.dumps(stations, ensure_ascii=False), encoding="utf-8")
    railways = [
        {"owl:sameAs": "odpt.Railway:TokyoMetro.Ginza", "odpt:operator": "odpt.Operator:TokyoMetro", "odpt:railwayTitle": {"ja": "銀座線", "en": "Ginza Line"}},
        {"owl:sameAs": "odpt.Railway:TokyoMetro.Hanzomon", "odpt:operator": "odpt.Operator:TokyoMetro", "odpt:railwayTitle": {"ja": "半蔵門線", "en": "Hanzomon Line"}},
    ]
    railway_path = tmp_path / "railways.json"
    railway_path.write_text(json.dumps(railways, ensure_ascii=False), encoding="utf-8")
    return gtfs, station_path, railway_path


def _common_policy(tmp_path, *, exceptions=(), overrides=()):
    path = tmp_path / "transfer-policy.json"
    path.write_text(json.dumps({
        "schema": POLICY_SCHEMA,
        "automatic_model": {
            "version": "odpt_same_station_conservative/v1",
            "eligible_relation": "same_station_slug",
            "unmatched_relation_policy": "disabled_requires_override",
            "minimum_minutes": 15,
            "walk_resource_meters": 600,
            "distance_basis": "unknown_consumes_full_segment_limit",
            "time_basis": "app_conservative_allowance",
            "official_minimum": False,
        },
        "overrides": list(overrides),
        "exceptions": list(exceptions),
    }), encoding="utf-8")
    return path


def _make_same_station_connection(stations_path):
    stations = json.loads(stations_path.read_text(encoding="utf-8"))
    old = "odpt.Station:TokyoMetro.Hanzomon.C"
    new = "odpt.Station:TokyoMetro.Hanzomon.B"
    stations[1]["odpt:connectingStation"] = [new]
    stations[2]["owl:sameAs"] = new
    stations[2]["odpt:connectingStation"] = [
        "odpt.Station:TokyoMetro.Ginza.B"
    ]
    stations_path.write_text(json.dumps(stations, ensure_ascii=False), encoding="utf-8")
    return "odpt.Station:TokyoMetro.Ginza.B", new


def test_feed_audit_and_import_preserve_exact_runs_calendar_and_24_hour_times(tmp_path):
    gtfs, stations, railways = _fixture(tmp_path)
    info = inspect_tokyo_metro_feed(str(gtfs))
    assert (info.version, info.start_date, info.end_date) == (
        "test-v1", dt.date(2026, 9, 19), dt.date(2027, 3, 12)
    )
    graph = nx.DiGraph()
    graph.add_node(("phys", "bus"), kind="phys", name="bus", name_en="bus",
                   lat=35.681, lon=139.761, transport_services=frozenset((TOEI_BUS,)))
    manager = TimetableManager()
    add_tokyo_metro_to_graph(
        graph, manager, gtfs_dir=str(gtfs), stations_path=str(stations),
        railways_path=str(railways), walk_radius=300,
    )
    a = "odpt.Station:TokyoMetro.Ginza.A"
    record = manager.tokyo_metro_patterns_by_service["0"][0]
    assert record["dep"] == 23 * 60 + 55
    assert record["arr"] == 24 * 60 + 5
    assert record["trip_id"] == "tokyo_metro:g-late"
    assert record["route_id"] == "tokyo_metro:1"
    assert TOKYO_METRO in graph.nodes[("phys", a)]["transport_services"]
    assert metro_service_is_active(manager, "0", dt.date(2026, 9, 22))
    assert not metro_service_is_active(manager, "0", dt.date(2026, 9, 21))
    assert metro_service_is_active(manager, "1", dt.date(2026, 9, 21))
    weekday = type("Day", (str,), {})("weekday")
    weekday.service_date = dt.date(2026, 9, 22)
    scoped = scoped_timetable_manager(
        manager, graph, frozenset((TOKYO_METRO,)), weekday
    )
    assert scoped.train_patterns_weekday[a][0] is record
    assert scoped.train_patterns_weekday[a][0]["calendar"] == ""
    holiday = type("Day", (str,), {})("holiday")
    holiday.service_date = dt.date(2026, 9, 21)
    holiday_scoped = scoped_timetable_manager(
        manager, graph, frozenset((TOKYO_METRO,)), holiday
    )
    assert not any(
        record["service_id"] == "0"
        for records in holiday_scoped.train_patterns_weekend.values()
        for record in records
    )
    weekend_record = manager.tokyo_metro_patterns_by_service["1"][0]
    assert any(
        candidate is weekend_record
        for records in holiday_scoped.train_patterns_weekend.values()
        for candidate in records
    )
    assert weekend_record["calendar"] == ""
    outside = type("Day", (str,), {})("weekday")
    outside.service_date = dt.date(2027, 3, 15)
    with unittest.TestCase().assertRaisesRegex(RouteInputError, "outside"):
        scoped_timetable_manager(
            manager, graph, frozenset((TOKYO_METRO,)), outside
        )
    selected = enrich_selected_metro_run(manager, {
        "run_key": "tokyo_metro:g-late",
        "segment_records": [{
            "origin_id": a,
            "next_sta": "odpt.Station:TokyoMetro.Ginza.B",
            "dep": 23 * 60 + 55,
            "arr": 24 * 60 + 5,
            "stop_sequence": 0,
        }],
    })
    assert selected["origin_gtfs_stop_id"] == "tokyo_metro:101"
    assert selected["destination_gtfs_stop_id"] == "tokyo_metro:102"


def test_committed_transfer_manifest_is_strict_and_reviewed():
    manifest = Path(__file__).resolve().parents[1] / "config" / "tokyo_metro_reviewed_transfers.json"
    policy = _transfer_policy(str(manifest))
    assert policy.schema == POLICY_SCHEMA
    assert policy.automatic_enabled is True
    assert policy.automatic_minutes == 15
    assert policy.automatic_resource_meters == 600
    assert policy.exceptions == {}
    transfers = _reviewed_transfers(str(manifest))
    assert len(transfers) == 4
    assert {
        tuple(sorted(pair))
        for pair in transfers
    } == {
        tuple(sorted(pair))
        for pair in (
            (
                "odpt.Station:TokyoMetro.Hibiya.Ningyocho",
                "odpt.Station:TokyoMetro.Hanzomon.Suitengumae",
            ),
            (
                "odpt.Station:TokyoMetro.Hanzomon.Suitengumae",
                "odpt.Station:Toei.Asakusa.Ningyocho",
            ),
            (
                "odpt.Station:TokyoMetro.Ginza.Toranomon",
                "odpt.Station:TokyoMetro.Hibiya.ToranomonHills",
            ),
            (
                "odpt.Station:TokyoMetro.Ginza.Ginza",
                "odpt.Station:TokyoMetro.Yurakucho.GinzaItchome",
            ),
        )
    }
    assert {item["path_class"] for item in transfers.values()} == {"linked_station"}
    assert MAX_TRAVEL_MIN == 240.0


def test_official_connection_requires_reviewed_transfer(tmp_path):
    gtfs, stations, railways = _fixture(tmp_path)
    graph = nx.DiGraph()
    toei = ("phys", "odpt.Station:Toei.Asakusa.X")
    graph.add_node(toei, kind="phys", name="X", name_en="X", lat=35.6825,
                   lon=139.7625, transport_services=frozenset((TOEI_SUBWAY,)))
    manager = TimetableManager()
    add_tokyo_metro_to_graph(graph, manager, gtfs_dir=str(gtfs),
                             stations_path=str(stations), railways_path=str(railways))
    b = ("phys", "odpt.Station:TokyoMetro.Ginza.B")
    c = ("phys", "odpt.Station:TokyoMetro.Hanzomon.C")
    assert not graph.has_edge(b, c)
    assert not graph.has_edge(b, toei)

    reviewed = tmp_path / "reviewed-transfers.json"
    reviewed.write_text(json.dumps({
        "schema": "tokyo_metro_reviewed_transfer/v1",
        "transfers": [{
            "from_station_id": b[1],
            "to_station_id": c[1],
            "minimum_minutes": 4,
            "walking_distance_meters": 120,
            "evidence_urls": [
                "https://www.tokyometro.jp/ticket/guide/transfertime/index.html"
            ],
            "reviewed_at": "2026-10-23",
        }],
    }), encoding="utf-8")
    reviewed_graph = nx.DiGraph()
    add_tokyo_metro_to_graph(
        reviewed_graph, TimetableManager(), gtfs_dir=str(gtfs),
        stations_path=str(stations), railways_path=str(railways),
        reviewed_transfers_path=str(reviewed),
    )
    edge = reviewed_graph.edges[b, c]
    assert edge["official_connection"] is True
    assert edge["transfer_time_basis"] == "reviewed_station_path"
    assert edge["reviewed_walk_minutes"] == 4
    assert edge["meters"] == 120
    assert reviewed_graph.edges[c, b] == edge


def test_common_model_generates_only_official_same_station_connections(tmp_path):
    gtfs, stations, railways = _fixture(tmp_path)
    first_id, second_id = _make_same_station_connection(stations)
    graph = nx.DiGraph()
    manager = TimetableManager()
    add_tokyo_metro_to_graph(
        graph, manager, gtfs_dir=str(gtfs), stations_path=str(stations),
        railways_path=str(railways),
        reviewed_transfers_path=str(_common_policy(tmp_path)),
    )
    edge = graph.edges[("phys", first_id), ("phys", second_id)]
    assert edge["official_connection"] is True
    assert edge["transfer_path_class"] == "same_station_unclassified"
    assert edge["transfer_time_basis"] == "app_conservative_allowance"
    assert edge["transfer_time_estimated"] is True
    assert edge["physical_walk_distance_known"] is False
    assert edge["walk_constraint_verified"] is False
    assert edge["official_relation_reciprocal"] is True
    assert edge["transfer_time_confidence"] == "unverified_conservative"
    assert edge["official_connection_verified"] is True
    assert edge["transfer_path_verified"] is False
    assert edge["transfer_distance_verified"] is False
    assert edge["transfer_time_verified"] is False
    assert edge["transfer_direction_verified"] is False
    assert edge["transfer_hours_verified"] is False
    assert edge["station_reference_point_separation_meters"] >= 0
    assert edge["reviewed_walk_minutes"] == 15
    assert edge["meters"] == 0.0
    assert edge["walk_resource_meters"] == 600.0
    assert manager.tokyo_metro_transfer_model_report["automatic_same_station"] == 1
    # The unrelated A/D identities have no official relation and must not be
    # turned into a clique by their presence in the same loaded graph.
    assert not graph.has_edge(
        ("phys", "odpt.Station:TokyoMetro.Ginza.A"),
        ("phys", "odpt.Station:TokyoMetro.Hanzomon.D"),
    )


def test_common_model_does_not_symmetrize_a_one_way_official_relation(tmp_path):
    gtfs, stations_path, railways = _fixture(tmp_path)
    first_id, second_id = _make_same_station_connection(stations_path)
    stations = json.loads(stations_path.read_text(encoding="utf-8"))
    target = next(row for row in stations if row.get("owl:sameAs") == second_id)
    target["odpt:connectingStation"] = []
    stations_path.write_text(json.dumps(stations), encoding="utf-8")
    graph = nx.DiGraph()
    manager = TimetableManager()
    add_tokyo_metro_to_graph(
        graph, manager, gtfs_dir=str(gtfs), stations_path=str(stations_path),
        railways_path=str(railways),
        reviewed_transfers_path=str(_common_policy(tmp_path)),
    )
    assert not graph.has_edge(("phys", first_id), ("phys", second_id))
    assert not graph.has_edge(("phys", second_id), ("phys", first_id))
    assert manager.tokyo_metro_transfer_model_report[
        "nonreciprocal_official_relation"
    ] == 1


def test_station_reference_separation_is_not_used_as_a_walk_lower_bound(tmp_path):
    gtfs, stations_path, railways = _fixture(tmp_path)
    first_id, second_id = _make_same_station_connection(stations_path)
    stations = json.loads(stations_path.read_text(encoding="utf-8"))
    for row in stations:
        if row.get("owl:sameAs") == first_id:
            row["geo:lat"], row["geo:long"] = 35.60, 139.70
        elif row.get("owl:sameAs") == second_id:
            row["geo:lat"], row["geo:long"] = 35.61, 139.70
    stations_path.write_text(json.dumps(stations), encoding="utf-8")
    graph = nx.DiGraph()
    manager = TimetableManager()
    add_tokyo_metro_to_graph(
        graph, manager, gtfs_dir=str(gtfs), stations_path=str(stations_path),
        railways_path=str(railways),
        reviewed_transfers_path=str(_common_policy(tmp_path)),
    )
    edge = graph.edges[("phys", first_id), ("phys", second_id)]
    # Representative station coordinates are neither path endpoints nor
    # mandatory waypoints.  Even a large separation therefore cannot prove
    # that the transfer corridor violates the walking cap.
    assert edge["station_reference_point_separation_meters"] > 600
    assert edge["walk_resource_meters"] == 600
    assert edge["walk_constraint_verified"] is False


def test_directional_exception_does_not_create_the_forbidden_reverse(tmp_path):
    gtfs, stations_path, railways = _fixture(tmp_path)
    first_id, second_id = _make_same_station_connection(stations_path)
    exception = {
        "from_station_id": first_id,
        "to_station_id": second_id,
        "directions": "from_to",
        "available_windows": [{"start": "05:00", "end": "24:10"}],
        "evidence_urls": ["https://www.tokyometro.jp/station/index.html"],
        "reason": "fixture directed passage",
    }
    graph = nx.DiGraph()
    add_tokyo_metro_to_graph(
        graph, TimetableManager(), gtfs_dir=str(gtfs),
        stations_path=str(stations_path), railways_path=str(railways),
        reviewed_transfers_path=str(_common_policy(
            tmp_path, exceptions=(exception,)
        )),
    )
    assert graph.has_edge(("phys", first_id), ("phys", second_id))
    assert not graph.has_edge(("phys", second_id), ("phys", first_id))
    edge = graph.edges[("phys", first_id), ("phys", second_id)]
    assert edge["transfer_direction_verified"] is True
    assert edge["transfer_hours_verified"] is True


def test_common_model_keeps_different_station_relation_disabled(tmp_path):
    gtfs, stations, railways = _fixture(tmp_path)
    graph = nx.DiGraph()
    manager = TimetableManager()
    add_tokyo_metro_to_graph(
        graph, manager, gtfs_dir=str(gtfs), stations_path=str(stations),
        railways_path=str(railways),
        reviewed_transfers_path=str(_common_policy(tmp_path)),
    )
    first = ("phys", "odpt.Station:TokyoMetro.Ginza.B")
    second = ("phys", "odpt.Station:TokyoMetro.Hanzomon.C")
    assert not graph.has_edge(first, second)
    report = manager.tokyo_metro_transfer_model_report
    assert report["unsupported_different_station"] == 1
    assert report["searchable_raw_pairs"] == 0


def test_common_transfer_closure_rejects_the_concrete_connection(tmp_path):
    gtfs, stations_path, railways_path = _fixture(tmp_path)
    first_id, second_id = _make_same_station_connection(stations_path)
    stations = json.loads(stations_path.read_text(encoding="utf-8"))
    for station, lat in zip(stations, (35.600, 35.610, 35.611, 35.630)):
        station["geo:lat"] = lat
        station["geo:long"] = 139.70
    stations_path.write_text(json.dumps(stations), encoding="utf-8")
    exception = {
        "from_station_id": first_id,
        "to_station_id": second_id,
        "available_windows": [{"start": "05:00", "end": "24:10"}],
        "evidence_urls": ["https://www.tokyometro.jp/station/index.html"],
        "reason": "fixture closing time",
    }
    graph = nx.DiGraph()
    manager = TimetableManager()
    add_tokyo_metro_to_graph(
        graph, manager, gtfs_dir=str(gtfs), stations_path=str(stations_path),
        railways_path=str(railways_path),
        reviewed_transfers_path=str(_common_policy(
            tmp_path, exceptions=(exception,)
        )),
    )
    app = SimpleNamespace(state=SimpleNamespace(
        G=graph, TM=manager, SI=SpatialIndex(graph), WALK_RAD=300,
    ))
    result = TokyoRouteEngine(app).search_legacy(
        alat=35.600, alon=139.70, blat=35.630, blon=139.70,
        pref="time", transport_scope=frozenset((TOKYO_METRO,)),
        include_estimated_transfers=True,
        start_time="23:49", date_str="2026-09-24", limit=1,
    )
    assert result["candidates"] == []


def test_common_allowance_rejects_early_train_and_reports_estimate(tmp_path):
    gtfs, stations_path, railways_path = _fixture(tmp_path)
    _make_same_station_connection(stations_path)
    stop_times = gtfs / "stop_times.txt"
    text = stop_times.read_text(encoding="utf-8")
    stop_times.write_text(
        text.replace("24:12:00,24:12:00,201", "24:25:00,24:25:00,201")
            .replace("24:16:00,24:16:00,202", "24:29:00,24:29:00,202"),
        encoding="utf-8",
    )
    stations = json.loads(stations_path.read_text(encoding="utf-8"))
    for station, lat in zip(stations, (35.600, 35.610, 35.611, 35.630)):
        station["geo:lat"] = lat
        station["geo:long"] = 139.70
    stations_path.write_text(json.dumps(stations), encoding="utf-8")
    graph = nx.DiGraph()
    manager = TimetableManager()
    add_tokyo_metro_to_graph(
        graph, manager, gtfs_dir=str(gtfs), stations_path=str(stations_path),
        railways_path=str(railways_path),
        reviewed_transfers_path=str(_common_policy(tmp_path)),
    )
    app = SimpleNamespace(state=SimpleNamespace(
        G=graph, TM=manager, SI=SpatialIndex(graph), WALK_RAD=300,
    ))
    result = TokyoRouteEngine(app).search_legacy(
        alat=35.600, alon=139.70, blat=35.630, blon=139.70,
        pref="time", transport_scope=frozenset((TOKYO_METRO,)),
        include_estimated_transfers=True,
        start_time="23:49", date_str="2026-09-24", limit=1,
    )
    steps = result["candidates"][0]["steps"]
    rails = [step for step in steps if step["kind"] == "rail"]
    transfer = next(step for step in steps if step.get("walking_time_estimated"))
    assert [step["trip_id"] for step in rails] == [
        "tokyo_metro:g-late", "tokyo_metro:z-after-transfer",
    ]
    assert rails[0]["arrival_time"] == "24:05"
    assert transfer["departure_time"] == "24:06"
    assert transfer["arrival_time"] == "24:21"
    assert transfer["minutes"] == 15
    assert transfer["meters"] == 0
    assert transfer["planning_walk_resource_meters"] == 600
    assert transfer["physical_walk_distance_known"] is False
    assert transfer["walking_connection_verified"] is False
    assert transfer["walking_time_basis"] == "app_conservative_allowance"
    assert transfer["planning_details"]["physical_walk_meters"] is None
    assert transfer["planning_details"][
        "station_reference_point_separations_meters"
    ]
    assert transfer["planning_details"]["planning_walk_resource_meters"] == 600
    assert transfer["planning_details"]["walk_constraint_verified"] is False
    assert transfer["planning_details"]["walking_time_measured"] is False
    assert transfer["planning_details"]["walking_time_confidence"] == (
        "unverified_conservative"
    )
    assert transfer["transfer_evidence"] == {
        "official_connection_verified": True,
        "path_verified": False,
        "physical_distance_verified": False,
        "minimum_time_verified": False,
        "direction_restrictions_verified": False,
        "availability_hours_verified": False,
    }
    assert rails[1]["departure_time"] == "24:25"


def test_reviewed_transfer_without_official_relation_fails(tmp_path):
    gtfs, stations, railways = _fixture(tmp_path)
    reviewed = tmp_path / "reviewed-transfers.json"
    reviewed.write_text(json.dumps({
        "schema": "tokyo_metro_reviewed_transfer/v1",
        "transfers": [{
            "from_station_id": "odpt.Station:TokyoMetro.Ginza.A",
            "to_station_id": "odpt.Station:TokyoMetro.Hanzomon.D",
            "minimum_minutes": 2,
            "walking_distance_meters": 80,
            "evidence_urls": ["https://www.tokyometro.jp/station/index.html"],
            "reviewed_at": "2026-10-23",
        }],
    }), encoding="utf-8")
    with unittest.TestCase().assertRaisesRegex(ValueError, "connectingStation"):
        add_tokyo_metro_to_graph(
            nx.DiGraph(), TimetableManager(), gtfs_dir=str(gtfs),
            stations_path=str(stations), railways_path=str(railways),
            reviewed_transfers_path=str(reviewed),
        )


def test_reviewed_transfer_cannot_be_faster_than_the_walk_distance(tmp_path):
    gtfs, stations, railways = _fixture(tmp_path)
    reviewed = tmp_path / "reviewed-transfers.json"
    reviewed.write_text(json.dumps({
        "schema": "tokyo_metro_reviewed_transfer/v1",
        "transfers": [{
            "from_station_id": "odpt.Station:TokyoMetro.Ginza.B",
            "to_station_id": "odpt.Station:TokyoMetro.Hanzomon.C",
            "minimum_minutes": 1,
            "walking_distance_meters": 120,
            "evidence_urls": ["https://www.tokyometro.jp/station/index.html"],
            "reviewed_at": "2026-10-23",
        }],
    }), encoding="utf-8")
    with unittest.TestCase().assertRaisesRegex(ValueError, "distance minimum"):
        add_tokyo_metro_to_graph(
            nx.DiGraph(), TimetableManager(), gtfs_dir=str(gtfs),
            stations_path=str(stations), railways_path=str(railways),
            reviewed_transfers_path=str(reviewed),
        )


def test_boundary_pickup_restriction_is_excluded_and_interior_fails(tmp_path):
    gtfs, stations, railways = _fixture(tmp_path)
    stop_times = gtfs / "stop_times.txt"
    original = stop_times.read_text(encoding="utf-8")
    stop_times.write_text(
        original.replace(
            "g-late,23:55:00,23:55:00,101,1,0,0",
            "g-late,23:55:00,23:55:00,101,1,1,0",
        ),
        encoding="utf-8",
    )
    manager = TimetableManager()
    add_tokyo_metro_to_graph(
        nx.DiGraph(), manager, gtfs_dir=str(gtfs), stations_path=str(stations),
        railways_path=str(railways),
    )
    assert not any(
        record["run_key"] == "tokyo_metro:g-late"
        for records in manager.tokyo_metro_patterns_by_service.values()
        for record in records
    )

    stop_times.write_text(
        original.replace(
            "z-holiday,10:04:00,10:04:00,202,2,0,0",
            "z-holiday,10:02:00,10:02:00,101,2,1,0\n"
            "z-holiday,10:04:00,10:04:00,202,3,0,0",
        ),
        encoding="utf-8",
    )
    with unittest.TestCase().assertRaisesRegex(ValueError, "interior no-pickup"):
        add_tokyo_metro_to_graph(
            nx.DiGraph(), TimetableManager(), gtfs_dir=str(gtfs),
            stations_path=str(stations), railways_path=str(railways),
        )


def test_metro_identity_is_verified_without_using_toei_static_gtfs():
    step = {
        "kind": "rail", "step_id": "rail-1", "operator_id": "tokyo_metro",
        "trip_id": "tokyo_metro:g-late", "route_id": "tokyo_metro:1",
        "service_id": "0", "departure_time": "23:55", "arrival_time": "24:05",
        "boarding_minutes": 2,
        "stops": [
            {"id": "tokyo_metro:101", "odpt_id": "odpt-a", "name": "A"},
            {"id": "tokyo_metro:102", "odpt_id": "odpt-b", "name": "B"},
        ],
        "selected_run": {
            "trip_id": "tokyo_metro:g-late", "route_id": "tokyo_metro:1",
            "service_id": "0", "origin_gtfs_stop_id": "tokyo_metro:101",
            "destination_gtfs_stop_id": "tokyo_metro:102",
            "segment_records": [{
                "trip_id": "tokyo_metro:g-late", "route_id": "tokyo_metro:1",
                "service_id": "0", "origin_gtfs_stop_id": "tokyo_metro:101",
                "next_gtfs_stop_id": "tokyo_metro:102",
            }],
        },
    }
    result = enrich_route_result_train_trip_ids(
        {"candidates": [{"id": "c", "steps": [step]}]},
        timetable_manager=object(), day_type="weekday", static_gtfs=StaticTrainGtfs(trips={}),
    )
    resolved = result["candidates"][0]["steps"][0]
    assert resolved["trip_id"] == "tokyo_metro:g-late"
    assert "selected_run" not in resolved


def test_metro_only_search_uses_exact_service_and_24_hour_trip(tmp_path):
    gtfs, stations_path, railways_path = _fixture(tmp_path)
    stations = json.loads(stations_path.read_text(encoding="utf-8"))
    stations[1]["geo:lat"] = 35.691
    stations[1]["geo:long"] = 139.771
    stations_path.write_text(json.dumps(stations), encoding="utf-8")

    graph = nx.DiGraph()
    manager = TimetableManager()
    add_tokyo_metro_to_graph(
        graph,
        manager,
        gtfs_dir=str(gtfs),
        stations_path=str(stations_path),
        railways_path=str(railways_path),
    )
    app = SimpleNamespace(
        state=SimpleNamespace(
            G=graph,
            TM=manager,
            SI=SpatialIndex(graph),
            WALK_RAD=300,
        )
    )
    result = TokyoRouteEngine(app).search_legacy(
        alat=35.681,
        alon=139.761,
        blat=35.691,
        blon=139.771,
        pref="time",
        transport_scope=frozenset((TOKYO_METRO,)),
        start_time="23:49",
        date_str="2026-09-24",
        limit=5,
    )

    rail = result["candidates"][0]["steps"][0]
    assert rail["operator_id"] == "tokyo_metro"
    assert rail["trip_id"] == "tokyo_metro:g-late"
    assert rail["route_id"] == "tokyo_metro:1"
    assert rail["departure_time"] == "23:55"
    assert rail["arrival_time"] == "24:05"
    assert [stop["id"] for stop in rail["stops"]] == [
        "tokyo_metro:101",
        "tokyo_metro:102",
    ]


def test_reviewed_transfer_time_rejects_the_train_that_cannot_be_boarded(tmp_path):
    gtfs, stations_path, railways_path = _fixture(tmp_path)
    stations = json.loads(stations_path.read_text(encoding="utf-8"))
    for station, lat in zip(stations, (35.60, 35.61, 35.62, 35.63)):
        station["geo:lat"] = lat
        station["geo:long"] = 139.70
    stations_path.write_text(json.dumps(stations), encoding="utf-8")
    reviewed = tmp_path / "reviewed-transfers.json"
    reviewed.write_text(json.dumps({
        "schema": "tokyo_metro_reviewed_transfer/v1",
        "transfers": [{
            "from_station_id": "odpt.Station:TokyoMetro.Ginza.B",
            "to_station_id": "odpt.Station:TokyoMetro.Hanzomon.C",
            "minimum_minutes": 4,
            "walking_distance_meters": 120,
            "evidence_urls": [
                "https://www.tokyometro.jp/ticket/guide/transfertime/index.html"
            ],
            "reviewed_at": "2026-10-23",
        }],
    }), encoding="utf-8")

    graph = nx.DiGraph()
    manager = TimetableManager()
    add_tokyo_metro_to_graph(
        graph,
        manager,
        gtfs_dir=str(gtfs),
        stations_path=str(stations_path),
        railways_path=str(railways_path),
        reviewed_transfers_path=str(reviewed),
    )
    app = SimpleNamespace(state=SimpleNamespace(
        G=graph, TM=manager, SI=SpatialIndex(graph), WALK_RAD=300,
    ))
    result = TokyoRouteEngine(app).search_legacy(
        alat=35.60,
        alon=139.70,
        blat=35.63,
        blon=139.70,
        pref="time",
        transport_scope=frozenset((TOKYO_METRO,)),
        start_time="23:49",
        date_str="2026-09-24",
        limit=1,
    )

    steps = result["candidates"][0]["steps"]
    rails = [step for step in steps if step["kind"] == "rail"]
    transfer = next(step for step in steps if step.get("walking_time_basis"))
    assert [step["trip_id"] for step in rails] == [
        "tokyo_metro:g-late",
        "tokyo_metro:z-after-transfer",
    ]
    assert rails[0]["arrival_time"] == "24:05"
    assert transfer["departure_time"] == "24:06"
    assert transfer["arrival_time"] == "24:10"
    assert transfer["minutes"] == 4
    assert transfer["walking_connection_verified"] is True
    assert transfer["evidence_urls"]
    assert transfer["transfer_evidence"] == {
        "official_connection_verified": True,
        "path_verified": True,
        "physical_distance_verified": True,
        "minimum_time_verified": True,
        "direction_restrictions_verified": False,
        "availability_hours_verified": False,
    }
    assert rails[1]["departure_time"] == "24:12"


class TokyoMetroGtfsTest(unittest.TestCase):
    def test_committed_transfer_manifest(self):
        test_committed_transfer_manifest_is_strict_and_reviewed()

    def test_feed_audit_import_and_service_days(self):
        with tempfile.TemporaryDirectory() as directory:
            test_feed_audit_and_import_preserve_exact_runs_calendar_and_24_hour_times(
                Path(directory)
            )

    def test_official_connection_requires_reviewed_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            test_official_connection_requires_reviewed_transfer(
                Path(directory)
            )

    def test_common_model_generates_only_official_same_station_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            test_common_model_generates_only_official_same_station_connections(
                Path(directory)
            )

    def test_common_model_keeps_different_station_relation_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            test_common_model_keeps_different_station_relation_disabled(
                Path(directory)
            )

    def test_common_model_requires_reciprocal_official_relation(self):
        with tempfile.TemporaryDirectory() as directory:
            test_common_model_does_not_symmetrize_a_one_way_official_relation(
                Path(directory)
            )

    def test_station_reference_separation_is_not_a_walk_lower_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            test_station_reference_separation_is_not_used_as_a_walk_lower_bound(
                Path(directory)
            )

    def test_directional_exception_forbids_reverse(self):
        with tempfile.TemporaryDirectory() as directory:
            test_directional_exception_does_not_create_the_forbidden_reverse(
                Path(directory)
            )

    def test_common_transfer_closure_rejects_concrete_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            test_common_transfer_closure_rejects_the_concrete_connection(
                Path(directory)
            )

    def test_common_allowance_rejects_early_train_and_reports_estimate(self):
        with tempfile.TemporaryDirectory() as directory:
            test_common_allowance_rejects_early_train_and_reports_estimate(
                Path(directory)
            )

    def test_metro_identity_is_verified_without_toei_feed(self):
        test_metro_identity_is_verified_without_using_toei_static_gtfs()

    def test_pickup_dropoff_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            test_boundary_pickup_restriction_is_excluded_and_interior_fails(
                Path(directory)
            )

    def test_reviewed_transfer_requires_official_relation(self):
        with tempfile.TemporaryDirectory() as directory:
            test_reviewed_transfer_without_official_relation_fails(Path(directory))

    def test_reviewed_transfer_respects_walking_floor(self):
        with tempfile.TemporaryDirectory() as directory:
            test_reviewed_transfer_cannot_be_faster_than_the_walk_distance(
                Path(directory)
            )

    def test_metro_only_exact_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            test_metro_only_search_uses_exact_service_and_24_hour_trip(
                Path(directory)
            )

    def test_reviewed_transfer_rejects_too_early_train(self):
        with tempfile.TemporaryDirectory() as directory:
            test_reviewed_transfer_time_rejects_the_train_that_cannot_be_boarded(
                Path(directory)
            )
