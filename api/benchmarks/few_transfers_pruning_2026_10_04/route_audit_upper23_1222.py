"""Independent enumeration of the user's specified three rides; no route search."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import pickle
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent / "route_comparison_1222_2026_10_05" / "upper23_independent_enumeration.json"
sys.path.insert(0, str(ROOT / "api"))
import toei_engine as te
from gtfs_state import load_compiled_state
from tokyo_timetable_choices import TimetableChoices
from app.services.train_realtime import parse_static_gtfs
from app.services.train_service_calendar import parse_train_service_calendar


def main():
    with (ROOT / "api/data/app_data_search_labels.pkl").open("rb") as source:
        data = pickle.load(source)
    graph, manager = data["G"], data["TM"]
    assets = ROOT / "api/data/search_rss_probe"
    manifest = json.loads((assets / "manifest.json").read_text(encoding="utf-8"))
    load_compiled_state(te.gtfs_repo, str(assets / "compiled.pkl.gz"),
                        expected_source_sha256=manifest["source_sha256"])
    day = te.determine_day_type("2026-10-05")
    choices = TimetableChoices(graph, manager, day_type=day, use_realtime=False,
                               bus_repository=te.gtfs_repo, deadline=982)
    physical = lambda name: [n for n, d in graph.nodes(data=True)
                             if d.get("kind") == "phys" and d.get("name") == name]
    names = {name: physical(name) for name in ("十間橋", "本所吾妻橋", "新橋駅前", "渋谷駅前")}
    rail_first = ("phys", "odpt.Station:Toei.Asakusa.HonjoAzumabashi")
    rail_last = ("phys", "odpt.Station:Toei.Asakusa.Shimbashi")
    origin, distance = te.nearest_phys(graph, 35.708166, 139.817434,
                                       spatial_index=data["SI"])
    destination = (35.658034, 139.701636)

    def walk(first, following):
        if first == following:
            return 0.0
        edge = graph.get_edge_data(first, following)
        if edge and edge.get("etype") == "walk":
            return float(edge["meters"])
        return None

    def bus_legs(place, route, finish_name, ready):
        for line, edge in graph[place].items():
            if edge.get("etype") != "board" or graph.nodes[line].get("mode") != "bus":
                continue
            if choices._bus_route(line) != route:
                continue
            for departure, state in choices.board_options(place, line, ready):
                first_state = state
                run = choices._runs[(state.provider, state.run_id)]
                position = choices._positions[(state.provider, state.run_id)][state.sequence]
                current, clock = line, departure
                visited = [line]
                for stop in run.stops[position + 1:]:
                    matching = [following for following, adjacent in graph[current].items()
                                if adjacent.get("etype") == "ride"
                                and choices._stop_id(following[1]) == stop.stop_id]
                    if len(matching) != 1:
                        break
                    following = matching[0]
                    options = choices.ride_options(current, following, clock, state)
                    if not options:
                        break
                    clock, state = options[0]
                    current = following
                    visited.append(current)
                    if stop.stop_id in te.gtfs_repo.stops and te.gtfs_repo.stops[stop.stop_id]["name"] == finish_name:
                        landing = next((n for n, e in graph[current].items()
                                        if e.get("etype") == "alight" and n[0] == "phys"), None)
                        if landing is None:
                            continue
                        trip = te.gtfs_repo.trips[state.trip_id]
                        yield {
                            "route": route, "trip_id": state.trip_id,
                            "service_id": state.service_id,
                            "trip_headsign": trip.get("trip_headsign"),
                            "direction_id": trip.get("direction_id"),
                            "origin_stop_id": choices._stop_id(place[1]),
                            "destination_stop_id": stop.stop_id,
                            "departure": departure, "arrival": clock,
                            "board_sequence": first_state.board_sequence,
                            "destination_sequence": state.sequence,
                            "line_pattern": state.line_id,
                            "physical_destination": landing,
                            "path_nodes": list(visited),
                        }

    def rail_legs(ready):
        for line, edge in graph[rail_first].items():
            if edge.get("etype") != "board" or graph.nodes[line].get("mode") != "rail":
                continue
            for departure, state in choices.board_options(rail_first, line, ready + 2):
                first_state = state
                run = choices._runs[(state.provider, state.run_id)]
                position = choices._positions[(state.provider, state.run_id)][state.sequence]
                current, clock = line, departure
                visited = [line]
                for stop in run.stops[position + 1:]:
                    following = ("line", stop.stop_id, state.line_id)
                    if not graph.has_edge(current, following):
                        break
                    options = choices.ride_options(current, following, clock, state)
                    if not options:
                        break
                    clock, state = options[0]
                    current = following
                    visited.append(current)
                    if stop.stop_id == rail_last[1]:
                        yield {
                            "departure": departure, "arrival": clock,
                            "train_number": state.train_number,
                            "source_run_key": run.source_run_key, "run_id": state.run_id,
                            "board_sequence": first_state.board_sequence,
                            "destination_sequence": state.sequence,
                            "path_nodes": list(visited),
                        }
                        break

    first_legs = []
    combinations = []
    count = 0
    for board_stop in names["十間橋"]:
        origin_walk = walk(origin, board_stop)
        if origin_walk is None:
            continue
        for first in bus_legs(board_stop, "070", "本所吾妻橋", 742 + origin_walk / 80):
            to_rail_walk = walk(first["physical_destination"], rail_first)
            if to_rail_walk is None:
                continue
            if first not in first_legs:
                first_legs.append(first)
            rail_ready = first["arrival"] + to_rail_walk / 80
            for train in rail_legs(rail_ready):
                for bus_stop in names["新橋駅前"]:
                    to_bus_walk = walk(rail_last, bus_stop)
                    if to_bus_walk is None:
                        continue
                    bus_ready = train["arrival"] + 1 + to_bus_walk / 80
                    for last in bus_legs(bus_stop, "006", "渋谷駅前", bus_ready):
                        last_data = graph.nodes[last["physical_destination"]]
                        final_walk = te.haversine(last_data["lat"], last_data["lon"], *destination)
                        final_arrival = last["arrival"] + final_walk / 80
                        count += 1
                        row = {"first": first, "rail": train, "last": last,
                               "origin_walk_m": origin_walk,
                               "first_bus_to_rail_walk_m": to_rail_walk,
                               "rail_ready_including_2min": rail_ready + 2,
                               "rail_alight_minutes": 1,
                               "rail_to_last_bus_walk_m": to_bus_walk,
                               "last_bus_ready": bus_ready,
                               "final_walk_m": final_walk, "final_arrival": final_arrival}
                        combinations.append(row)
                        combinations.sort(key=lambda r: (r["final_arrival"], r["first"]["departure"], r["rail"]["departure"]))
                        combinations = combinations[:20]
    # Collapse duplicate graph patterns of the same three concrete runs.
    seen, unique = set(), []
    for row in combinations:
        key = row["first"]["trip_id"], row["rail"]["run_id"], row["last"]["trip_id"]
        if key not in seen:
            seen.add(key)
            unique.append(row)
    train_content = (ROOT / "api/data/Toei-Train-GTFS.zip").read_bytes()
    train_calendar = parse_train_service_calendar(train_content)
    train_static = parse_static_gtfs(train_content)
    train_active = train_calendar.active_trip_ids(dt.date(2026, 10, 5))
    train_neighbors = []
    for trip_id, trip in train_static.trips.items():
        if trip_id not in train_active:
            continue
        for first_index, first_stop in enumerate(trip.stops):
            if first_stop.stop_name != "本所吾妻橋":
                continue
            for last_index, last_stop in enumerate(trip.stops[first_index + 1:], first_index + 1):
                if last_stop.stop_name != "新橋":
                    continue
                if first_stop.departure_time is None or last_stop.arrival_time is None:
                    continue
                def minute(clock):
                    h, m, s = map(int, clock.split(":"))
                    return h * 60 + m + s / 60
                departure, arrival = minute(first_stop.departure_time), minute(last_stop.arrival_time)
                if 765 <= departure <= 780:
                    train_neighbors.append({
                        "trip_id": trip_id, "route_id": trip.route_id,
                        "headsign": trip.headsign, "departure": departure, "arrival": arrival,
                        "stations": [stop.stop_name for stop in trip.stops[first_index:last_index + 1]],
                        "stop_ids": [stop.stop_id for stop in trip.stops[first_index:last_index + 1]],
                        "stop_codes": [stop.stop_code for stop in trip.stops[first_index:last_index + 1]],
                        "departure_wire": first_stop.departure_time, "arrival_wire": last_stop.arrival_time,
                    })
    for row in unique:
        selected = row["rail"]
        names_on_path = [graph.nodes[node]["name"].split("@")[0]
                         for node in selected["path_nodes"]]
        matched = [record for record in train_neighbors
                   if record["departure"] == selected["departure"]
                   and record["arrival"] == selected["arrival"]
                   and record["stations"] == names_on_path]
        selected["train_gtfs_identity_matches"] = matched
    first_bus_neighbors = []
    for scheduled, sequence, trip_id in te.gtfs_repo.timetable_index.get("070|0751-02", ()):
        trip = te.gtfs_repo.trips[trip_id]
        if not (700 <= scheduled <= 790 and trip["service_id"] in day.active_service_ids):
            continue
        for following_sequence, stop in sorted(te.gtfs_repo.stop_times[trip_id].items()):
            if following_sequence > sequence and stop[0] == "1414-04":
                first_bus_neighbors.append({"trip_id": trip_id, "service_id": trip["service_id"],
                                            "departure": scheduled, "arrival": stop[1]})
                break
    report = {"scope": "Static three-ride enumeration through specified transfer points; no A*, dominance or search safety-limit changes",
              "date": "2026-10-05", "start": "12:22", "day_type": str(day),
              "active_services": sorted(day.active_service_ids), "origin": origin,
              "origin_distance_m": distance, "destination": destination,
              "source_files": ["api/data/app_data_search_labels.pkl", "api/data/odpt_TrainTimetable.json",
                               "api/data/ToeiBus-GTFS/trips.txt", "api/data/ToeiBus-GTFS/stop_times.txt",
                               "api/data/ToeiBus-GTFS/calendar.txt", "api/data/ToeiBus-GTFS/stops.txt",
                               "api/data/Toei-Train-GTFS.zip"],
              "first_bus_options": sorted(first_legs, key=lambda r: r["departure"])[:8],
              "first_bus_neighbor_departures": first_bus_neighbors,
              "train_gtfs_neighbor_departures": sorted(train_neighbors, key=lambda r: r["departure"]),
              "enumerated_combinations": count, "best_combinations": unique}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "enumerated_combinations": count,
                      "first_bus_options": [{k: r[k] for k in ("departure", "arrival", "trip_id", "origin_stop_id", "destination_stop_id", "trip_headsign")}
                                            for r in report["first_bus_options"]],
                      "best": unique[:2]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
