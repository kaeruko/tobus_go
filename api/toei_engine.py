#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# toei_engine.py

import json, argparse, math, sys, heapq, bisect, datetime
import csv, os, glob
import networkx as nx
from collections import defaultdict

# -------------------- チューニング定数 --------------------
BUS_RIDE_COST = 0.8
RAIL_RIDE_COST = 0.8
WALK_COST = 1.5
WALK_SPEED_M_PER_MIN = 80.0 

TRANSFER_PENALTY = 5.0
BUS_WAIT_PENALTY = 15.0
BUS_ALIGHT_PENALTY = 5.0

MAX_WALK_SEG_M = 300.0

# 追加: 経路として許容する最大所要時間・総徒歩距離
MAX_TRAVEL_MIN = 240.0      # 例: 4 時間を上限
MAX_TOTAL_WALK_M = 3000.0   # 例: 総徒歩 3km まで

# -------------------- ユーティリティ --------------------
def _line_norm(s: str) -> str:
    tbl = str.maketrans("０１２３４５６７８９　（）", "0123456789 ()")
    return (s or "").translate(tbl).replace(" ", "")

def _norm_line(s): return _line_norm(s)

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(a))

def is_station_id(pid: str) -> bool:
    return isinstance(pid, str) and pid.startswith("odpt.Station:")

def is_toei(op):
    if isinstance(op, list): return any("Toei" in x for x in op)
    return isinstance(op, str) and "Toei" in op

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "result" in data: return data["result"]
    return data if isinstance(data, list) else [data]

def get_id(o): return o.get("owl:sameAs") or o.get("@id") or o.get("id")
def get_lat(o): return o.get("geo:lat")
def get_lon(o): return o.get("geo:long")
def time_str_to_min(t_str):
    if not t_str: return 99999
    h, m = map(int, t_str.split(":"))
    return h * 60 + m

def min_to_time_str(m):
    h = int(m // 60)
    mn = int(m % 60)
    return f"{h:02d}:{mn:02d}"

def _create_int_dd():
    return defaultdict(int)

def reconstruct_path(chain):
    """
    (current_node, parent_chain) の形式のタプルチェーンから
    [node1, node2, ..., current_node] のリストを復元する
    """
    path = []
    curr = chain
    while curr:
        node, parent = curr
        path.append(node)
        curr = parent
    return path[::-1]  # 逆順になおす

# -------------------- 空間インデックス (Grid Index) --------------------
REF_LAT = 35.681236  # Tokyo Station
REF_LON = 139.767125
METERS_PER_DEG_LAT = 111_132.954
METERS_PER_DEG_LON = 91_387.818 # approx at Tokyo

def to_local_meters(lat, lon):
    y = (lat - REF_LAT) * METERS_PER_DEG_LAT
    x = (lon - REF_LON) * METERS_PER_DEG_LON
    return x, y

class SpatialIndex:
    def __init__(self, G=None, cell_size_m=500.0):
        self.cell_size_m = cell_size_m
        self.grid = defaultdict(list)
        if G:
            self.build(G)

    def build(self, G):
        print(f"[INFO] Building SpatialIndex (cell={self.cell_size_m}m)...")
        count = 0
        for n, d in G.nodes(data=True):
            if n[0] == "phys" and "lat" in d and "lon" in d:
                x, y = to_local_meters(d["lat"], d["lon"])
                cx = int(x // self.cell_size_m)
                cy = int(y // self.cell_size_m)
                self.grid[(cx, cy)].append((n, d["lat"], d["lon"]))
                count += 1
        print(f"[INFO] Indexed {count} phys nodes.")

    def nearby_candidates(self, lat, lon, radius_m):
        x, y = to_local_meters(lat, lon)
        cx = int(x // self.cell_size_m)
        cy = int(y // self.cell_size_m)
        
        candidates = []
        # Check 3x3 cells
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                cell = (cx + dx, cy + dy)
                for item in self.grid.get(cell, []):
                    candidates.append(item)
        return candidates

# -------------------- 時刻表マネージャー (名寄せ強化版) --------------------
class TimetableManager:
    def __init__(self):
        # key: pole_id, value: { route_id: [{'dep': minutes, 'dest': dest_pole_id}, ...] }
        # Value structure changed from list of minutes to list of dicts
        # key: pole_id, value: { route_id: [{'dep': minutes, 'dest': dest_pole_id}, ...] }
        # Value structure changed from list of minutes to list of dicts
        self.bus_departures_weekday = {}
        self.bus_departures_saturday = {}
        self.bus_departures_holiday = {}
        self.route_patterns_map = defaultdict(list) # route_id -> [ [stop1, stop2...], [stop1...] ]
        
        # key: station_id, value: [ {dep, arr, next_sta, train_id} ]
        self.train_patterns_weekday = {}
        self.train_patterns_weekend = {}
        
        # 名前インデックス (共通)
        self.name_to_pids = defaultdict(list)
        # リアルタイム遅延 (共通)
        self.realtime_delays = {}
        
        # GTFS Mappings (Default empty)
        self.gtfs_route_map = {}
        self.gtfs_stop_map = {}
        self.route_stop_stats = defaultdict(lambda: defaultdict(int))

    def update_delays(self, train_data_list):
        count = 0
        for t in train_data_list:
            t_num = t.get("odpt:trainNumber")
            delay = t.get("odpt:delay", 0)
            if t_num:
                self.realtime_delays[t_num] = delay
                count += 1
        print(f"[INFO] Updated delays for {count} trains.")

    def get_delays_snapshot(self):
        """Return a copy of current realtime delays for consistency during search"""
        return self.realtime_delays.copy()

    def load_bus_route_patterns(self, json_path):
        data = load_json(json_path)
        count = 0
        for entry in data:
            route_id = entry.get("odpt:busroute")
            orders = entry.get("odpt:busstopPoleOrder") or []
            try:
                orders = sorted(orders, key=lambda x: x.get("odpt:index", 0))
            except:
                pass

            seq = [o.get("odpt:busstopPole") for o in orders if o.get("odpt:busstopPole")]
            if not route_id or not seq:
                continue

            key = tuple(seq)
            exists = False
            for s in self.route_patterns_map[route_id]:
                if tuple(s) == key:
                    exists = True
                    break
            if not exists:
                self.route_patterns_map[route_id].append(seq)
                count += 1

        print(f"[DEBUG] Loaded Bus Patterns for {count} patterns.")

    def load_bus_timetables(self, json_path):
        data = load_json(json_path)
        count = 0
        for entry in data:
            pole_id = entry.get("odpt:busstopPole")
            route_id = entry.get("odpt:busroute")
            calendar = entry.get("odpt:calendar", "")
            if not pole_id: continue

            # [{'dep': 600, 'dest': 'pole_id_xyz'}]
            times = []
            for obj in entry.get("odpt:busstopPoleTimetableObject", []):
                dep = obj.get("odpt:departureTime")
                dest = obj.get("odpt:destinationBusstopPole")
                if dep:
                    times.append({
                        "dep": time_str_to_min(dep),
                        "dest": dest
                    })
            
            # depでソート
            times.sort(key=lambda x: x["dep"])
            
            if not times: continue



            # 振り分け
            targets = []
            
            # Heuristic Mapping (Generalized Suffix Match)
            # Weekday: Ends with -170 or -174 (To01 case), or has "Weekday"
            is_wk = (
                "Weekday" in calendar 
                or calendar.endswith("-170") 
                or calendar.endswith("-174")
            )
            
            # Saturday: Ends with -160 or has "Saturday"
            is_sat = (
                "Saturday" in calendar 
                or calendar.endswith("-160")
            )
            
            # Holiday: Ends with -100, -109, or has "Holiday"
            is_hol = (
                "Holiday" in calendar 
                or calendar.endswith("-100") 
                or calendar.endswith("-109")
            )

            if is_wk: targets.append(self.bus_departures_weekday)
            if is_sat: targets.append(self.bus_departures_saturday)
            if is_hol: targets.append(self.bus_departures_holiday)
            
            # If nothing matched, log for investigation (optional)
            if not targets and "Specific" in calendar:
                # print(f"[WARN] Unknown Specific Calendar: {calendar} for {route_id}")
                pass
            
            for target_dict in targets:
                if pole_id not in target_dict: target_dict[pole_id] = {}
                if route_id not in target_dict[pole_id]: target_dict[pole_id][route_id] = []
                target_dict[pole_id][route_id].extend(times)
                
            count += 1
        
        # ソート ensures consistency after extend
        for d in [self.bus_departures_weekday, self.bus_departures_saturday, self.bus_departures_holiday]:
            for pid in d:
                for rid in d[pid]:
                    d[pid][rid].sort(key=lambda x: x["dep"])
        print(f"[DEBUG] Loaded Bus Timetables (Entries used: {count})")

    def load_train_timetables(self, json_path):
        data = load_json(json_path)
        count = 0
        for entry in data:
            train_num = entry.get("odpt:trainNumber")
            calendar = entry.get("odpt:calendar", "")
            
            objs = entry.get("odpt:trainTimetableObject", [])
            
            # 振り分け
            target_dict = self.train_patterns_weekend
            if "Weekday" in calendar:
                target_dict = self.train_patterns_weekday

            for i in range(len(objs) - 1):
                curr = objs[i]
                next_stop = objs[i+1]
                dep_sta = curr.get("odpt:departureStation")
                arr_sta = next_stop.get("odpt:arrivalStation")
                dep_time = time_str_to_min(curr.get("odpt:departureTime"))
                arr_time = time_str_to_min(next_stop.get("odpt:arrivalTime"))
                
                if dep_sta and arr_sta:
                    if dep_sta not in target_dict: target_dict[dep_sta] = []
                    target_dict[dep_sta].append({
                        "dep": dep_time, 
                        "arr": arr_time, 
                        "next_sta": arr_sta,
                        "train_num": train_num
                    })
            count += 1
        
        for d in [self.train_patterns_weekday, self.train_patterns_weekend]:
            for sid in d:
                d[sid].sort(key=lambda x: x["dep"])
        print(f"[DEBUG] Loaded Train Timetables (Entries used: {count})")

    def build_name_index(self, G):
        print("[INFO] Building Name Index for fuzzy matching...")
        count = 0
        for n, d in G.nodes(data=True):
            if n[0] == "phys":
                name = d.get("name")
                pid = n[1]
                if name:
                    self.name_to_pids[name].append(pid)
                    count += 1
        print(f"[INFO] Index built. Total {count} nodes.")

    def get_next_bus_departure(self, pole_id, route_id, current_time_min, pole_name=None, day_type="weekday", target_pole_id=None, debug=False):
        if not debug:
            dbg_env = os.getenv("DEBUG_BUS", "0")
            if dbg_env == "1":
                debug = True
            elif dbg_env != "0" and pole_name and dbg_env in pole_name:
                debug = True

        if not debug:
            return self._get_next_bus_departure_impl(pole_id, route_id, current_time_min, pole_name, day_type, target_pole_id=target_pole_id, debug=False)
        
        return self._get_next_bus_departure_impl(pole_id, route_id, current_time_min, pole_name, day_type, target_pole_id=target_pole_id, debug=True)

    def _get_next_bus_departure_impl(self, pole_id, route_id, current_time_min, pole_name=None, day_type="weekday", target_pole_id=None, debug=False):
        if day_type == "saturday":
            target_dict = self.bus_departures_saturday
        elif day_type == "holiday":
            target_dict = self.bus_departures_holiday
        else:
            target_dict = self.bus_departures_weekday

        def find_trips(routes_dict, target_rid):
            if target_rid in routes_dict:
                return routes_dict[target_rid]
            for r_key, t_list in routes_dict.items():
                if target_rid in r_key or r_key in target_rid:
                    if debug:
                        print(f"[🚌BUS] 🔎 Fuzzy match: target={target_rid} matched={r_key}")
                    return t_list
            return None

        def is_valid_trip(trip, rid, board_pole_id):
            if not target_pole_id:
                return True

            dest_id = trip.get("dest")
            if not dest_id:
                return True

            patterns = self.route_patterns_map.get(rid) or []
            if not patterns:
                return True

            any_directional_pattern = False

            for stops in patterns:
                if board_pole_id not in stops:
                    continue
                if dest_id not in stops:
                    continue

                b = stops.index(board_pole_id)
                d = stops.index(dest_id)

                if d < b:
                    continue

                any_directional_pattern = True

                if target_pole_id not in stops:
                    continue

                t = stops.index(target_pole_id)
                if b <= t <= d:
                    return True

            if any_directional_pattern:
                if debug:
                    print(f"[🚌BUS] ❌ REJECT: Direction mismatch (Total {len(patterns)} patterns checked). rid={rid} board={board_pole_id} target={target_pole_id} dest={dest_id}")
                return False

            if target_pole_id and patterns:
                # 路線パターンは存在するが、このトリップの目的地(dest_id)がいずれのパターンにも含まれない場合
                # （入庫便など、通常の路線図に載らない特殊なパターンの可能性が高い）
                if debug:
                    print(f"[🚌BUS] ❌ REJECT: Trip destination {dest_id} is not in any pattern of {rid}. Cannot guarantee it stops at {target_pole_id}.")
                return False

            if debug:
                print(f"[🚌BUS] ⚠️ WARNING: No patterns at all for rid={rid}. Assuming OK. board={board_pole_id} dest={dest_id}")
            return True

        if debug:
            print(f"\n[🚌BUS] ────────── SEARCH START ──────────")
            print(f"[🚌BUS] 📍 Boarding: {pole_name} (ID: {pole_id})")
            print(f"[🚌BUS] 🆔 Route: {route_id} | Day: {day_type}")

        routes = target_dict.get(pole_id)
        candidate_trips = None

        if routes:
            candidate_trips = find_trips(routes, route_id)
            if debug and candidate_trips:
                print(f"[🚌BUS] ✅ Direct Match: ID={pole_id}")

        if not candidate_trips and pole_name and pole_name in self.name_to_pids:
            if debug:
                print(f"[🚌BUS] 🔄 ID Mismatch. Falling back to name match: '{pole_name}'")
                print(f"[🚌BUS]    Alternatives: {self.name_to_pids[pole_name]}")
            for alt_pid in self.name_to_pids[pole_name]:
                if alt_pid == pole_id:
                    continue
                alt_routes = target_dict.get(alt_pid)
                if not alt_routes:
                    if debug:
                        print(f"[🚌BUS]    ❌ Skip ID={alt_pid} (No timetable for {day_type})")
                    continue
                candidate_trips = find_trips(alt_routes, route_id)
                if candidate_trips:
                    if debug:
                        print(f"[🚌BUS]    ✅ Match Found! Using ID={alt_pid}")
                    break
                elif debug:
                    print(f"[🚌BUS]    ❌ Skip ID={alt_pid} (Route {route_id} not found)")

        if not candidate_trips:
            if debug:
                print(f"[🚌BUS] ❌ FINAL FAIL: No timetable for Route={route_id} at Bus Stop={pole_name}")
            return None

        if debug:
            now_str = min_to_time_str(current_time_min)
            sample = candidate_trips[: min(40, len(candidate_trips))]
            counts = {}
            for tr in sample:
                d = tr.get("dest") or "unknown"
                counts[d] = counts.get(d, 0) + 1
            print(f"[🚌BUS] 📊 Stats: Now={now_str} | Trips={len(candidate_trips)} | Targets={counts}")

        for trip in candidate_trips:
            dep = trip.get("dep")
            if dep is None:
                continue
            if dep >= current_time_min:
                if is_valid_trip(trip, route_id, pole_id):
                    if debug:
                        dest_id = trip.get("dest")
                        print(f"[🚌BUS] ⭐ PICKED: Departure={min_to_time_str(dep)} | Destination={dest_id}")
                    return dep

        if debug:
            print(f"[🚌BUS] ❌ NO UPCOMING: Current time {min_to_time_str(current_time_min)} exceeded all departures for this route.")
        return None

    def get_future_bus_trips(self, pole_id, route_id, current_time_min, limit=10, pole_name=None, day_type="weekday", target_pole_id=None, debug=False):
        if not debug:
            debug = os.getenv("DEBUG_BUS") == "1"

        if day_type == "saturday":
            target_dict = self.bus_departures_saturday
        elif day_type == "holiday":
            target_dict = self.bus_departures_holiday
        else:
            target_dict = self.bus_departures_weekday

        def find_trips(routes_dict, target_rid):
            if target_rid in routes_dict:
                return routes_dict[target_rid]
            for r_key, t_list in routes_dict.items():
                if target_rid in r_key or r_key in target_rid:
                    if debug:
                        print(f"[DEBUG_BUS] Fuzzy match route_id={target_rid} matched_key={r_key}")
                    return t_list
            return None

        def is_valid_trip(trip, rid, board_pole_id):
            if not target_pole_id:
                return True

            dest_id = trip.get("dest")
            if not dest_id:
                return True

            patterns = self.route_patterns_map.get(rid) or []
            if not patterns:
                return True

            any_directional_pattern = False

            for stops in patterns:
                if board_pole_id not in stops:
                    continue
                if dest_id not in stops:
                    continue

                b = stops.index(board_pole_id)
                d = stops.index(dest_id)

                if d < b:
                    continue

                any_directional_pattern = True

                if target_pole_id not in stops:
                    continue

                t = stops.index(target_pole_id)
                if b <= t <= d:
                    return True

            if any_directional_pattern:
                if debug:
                    print(f"[DEBUG_BUS] REJECT cannot reach target rid={rid} board={board_pole_id} target={target_pole_id} dest={dest_id}")
                return False

            return True

        routes = target_dict.get(pole_id) or {}
        candidate_trips = find_trips(routes, route_id)

        if not candidate_trips and pole_name and pole_name in self.name_to_pids:
            for alt_pid in self.name_to_pids[pole_name]:
                if alt_pid == pole_id:
                    continue
                alt_routes = target_dict.get(alt_pid) or {}
                candidate_trips = find_trips(alt_routes, route_id)
                if candidate_trips:
                    if debug:
                        print(f"[DEBUG_BUS] Fallback pole_id={pole_id} alt_pid={alt_pid} pole_name={pole_name}")
                    break

        if not candidate_trips:
            if debug:
                print(f"[DEBUG_BUS] No timetable pole_id={pole_id} route_id={route_id} day_type={day_type}")
            return []

        out = []
        rejected = 0
        for trip in candidate_trips:
            dep = trip.get("dep")
            if dep is None:
                continue
            if dep < current_time_min:
                continue
            if is_valid_trip(trip, route_id, pole_id):
                out.append(trip)
                if len(out) >= limit:
                    break
            else:
                rejected += 1

        if debug:
            now_str = min_to_time_str(current_time_min)
            dests = {}
            for tr in out:
                d = tr.get("dest") or "unknown"
                dests[d] = dests.get(d, 0) + 1
            print(f"[DEBUG_BUS] Future pole_id={pole_id} route_id={route_id} day_type={day_type} now={now_str} target_pole_id={target_pole_id} future={len(out)} rejected={rejected} dest_counts={dests}")

        return out

    def get_next_train_arrival(self, current_sta, next_sta, current_time_min, day_type="weekday", delays_snapshot=None):
        target_dict = self.train_patterns_weekday if day_type == "weekday" else self.train_patterns_weekend
        # For trains, we might need a similar split, but for now assuming weekend=holiday for trains
        # or we update load_train_timetables too? 
        # For Toei subway, Sat/Hol are usually same.
        trains = target_dict.get(current_sta)
        
        if "Asakusa" in current_sta and "Honjo" in current_sta:
             # print(f"[DEBUG TRAIN] Looking up {current_sta} -> {next_sta} at {current_time_min}. Found: {len(trains) if trains else 0} trips. DayType={day_type}")
             pass

        if not trains: return None
        
        for t in trains:
            base_dep = t["dep"]
            base_arr = t["arr"]
            
            # Use snapshot if provided, otherwise failover to live (though we should always have snapshot in search)
            delays_source = delays_snapshot if delays_snapshot is not None else self.realtime_delays
            delay_sec = delays_source.get(t["train_num"], 0)
            delay_min = delay_sec / 60.0
            
            actual_dep = base_dep + delay_min
            actual_arr = base_arr + delay_min

            if actual_dep >= current_time_min and t["next_sta"] == next_sta:
                return actual_arr
        return None

    # -------------------- GTFS ID Resolution --------------------
    def load_gtfs_mappings(self, gtfs_dir):
        print(f"[INFO] Loading GTFS mappings from {gtfs_dir}...")
        self.gtfs_route_map = {} # normalized_name -> route_id
        self.gtfs_stop_map = {}  # stop_name -> list of stop_ids

        # Load routes.txt
        routes_path = os.path.join(gtfs_dir, "routes.txt")
        if os.path.exists(routes_path):
            with open(routes_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rid = row['route_id']
                    short_name = row['route_short_name'] # e.g. "波01"
                    # norm matches _line_norm in engine
                    norm_name = _line_norm(short_name)
                    self.gtfs_route_map[norm_name] = rid
            print(f"[INFO] Loaded {len(self.gtfs_route_map)} routes from GTFS.")
        else:
            print(f"[WARN] routes.txt not found at {routes_path}")

        # Load stops.txt
        stops_path = os.path.join(gtfs_dir, "stops.txt")
        if os.path.exists(stops_path):
            with open(stops_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sid = row['stop_id']
                    name = row['stop_name']
                    if name not in self.gtfs_stop_map: self.gtfs_stop_map[name] = []
                    self.gtfs_stop_map[name].append(sid)
            print(f"[INFO] Loaded stops from GTFS.")
        else:
            print(f"[WARN] stops.txt not found at {stops_path}")

        # --- Load app_timetable.json for smart resolution ---
        # Assuming gtfs_dir is something like "data/ToeiBus-GTFS", parent is "data"
        timetable_path = os.path.join(os.path.dirname(gtfs_dir), "app_timetable.json")
        self.route_stop_stats = defaultdict(_create_int_dd) # route_id -> stop_id -> total_trips

        if os.path.exists(timetable_path):
            print(f"[INFO] Loading app timetable stats from {timetable_path}...")
            try:
                with open(timetable_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for rid, stops in data.items():
                        for sid, dirs in stops.items():
                            total = 0
                            for _, days in dirs.items():
                                for _, times in days.items():
                                    total += len(times)
                            self.route_stop_stats[rid][sid] = total
                print(f"[INFO] Loaded stats for {len(self.route_stop_stats)} routes.")
            except Exception as e:
                print(f"[WARN] Failed to load app_timetable.json: {e}")
        else:
            print(f"[WARN] app_timetable.json not found at {timetable_path} (Smart ID resolution disabled)")

    def convert_odpt_id_to_gtfs(self, odpt_id):
        """
        Convert ODPT BusstopPole ID to GTFS Stop ID.
        Example: odpt.BusstopPole:Toei.HiraiNanachomeDaisanApato.2205.3 -> 2205-03
        """
        if not odpt_id:
            print(f"[DEBUG] convert_odpt_id_to_gtfs: Empty odpt_id")
            return ""
        
        print(f"[DEBUG] convert_odpt_id_to_gtfs: Input odpt_id='{odpt_id}'")
        
        try:
            parts = odpt_id.split('.')
            print(f"[DEBUG] convert_odpt_id_to_gtfs: parts={parts}")
            
            if len(parts) >= 2:
                # Last two parts are usually code ("2205") and suffix ("3")
                code = parts[-2]
                suffix = parts[-1]
                print(f"[DEBUG] convert_odpt_id_to_gtfs: code='{code}', suffix='{suffix}'")
                
                if code.isdigit() and suffix.isdigit():
                    # GTFS stop_id uses 4-digit code (zero-padded) + 2-digit suffix
                    # Example: 665 -> 0665, 3 -> 03 => 0665-03
                    gtfs_id = f"{code.zfill(4)}-{int(suffix):02d}"
                    return gtfs_id
        except Exception as e:
            print(f"[WARN] Failed to convert ODPT ID {odpt_id}: {e}")
        
        return ""

    def resolve_gtfs_route_id(self, route_name_disp):
        # route_name_disp e.g. "都02"
        # normalize
        norm = _line_norm(route_name_disp)
        # Use getattr for safety against init issues
        mapping = getattr(self, 'gtfs_route_map', {})
        result = mapping.get(norm, "")
        print(f"[DEBUG] resolve_gtfs_route_id: '{route_name_disp}' -> norm:'{norm}' -> routeId:'{result}'")
        return result

    def resolve_gtfs_stop_id(self, gtfs_route_id, stop_name):
        print(f"[DEBUG] resolve_gtfs_stop_id: gtfs_route_id='{gtfs_route_id}', stop_name='{stop_name}'")
        
        mapping = getattr(self, 'gtfs_stop_map', {})
        candidates = mapping.get(stop_name, [])
        print(f"[DEBUG] resolve_gtfs_stop_id: candidates={candidates}")
        
        if not candidates:
            print(f"[DEBUG] resolve_gtfs_stop_id: No candidates for stop_name='{stop_name}'")
            return ""

        # Smart Resolution: Check if candidates exist in known route stats
        if gtfs_route_id and hasattr(self, 'route_stop_stats') and gtfs_route_id in self.route_stop_stats:
            known_stops = self.route_stop_stats[gtfs_route_id]
            print(f"[DEBUG] resolve_gtfs_stop_id: route_stop_stats available for route {gtfs_route_id}")
            
            # Valid candidates are those that exist in the timetable for this route and have trips
            valid_candidates = [c for c in candidates if c in known_stops and known_stops[c] > 0]
            print(f"[DEBUG] resolve_gtfs_stop_id: valid_candidates={valid_candidates}")
            
            if valid_candidates:
                # Sort by number of trips (descending)
                valid_candidates.sort(key=lambda x: known_stops[x], reverse=True)
                best = valid_candidates[0]
                print(f"[DEBUG] resolve_gtfs_stop_id (smart): '{stop_name}' (Route {gtfs_route_id}) -> {best} (trips: {known_stops[best]})")
                return best
            else:
                print(f"[DEBUG] resolve_gtfs_stop_id: Candidates {candidates} not found in timetable for Route {gtfs_route_id}")
        
        # Fallback: Prefer ID matching common patterns
        for c in candidates:
            if c.endswith("-01"):
                print(f"[DEBUG] resolve_gtfs_stop_id (fallback): '{stop_name}' -> '{c}' (preferred -01)")
                return c
        result = candidates[0]
        print(f"[DEBUG] resolve_gtfs_stop_id (fallback): '{stop_name}' -> '{result}' (first candidate)")
        return result


# -------------------- グラフ構築 --------------------
def build_graph(busstop_poles_path, busroute_patterns_path, stations_path, railways_path, walk_radius=300):
    G = nx.DiGraph()
    poles = load_json(busstop_poles_path)
    phys = {}
    for p in poles:
        pid = get_id(p)
        lat, lon = get_lat(p), get_lon(p)
        if pid and lat and lon:
            phys[pid] = {"lat": float(lat), "lon": float(lon), "name": p.get("dc:title") or pid}
    stations = load_json(stations_path)
    for s in stations:
        if not is_toei(s.get("odpt:operator")): continue
        sid = get_id(s)
        lat, lon = get_lat(s), get_lon(s)
        if sid and lat and lon:
            phys[sid] = {"lat": float(lat), "lon": float(lon), "name": s.get("dc:title") or sid}
    for pid, d in phys.items():
        G.add_node(("phys", pid), **d, kind="phys")

    def ensure_line_node(phys_id, line_id, display_name, mode, real_route_id=None):
        n = ("line", phys_id, line_id)
        if n not in G:
            base = phys[phys_id]
            G.add_node(n, lat=base["lat"], lon=base["lon"], name=f"{base['name']}@{display_name}",
                       line=line_id, kind="line", disp=display_name, norm=_norm_line(display_name), 
                       mode=mode, route_id=real_route_id)
            G.add_edge(("phys", phys_id), n, w=TRANSFER_PENALTY, etype="board")
            G.add_edge(n, ("phys", phys_id), w=0, etype="alight")
        return n

    patterns = load_json(busroute_patterns_path)
    for pat in patterns:
        if not is_toei(pat.get("odpt:operator")): continue
        route_id = pat.get("odpt:busroute")
        disp = (pat.get("dc:title") or "???").split()[0]
        norm = _norm_line(disp)
        family_key = f"bus:{norm}"
        orders = pat.get("odpt:busstopPoleOrder") or []
        try: orders = sorted(orders, key=lambda x: x.get("odpt:index", 0))
        except: pass
        seq = [o.get("odpt:busstopPole") for o in orders if o.get("odpt:busstopPole") in phys]
        
        if "T01" in route_id:
             print(f"[DEBUG GRAPH] Processing T01: {route_id} Title='{disp}' Norm='{norm}' SeqLen={len(seq)}")
        
        for a, b in zip(seq, seq[1:]):
            na = ensure_line_node(a, family_key, disp, "bus", route_id)
            nb = ensure_line_node(b, family_key, disp, "bus", route_id)
            if not G.has_edge(na, nb):
                G.add_edge(na, nb, w=BUS_RIDE_COST, etype="ride", line=family_key, mode="bus")
                if "T01" in route_id:
                     print(f"[DEBUG GRAPH] Added T01 edge: {na} -> {nb}")

    railways = load_json(railways_path)
    for rw in railways:
        if not is_toei(rw.get("odpt:operator")): continue
        line_id = get_id(rw)
        disp = rw.get("dc:title") or line_id
        orders = rw.get("odpt:stationOrder") or []
        try: orders = sorted(orders, key=lambda x: x.get("odpt:index", 0))
        except: pass
        seq = [o.get("odpt:station") for o in orders if o.get("odpt:station") in phys]
        for a, b in zip(seq, seq[1:]):
            na = ensure_line_node(a, line_id, disp, "rail")
            nb = ensure_line_node(b, line_id, disp, "rail")
            G.add_edge(na, nb, w=RAIL_RIDE_COST, etype="ride", line=line_id, mode="rail")
            G.add_edge(nb, na, w=RAIL_RIDE_COST, etype="ride", line=line_id, mode="rail")

    connect_walk_edges_phys(G, radius_m=walk_radius)
    return G

def connect_walk_edges_phys(G, radius_m=300):
    """Connect physical nodes within the walking radius using a simple spatial index."""

    phys_nodes = []
    for idx, (n, d) in enumerate(G.nodes(data=True)):
        if n[0] != "phys":
            continue
        phys_nodes.append((idx, n, d))

    if not phys_nodes:
        return

    # Approximate conversion from degrees to meters around the reference latitude.
    ref_lat = phys_nodes[0][2]["lat"]
    ref_lon = phys_nodes[0][2]["lon"]
    ref_lat_rad = math.radians(ref_lat)
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = math.cos(ref_lat_rad) * 111_320.0

    def to_local_meters(lat, lon):
        return (
            (lon - ref_lon) * meters_per_deg_lon,
            (lat - ref_lat) * meters_per_deg_lat,
        )

    cell_size = float(radius_m)
    grid = defaultdict(list)
    indexed_nodes = []

    for idx, node, data in phys_nodes:
        x, y = to_local_meters(data["lat"], data["lon"])
        cx, cy = int(x // cell_size), int(y // cell_size)
        grid[(cx, cy)].append(idx)
        indexed_nodes.append((idx, node, data, x, y, cx, cy))

    for idx, u, du, ux, uy, ucx, ucy in indexed_nodes:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for vidx in grid.get((ucx + dx, ucy + dy), []):
                    if vidx <= idx:
                        continue
                    v, dv = phys_nodes[vidx][1], phys_nodes[vidx][2]
                    dist = haversine(du["lat"], du["lon"], dv["lat"], dv["lon"])
                    if dist <= radius_m:
                        minutes = max(1.0, dist / WALK_SPEED_M_PER_MIN)
                        w = WALK_COST * minutes
                        G.add_edge(u, v, w=w, etype="walk", meters=dist)
                        G.add_edge(v, u, w=w, etype="walk", meters=dist)

def get_virtual_connections(G, lat, lon, name="目的地", walk_radius=300, spatial_index=None):
    """
    仮想目的地への接続情報を返す (G.copy()を回避するため)。
    
    Returns:
        dest_node_id (tuple): ("phys", "dest:...")
        connections (list): [(phys_node_id, weight, meters), ...]
    """
    dest_id = f"dest:{lat:.6f},{lon:.6f}"
    dest_node = ("phys", dest_id)
    
    connections = []
    
    # Use Spatial Index if available
    candidates = []
    if spatial_index:
        candidates = spatial_index.nearby_candidates(lat, lon, walk_radius)
        # candidates are lists of (node_id, lat, lon)
        
        # Convert to format for loop
        # Note: spatial_index candidates are (nid, lat, lon)
        # We need G loop style if we want to share logic, 
        # but here we just iterate candidates.
        for nid, nlat, nlon in candidates:
             dist = haversine(lat, lon, nlat, nlon)
             if dist <= walk_radius:
                 minutes = max(1.0, dist / WALK_SPEED_M_PER_MIN)
                 w = WALK_COST * minutes
                 connections.append((nid, w, dist))
    
    else:
        # Fallback to full scan
        for n, d in G.nodes(data=True):
            if n[0] != "phys": continue
            dist = haversine(lat, lon, d.get("lat"), d.get("lon"))
            if dist <= walk_radius:
                minutes = max(1.0, dist / WALK_SPEED_M_PER_MIN)
                w = WALK_COST * minutes
                connections.append((n, w, dist))
                
    count = len(connections)
    print(f"[DEBUG_DEST] Found {count} virtual connections for {dest_node} (radius={walk_radius}m)")
    return dest_node, connections

def nearest_phys(G, lat, lon, station_only=False, spatial_index=None):
    best, bestd = None, 1e30
    
    candidates = []
    if spatial_index:
        # Use simple radius (e.g. 1000m) for finding nearest
        raw_candidates = spatial_index.nearby_candidates(lat, lon, 1000)
        if not raw_candidates:
             # Retry wider if empty (fallback to all just in case, or wider radius)
             candidates = G.nodes(data=True) 
        else:
             candidates = []
             for nid, nlat, nlon in raw_candidates:
                 # Reconstruct data tuple expected by loop
                 candidates.append((nid, G.nodes[nid]))
    else:
        candidates = G.nodes(data=True)

    for n, d in candidates:
        if n[0] != "phys": continue
        if station_only and not is_station_id(n[1]): continue
        
        # Grid returns nlat/nlon, but 'd' has it too.
        # If using G.nodes(data=True) 'd' is full dict. 
        # If using grid, we constructed (n, node_data).
        
        # Simplified loop:
        dist = haversine(lat, lon, d["lat"], d["lon"])
        if dist < bestd: best, bestd = n, dist
        
    return best, bestd

# -------------------- 探索ロジック --------------------
def get_logical_signature(G, path):
    sig = []
    current_line = None
    for u, v in zip(path, path[1:]):
        e = G.edges[u, v]
        etype = e.get("etype")
        if etype == "ride":
            current_line = G.nodes[u].get("norm") or G.nodes[u].get("disp")
        elif etype == "alight":
            stop_name = G.nodes[v].get("name")
            if current_line:
                sig.append((current_line, stop_name))
                current_line = None
    return tuple(sig)

# -------------------- 共通ロジック: 時間計算ヘルパー --------------------
def advance_time(G, tm, u, v, curr_time, day_type="weekday", delays_snapshot=None, **kwargs):
    """
    1 本のエッジ (u -> v) に対して、現在時刻 curr_time を
    「実際の到着時刻」に進める。
    乗れない（終バス後など）場合は None を返す。
    **kwargs: target_pole_id 等のオプション
    """
    edge = G.edges[u, v]
    etype = edge.get("etype")

    # 徒歩
    if etype == "walk":
        return curr_time + (edge.get("meters", 0) / WALK_SPEED_M_PER_MIN)

    # 乗車（board）
    if etype == "board":
        phys_id = u[1]
        node = v if v[0] == "line" else u
        mode = G.nodes[node].get("mode")

        if mode == "bus":
            route_id = G.nodes[node].get("route_id")
            stop_name = G.nodes[u].get("name")
            
            # ターゲット指定があれば渡す
            target_pid = kwargs.get("target_pole_id")
            dep = tm.get_next_bus_departure(
                phys_id, route_id, curr_time,
                pole_name=stop_name,
                day_type=day_type,
                target_pole_id=target_pid
            )
            return dep
        elif mode == "rail":
            # 電車の乗車時点ではざっくり乗り換え待ち 2 分
            return curr_time + 2.0
        return curr_time

    # 走行（ride）
    if etype == "ride":
        mode = edge.get("mode")
        if mode == "rail":
            arr = tm.get_next_train_arrival(u[1], v[1], curr_time, day_type=day_type, delays_snapshot=delays_snapshot)
            return arr  # arr が None のときは呼び出し側で弾く
        elif mode == "bus":
            dist = edge.get("meters", 0)
            if dist > 0:
                return curr_time + (dist / 250.0) + 0.8
            else:
                return curr_time + 2.5
        return curr_time

    # 降車/乗換
    if etype in ("alight", "xfer"):
        return curr_time + 1.0

    return curr_time

# -------------------- 共通ロジック: セグメント詳細化 --------------------
# server.py から移動・共通化



def path_to_coords(G, path):
    """
    パス(ノード列)を [lat, lon] のリストに変換する
    """
    points = []
    for u in path:
        d = G.nodes[u]
        points.append([d["lat"], d["lon"]])
    return points


# -------------------- 統合検索ロジック --------------------
def search_best_routes_once(G, tm, a_phys, b_phys, mode="cost", start_time="10:00", limit=5, target_date_str=None, target_node=None, day_type=None, virtual_dest_connections=None, target_coords=None):
    """
    日付を指定して検索し、結果が0件なら翌日以降も探すラッパー
    """
    now = datetime.datetime.now()
    
    # 日付指定がある場合はそれを使う
    if target_date_str:
        try:
            d = datetime.datetime.strptime(target_date_str, "%Y-%m-%d")
            base_date = d.replace(hour=now.hour, minute=now.minute, second=now.second, microsecond=now.microsecond)
        except ValueError:
            print(f"[WARN] Invalid target_date_str: {target_date_str}, using today")
            base_date = now
    else:
        base_date = now
    
    print(f"[USER_DEBUG] search_best_routes_once: Received start_time={start_time}, target_date_str={target_date_str}")
    h, m = map(int, start_time.split(":"))
    start_dt = base_date.replace(hour=h, minute=m, second=0, microsecond=0)
    
    print(f"[DEBUG_TIME] search_best_routes_once: Calculated start_dt={start_dt}")

    # 単発検索（リトライなし）
    target_date = start_dt
    print(f"[DEBUG] Trying date: {target_date.date()}")
    
    current_time_str = start_time
    
    # 検索実行
    candidates = search_best_routes(G, tm, a_phys, b_phys, mode, current_time_str, limit, target_date, target_node=target_node, day_type=day_type, virtual_dest_connections=virtual_dest_connections, target_coords=target_coords)
    
    if candidates:
        # 見つかった！
        # 結果に日付情報を付与
        for cand in candidates:
            cand["departure_date"] = target_date.strftime("%Y-%m-%d")
            cand["is_future_suggestion"] = False
        return candidates

    return []

def search_best_routes(G, tm, a_phys, b_phys, mode="cost", start_time="10:00", limit=5, target_date=None, target_node=None, day_type=None, virtual_dest_connections=None, target_coords=None):
    """
    ServerとCLI共通のエントリーポイント。
    経路探索 -> 時刻表バリデーション -> セグメント化 -> 結果辞書のリスト作成 までを一気通貫で行う。
    """
    print(f"[DEBUG_TIME] search_best_routes: start_time_str={start_time}")
    if target_date is None:
        target_date = datetime.datetime.now()
    
    # 平日判定 (0-4: 月-金, 5-6: 土日)
    # 平日判定 (0-4: 月-金, 5-6: 土日) - AND NOW HOLIDAY SUPPORT
    if day_type is None:
        wd = target_date.weekday()
        if wd == 5:
            day_type = "saturday"
        elif wd == 6:
            day_type = "holiday"
        else:
            day_type = "weekday"
    
    # NOTE: Holidays on weekdays are not supported yet (needs holiday lib)
    target = target_node or b_phys
    print(f"[DEBUG] search_best_routes: date={target_date.date()}, day_type={day_type}, target={target}")
    
    candidates = []
    
    # Snapshot delays at the start of search
    delays_snapshot = tm.get_delays_snapshot()

    # 1. Timeモード (最速経路1つ)
    if mode == "time" or mode == "fast":
        arr_min, path = find_fastest_path(
            G,
            tm,
            a_phys,
            target,
            start_time_str=start_time,
            day_type=day_type,
            delays_snapshot=delays_snapshot,
            virtual_dest_connections=virtual_dest_connections,
            target_coords=target_coords,
        )
        
        # Check validity (Short Trip check)
        if path:
            real_arr = calculate_real_arrival_time(G, tm, path, start_time, day_type=day_type, delays_snapshot=delays_snapshot)
            if real_arr is None:
                print(f"[WARN] Fastest path invalidated by timetable check (possibly short trip).")
                path = None # Discard

        if path:
            segs = segments_detailed(G, path, tm, start_time, day_type=day_type, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections)
            lines = list(dict.fromkeys([s["title"] for s in segs if s["kind"] in ("bus", "rail")]))
            
            # デバッグログ: 経路セグメント詳細
            print("[DEBUG] ========== Route Segments (Fastest) ==========")
            for i, seg in enumerate(segs):
                print(f"[DEBUG] Segment {i+1}: kind={seg['kind']}, title={seg.get('title', 'N/A')}, from={seg.get('from_', 'N/A')}, to={seg.get('to', 'N/A')}")
            print("[DEBUG] ================================================")
            
            start_min = time_str_to_min(start_time)
            duration = int(arr_min - start_min)
            
            # 統計情報の計算
            num_rides = sum(1 for s in segs if s["kind"] in ("bus", "rail"))
            walk_dist = sum(s["meters"] for s in segs if s["kind"] == "walk")

            candidates.append({
                "id": "Fastest",
                "lines": lines,
                "total_time": duration,
                "arrival_time": min_to_time_str(arr_min),
                "steps": segs,
                "score_label": f"{duration}分",
                "cost_score": 0.0,
                "walk_m": walk_dist,
                "path": path,
                "points": path_to_coords(G, path),
                "total": duration,
                "transfers": max(0, num_rides - 1),
                "rides": num_rides,
                "walks": int(walk_dist),
                "boards": num_rides,
            })

    # 2. Costモード (楽な経路トップK)
    else:
        path_gen = find_paths_generator(
            G,
            tm,
            a_phys,
            target,
            start_time_str=start_time,
            day_type=day_type,
            max_search=30000,
            max_visited=100000,
            max_travel_min=MAX_TRAVEL_MIN,
            delays_snapshot=delays_snapshot,
        )

        valid_count = 0
        
        for cand in path_gen:
            path = cand["path"]
            
            # 答え合わせ (時刻表チェック)
            real_arr = calculate_real_arrival_time(G, tm, path, start_time, day_type=day_type, delays_snapshot=delays_snapshot)
            
            if real_arr is not None:
                # 合格
                segs = segments_detailed(G, path, tm, start_time, day_type=day_type, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections)
                lines = list(dict.fromkeys([s["title"] for s in segs if s["kind"] in ("bus", "rail")]))
                
                # デバッグログ: 経路セグメント詳細
                # print(f"[DEBUG] ========== Route Segments (Comfort-{valid_count+1}) ==========")
                # for i, seg in enumerate(segs):
                #    dep_s = seg.get('dep_time', 'N/A')
                #    arr_s = seg.get('arr_time', 'N/A')
                #    print(f"[DEBUG] Segment {i+1}: [{dep_s} - {arr_s}] kind={seg['kind']}, title={seg.get('title', 'N/A')}, from={seg.get('from_', 'N/A')}, to={seg.get('to', 'N/A')}")
                # print("[DEBUG] ================================================")
                
                start_min = time_str_to_min(start_time)
                duration = int(real_arr - start_min)
                
                num_rides = sum(1 for s in segs if s["kind"] in ("bus", "rail"))
                
                candidates.append({
                    "id": f"Comfort-{valid_count+1}",
                    "lines": lines,
                    "total_time": duration,
                    "arrival_time": min_to_time_str(real_arr),
                    "steps": segs,
                    "score_label": f"楽さ {cand['cost']:.1f} (所要{duration}分)",
                    "cost_score": cand['cost'],
                    "walk_m": cand['walk_m'],
                    "path": path,
                    "points": path_to_coords(G, path),
                    "total": int(cand['cost']),
                    "transfers": max(0, num_rides - 1),
                    "rides": num_rides,
                    "walks": int(cand['walk_m']),
                    "boards": num_rides,
                })
                
                valid_count += 1
                if valid_count >= limit:
                    break
            else:
                # 不合格（終バス後など）
                print(f"[DEBUG] Candidate rejected by timetable check: path_len={len(path)}") 
                pass
                
    return candidates

# -------------------- 探索ロジック --------------------

def pole_base(pid: str) -> str:
    """
    Extracts the logical stop ID from a pole ID.
    e.g. odpt.BusstopPole:Toei.HiraiNanachome.1350.1 -> odpt.BusstopPole:Toei.HiraiNanachome.1350
    """
    if not (isinstance(pid, str) and pid.startswith("odpt.BusstopPole:")):
        return pid
    parts = pid.split(".")
    if len(parts) < 2:
        return pid
    return ".".join(parts[:-1])


def find_paths_generator(
    G,
    tm,
    start_node,
    target_node,
    start_time_str="10:00",
    day_type="weekday",
    max_search=30000,
    max_visited=15000,
    max_travel_min=MAX_TRAVEL_MIN,
    delays_snapshot=None,
    time_limit_sec=15.0,
    virtual_dest_connections=None,
    target_coords=None,
):
    import time
    start_clock = time.monotonic()

    print(f"[DEBUG_TIME] find_paths_generator: start_time_str={start_time_str}")
    start_min = time_str_to_min(start_time_str)

    t_lat, t_lon = None, None
    if target_coords:
        t_lat, t_lon = target_coords
    else:
        try:
            t_lat = G.nodes[target_node]["lat"]
            t_lon = G.nodes[target_node]["lon"]
        except KeyError:
            pass

    def heuristic(n):
        if t_lat is None:
            return 0.0
        n_lat = G.nodes[n].get("lat")
        n_lon = G.nodes[n].get("lon")
        if n_lat is None or n_lon is None:
            return 0.0
        dist = haversine(n_lat, n_lon, t_lat, t_lon)
        return dist / 400.0

    start_h = heuristic(start_node)
    pq = [(start_h, 0.0, start_node, 0.0, 0.0, start_min, (start_node, None))]

    # ゴール判定用ノード集合の構築
    # 目的地が特定のポール（例: 平井七丁目.2）でも、同じ停留所の別ポール（.1など）に
    # 到着すればゴールと見なす。ただし仮想（座標）目的地の時は拡張しない。
    target_goal_nodes = {target_node}
    if target_node and target_node[0] == "phys":
        pid = target_node[1]
        if isinstance(pid, str) and pid.startswith("odpt.BusstopPole:"):
            base = pole_base(pid)
            for n in G.nodes:
                if n[0] == "phys" and isinstance(n[1], str) and n[1].startswith("odpt.BusstopPole:"):
                    if pole_base(n[1]) == base:
                        target_goal_nodes.add(n)
    
    if len(target_goal_nodes) > 1:
        print(f"[DEBUG_TARGET] Expanded target_goal_nodes: {len(target_goal_nodes)} poles included.")

    if target_goal_nodes:
        print(f"[DEBUG_TARGET] target_goal_nodes size={len(target_goal_nodes)}")


    count_visited = defaultdict(int)
    best_cost = {}
    seen_logical_routes = set()
    yielded_count = 0
    visited_count = 0

    while pq:
        if visited_count > 0 and visited_count % 1000 == 0:
            if time.monotonic() - start_clock > time_limit_sec:
                print(f"[WARN] Search timed out after {time_limit_sec}s. Yielded {yielded_count} paths.")
                return

        _, cost, u, total_walk_m, seg_walk_m, curr_time, path_chain = heapq.heappop(pq)
        visited_count += 1

        if visited_count > max_visited:
            print(f"[WARN] Search exceeded max_visited {max_visited}. Stopping.")
            return

        if curr_time - start_min > max_travel_min:
            continue

        walk_bucket = int(seg_walk_m // 10)
        state_key = (u, walk_bucket)

        prev_best = best_cost.get(state_key)
        if prev_best is not None and cost >= prev_best:
            continue
        best_cost[state_key] = cost

        if u in target_goal_nodes: # Modified: Check against target_goal_nodes
            full_path = reconstruct_path(path_chain)
            sig = get_logical_signature(G, full_path)
            if sig in seen_logical_routes:
                continue
            seen_logical_routes.add(sig)

            yield {
                "cost": cost,
                "path": full_path,
                "walk_m": total_walk_m,
            }
            yielded_count += 1
            if yielded_count >= max_search:
                return
            continue

        # Removed aggressive pruning:
        # if count_visited[state_key] >= 20:
        #     continue
        # count_visited[state_key] += 1

        if virtual_dest_connections and target_node and target_node[0] == "phys" and str(target_node[1]).startswith("dest:"):
            for nid, vw, vmeters in virtual_dest_connections:
                if nid == u:
                    next_time_v = curr_time + (vmeters / WALK_SPEED_M_PER_MIN)
                    if next_time_v - start_min <= max_travel_min:
                        new_total_v = total_walk_m + vmeters
                        new_seg_v = vmeters
                        if new_total_v <= MAX_TOTAL_WALK_M and new_seg_v <= MAX_WALK_SEG_M:
                            new_cost_v = cost + vw
                            heapq.heappush(
                                pq,
                                (new_cost_v + heuristic(target_node), new_cost_v, target_node,
                                 new_total_v, new_seg_v, next_time_v, (target_node, path_chain)),
                            )
                    break


        for v in G[u]:
            edge = G[u][v]
            w = edge.get("w", 0.0)
            meters = edge.get("meters", 0.0)

            next_time = advance_time(G, tm, u, v, curr_time, day_type=day_type, delays_snapshot=delays_snapshot)
            if next_time is None:
                continue
            if next_time - start_min > max_travel_min:
                continue

            new_total_walk_m = total_walk_m
            new_seg_walk_m = seg_walk_m

            if edge.get("etype") == "walk":
                step_m = meters if meters > 0 else 1.0
                new_seg_walk_m = seg_walk_m + step_m
                if new_seg_walk_m > MAX_WALK_SEG_M:
                    continue
                new_total_walk_m = total_walk_m + step_m
                if new_total_walk_m > MAX_TOTAL_WALK_M:
                    continue
            else:
                new_seg_walk_m = 0.0

            new_cost = cost + w
            new_h = heuristic(v)

            heapq.heappush(
                pq,
                (new_cost + new_h, new_cost, v, new_total_walk_m, new_seg_walk_m, next_time, (v, path_chain)),
            )

def find_fastest_path(
    G,
    tm,
    start_node,
    target_node,
    start_time_str="10:00",
    day_type="weekday",
    max_travel_min=MAX_TRAVEL_MIN,
    delays_snapshot=None,
    virtual_dest_connections=None, # Added for consistency, though not used in fastest path logic
    target_coords=None, # Added for consistency, though not used in fastest path logic
):
    """
    最速パス探索（メモリ最適化版）
    """
    start_min = time_str_to_min(start_time_str)
    # ★変更: path をタプルチェーンに
    pq = [(start_min, start_node, (start_node, None), 0.0, 0.0)]
    visited_time = {}

    # 目的地のバス停ID群を取得（方向フィルタリング用）
    target_pole_ids = set()
    def add_poles_by_name(pid):
        if not (isinstance(pid, str) and pid.startswith("odpt.BusstopPole:")):
            return
        node_id = ("phys", pid)
        if node_id in G.nodes:
            name = G.nodes[node_id].get("name")
            if name and tm and hasattr(tm, "name_to_pids"):
                for p in tm.name_to_pids.get(name, []):
                    if p.startswith("odpt.BusstopPole:"):
                        target_pole_ids.add(p)
        target_pole_ids.add(pid)

    if virtual_dest_connections:
        for nid, _, _ in virtual_dest_connections:
            if nid[0] == "phys":
                add_poles_by_name(nid[1])
    elif target_node and target_node[0] == "phys":
        add_poles_by_name(target_node[1])

    while pq:
        curr_time, u, path_chain, total_walk_m, seg_walk_m = heapq.heappop(pq)
        
        if curr_time - start_min > max_travel_min:
            continue

        if u == target_node:
            # ★変更: 復元して返す
            return curr_time, reconstruct_path(path_chain)

        state_key = (u, int(seg_walk_m // 10))
        if state_key in visited_time and visited_time[state_key] <= curr_time:
            continue
        visited_time[state_key] = curr_time

        for v in G[u]:
            edge = G[u][v]
            etype = edge.get("etype")
            meters = edge.get("meters", 0.0)

            next_time = advance_time(G, tm, u, v, curr_time, day_type=day_type, delays_snapshot=delays_snapshot, target_pole_ids=target_pole_ids)
            if next_time is None:
                continue
            if next_time - start_min > max_travel_min:
                continue

            new_total_walk = total_walk_m
            new_seg_walk = seg_walk_m

            if etype == "walk":
                step_m = meters if meters > 0 else 1.0
                new_seg_walk = seg_walk_m + step_m
                if new_seg_walk > MAX_WALK_SEG_M:
                    continue
                new_total_walk = total_walk_m + step_m
                if new_total_walk > MAX_TOTAL_WALK_M:
                    continue
            else:
                new_seg_walk = 0.0

            # ★変更: タプルチェーンで push
            heapq.heappush(pq, (next_time, v, (v, path_chain), new_total_walk, new_seg_walk))
            
    return None, None

def calculate_real_arrival_time(
    G,
    tm,
    path,
    start_time_str="10:00",
    day_type="weekday",
    max_search=30000,
    max_travel_min=MAX_TRAVEL_MIN,
    delays_snapshot=None,
):
    start_min = time_str_to_min(start_time_str)
    curr_time = start_min
    
    for i in range(len(path) - 1):
        u = path[i]
        v = path[i+1]
        
        edge = G.edges[u, v]
        etype = edge.get("etype")
        target_pid = None
        
        # If boarding, look ahead for alight (短区間バスの除外ロジック)
        if etype == "board" and G.nodes[v].get("mode") == "bus":
            if v[0] == "line":
                for j in range(i + 1, len(path) - 1):
                    u2 = path[j]
                    v2 = path[j+1]
                    e2 = G.edges[u2, v2]
                    if e2.get("etype") == "alight":
                        target_pid = v2[1]
                        break
        
        next_time = advance_time(
            G, tm, u, v,
            curr_time,
            day_type=day_type,
            target_pole_id=target_pid,
            delays_snapshot=delays_snapshot,
        )
        if next_time is None:
            print(f"[DEBUG] Path REJECTED in calc_real_time: Cannot advance time at {u}->{v} (etype={etype})")
            return None
        
        if next_time - start_min > max_travel_min:
            # 上限時間を超える経路は「現実的でない」とみなして不採用
            print(f"[DEBUG] Path REJECTED in calc_real_time: Time limit exceeded at {u}->{v}. {next_time - start_min:.0f} > {max_travel_min}")
            return None

        curr_time = next_time
            
    return curr_time

def segments_detailed(G, path, tm, start_time_str="10:00", day_type="weekday", delays_snapshot=None, virtual_dest_connections=None):
    print(f"[DEBUG_TIME] segments_detailed: start_time_str={start_time_str}", flush=True)
    segs = []
    cur = None
    last_phys = None
    curr_time = time_str_to_min(start_time_str)

    def flush():
        nonlocal cur
        if cur:
            if cur["kind"] == "walk":
                # 0m 移動など実質的に位置が変わらない場合は捨てる
                if cur.get("meters", 0) <= 0 or cur.get("from_") == cur.get("to"):
                    cur = None
                    return
                cur["minutes"] = max(
                    1,
                    math.ceil(cur.get("meters", 0) / WALK_SPEED_M_PER_MIN)
                )
            elif cur["kind"] in ("bus", "rail"):
                if cur.get("arrival_time"):
                    dep_min = time_str_to_min(cur.get("departure_time"))
                    arr_min = time_str_to_min(cur.get("arrival_time"))
                    cur["minutes"] = max(1, int(arr_min - dep_min))
                else:
                    cur["minutes"] = max(1, int(cur.get("edges", 0) * 2.0))
            segs.append(cur)
            cur = None

    for i, (u, v) in enumerate(zip(path, path[1:])):
        # 仮想エッジ対応
        edge = None
        if G.has_edge(u, v):
            edge = G.edges[u, v]
        else:
            # Gにない場合、仮想目的地の接続を確認
            if virtual_dest_connections and u[0] == "phys" and v[0] == "phys" and str(v[1]).startswith("dest:"):
               # u -> v(dest)
               for nid, w, dist in virtual_dest_connections:
                   if nid == u:
                       # 仮想エッジを合成
                       edge = {"etype": "walk", "meters": dist, "w": w}
                       print(f"[DEBUG_VIRTUAL] Synthesized virtual edge {u} -> {v} meters={dist}")
                       break
        
        if not edge:
            print(f"[WARN] Edge not found {u} -> {v} in segments_detailed. Skipping. u_phys={u[0]=='phys'} v_starts_dest={str(v[1]).startswith('dest:')} has_vconn={bool(virtual_dest_connections)}")
            if virtual_dest_connections:
                print(f"[DEBUG_VIRTUAL] Connections available: {virtual_dest_connections}")
            continue

        etype = edge.get("etype")
        if u[0] == "phys": last_phys = u

        if etype == "walk":
            if not cur or cur["kind"] != "walk":
                flush()
                from_name = G.nodes[u]["name"] if u[0]=="phys" else "???"
                cur = { "kind": "walk", "title": "徒歩", "edges": 0, "from_": from_name, "to": None, "meters": 0 }
            cur["edges"] += 1
            cur["meters"] += edge.get("meters", 0)
            if v[0] == "phys": cur["to"] = G.nodes[v]["name"]
            curr_time += (edge.get("meters", 0) / WALK_SPEED_M_PER_MIN)
            continue

        node = v if v[0] == "line" else (u if u[0] == "line" else None)
        if not node: continue
        line_id = G.nodes[node].get("line")
        line_disp = G.nodes[node].get("disp") or "???"
        mode = G.nodes[node].get("mode") # bus or rail

        if etype == "board":
            flush()
            from_name = G.nodes[last_phys]["name"] if last_phys else "???"
            
            # Get coords for Boarding Stop
            start_lat = G.nodes[last_phys]["lat"] if last_phys and "lat" in G.nodes[last_phys] else None
            start_lon = G.nodes[last_phys]["lon"] if last_phys and "lon" in G.nodes[last_phys] else None
            
            curr_stops = [{
                "name": from_name, 
                "is_origin": True,
                "lat": start_lat,
                "lon": start_lon
            }]
            print(f"[DEBUG_COORD] Board {from_name}: lat={start_lat}, lon={start_lon}")

            phys_id = u[1]
            gtfs_route_id = ""
            gtfs_stop_id = ""

            if mode == "bus":
                route_id = G.nodes[v].get("route_id") # ODPT Route ID (or internal)
                stop_name = G.nodes[u].get("name")
                
                # Lookahead for target_pole_id
                target_pid = None
                if v[0] == "line":
                     for j in range(i + 1, len(path) - 1):
                        u2 = path[j]
                        v2 = path[j+1]
                        e2 = G.edges[u2, v2]
                        if e2.get("etype") == "alight":
                            target_pid = v2[1]
                            break

                # Update Time
                dep = tm.get_next_bus_departure(phys_id, route_id, curr_time, pole_name=stop_name, day_type=day_type, target_pole_id=target_pid)

                if "Ue23" in route_id:
                     print(f"[DEBUG TRACE] Boarding Ue23 at {stop_name} ({phys_id}): curr={min_to_time_str(curr_time)}, result={min_to_time_str(dep) if dep else 'None'}")

                # 過去便で巻き戻さない
                if dep is not None and dep + 1e-6 >= curr_time:
                    curr_time = dep
                else:
                    print(f"[WARN_TIME] dep rollback blocked start={min_to_time_str(time_str_to_min(start_time_str))} curr={min_to_time_str(curr_time)} dep={min_to_time_str(dep) if dep is not None else 'None'} stop={stop_name} rid={route_id} pid={phys_id}")
                
                # Resolve GTFS IDs
                if hasattr(tm, "resolve_gtfs_route_id"):
                    gtfs_route_id = tm.resolve_gtfs_route_id(line_disp)
                    if gtfs_route_id:
                        # 1. Try direct conversion from ODPT ID (Precise branch handling)
                        gtfs_stop_id = tm.convert_odpt_id_to_gtfs(phys_id)
                        if gtfs_stop_id:
                            print(f"[DEBUG] Converted ODPT ID {phys_id} -> GTFS ID {gtfs_stop_id}")
                        
                        # 2. Fallback to name-based resolution (Smart/Stats based)
                        if not gtfs_stop_id:
                            gtfs_stop_id = tm.resolve_gtfs_stop_id(gtfs_route_id, from_name)
                
                print(f"[DEBUG] Board segment: line_disp='{line_disp}', gtfs_route_id='{gtfs_route_id}', gtfs_stop_id='{gtfs_stop_id}'")

            elif mode == "rail":
                curr_time += 2.0
            
            odpt_route_id = route_id if mode == "bus" else ""
            departure_pole_id = phys_id if mode == "bus" else ""
            cur = {
                "kind": mode, "title": line_disp, "line": line_id, 
                "edges": 0, "from_": from_name, "to": None, "stops": curr_stops,
                "odptRouteId": odpt_route_id,
                "departurePoleId": departure_pole_id,
                "routeId": gtfs_route_id,
                "departureStopId": gtfs_stop_id,
                "departure_time": min_to_time_str(curr_time)
            }
        
        elif etype == "ride":
            if cur and cur["kind"] in ("bus", "rail"):
                cur["edges"] += 1
                stop_name = "???"
                phys_key = ("phys", v[1]) if v[0] == "line" else ("phys", u[1])
                
                s_lat, s_lon = None, None
                if phys_key in G: 
                    stop_name = G.nodes[phys_key]["name"]
                    s_lat = G.nodes[phys_key].get("lat")
                    s_lon = G.nodes[phys_key].get("lon")

                if not cur["stops"] or cur["stops"][-1]["name"] != stop_name:
                    cur["stops"].append({
                        "name": stop_name,
                        "lat": s_lat,
                        "lon": s_lon
                    })
            
            if mode == "rail":
                arr = tm.get_next_train_arrival(u[1], v[1], curr_time, day_type=day_type, delays_snapshot=delays_snapshot)
                if arr: curr_time = arr
                else: curr_time += edge.get("w", 2.0)
            else:
                dist = edge.get("meters", 0)
                if dist > 0: curr_time += (dist / 250.0) + 0.8
                else: curr_time += 2.5

        elif etype in ("alight", "xfer"):
            if cur and cur["kind"] in ("bus", "rail"):
                to_phys = v if v[0] == "phys" else last_phys
                if to_phys:
                    to_name = G.nodes[to_phys]["name"]
                    cur["to"] = to_name

                    if cur.get("kind") == "bus":
                        arrival_pole_id = to_phys[1]
                        cur["arrivalPoleId"] = arrival_pole_id
                        arrival_stop_id = ""
                        if cur.get("routeId") and hasattr(tm, "convert_odpt_id_to_gtfs"):
                            arrival_stop_id = tm.convert_odpt_id_to_gtfs(arrival_pole_id)
                            if not arrival_stop_id and hasattr(tm, "resolve_gtfs_stop_id"):
                                arrival_stop_id = tm.resolve_gtfs_stop_id(cur["routeId"], to_name)
                        cur["arrivalStopId"] = arrival_stop_id
                    
                    e_lat = G.nodes[to_phys].get("lat")
                    e_lon = G.nodes[to_phys].get("lon")
                    print(f"[DEBUG_COORD] Alight {to_name}: lat={e_lat}, lon={e_lon}")

                    if not cur["stops"] or cur["stops"][-1]["name"] != to_name:
                        cur["stops"].append({
                            "name": to_name, 
                            "is_destination": True,
                            "lat": e_lat,
                            "lon": e_lon
                        })
                    else:
                        cur["stops"][-1]["is_destination"] = True
                        cur["stops"][-1]["lat"] = e_lat
                        cur["stops"][-1]["lon"] = e_lon

                cur["arrival_time"] = min_to_time_str(curr_time)
                flush()
            curr_time += 1.0

    if cur: flush()
    return segs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--busstop-poles", required=True)
    ap.add_argument("--busroute-patterns", required=True)
    ap.add_argument("--stations", required=True)
    ap.add_argument("--railways", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--walk", type=int, default=300)
    ap.add_argument("--mode", choices=["cost", "time"], default="cost")
    ap.add_argument("--start-time", default="10:00")
    ap.add_argument("--bus-timetables", default="data/odpt_BusstopPoleTimetable.json")
    ap.add_argument("--train-timetables", default="data/odpt_TrainTimetable.json")
    args = ap.parse_args()

    print("[INFO] Building Graph...")
    G = build_graph(args.busstop_poles, args.busroute_patterns, args.stations, args.railways, walk_radius=args.walk)
    
    alat, alon = map(float, args.a.split(","))
    blat, blon = map(float, args.b.split(","))
    a_phys, ad = nearest_phys(G, alat, alon)
    b_phys, bd = nearest_phys(G, blat, blon, station_only=True)
    if not b_phys or bd > 500: b_phys, bd = nearest_phys(G, blat, blon)

    if not a_phys or not b_phys:
        print("[FAIL] Start/End not found")
        sys.exit(1)
    print(f"[INFO] {G.nodes[a_phys]['name']} -> {G.nodes[b_phys]['name']}")

    virtual_graph, dest_node, conn_count = add_virtual_destination_node(
        G, blat, blon, name="目的地", walk_radius=args.walk
    )
    if conn_count == 0:
        print(f"[DEBUG_DEST] No nearby Toei nodes within walk radius {args.walk}m for destination.")

    tm = TimetableManager()
    print(f"[INFO] Loading Timetables...")
    tm.load_bus_timetables(args.bus_timetables)
    tm.load_bus_route_patterns(args.busroute_patterns)
    tm.load_train_timetables(args.train_timetables)
    tm.build_name_index(G)
    
    print("[server] Initialization Done.")
    
    # ★変更: リトライ付き検索を呼び出す
    results = search_best_routes_once(
        virtual_graph, tm, a_phys, b_phys,
        mode=args.mode,
        start_time=args.start_time,
        limit=5,
        target_node=dest_node,
    )

    if not results:
        print(f"[DEBUG_DEST] Virtual destination search produced no candidates. Falling back to nearest node {b_phys}.")
        results = search_best_routes_once(
            G,
            tm,
            a_phys,
            b_phys,
            mode=args.mode,
            start_time=args.start_time,
            limit=5,
        )

    if not results:
        print("No valid route found.")
        return
    else:
        for cand in results:
            steps = cand.get("steps") or []
            if not steps:
                continue
            last = steps[-1]
            meters = last.get("meters") or last.get("distance") or 0
            print(
                f"[DEBUG_DEST] Candidate {cand.get('id')} last_kind={last.get('kind')} "
                f"to={last.get('to')} meters={meters}"
            )

    print(f"\n[INFO] Found {len(results)} Routes")
    for i, res in enumerate(results, 1):
        print("-" * 40)
        print(f"#{i} {res['score_label']} / Arr: {res['arrival_time']}")
        if res.get("is_future_suggestion"):
            print(f"  [WARNING] Future Suggestion: {res.get('departure_date')}")
        print(f"    Lines: {' -> '.join(res['lines'])}")
        print(f"    Steps:")
        for step in res['steps']:
            if step['kind'] == 'walk':
                print(f"      [徒歩] {step['meters']:.0f}m ({step['minutes']:.0f}分)")
            else:
                print(f"      [{step['kind'].upper()}] {step['title']} ({step['from_']} -> {step['to']})")


# -------------------- 新機能: 一本で行ける場所検索 --------------------

def get_reachable_stops(G, tm, lat, lon, limit_dist=1000, spatial_index=None):
    """
    GPS座標から最寄りのバス停・駅を特定し、そこから乗り換えなしで行ける
    すべてのバス停・駅のリストを返す。
    """
    # 1. 最寄りの物理ノード（バス停/駅）を探す
    start_candidates = []
    
    # まず「一番近いノード」を見つける (基準点)
    nearest_node, nearest_dist = nearest_phys(G, lat, lon, spatial_index=spatial_index)
    
    if not nearest_node or nearest_dist > limit_dist:
        return {
            "found": False,
            "message": "近くに都営交通のバス停・駅が見つかりませんでした。"
        }
    
    SEARCH_RADIUS_M = 500.0  # 500m以内のポールはすべて「現在地」とみなす
    
    if spatial_index:
        raw_candidates = spatial_index.nearby_candidates(lat, lon, SEARCH_RADIUS_M)
        for nid, nlat, nlon in raw_candidates:
            dist = haversine(lat, lon, nlat, nlon)
            if dist <= SEARCH_RADIUS_M:
                start_candidates.append(nid[1])
    else:
        for n, d in G.nodes(data=True):
            if n[0] != "phys": continue
            n_lat = d.get("lat")
            n_lon = d.get("lon")
            if n_lat and n_lon:
                dist = haversine(lat, lon, n_lat, n_lon)
                if dist <= SEARCH_RADIUS_M:
                    start_candidates.append(n[1]) # IDを追加

    # 万が一何もなければ（nearest_physで見つかってるのでありえないが）nearestを入れる
    if not start_candidates:
        start_candidates.append(nearest_node[1])

    nearest_info = G.nodes[nearest_node]
    
    # 到達可能なバス停を格納する辞書 (id -> info)
    reachable_map = {}
    
    # 2. 候補となるすべてのバス停（ポール）について、通る路線を走査
    for start_id in start_candidates:
        for route_id, patterns in tm.route_patterns_map.items():
            for seq in patterns:
                # このパターンに現在地が含まれているか？
                if start_id in seq:
                    idx = seq.index(start_id)
                    
                    # 終点の場合はスキップ
                    if idx == len(seq) - 1:
                        continue

                    # 現在地より「後」にあるバス停はすべて到達可能
                    future_stops = seq[idx+1:]
                    
                    for next_stop_id in future_stops:
                        # 既に登録済みならスキップ（複数路線で行ける場合など）
                        if next_stop_id in reachable_map:
                            continue
                            
                        # 自分自身（候補に入っているポール）への移動は除外
                        if next_stop_id in start_candidates:
                            continue

                        node_key = ("phys", next_stop_id)
                        if node_key in G:
                            node_data = G.nodes[node_key]
                            reachable_map[next_stop_id] = {
                                "id": next_stop_id,
                                "name": node_data.get("name"),
                                "lat": node_data.get("lat"),
                                "lon": node_data.get("lon"),
                                # どの路線で行けるか（代表の1つを入れておく、またはリスト化する）
                                "via_route": route_id 
                            }

    # リストに変換してソート（必要なら距離順や名前順に）
    reachable_list = list(reachable_map.values())
    
    return {
        "found": True,
        "nearest_stop": {
            "id": nearest_node[1],
            "name": nearest_info.get("name"),
            "lat": nearest_info.get("lat"),
            "lon": nearest_info.get("lon"),
            "dist_m": nearest_dist
        },
        "reachable_stops": reachable_list,
        "count": len(reachable_list)
    }


if __name__ == "__main__":
    main()