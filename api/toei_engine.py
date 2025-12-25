#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# toei_engine.py

import json, argparse, math, sys, heapq, datetime
import os
import networkx as nx
from collections import defaultdict


# -------------------- チューニング定数 --------------------
print("[INFO] toei_engine loaded: build=2025-12-26-1") # Deployment Verification Log
BUS_RIDE_COST = 0.8
RAIL_RIDE_COST = 0.8
WALK_COST = 1.5
WALK_SPEED_M_PER_MIN = 80.0 

TRANSFER_PENALTY = 5.0

MAX_WALK_SEG_M = 1000.0

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
    
    # Restore safety check for wrapped result
    if isinstance(data, dict):
        if "result" in data and isinstance(data["result"], list):
            return data["result"]
        return [data]

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
        # Dynamic search range based on radius
        # Typically 1 cell is enough for radius < cell_size, but safe to cover ceil
        range_val = int(math.ceil(radius_m / self.cell_size_m))
        
        for dx in range(-range_val, range_val + 1):
            for dy in range(-range_val, range_val + 1):
                cell = (cx + dx, cy + dy)
                for item in self.grid.get(cell, []):
                    candidates.append(item)
        return candidates

def pole_base(pid: str) -> str:
    if not (isinstance(pid, str) and "BusstopPole:" in pid):
        return pid
    # Expect: ...BusstopPole:Name.123.1 -> ...BusstopPole:Name.123
    # If just ...BusstopPole:Name.123 -> ...BusstopPole:Name.123
    parts = pid.rsplit(".", 1)
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) <= 2: # simple heuristic for suffix like .1, .2
         return parts[0]
    return pid

def route_base(rid: str) -> str:
    if not isinstance(rid, str): return rid
    # Expect: ...Busroute:Toei.Nishiki27-3 -> ...Busroute:Toei.Nishiki27
    return rid.split("-")[0]

# -------------------- 時刻表マネージャー (名寄せ強化版) --------------------
class TimetableManager:
    def __init__(self):
        # key: pole_id, value: { route_id: [{'dep': minutes, 'dest': dest_pole_id}, ...] }
        self.bus_departures_weekday = {}
        self.bus_departures_saturday = {}
        self.bus_departures_holiday = {}
        
        # ID-based indexes (pole_base -> [pole_id, ...])
        self.pole_base_index_weekday = defaultdict(list)
        self.pole_base_index_saturday = defaultdict(list)
        self.pole_base_index_holiday = defaultdict(list)
        
        # Optimization Cache: (day_type_key, pole_id, route_id) -> effective_pole_id
        self._resolved_pole_cache = {}
        
        # Controlled Debugging
        self._debug_once = set()
        self._debug_counts = defaultdict(int)

        self.route_patterns_map = defaultdict(list) # route_id -> [ [stop1, stop2...], [stop1...] ]
        
        # key: station_id, value: [ {dep, arr, next_sta, train_id} ]
        self.train_patterns_weekday = {}
        self.train_patterns_weekend = {}
        
        # 名前インデックス (共通 - used for graph building hints maybe, but less for timetable now)
        self.name_to_pids = defaultdict(list)
        # リアルタイム遅延 (共通)
        self.realtime_delays = {}

    def __setstate__(self, state):
        self.__dict__.update(state)

        # Restore missing attributes from older pickles and guard None values

        need_rebuild_indexes = False

        if (not hasattr(self, "pole_base_index_weekday")) or (self.pole_base_index_weekday is None):
            need_rebuild_indexes = True
        if (not hasattr(self, "pole_base_index_saturday")) or (self.pole_base_index_saturday is None):
            need_rebuild_indexes = True
        if (not hasattr(self, "pole_base_index_holiday")) or (self.pole_base_index_holiday is None):
            need_rebuild_indexes = True

        if need_rebuild_indexes:
            print("[INFO] Migrating TimetableManager: Initializing missing or None indexes...")
            self.pole_base_index_weekday = defaultdict(list)
            self.pole_base_index_saturday = defaultdict(list)
            self.pole_base_index_holiday = defaultdict(list)

        if (not hasattr(self, "_resolved_pole_cache")) or (self._resolved_pole_cache is None):
            self._resolved_pole_cache = {}

        if (not hasattr(self, "_debug_once")) or (self._debug_once is None):
            self._debug_once = set()

        if (not hasattr(self, "_debug_counts")) or (self._debug_counts is None):
            self._debug_counts = defaultdict(int)

        has_any_bus_data = False
        if hasattr(self, "bus_departures_weekday") and self.bus_departures_weekday:
            has_any_bus_data = True
        if hasattr(self, "bus_departures_saturday") and self.bus_departures_saturday:
            has_any_bus_data = True
        if hasattr(self, "bus_departures_holiday") and self.bus_departures_holiday:
            has_any_bus_data = True

        if has_any_bus_data:
            self.finalize_indexes()

    def __getattr__(self, name):
        # Fail-safe for missing attributes if __setstate__ didn't run or failed

        if name.startswith("pole_base_index_"):
            print(f"[WARN] Fail-safe init for {name}")

            # CRITICAL FIX
            # Use sequential if statements to ensure all missing indexes are detected

            missing_any = False

            if ("pole_base_index_weekday" not in self.__dict__) or (self.__dict__.get("pole_base_index_weekday") is None):
                missing_any = True
            if ("pole_base_index_saturday" not in self.__dict__) or (self.__dict__.get("pole_base_index_saturday") is None):
                missing_any = True
            if ("pole_base_index_holiday" not in self.__dict__) or (self.__dict__.get("pole_base_index_holiday") is None):
                missing_any = True

            if missing_any:
                self.pole_base_index_weekday = defaultdict(list)
                self.pole_base_index_saturday = defaultdict(list)
                self.pole_base_index_holiday = defaultdict(list)

            has_any_bus_data = False
            if self.__dict__.get("bus_departures_weekday"):
                has_any_bus_data = True
            if self.__dict__.get("bus_departures_saturday"):
                has_any_bus_data = True
            if self.__dict__.get("bus_departures_holiday"):
                has_any_bus_data = True

            if has_any_bus_data:
                self.finalize_indexes()

            return self.__dict__[name]

        if name == "_resolved_pole_cache":
            print(f"[WARN] Fail-safe init for {name}")
            val = {}
            self.__dict__[name] = val
            return val

        if name == "_debug_once":
            print(f"[WARN] Fail-safe init for {name}")
            val = set()
            self.__dict__[name] = val
            if ("_debug_counts" not in self.__dict__) or (self.__dict__.get("_debug_counts") is None):
                self._debug_counts = defaultdict(int)
            return val

        if name == "_debug_counts":
            print(f"[WARN] Fail-safe init for {name}")
            val = defaultdict(int)
            self.__dict__[name] = val
            if ("_debug_once" not in self.__dict__) or (self.__dict__.get("_debug_once") is None):
                self._debug_once = set()
            return val

        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def debug_once(self, key, msg):
        self._debug_counts[key] += 1
        if key not in self._debug_once:
            self._debug_once.add(key)
            print(msg)
            
    def _build_pole_base_index_for(self, departures_dict, out_index):
        out_index.clear()
        for pid in departures_dict.keys():
            out_index[pole_base(pid)].append(pid)

    def finalize_indexes(self):
        self._build_pole_base_index_for(self.bus_departures_weekday, self.pole_base_index_weekday)
        self._build_pole_base_index_for(self.bus_departures_saturday, self.pole_base_index_saturday)
        self._build_pole_base_index_for(self.bus_departures_holiday, self.pole_base_index_holiday)
        print("[INFO] Bus ID-based indexes finalized.")
        
    def update_delays(self, train_data_list):
        count = 0
        for t in train_data_list:
            t_num = t.get("odpt:trainNumber")
            delay = t.get("odpt:delay", 0)
            if t_num:
                self.realtime_delays[t_num] = delay
                count += 1
        # print(f"[INFO] Updated delays for {count} trains.")

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
            
            is_wk = (
                "Weekday" in calendar 
                or calendar.endswith("-170") 
                or calendar.endswith("-174")
            )
            is_sat = (
                "Saturday" in calendar 
                or calendar.endswith("-160")
            )
            is_hol = (
                "Holiday" in calendar 
                or calendar.endswith("-100") 
                or calendar.endswith("-109")
            )

            if is_wk: targets.append(self.bus_departures_weekday)
            if is_sat: targets.append(self.bus_departures_saturday)
            if is_hol: targets.append(self.bus_departures_holiday)
            
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
        self.finalize_indexes()
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

        # Determine target dictionary and index
        if day_type == "saturday":
            target_dict = self.bus_departures_saturday
            base_index = self.pole_base_index_saturday
        elif day_type == "holiday":
            target_dict = self.bus_departures_holiday
            base_index = self.pole_base_index_holiday
        else:
            target_dict = self.bus_departures_weekday
            base_index = self.pole_base_index_weekday

        # Cache Check
        cache_key = (day_type, pole_id, route_id)
        cached_pid = self._resolved_pole_cache.get(cache_key)
        
        # Effective Pole ID to use
        effective_pole_id = cached_pid if cached_pid else pole_id

        def find_trips_smart(routes_dict, target_rid):
            # 1. Exact match
            if target_rid in routes_dict:
                return routes_dict[target_rid]
            
            # 2. Route Base match (e.g. Nishiki27 matches Nishiki27-2)
            base = route_base(target_rid)
            for r_key, t_list in routes_dict.items():
                if route_base(r_key) == base:
                    # Log only once
                    if debug:
                        self.debug_once(
                            f"route_fuzzy:{target_rid}", 
                            f"[BUS] Fuzzy Route Match: {target_rid} -> {r_key} (base={base})"
                        )
                    return t_list
            return None

        def is_valid_trip(trip, rid, board_pole_id):
            if not target_pole_id: return True
            dest_id = trip.get("dest")
            if not dest_id: return True

            patterns = self.route_patterns_map.get(rid) or []
            if not patterns: return True # Pattern missing, assume valid

            any_directional_pattern = False
            for stops in patterns:
                # Check if both board and dest exist in this pattern
                if board_pole_id not in stops: continue
                if dest_id not in stops: continue

                b = stops.index(board_pole_id)
                d = stops.index(dest_id)
                if d < b: continue # Wrong direction
                
                any_directional_pattern = True
                
                if target_pole_id:
                    if target_pole_id not in stops: continue
                    t = stops.index(target_pole_id)
                    if b <= t <= d: return True # Valid intermediate
                else:
                    return True # Valid if no specific target check needed

            if any_directional_pattern:
                return False # Found directional patterns but none matched
            
            return True # Fallback if no patterns contained these stops

        # Primary Lookup
        routes = target_dict.get(effective_pole_id)
        candidate_trips = None
        if routes:
            candidate_trips = find_trips_smart(routes, route_id)

        # Fallback: Pole Base (Only if not cached or cache failed somehow)
        if not candidate_trips and not cached_pid:
            base = pole_base(pole_id)
            candidates = base_index.get(base, [])
            
            for alt_pid in candidates:
                if alt_pid == pole_id: continue
                alt_routes = target_dict.get(alt_pid)
                if not alt_routes: continue
                
                alt_trips = find_trips_smart(alt_routes, route_id)
                if alt_trips:
                    if debug:
                        self.debug_once(
                            f"pole_fallback:{pole_id}:{route_id}", 
                            f"[BUS] Pole Fallback: {pole_id} -> {alt_pid} (base={base})"
                        )
                    candidate_trips = alt_trips
                    self._resolved_pole_cache[cache_key] = alt_pid
                    effective_pole_id = alt_pid # Update for is_valid_trip check
                    break

        if not candidate_trips:
            return None

        # Determine the board_pole_id to use for validation
        # If we fell back to alt_pid, we should strictly check against alt_pid patterns?
        # Usually checking original ID is safer for graph consistency, but timetable logic needs ID with pattern.
        # Let's use effective_pole_id for pattern check.
        
        for trip in candidate_trips:
            dep = trip.get("dep")
            if dep is None: continue
            if dep >= current_time_min:
                if is_valid_trip(trip, route_id, effective_pole_id):
                    return dep
        return None

    def get_future_bus_trips(self, pole_id, route_id, current_time_min, limit=10, pole_name=None, day_type="weekday", target_pole_id=None, debug=False):
        # Simplified for debugging/UI - Removed GTFS & double return bug
        if not debug:
            debug = os.getenv("DEBUG_BUS") == "1"

        if day_type == "saturday":
            target_dict = self.bus_departures_saturday
        elif day_type == "holiday":
            target_dict = self.bus_departures_holiday
        else:
            target_dict = self.bus_departures_weekday

        def find_trips(routes_dict, target_rid):
            if target_rid in routes_dict: return routes_dict[target_rid]
            for r_key, t_list in routes_dict.items():
                if target_rid in r_key or r_key in target_rid:
                    return t_list
            return None

        def is_valid_trip(trip, rid, board_pole_id):
            if not target_pole_id: return True
            dest_id = trip.get("dest")
            if not dest_id: return True
            patterns = self.route_patterns_map.get(rid) or []
            if not patterns: return True
            any_directional_pattern = False
            for stops in patterns:
                if board_pole_id not in stops or dest_id not in stops: continue
                b = stops.index(board_pole_id)
                d = stops.index(dest_id)
                if d < b: continue
                any_directional_pattern = True
                if target_pole_id not in stops: continue
                t = stops.index(target_pole_id)
                if b <= t <= d: return True
            if any_directional_pattern: return False
            return True

        routes = target_dict.get(pole_id) or {}
        candidate_trips = find_trips(routes, route_id)

        if not candidate_trips and pole_name and pole_name in self.name_to_pids:
            for alt_pid in self.name_to_pids[pole_name]:
                if alt_pid == pole_id: continue
                alt_routes = target_dict.get(alt_pid) or {}
                candidate_trips = find_trips(alt_routes, route_id)
                if candidate_trips: break

        if not candidate_trips: return []

        out = []
        for trip in candidate_trips:
            dep = trip.get("dep")
            if dep is None: continue
            if dep < current_time_min: continue
            if is_valid_trip(trip, route_id, pole_id):
                out.append(trip)
                if len(out) >= limit: break
        return out

    def get_next_train_arrival(self, current_sta, next_sta, current_time_min, day_type="weekday", delays_snapshot=None):
        target_dict = self.train_patterns_weekday if day_type == "weekday" else self.train_patterns_weekend
        trains = target_dict.get(current_sta)
        if not trains: return None
        
        delays_source = delays_snapshot if delays_snapshot is not None else self.realtime_delays
        
        for t in trains:
            base_dep = t["dep"]
            base_arr = t["arr"]
            delay_sec = delays_source.get(t["train_num"], 0)
            delay_min = delay_sec / 60.0
            
            actual_dep = base_dep + delay_min
            actual_arr = base_arr + delay_min

            if actual_dep >= current_time_min and t["next_sta"] == next_sta:
                return actual_arr
        return None

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
        
        for a, b in zip(seq, seq[1:]):
            na = ensure_line_node(a, family_key, disp, "bus", route_id)
            nb = ensure_line_node(b, family_key, disp, "bus", route_id)
            if not G.has_edge(na, nb):
                G.add_edge(na, nb, w=BUS_RIDE_COST, etype="ride", line=family_key, mode="bus")

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
    # Use spatial index reuse logic
    si = SpatialIndex(G)
    
    phys_nodes = []
    for idx, (n, d) in enumerate(G.nodes(data=True)):
        if n[0] != "phys": continue
        phys_nodes.append((n, d))

    for u, du in phys_nodes:
        candidates = si.nearby_candidates(du["lat"], du["lon"], radius_m)
        for (v, lat, lon) in candidates:
            if u == v: continue
            dist = haversine(du["lat"], du["lon"], lat, lon)
            if dist <= radius_m:
                 if not G.has_edge(u, v):
                     minutes = max(1.0, dist / WALK_SPEED_M_PER_MIN)
                     w = WALK_COST * minutes
                     G.add_edge(u, v, w=w, etype="walk", meters=dist)

def get_virtual_connections(G, lat, lon, name="目的地", walk_radius=300, spatial_index=None):
    dest_id = f"dest:{lat:.6f},{lon:.6f}"
    dest_node = ("phys", dest_id)
    connections = []
    
    if spatial_index:
        candidates = spatial_index.nearby_candidates(lat, lon, walk_radius)
        for nid, nlat, nlon in candidates:
             dist = haversine(lat, lon, nlat, nlon)
             if dist <= walk_radius:
                 minutes = max(1.0, dist / WALK_SPEED_M_PER_MIN)
                 w = WALK_COST * minutes
                 connections.append((nid, w, dist))
    else:
        # Fallback
        for n, d in G.nodes(data=True):
            if n[0] != "phys": continue
            dist = haversine(lat, lon, d.get("lat"), d.get("lon"))
            if dist <= walk_radius:
                minutes = max(1.0, dist / WALK_SPEED_M_PER_MIN)
                w = WALK_COST * minutes
                connections.append((n, w, dist))
                
    return dest_node, connections

def nearest_phys(G, lat, lon, station_only=False, spatial_index=None):
    best, bestd = None, 1e30
    candidates = []
    if spatial_index:
        raw_candidates = spatial_index.nearby_candidates(lat, lon, 1000)
        # Flatten tuple from si
        candidates = [(nid, G.nodes[nid]) for nid,_,_ in raw_candidates]
        if not candidates: # fallback wider scan
             candidates = G.nodes(data=True)
    else:
        candidates = G.nodes(data=True)

    for n, d in candidates:
        if n[0] != "phys": continue
        if station_only and not is_station_id(n[1]): continue
        dist = haversine(lat, lon, d["lat"], d["lon"])
        if dist < bestd: best, bestd = n, dist
    return best, bestd

# -------------------- 探索ロジック --------------------
def get_logical_signature(G, path):
    sig = []
    current_line = None
    for u, v in zip(path, path[1:]):
        if G.has_edge(u, v):
            e = G.get_edge_data(u, v)
            etype = e.get("etype")
        else:
            etype = "walk"

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
    if G.has_edge(u, v):
        edge = G.edges[u, v]
        etype = edge.get("etype")
        meters = edge.get("meters", 0)
    else:
        # Virtual edge fallback
        return curr_time # Should rarely happen here unless virtual logic changes

    if etype == "walk":
        return curr_time + (meters / WALK_SPEED_M_PER_MIN)

    if etype == "board":
        node = v if v[0] == "line" else u
        mode = G.nodes[node].get("mode")

        if mode == "bus":
            route_id = G.nodes[node].get("route_id")
            stop_name = G.nodes[u].get("name")
            target_pid = kwargs.get("target_pole_id")
            dep = tm.get_next_bus_departure(
                u[1], route_id, curr_time,
                pole_name=stop_name,
                day_type=day_type,
                target_pole_id=target_pid
            )
            return dep
        elif mode == "rail":
            return curr_time + 2.0
        return curr_time

    if etype == "ride":
        mode = edge.get("mode")
        if mode == "rail":
            arr = tm.get_next_train_arrival(u[1], v[1], curr_time, day_type=day_type, delays_snapshot=delays_snapshot)
            return arr
        elif mode == "bus":
            if meters > 0:
                return curr_time + (meters / 250.0) + 0.8
            else:
                return curr_time + 2.5
        return curr_time

    if etype in ("alight", "xfer"):
        return curr_time + 1.0

    return curr_time

# -------------------- 共通ロジック: セグメント詳細化 --------------------
def path_to_coords(G, path):
    points = []
    for u in path:
        if u[0] == "phys" and str(u[1]).startswith("dest:"):
            try:
                parts = str(u[1]).split(":")[1].split(",")
                lat, lon = float(parts[0]), float(parts[1])
                points.append([lat, lon])
            except: pass
        elif u in G.nodes:
            d = G.nodes[u]
            points.append([d["lat"], d["lon"]])
    return points

def search_best_routes_once(G, tm, a_phys, b_phys, mode="cost", start_time="10:00", limit=5, target_date_str=None, target_node=None, day_type=None, virtual_dest_connections=None, target_coords=None):
    now = datetime.datetime.now()
    if target_date_str:
        try:
            d = datetime.datetime.strptime(target_date_str, "%Y-%m-%d")
            base_date = d.replace(hour=now.hour, minute=now.minute, second=0, microsecond=0)
        except:
            base_date = now
    else:
        base_date = now
    
    h, m = map(int, start_time.split(":"))
    start_dt = base_date.replace(hour=h, minute=m, second=0, microsecond=0)
    
    candidates = search_best_routes(G, tm, a_phys, b_phys, mode, start_time, limit, start_dt, target_node=target_node, day_type=day_type, virtual_dest_connections=virtual_dest_connections, target_coords=target_coords)
    
    if candidates:
        for cand in candidates:
            cand["departure_date"] = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
            cand["is_future_suggestion"] = False
        return candidates
    return []

def search_best_routes(G, tm, a_phys, b_phys, mode="cost", start_time="10:00", limit=5, target_date=None, target_node=None, day_type=None, virtual_dest_connections=None, target_coords=None):
    if target_date is None: target_date = datetime.datetime.now()
    if day_type is None:
        wd = target_date.weekday()
        if wd == 5: day_type = "saturday"
        elif wd == 6: day_type = "holiday"
        else: day_type = "weekday"
    
    target = target_node or b_phys
    candidates = []
    delays_snapshot = tm.get_delays_snapshot()

    if mode == "time" or mode == "fast":
        arr_min, path = find_fastest_path(G, tm, a_phys, target, start_time, day_type=day_type, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections, target_coords=target_coords)
        if path:
            real_arr = calculate_real_arrival_time(G, tm, path, start_time, day_type=day_type, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections)
            if real_arr is None:
                path = None 

        if path:
            segs = segments_detailed(G, path, tm, start_time, day_type=day_type, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections)
            lines = list(dict.fromkeys([s["title"] for s in segs if s["kind"] in ("bus", "rail")]))
            start_min = time_str_to_min(start_time)
            duration = int(arr_min - start_min)
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
    else:
        path_gen = find_paths_generator(G, tm, a_phys, target, start_time, day_type=day_type, max_search=30000, max_visited=100000, max_travel_min=MAX_TRAVEL_MIN, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections, target_coords=target_coords)
        valid_count = 0
        for cand in path_gen:
            path = cand["path"]
            real_arr = calculate_real_arrival_time(G, tm, path, start_time, day_type=day_type, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections)
            if real_arr is not None:
                segs = segments_detailed(G, path, tm, start_time, day_type=day_type, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections)
                lines = list(dict.fromkeys([s["title"] for s in segs if s["kind"] in ("bus", "rail")]))
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
                if valid_count >= limit: break
    return candidates



def find_paths_generator(G, tm, start_node, target_node, start_time_str="10:00", day_type="weekday", max_search=30000, max_visited=15000, max_travel_min=MAX_TRAVEL_MIN, delays_snapshot=None, time_limit_sec=15.0, virtual_dest_connections=None, target_coords=None):
    import time
    start_clock = time.monotonic()
    start_min = time_str_to_min(start_time_str)

    t_lat, t_lon = None, None
    if target_coords: t_lat, t_lon = target_coords
    else:
        try:
            t_lat = G.nodes[target_node]["lat"]
            t_lon = G.nodes[target_node]["lon"]
        except: pass

    def heuristic(n):
        if n == target_node: return 0.0
        if t_lat is None: return 0.0
        d = G.nodes.get(n)
        if not d: return 0.0
        dist = haversine(d.get("lat",0), d.get("lon",0), t_lat, t_lon)
        return dist / 400.0

    start_h = heuristic(start_node)
    pq = [(start_h, 0.0, start_node, 0.0, 0.0, start_min, (start_node, None))]

    target_goal_nodes = {target_node}
    if target_node and target_node[0] == "phys":
        pid = target_node[1]
        if isinstance(pid, str) and pid.startswith("odpt.BusstopPole:"):
            base = pole_base(pid)
            for n in G.nodes:
                if n[0] == "phys" and isinstance(n[1], str) and n[1].startswith("odpt.BusstopPole:"):
                    if pole_base(n[1]) == base:
                        target_goal_nodes.add(n)

    best_cost = {}
    seen_logical_routes = set()
    yielded_count = 0
    visited_count = 0

    while pq:
        if visited_count > 0 and visited_count % 1000 == 0:
            if time.monotonic() - start_clock > time_limit_sec:
                print(f"[WARN] Search timeout {yielded_count} paths.")
                return

        _, cost, u, total_walk_m, seg_walk_m, curr_time, path_chain = heapq.heappop(pq)
        visited_count += 1
        if visited_count > max_visited: return

        if curr_time - start_min > max_travel_min: continue

        walk_bucket = int(seg_walk_m // 10)
        state_key = (u, walk_bucket)
        prev_best = best_cost.get(state_key)
        if prev_best is not None and cost >= prev_best: continue
        best_cost[state_key] = cost

        if u in target_goal_nodes:
            full_path = reconstruct_path(path_chain)
            sig = get_logical_signature(G, full_path)
            if sig in seen_logical_routes: continue
            seen_logical_routes.add(sig)
            yield {"cost": cost, "path": full_path, "walk_m": total_walk_m}
            yielded_count += 1
            if yielded_count >= max_search: return
            continue

        if virtual_dest_connections and target_node and target_node[0] == "phys" and str(target_node[1]).startswith("dest:"):
            for nid, vw, vmeters in virtual_dest_connections:
                if nid == u:
                    next_time_v = curr_time + (vmeters / WALK_SPEED_M_PER_MIN)
                    if next_time_v - start_min <= max_travel_min:
                        new_total_v = total_walk_m + vmeters
                        new_seg_v = vmeters
                        if new_total_v <= MAX_TOTAL_WALK_M and new_seg_v <= MAX_WALK_SEG_M:
                            new_cost_v = cost + vw
                            heapq.heappush(pq, (new_cost_v + heuristic(target_node), new_cost_v, target_node, new_total_v, new_seg_v, next_time_v, (target_node, path_chain)))
                    break

        for v in G[u]:
            edge = G[u][v]
            w = edge.get("w", 0.0)
            meters = edge.get("meters", 0.0)
            next_time = advance_time(G, tm, u, v, curr_time, day_type, delays_snapshot)
            if next_time is None or next_time - start_min > max_travel_min: continue

            new_total_walk_m = total_walk_m
            new_seg_walk_m = seg_walk_m
            if edge.get("etype") == "walk":
                step_m = meters if meters > 0 else 1.0
                new_seg_walk_m += step_m
                if new_seg_walk_m > MAX_WALK_SEG_M: continue
                new_total_walk_m += step_m
                if new_total_walk_m > MAX_TOTAL_WALK_M: continue
            else:
                new_seg_walk_m = 0.0

            new_cost = cost + w
            new_h = heuristic(v)
            heapq.heappush(pq, (new_cost + new_h, new_cost, v, new_total_walk_m, new_seg_walk_m, next_time, (v, path_chain)))

def find_fastest_path(G, tm, start_node, target_node, start_time_str="10:00", day_type="weekday", max_travel_min=MAX_TRAVEL_MIN, delays_snapshot=None, virtual_dest_connections=None, target_coords=None):
    start_min = time_str_to_min(start_time_str)
    pq = [(start_min, start_node, (start_node, None), 0.0, 0.0)]
    visited_time = {}
    
    target_pole_ids = set()
    def add_poles(pid):
        node_id = ("phys", pid)
        if node_id in G.nodes:
            name = G.nodes[node_id].get("name")
            if name and tm:
                for p in tm.name_to_pids.get(name, []):
                    target_pole_ids.add(p)
        target_pole_ids.add(pid)

    if virtual_dest_connections:
        for nid,_,_ in virtual_dest_connections:
            if nid[0] == "phys": add_poles(nid[1])
    elif target_node and target_node[0] == "phys":
        add_poles(target_node[1])

    while pq:
        curr_time, u, path_chain, total_walk, seg_walk = heapq.heappop(pq)
        if curr_time - start_min > max_travel_min: continue
        
        if u == target_node:
            return curr_time, reconstruct_path(path_chain)

        state = (u, int(seg_walk // 10))
        if state in visited_time and visited_time[state] <= curr_time: continue
        visited_time[state] = curr_time

        if virtual_dest_connections and u[0] == "phys" and target_node and str(target_node[1]).startswith("dest:"):
            for nid, vw, vmeters in virtual_dest_connections:
                if nid == u:
                    v_time = curr_time + (vmeters / WALK_SPEED_M_PER_MIN)
                    new_seg = seg_walk + vmeters
                    new_tot = total_walk + vmeters
                    if v_time - start_min <= max_travel_min and new_seg <= MAX_WALK_SEG_M and new_tot <= MAX_TOTAL_WALK_M:
                        heapq.heappush(pq, (v_time, target_node, (target_node, path_chain), new_tot, new_seg))

        for v in G[u]:
            edge = G[u][v]
            etype = edge.get("etype")
            meters = edge.get("meters", 0)
            next_time = advance_time(G, tm, u, v, curr_time, day_type, delays_snapshot, target_pole_id=None) # target_pole_ids not easily passed to advance_time currently refactored
            if next_time is None: continue

            new_seg = seg_walk + (meters if etype == "walk" else 0) if etype == "walk" else 0
            new_tot = total_walk + (meters if etype == "walk" else 0) if etype == "walk" else total_walk
            if new_seg > MAX_WALK_SEG_M or new_tot > MAX_TOTAL_WALK_M: continue
            
            heapq.heappush(pq, (next_time, v, (v, path_chain), new_tot, new_seg))
    return None, None

def calculate_real_arrival_time(G, tm, path, start_time_str="10:00", day_type="weekday", max_search=30000, max_travel_min=MAX_TRAVEL_MIN, delays_snapshot=None, virtual_dest_connections=None):
    start_min = time_str_to_min(start_time_str)
    curr_time = start_min
    for i in range(len(path) - 1):
        u, v = path[i], path[i+1]
        edge = G.get_edge_data(u, v)
        if not edge and virtual_dest_connections: # Check virtual
             for nid, w, dist in virtual_dest_connections:
                 if nid == u and v[0] == "phys" and str(v[1]).startswith("dest:"):
                      edge = {"etype": "walk", "meters": dist}
        if not edge: return None
        
        target_pid = None
        if edge.get("etype") == "board" and G.nodes[v].get("mode") == "bus":
            if v[0] == "line":
                for j in range(i+1, len(path)-1):
                    u2, v2 = path[j], path[j+1]
                    if G.has_edge(u2, v2):
                         e2 = G.get_edge_data(u2, v2)
                         if e2.get("etype") == "alight":
                            target_pid = v2[1]
                            break

        if not G.has_edge(u, v) and edge.get("etype") == "walk":
             next_time = curr_time + (edge.get("meters", 0) / WALK_SPEED_M_PER_MIN)
        else:
            next_time = advance_time(G, tm, u, v, curr_time, day_type, delays_snapshot, target_pole_id=target_pid)
            
        if next_time is None or next_time - start_min > max_travel_min: return None
        curr_time = next_time
    return curr_time

def segments_detailed(G, path, tm, start_time_str="10:00", day_type="weekday", delays_snapshot=None, virtual_dest_connections=None):
    segs = []
    cur = None
    last_phys = None
    curr_time = time_str_to_min(start_time_str)

    def flush():
        nonlocal cur
        if cur:
            if cur["kind"] == "walk":
                if cur.get("meters", 0) <= 0 or cur.get("from_") == cur.get("to"):
                    cur = None
                    return
                cur["minutes"] = max(1, math.ceil(cur.get("meters", 0) / WALK_SPEED_M_PER_MIN))
            elif cur["kind"] in ("bus", "rail"):
                if cur.get("arrival_time"):
                    d = time_str_to_min(cur.get("departure_time"))
                    a = time_str_to_min(cur.get("arrival_time"))
                    cur["minutes"] = max(1, int(a - d))
                else:
                    cur["minutes"] = max(1, int(cur.get("edges", 0) * 2.0))
            segs.append(cur)
            cur = None

    for i, (u, v) in enumerate(zip(path, path[1:])):
        edge = G.get_edge_data(u, v)
        if not edge and virtual_dest_connections:
            for nid, w, dist in virtual_dest_connections:
                 if nid == u: edge = {"etype": "walk", "meters": dist}
        if not edge: continue
        
        etype = edge.get("etype")
        if u[0] == "phys": last_phys = u

        if etype == "walk":
            if not cur or cur["kind"] != "walk":
                flush()
                from_name = G.nodes[u]["name"] if u[0]=="phys" else "???"
                cur = { "kind": "walk", "title": "徒歩", "edges": 0, "from_": from_name, "to": None, "meters": 0 }
            cur["edges"] += 1
            cur["meters"] += edge.get("meters", 0)
            if v[0] == "phys":
                if str(v[1]).startswith("dest:"): cur["to"] = "目的地"
                elif v in G.nodes: cur["to"] = G.nodes[v]["name"]
                else: cur["to"] = str(v[1])
            curr_time += (edge.get("meters", 0) / WALK_SPEED_M_PER_MIN)
            continue

        node = v if v[0] == "line" else (u if u[0] == "line" else None)
        if not node: continue
        line_disp = G.nodes[node].get("disp") or "???"
        mode = G.nodes[node].get("mode")

        if etype == "board":
            flush()
            from_name = G.nodes[last_phys]["name"] if last_phys else "???"
            curr_stops = [{"name": from_name, "is_origin": True}]
            
            phys_id = u[1]
            if mode == "bus":
                route_id = G.nodes[v].get("route_id")
                target_pid = None
                if v[0] == "line":
                     for j in range(i + 1, len(path) - 1):
                        u2, v2 = path[j], path[j+1]
                        if G.has_edge(u2, v2):
                             e2 = G.get_edge_data(u2, v2)
                             if e2.get("etype") == "alight":
                                target_pid = v2[1]
                                break
                dep = tm.get_next_bus_departure(phys_id, route_id, curr_time, pole_name=from_name, day_type=day_type, target_pole_id=target_pid)
                
                if dep and dep > curr_time:
                    wait_min = int(dep - curr_time)
                    if wait_min > 0:
                        flush()
                        segs.append({
                            "kind": "wait", "title": "待ち時間", "minutes": wait_min,
                            "edges": 0, "from_": from_name, "to": from_name, "meters": 0,
                            "departure_time": min_to_time_str(curr_time),
                            "arrival_time": min_to_time_str(dep),
                            "startLabel": "待ち時間", "place": from_name
                        })
                if dep and dep >= curr_time: curr_time = dep
            else:
                curr_time += 2.0 # Rail wait

            cur = {
                "kind": mode, "title": line_disp, "edges": 0, 
                "from_": from_name, "to": None, "stops": curr_stops,
                "departure_time": min_to_time_str(curr_time)
            }

        elif etype == "ride":
            if cur and cur["kind"] in ("bus", "rail"):
                cur["edges"] += 1
                stop_name = "???"
                phys_key = ("phys", v[1]) if v[0] == "line" else ("phys", u[1])
                if phys_key in G: stop_name = G.nodes[phys_key]["name"]
                if not cur["stops"] or cur["stops"][-1]["name"] != stop_name:
                    cur["stops"].append({"name": stop_name})
            
            if mode == "rail":
                arr = tm.get_next_train_arrival(u[1], v[1], curr_time, day_type, delays_snapshot)
                if arr: curr_time = arr
                else: curr_time += edge.get("w", 2.0)
            else:
                dist = edge.get("meters", 0)
                curr_time += (dist/250.0 if dist>0 else 2.5) + 0.8

        elif etype in ("alight", "xfer"):
            if cur and cur["kind"] in ("bus", "rail"):
                to_phys = v if v[0] == "phys" else last_phys
                if to_phys:
                    to_name = G.nodes[to_phys]["name"]
                    cur["to"] = to_name
                    if not cur["stops"] or cur["stops"][-1]["name"] != to_name:
                        cur["stops"].append({"name": to_name, "is_destination": True})
                    else:
                        cur["stops"][-1]["is_destination"] = True
                cur["arrival_time"] = min_to_time_str(curr_time)
                flush()
            curr_time += 1.0
            
    if cur: flush()
    return segs

# -------------------- Main --------------------
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

    dest_node, connections = get_virtual_connections(G, blat, blon, name="目的地", walk_radius=args.walk)

    tm = TimetableManager()
    tm.load_bus_timetables(args.bus_timetables)
    tm.load_bus_route_patterns(args.busroute_patterns)
    tm.load_train_timetables(args.train_timetables)
    tm.build_name_index(G)
    
    results = search_best_routes_once(G, tm, a_phys, b_phys, mode=args.mode, start_time=args.start_time, limit=5, target_node=dest_node, virtual_dest_connections=connections)

    if not results:
        results = search_best_routes_once(G, tm, a_phys, b_phys, mode=args.mode, start_time=args.start_time, limit=5)

    if not results:
        print("No valid route found.")
        return

    print(f"\n[INFO] Found {len(results)} Routes")
    for i, res in enumerate(results, 1):
        print(f"#{i} {res['score_label']}")

def get_reachable_stops(G, tm, lat, lon, limit_dist=1000, spatial_index=None):
    nearest_node, nearest_dist = nearest_phys(G, lat, lon, spatial_index=spatial_index)
    if not nearest_node or nearest_dist > limit_dist:
        return {"found": False, "message": "Not found"}

    start_candidates = []
    SEARCH_RADIUS_M = 500.0
    
    if spatial_index:
        raw_candidates = spatial_index.nearby_candidates(lat, lon, SEARCH_RADIUS_M)
        for nid, _, _ in raw_candidates:
             dist = haversine(lat, lon, G.nodes[nid]["lat"], G.nodes[nid]["lon"])
             if dist <= SEARCH_RADIUS_M: start_candidates.append(nid[1])
    else:
        # Fallback
        for n, d in G.nodes(data=True):
             if n[0] == "phys":
                 if haversine(lat, lon, d["lat"], d["lon"]) <= SEARCH_RADIUS_M:
                     start_candidates.append(n[1])

    if not start_candidates: start_candidates.append(nearest_node[1])
    
    reachable_map = {}
    for start_id in start_candidates:
        for route_id, patterns in tm.route_patterns_map.items():
            for seq in patterns:
                if start_id in seq:
                    idx = seq.index(start_id)
                    if idx == len(seq) - 1: continue
                    future_stops = seq[idx+1:]
                    for next_stop_id in future_stops:
                        if next_stop_id in reachable_map: continue
                        if next_stop_id in start_candidates: continue # Self
                        node_key = ("phys", next_stop_id)
                        if node_key in G:
                            node_data = G.nodes[node_key]
                            reachable_map[next_stop_id] = {
                                "id": next_stop_id, "name": node_data.get("name"),
                                "lat": node_data.get("lat"), "lon": node_data.get("lon"),
                                "via_route": route_id 
                            }
    reachable_list = list(reachable_map.values())
    return {"found": True, "nearest_stop": {"id": nearest_node[1], "name": G.nodes[nearest_node]["name"]}, "reachable_stops": reachable_list, "count": len(reachable_list)}

if __name__ == "__main__":
    main()