#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# toei_reach_final_v2.py

import json, argparse, math, sys, heapq, bisect
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
        self.bus_departures = {}
        self.train_patterns = {}
        # ★追加: 名前からIDリストを引くための辞書
        self.name_to_pids = defaultdict(list)

    def load_bus_timetables(self, json_path):
        data = load_json(json_path)
        count = 0
        for entry in data:
            pole_id = entry.get("odpt:busstopPole")
            route_id = entry.get("odpt:busroute")
            if not pole_id: continue

            times = []
            for obj in entry.get("odpt:busstopPoleTimetableObject", []):
                dep = obj.get("odpt:departureTime")
                if dep: times.append(time_str_to_min(dep))
            times.sort()
            
            if not times: continue
            if pole_id not in self.bus_departures: self.bus_departures[pole_id] = {}
            if route_id not in self.bus_departures[pole_id]: self.bus_departures[pole_id][route_id] = []
            
            self.bus_departures[pole_id][route_id].extend(times)
            count += 1
        
        for pid in self.bus_departures:
            for rid in self.bus_departures[pid]:
                self.bus_departures[pid][rid].sort()
        print(f"[DEBUG] Loaded Bus Timetables (Entries used: {count})")

    def load_train_timetables(self, json_path):
        data = load_json(json_path)
        count = 0
        for entry in data:
            objs = entry.get("odpt:trainTimetableObject", [])
            for i in range(len(objs) - 1):
                curr = objs[i]
                next_stop = objs[i+1]
                dep_sta = curr.get("odpt:departureStation")
                arr_sta = next_stop.get("odpt:arrivalStation")
                dep_time = time_str_to_min(curr.get("odpt:departureTime"))
                arr_time = time_str_to_min(next_stop.get("odpt:arrivalTime"))
                
                if dep_sta and arr_sta:
                    if dep_sta not in self.train_patterns: self.train_patterns[dep_sta] = []
                    self.train_patterns[dep_sta].append({
                        "dep": dep_time, "arr": arr_time, "next_sta": arr_sta
                    })
            count += 1
        
        for sid in self.train_patterns:
            self.train_patterns[sid].sort(key=lambda x: x["dep"])
        print(f"[DEBUG] Loaded Train Timetables (Entries used: {count})")

    # ★追加: グラフデータから「バス停名 -> IDリスト」の対応表を作る
    def build_name_index(self, G):
        print("[INFO] Building Name Index for fuzzy matching...")
        count = 0
        jimbocho_count = 0
        
        for n, d in G.nodes(data=True):
            if n[0] == "phys":
                name = d.get("name")
                pid = n[1]
                if name:
                    self.name_to_pids[name].append(pid)
                    count += 1
                    if "神保町二丁目" in name:
                        jimbocho_count += 1
                        print(f"  [DEBUG-INDEX] Found: {name} -> {pid}")

        print(f"[INFO] Index built. Total {count} nodes. (Jimbocho: {jimbocho_count})")

    # TimetableManagerクラスの中
    def get_next_bus_departure(self, pole_id, route_id, current_time_min, pole_name=None):
        # ヘルパー: 辞書の中から route_id を探す
        def find_times(routes_dict, target_rid):
            if target_rid in routes_dict: return routes_dict[target_rid]
            for r_key, t_list in routes_dict.items():
                if target_rid in r_key or r_key in target_rid:
                    return t_list
            return None

        # 1. まずはIDそのもので探す
        routes = self.bus_departures.get(pole_id)
        if routes:
            times = find_times(routes, route_id)
            if times:
                idx = bisect.bisect_left(times, current_time_min)
                if idx < len(times): return times[idx]

        # 2. ★ここが修正点: 名前を使って、違うIDのポールも全部探す
        # (IDが 458 でも 762 でも、名前が同じなら中身を見る)
        if pole_name and pole_name in self.name_to_pids:
            for alt_pid in self.name_to_pids[pole_name]:
                if alt_pid == pole_id: continue 
                
                alt_routes = self.bus_departures.get(alt_pid)
                if alt_routes:
                    times = find_times(alt_routes, route_id)
                    if times:
                        # 見つかった！
                        idx = bisect.bisect_left(times, current_time_min)
                        if idx < len(times): return times[idx]
        return None

    def get_next_train_arrival(self, current_sta, next_sta, current_time_min):
        trains = self.train_patterns.get(current_sta)
        if not trains: return None
        for t in trains:
            if t["dep"] >= current_time_min and t["next_sta"] == next_sta:
                return t["arr"]
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
    phys_nodes = [(n, d) for n, d in G.nodes(data=True) if n[0] == "phys"]
    for i, (u, du) in enumerate(phys_nodes):
        for j, (v, dv) in enumerate(phys_nodes):
            if i >= j: continue
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

# -------------------- 探索ロジック --------------------

# 1. これが本体（中身はさっきの高速ジェネレータ）
def find_paths_generator(G, start_node, target_node, max_search=30000):
    """
    経路を1つずつ見つけては返すジェネレータ関数。
    """
    pq = [(0.0, start_node, 0.0, [start_node])]
    count_visited = defaultdict(int)
    seen_logical_routes = set()
    
    yielded_count = 0

    while pq:
        cost, u, walk_m, path = heapq.heappop(pq)
        
        # ゴール判定
        if u == target_node:
            sig = get_logical_signature(G, path)
            if sig in seen_logical_routes:
                continue
            seen_logical_routes.add(sig)
            
            # 見つけた端から yield で返す
            yield {"cost": cost, "path": path, "walk_m": walk_m}
            
            yielded_count += 1
            if yielded_count >= max_search:
                return
            continue

        # 枝刈り
        walk_bucket = int(walk_m // 10)
        state_key = (u, walk_bucket)
        
        if count_visited[state_key] >= 20: 
            continue
        count_visited[state_key] += 1
        
        for v in G[u]:
            edge = G[u][v]
            w = edge.get("w", 0.0)
            meters = edge.get("meters", 0.0)
            new_walk_m = 0.0
            if edge.get("etype") == "walk":
                step_m = meters if meters > 0 else 1.0
                new_walk_m = walk_m + step_m
                if new_walk_m > MAX_WALK_SEG_M: continue
            heapq.heappush(pq, (cost + w, v, new_walk_m, path + [v]))


# 2. これが「窓口」（server.py が呼ぶやつ）
def find_top_k_paths(G, start_node, target_node, K=5):
    """
    ジェネレータを使って K個 のリストを作って返すラッパー関数。
    これがあれば server.py はエラーにならない。
    """
    generator = find_paths_generator(G, start_node, target_node)
    results = []
    
    # ジェネレータから K個 取り出す
    for _ in range(K):
        try:
            results.append(next(generator))
        except StopIteration:
            break
            
    return results

def find_fastest_path(G, tm, start_node, target_node, start_time_str="10:00"):
    start_min = time_str_to_min(start_time_str)
    pq = [(start_min, start_node, [start_node])]
    visited_time = {}
    print(f"[DEBUG] Search Start: {start_time_str} ({start_min})")

    while pq:
        curr_time, u, path = heapq.heappop(pq)
        if u == target_node: return curr_time, path
        if u in visited_time and visited_time[u] <= curr_time: continue
        visited_time[u] = curr_time
        
        for v in G[u]:
            edge = G[u][v]
            etype = edge.get("etype")
            arr = curr_time
            if etype == "walk":
                arr += (edge.get("meters", 0) / 80.0)
            elif etype == "board":
                phys_id = u[1]
                mode = G.nodes[v].get("mode")
                if mode == "bus":
                    rid = G.nodes[v].get("route_id")
                    # Time Modeでも名前検索(名寄せ)を有効化
                    stop_name = G.nodes[u].get("name")
                    dep = tm.get_next_bus_departure(phys_id, rid, curr_time, pole_name=stop_name)
                    if dep: arr = dep
                    else: continue
                elif mode == "rail":
                    arr += 2.0
            elif etype == "ride":
                mode = edge.get("mode")
                if mode == "rail":
                    real_arr = tm.get_next_train_arrival(u[1], v[1], curr_time)
                    if real_arr: arr = real_arr
                    else: continue
                else:
                    arr += edge.get("w", 2.0)
            elif etype == "alight" or etype == "xfer":
                arr += 1.0
            heapq.heappush(pq, (arr, v, path + [v]))
    return None, None

def calculate_real_arrival_time(G, tm, path, start_time_str="10:00"):
    curr_time = time_str_to_min(start_time_str)
    
    for u, v in zip(path, path[1:]):
        edge = G.edges[u, v]
        etype = edge.get("etype")
        
        if etype == "walk":
            curr_time += (edge.get("meters", 0) / WALK_SPEED_M_PER_MIN)
            
        elif etype == "board":
            phys_id = u[1]
            mode = G.nodes[v].get("mode")
            if mode == "bus":
                route_id = G.nodes[v].get("route_id")
                stop_name = G.nodes[u].get("name")
                
                # 名前検索(名寄せ)付きで時刻表を引く
                dep = tm.get_next_bus_departure(phys_id, route_id, curr_time, pole_name=stop_name)
                
                if dep:
                    curr_time = dep
                else:
                    # バスの便がない（終バス後など）
                    return None 

            elif mode == "rail":
                curr_time += 2.0
                
        elif etype == "ride":
            mode = edge.get("mode")
            if mode == "rail":
                arr = tm.get_next_train_arrival(u[1], v[1], curr_time)
                if arr: curr_time = arr
                else: curr_time += edge.get("w", 2.0)
            else:
                # バスの移動時間（距離ベース + 停車ロス）
                dist = edge.get("meters", 0)
                if dist > 0: curr_time += (dist / 250.0) + 0.8
                else: curr_time += 2.5

        elif etype == "alight" or etype == "xfer":
            curr_time += 1.0
            
    return curr_time

def print_time_mode_result(G, path, start_time_str, arr_time_min):
    print(f"\n[RESULT] Time Mode")
    print(f"Depart: {start_time_str} -> Arrive: {min_to_time_str(arr_time_min)}")
    curr_mode = None
    lines = []
    for u, v in zip(path, path[1:]):
        e = G.edges[u, v]
        if e.get("etype") == "ride":
            name = G.nodes[u].get("disp")
            if name != curr_mode:
                lines.append(name)
                curr_mode = name
    print(f"Route: {' -> '.join(lines)}")

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
    print(f"[INFO] {G.nodes[a_phys]['name']} -> {G.nodes[b_phys]['name']}")

    if args.mode == "cost":
        print(f"[INFO] Mode: Cost Priority (Lazy Route)")
        tm = TimetableManager()
        print(f"[INFO] Loading Timetables for validation...")
        tm.load_bus_timetables(args.bus_timetables)
        tm.load_train_timetables(args.train_timetables)
        tm.build_name_index(G)

        # 重み設定 (変更なし)
        A_ID = a_phys[1]
        for u, v, data in G.edges(data=True):
            if data.get("etype") == "board":
                if u == ("phys", A_ID): data["w"] = 0.0
                else:
                    mode = G.nodes[v].get("mode") if v[0]=="line" else None
                    base = TRANSFER_PENALTY
                    if mode=="bus": base += BUS_WAIT_PENALTY
                    data["w"] = base
            if data.get("etype") == "alight" and data.get("mode") == "bus":
                data["w"] = BUS_ALIGHT_PENALTY
        
        # ★ここから変更: ジェネレータを回す
        print("[INFO] Searching and Validating routes incrementally...")
        
        # Generatorを作成 (max_search=1000にしておけば、事実上無限に探してくれる)
        path_gen = find_paths_generator(G, a_phys, b_phys, max_search=1000)
        
        valid_routes = []
        
        # 1つずつ取り出してチェック
        for cand in path_gen:
            # 答え合わせ
            real_arr = calculate_real_arrival_time(G, tm, cand["path"], args.start_time)
            
            if real_arr is not None:
                # 合格！
                cand["real_arr"] = real_arr
                valid_routes.append(cand)
                print(f"[FOUND] Valid Route #{len(valid_routes)} found! (Comfort: {cand['cost']:.1f})")
            else:
                # 不合格（終バス後など）
                # print(f"[SKIP] Route candidate failed timetable check.") # ログがうるさければコメントアウト
                pass

            # 5つ揃ったら終了
            if len(valid_routes) >= 5:
                break
        
        # 最終結果表示
        if valid_routes:
            print(f"\n[INFO] Top {len(valid_routes)} Valid 'Lazy' Routes")
            for i, sol in enumerate(valid_routes, 1):
                real_arr = sol["real_arr"]
                duration = int(real_arr - time_str_to_min(args.start_time))
                time_info = f"{min_to_time_str(real_arr)} Arrival ({duration} min)"
                
                print("-" * 40)
                print(f"#{i} [Comfort Score: {sol['cost']:.1f}] Real Time: {time_info}")
                print(f"    Total Walk: {sol['walk_m']:.0f}m")
                
                curr_mode = None
                for u, v in zip(sol["path"], sol["path"][1:]):
                    e = G.edges[u, v]
                    if e.get("etype") == "ride":
                        name = G.nodes[u].get("disp")
                        if name != curr_mode:
                            print(f"    [乗車] {name}")
                            curr_mode = name
                    elif e.get("etype") == "walk":
                        if curr_mode != "walk":
                            print(f"    [徒歩] {int(e.get('meters',0))}m")
                            curr_mode = "walk"
        else:
            print("No valid route found.")

    elif args.mode == "time":
        tm = TimetableManager()
        print(f"[INFO] Loading Timetables...")
        tm.load_bus_timetables(args.bus_timetables)
        tm.load_train_timetables(args.train_timetables)
        tm.build_name_index(G) # Timeモードでも名寄せ有効化
        
        arr, path = find_fastest_path(G, tm, a_phys, b_phys, args.start_time)
        if path: print_time_mode_result(G, path, args.start_time, arr)
        else: print("No route found (Time mode).")

if __name__ == "__main__":
    main()