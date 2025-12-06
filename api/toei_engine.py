#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# toei_reach_final_v2.py

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

# -------------------- 時刻表マネージャー (名寄せ強化版) --------------------
class TimetableManager:
    def __init__(self):
        # key: pole_id, value: { route_id: [minutes, ...] }
        self.bus_departures_weekday = {}
        self.bus_departures_weekend = {}
        
        # key: station_id, value: [ {dep, arr, next_sta, train_id} ]
        self.train_patterns_weekday = {}
        self.train_patterns_weekend = {}
        
        # 名前インデックス (共通)
        self.name_to_pids = defaultdict(list)
        # リアルタイム遅延 (共通)
        self.realtime_delays = {}

    def update_delays(self, train_data_list):
        count = 0
        for t in train_data_list:
            t_num = t.get("odpt:trainNumber")
            delay = t.get("odpt:delay", 0)
            if t_num:
                self.realtime_delays[t_num] = delay
                count += 1
        print(f"[INFO] Updated delays for {count} trains.")

    def load_bus_timetables(self, json_path):
        data = load_json(json_path)
        count = 0
        for entry in data:
            pole_id = entry.get("odpt:busstopPole")
            route_id = entry.get("odpt:busroute")
            calendar = entry.get("odpt:calendar", "")
            if not pole_id: continue

            times = []
            for obj in entry.get("odpt:busstopPoleTimetableObject", []):
                dep = obj.get("odpt:departureTime")
                if dep: times.append(time_str_to_min(dep))
            times.sort()
            
            if not times: continue

            # 振り分け
            target_dict = self.bus_departures_weekend
            if "Weekday" in calendar:
                target_dict = self.bus_departures_weekday
            
            if pole_id not in target_dict: target_dict[pole_id] = {}
            if route_id not in target_dict[pole_id]: target_dict[pole_id][route_id] = []
            
            target_dict[pole_id][route_id].extend(times)
            count += 1
        
        # ソート
        for d in [self.bus_departures_weekday, self.bus_departures_weekend]:
            for pid in d:
                for rid in d[pid]:
                    d[pid][rid].sort()
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

    def get_next_bus_departure(self, pole_id, route_id, current_time_min, pole_name=None, is_weekday=True):
        target_dict = self.bus_departures_weekday if is_weekday else self.bus_departures_weekend
        
        def find_times(routes_dict, target_rid):
            if target_rid in routes_dict: return routes_dict[target_rid]
            for r_key, t_list in routes_dict.items():
                if target_rid in r_key or r_key in target_rid:
                    return t_list
            return None

        routes = target_dict.get(pole_id)
        if routes:
            times = find_times(routes, route_id)
            if times:
                idx = bisect.bisect_left(times, current_time_min)
                if idx < len(times): return times[idx]

        if pole_name and pole_name in self.name_to_pids:
            for alt_pid in self.name_to_pids[pole_name]:
                if alt_pid == pole_id: continue 
                alt_routes = target_dict.get(alt_pid)
                if alt_routes:
                    times = find_times(alt_routes, route_id)
                    if times:
                        idx = bisect.bisect_left(times, current_time_min)
                        if idx < len(times): return times[idx]
        return None

    def get_next_train_arrival(self, current_sta, next_sta, current_time_min, is_weekday=True):
        target_dict = self.train_patterns_weekday if is_weekday else self.train_patterns_weekend
        trains = target_dict.get(current_sta)
        if not trains: return None
        
        for t in trains:
            base_dep = t["dep"]
            base_arr = t["arr"]
            
            delay_sec = self.realtime_delays.get(t["train_num"], 0)
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
        self.route_stop_stats = defaultdict(lambda: defaultdict(int)) # route_id -> stop_id -> total_trips

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
        if not odpt_id: return ""
        try:
            parts = odpt_id.split('.')
            if len(parts) >= 2:
                # Last two parts are usually code ("2205") and suffix ("3")
                code = parts[-2]
                suffix = parts[-1]
                if code.isdigit() and suffix.isdigit():
                    gtfs_id = f"{code}-{int(suffix):02d}"
                    return gtfs_id
        except Exception as e:
            print(f"[WARN] Failed to convert ODPT ID {odpt_id}: {e}")
        return ""

    def resolve_gtfs_route_id(self, route_name_disp):
        # route_name_disp e.g. "都02"
        # normalize
        norm = _line_norm(route_name_disp)
        result = self.gtfs_route_map.get(norm, "")
        print(f"[DEBUG] resolve_gtfs_route_id: '{route_name_disp}' -> norm:'{norm}' -> routeId:'{result}'")
        return result

    def resolve_gtfs_stop_id(self, gtfs_route_id, stop_name):
        candidates = self.gtfs_stop_map.get(stop_name, [])
        if not candidates:
            print(f"[DEBUG] resolve_gtfs_stop_id: No candidates for stop_name='{stop_name}'")
            return ""

        # Smart Resolution: Check if candidates exist in known route stats
        if gtfs_route_id and hasattr(self, 'route_stop_stats') and gtfs_route_id in self.route_stop_stats:
            known_stops = self.route_stop_stats[gtfs_route_id]
            # Valid candidates are those that exist in the timetable for this route and have trips
            valid_candidates = [c for c in candidates if c in known_stops and known_stops[c] > 0]
            
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

def nearest_phys(G, lat, lon, station_only=False):
    best, bestd = None, 1e30
    for n, d in G.nodes(data=True):
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
def advance_time(G, tm, u, v, curr_time, is_weekday=True):
    """
    1 本のエッジ (u -> v) に対して、現在時刻 curr_time を
    「実際の到着時刻」に進める。
    乗れない（終バス後など）場合は None を返す。
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
            dep = tm.get_next_bus_departure(
                phys_id, route_id, curr_time,
                pole_name=stop_name,
                is_weekday=is_weekday,
            )
            return dep  # dep が None のときは呼び出し側で弾く
        elif mode == "rail":
            # 電車の乗車時点ではざっくり乗り換え待ち 2 分
            return curr_time + 2.0
        return curr_time

    # 走行（ride）
    if etype == "ride":
        mode = edge.get("mode")
        if mode == "rail":
            arr = tm.get_next_train_arrival(u[1], v[1], curr_time, is_weekday=is_weekday)
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
def segments_detailed(G, path, tm, start_time_str="10:00"):
    """
    パス(ノード列)を、UI表示やログ出力用の詳細セグメントリストに変換する
    """
    segs = []
    cur = None
    
    # 直前の物理ノード（駅やバス停）を記録しておく
    last_phys = None
    
    # 時刻追跡用
    curr_time = time_str_to_min(start_time_str)

    def flush():
        nonlocal cur
        if cur:
            # 分計算 (概算)
            if cur["kind"] == "walk":
                cur["minutes"] = max(1, int(cur.get("meters", 0) / WALK_SPEED_M_PER_MIN))
            elif cur["kind"] in ("bus", "rail"):
                # 到着時刻があればそれを使う
                if cur.get("arrival_time"):
                    dep_min = time_str_to_min(cur.get("departure_time"))
                    arr_min = time_str_to_min(cur.get("arrival_time"))
                    cur["minutes"] = max(1, int(arr_min - dep_min))
                else:
                    # フォールバック
                    cur["minutes"] = max(1, int(cur.get("edges", 0) * 2.0))
            
            segs.append(cur)
            cur = None

    for u, v in zip(path, path[1:]):
        edge = G.edges[u, v]
        etype = edge.get("etype")
        
        if u[0] == "phys": last_phys = u

        # Next time calculation using helper
        next_time = advance_time(G, tm, u, v, curr_time, is_weekday=is_weekday)

        # --- 徒歩 ---
        if etype == "walk":
            if not cur or cur["kind"] != "walk":
                flush()
                from_name = G.nodes[u]["name"] if u[0]=="phys" else "???"
                cur = {
                    "kind": "walk", "title": "徒歩", "edges": 0,
                    "from_": from_name, "to": None, "meters": 0
                }
            cur["edges"] += 1
            cur["meters"] += edge.get("meters", 0)
            if v[0] == "phys": cur["to"] = G.nodes[v]["name"]
            
            # 時間加算
            if next_time is not None:
                curr_time = next_time
            else:
                curr_time += (edge.get("meters", 0) / WALK_SPEED_M_PER_MIN) # Fallback
            continue

        # --- 乗り物 (Board / Ride / Alight / Xfer) ---
        node = v if v[0] == "line" else (u if u[0] == "line" else None)
        if not node: continue

        line_id = G.nodes[node].get("line")
        line_disp = G.nodes[node].get("disp") or "???"
        mode = G.nodes[node].get("mode") # bus or rail

        if etype == "board":
            flush()
            from_name = G.nodes[last_phys]["name"] if last_phys else "???"
            cur = {
                "kind": mode, "title": line_disp, "line": line_id,
                "edges": 0, "from_": from_name, "to": None, "stops": []
            }
            # 乗車駅を追加
            cur["stops"].append({"name": from_name, "is_origin": True})
            
            # 出発時刻更新
            if next_time: curr_time = next_time
            cur["departure_time"] = min_to_time_str(curr_time)
        
        elif etype == "ride":
            if cur and cur["kind"] in ("bus", "rail"):
                cur["edges"] += 1
                # 停車駅名
                stop_name = "???"
                phys_key = ("phys", v[1]) if v[0] == "line" else ("phys", u[1])
                if phys_key in G:
                    stop_name = G.nodes[phys_key]["name"]
                
                if not cur["stops"] or cur["stops"][-1]["name"] != stop_name:
                    cur["stops"].append({"name": stop_name})
            
            # 移動時間加算
            if next_time: curr_time = next_time
            else: curr_time += 2.0 # fallback

        elif etype in ("alight", "xfer"):
            if cur and cur["kind"] in ("bus", "rail"):
                to_phys = v if v[0] == "phys" else last_phys
                if to_phys:
                    to_name = G.nodes[to_phys]["name"]
                    cur["to"] = to_name
                    # 最後の駅
                    if not cur["stops"] or cur["stops"][-1]["name"] != to_name:
                        cur["stops"].append({"name": to_name, "is_destination": True})
                    else:
                        cur["stops"][-1]["is_destination"] = True
                
                cur["arrival_time"] = min_to_time_str(curr_time)
                flush()
            
            if next_time: curr_time = next_time
            else: curr_time += 1.0

    if cur: flush()
    return segs


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
def search_best_routes_with_retry(G, tm, a_phys, b_phys, mode="cost", start_time="10:00", limit=5):
    """
    日付を指定して検索し、結果が0件なら翌日以降も探すラッパー
    """
    # 現在日時を基準にする（簡易実装）
    # 本来はリクエストパラメータで日付を受け取るべきだが、今回は「今日」からスタート
    now = datetime.datetime.now()
    
    # start_time が "HH:MM" 形式なので、今日のその時間に設定
    h, m = map(int, start_time.split(":"))
    start_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    
    print(f"[DEBUG] search_best_routes_with_retry: Start from {start_dt}")

    for day_offset in range(4): # 今日含めて4日間トライ
        target_date = start_dt + datetime.timedelta(days=day_offset)
        print(f"[DEBUG] Trying date: {target_date.date()} (offset={day_offset})")
        
        # 2日目以降は、時刻を維持するか、始発にするか？
        # ユーザーの要望は「次に使える経路」なので、同じ時刻で良いはず
        # ただし、夜遅く(25:00とか)の場合は日付の扱いが難しいが、ここではシンプルに
        # 「指定時刻」で検索する
        
        current_time_str = start_time
        
        # 検索実行
        candidates = search_best_routes(G, tm, a_phys, b_phys, mode, current_time_str, limit, target_date)
        
        if candidates:
            # 見つかった！
            # 結果に日付情報を付与
            for cand in candidates:
                cand["departure_date"] = target_date.strftime("%Y-%m-%d")
                cand["is_future_suggestion"] = (day_offset > 0)
            return candidates

    return []

def search_best_routes(G, tm, a_phys, b_phys, mode="cost", start_time="10:00", limit=5, target_date=None):
    """
    ServerとCLI共通のエントリーポイント。
    経路探索 -> 時刻表バリデーション -> セグメント化 -> 結果辞書のリスト作成 までを一気通貫で行う。
    """
    if target_date is None:
        target_date = datetime.datetime.now()
    
    # 平日判定 (0-4: 月-金, 5-6: 土日)
    is_weekday = target_date.weekday() < 5
    
    candidates = []
    
    # 1. Timeモード (最速経路1つ)
    if mode == "time" or mode == "fast":
        arr_min, path = find_fastest_path(G, tm, a_phys, b_phys, start_time_str=start_time, is_weekday=is_weekday)
        if path:
            segs = segments_detailed(G, path, tm, start_time, is_weekday=is_weekday)
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
        path_gen = find_paths_generator(G, a_phys, b_phys, max_search=2000)
        valid_count = 0
        
        for cand in path_gen:
            path = cand["path"]
            
            # 答え合わせ (時刻表チェック)
            real_arr = calculate_real_arrival_time(G, tm, path, start_time, is_weekday=is_weekday)
            
            if real_arr is not None:
                # 合格
                segs = segments_detailed(G, path, tm, start_time, is_weekday=is_weekday)
                lines = list(dict.fromkeys([s["title"] for s in segs if s["kind"] in ("bus", "rail")]))
                
                # デバッグログ: 経路セグメント詳細
                print(f"[DEBUG] ========== Route Segments (Comfort-{valid_count+1}) ==========")
                for i, seg in enumerate(segs):
                    print(f"[DEBUG] Segment {i+1}: kind={seg['kind']}, title={seg.get('title', 'N/A')}, from={seg.get('from_', 'N/A')}, to={seg.get('to', 'N/A')}")
                print("[DEBUG] ================================================")
                
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
                # print(f"[DEBUG] Candidate rejected: {path}") # ログ多すぎるかも
                pass
                
    return candidates

# -------------------- 探索ロジック --------------------

def find_paths_generator(G, start_node, target_node, max_search=30000):
    # cost, node, total_walk_m, seg_walk_m, path
    pq = [(0.0, start_node, 0.0, 0.0, [start_node])]
    count_visited = defaultdict(int)
    seen_logical_routes = set()
    yielded_count = 0
    visited_count = 0

    while pq:
        cost, u, total_walk_m, seg_walk_m, path = heapq.heappop(pq)
        visited_count += 1
        if visited_count % 5000 == 0:
            print(f"[DEBUG] find_paths_generator: visited={visited_count}, yielded={yielded_count}, pq_size={len(pq)}")
        
        # ゴール判定
        if u == target_node:
            sig = get_logical_signature(G, path)
            if sig in seen_logical_routes: continue
            seen_logical_routes.add(sig)
            # walk_m は total_walk_m を返す
            yield {"cost": cost, "path": path, "walk_m": total_walk_m}
            yielded_count += 1
            if yielded_count >= max_search: return
            continue

        walk_bucket = int(seg_walk_m // 10)
        state_key = (u, walk_bucket)
        if count_visited[state_key] >= 20: continue
        count_visited[state_key] += 1
        
        for v in G[u]:
            edge = G[u][v]
            w = edge.get("w", 0.0)
            meters = edge.get("meters", 0.0)

            new_total_walk_m = total_walk_m
            new_seg_walk_m = seg_walk_m
            
            if edge.get("etype") == "walk":
                step_m = meters if meters > 0 else 1.0
                new_seg_walk_m = seg_walk_m + step_m
                if new_seg_walk_m > MAX_WALK_SEG_M: continue
                new_total_walk_m = total_walk_m + step_m
            else:
                new_seg_walk_m = 0.0

            heapq.heappush(pq, (cost + w, v, new_total_walk_m, new_seg_walk_m, path + [v]))

def find_fastest_path(G, tm, start_node, target_node, start_time_str="10:00", is_weekday=True):
    start_min = time_str_to_min(start_time_str)
    pq = [(start_min, start_node, [start_node])]
    visited_time = {}
    # print(f"[DEBUG] Search Start: {start_time_str} ({start_min}) Weekday={is_weekday}")

    while pq:
        curr_time, u, path = heapq.heappop(pq)
        if u == target_node: return curr_time, path
        if u in visited_time and visited_time[u] <= curr_time: continue
        visited_time[u] = curr_time
        
        for v in G[u]:
            # advance_time を利用
            next_time = advance_time(G, tm, u, v, curr_time, is_weekday=is_weekday)
            if next_time is None:
                continue
            heapq.heappush(pq, (next_time, v, path + [v]))
    return None, None

def calculate_real_arrival_time(G, tm, path, start_time_str="10:00", is_weekday=True):
    curr_time = time_str_to_min(start_time_str)
    
    for u, v in zip(path, path[1:]):
        next_time = advance_time(G, tm, u, v, curr_time, is_weekday=is_weekday)
        if next_time is None:
            return None
        curr_time = next_time
            
    return curr_time

def segments_detailed(G, path, tm, start_time_str="10:00", is_weekday=True):
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
                cur["minutes"] = max(1, int(cur.get("meters", 0) / WALK_SPEED_M_PER_MIN))
            elif cur["kind"] in ("bus", "rail"):
                if cur.get("arrival_time"):
                    dep_min = time_str_to_min(cur.get("departure_time"))
                    arr_min = time_str_to_min(cur.get("arrival_time"))
                    cur["minutes"] = max(1, int(arr_min - dep_min))
                else:
                    cur["minutes"] = max(1, int(cur.get("edges", 0) * 2.0))
            segs.append(cur)
            cur = None

    for u, v in zip(path, path[1:]):
        edge = G.edges[u, v]
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
            curr_stops = [{"name": from_name, "is_origin": True}]

            phys_id = u[1]
            gtfs_route_id = ""
            gtfs_stop_id = ""

            if mode == "bus":
                route_id = G.nodes[v].get("route_id") # ODPT Route ID (or internal)
                stop_name = G.nodes[u].get("name")
                
                # Update Time
                dep = tm.get_next_bus_departure(phys_id, route_id, curr_time, pole_name=stop_name, is_weekday=is_weekday)
                if dep: curr_time = dep
                
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

            elif mode == "rail":
                curr_time += 2.0
            
            cur = {
                "kind": mode, "title": line_disp, "line": line_id, 
                "edges": 0, "from_": from_name, "to": None, "stops": curr_stops,
                "routeId": gtfs_route_id,
                "departureStopId": gtfs_stop_id,
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
                arr = tm.get_next_train_arrival(u[1], v[1], curr_time, is_weekday=is_weekday)
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
                    if not cur["stops"] or cur["stops"][-1]["name"] != to_name:
                        cur["stops"].append({"name": to_name, "is_destination": True})
                    else:
                        cur["stops"][-1]["is_destination"] = True
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

    tm = TimetableManager()
    print(f"[INFO] Loading Timetables...")
    tm.load_bus_timetables(args.bus_timetables)
    tm.load_train_timetables(args.train_timetables)
    tm.build_name_index(G)

    # ★変更: リトライ付き検索を呼び出す
    results = search_best_routes_with_retry(
        G, tm, a_phys, b_phys, 
        mode=args.mode, 
        start_time=args.start_time, 
        limit=5
    )

    if not results:
        print("No valid route found.")
        return

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

if __name__ == "__main__":
    main()