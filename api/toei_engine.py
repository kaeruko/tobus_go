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
        
        # ★追加: リアルタイム遅延情報を保持する辞書
        # Key: 列車番号(train_number), Value: 遅延秒数(int)
        self.realtime_delays = {}

    # ★追加: 外部から遅延情報を更新するメソッド
    def update_delays(self, train_data_list):
        """
        odpt:Train のリストを受け取り、遅延情報を更新する
        """
        count = 0
        for t in train_data_list:
            t_num = t.get("odpt:trainNumber")
            delay = t.get("odpt:delay", 0)  # 秒単位
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
            # ★変更: 列車番号を取得
            train_num = entry.get("odpt:trainNumber")
            
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
                        "dep": dep_time, 
                        "arr": arr_time, 
                        "next_sta": arr_sta,
                        "train_num": train_num  # ★追加: ここで列車番号を保持
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
            # 基本ダイヤの時刻
            base_dep = t["dep"]
            base_arr = t["arr"]
            
            # ★変更: 遅延を考慮した時刻を計算
            # 列車番号で遅延辞書を検索（なければ0秒）
            delay_sec = self.realtime_delays.get(t["train_num"], 0)
            delay_min = delay_sec / 60.0
            
            actual_dep = base_dep + delay_min
            actual_arr = base_arr + delay_min

            # 現在時刻以降に出発できるか？
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
            curr_time += (edge.get("meters", 0) / WALK_SPEED_M_PER_MIN)
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
            
            # 出発時刻計算
            phys_id = u[1]
            if mode == "bus":
                route_id = G.nodes[v].get("route_id")
                stop_name = G.nodes[u].get("name")
                dep = tm.get_next_bus_departure(phys_id, route_id, curr_time, pole_name=stop_name)
                if dep: curr_time = dep
            elif mode == "rail":
                curr_time += 2.0 # 乗り換え待ち概算
            
            cur["departure_time"] = min_to_time_str(curr_time)
        
        elif etype == "ride":
            if cur and cur["kind"] in ("bus", "rail"):
                cur["edges"] += 1
                # 停車駅名（lineノードに対応する物理名を引くのは簡易実装）
                # 厳密には v[1] が phys_id なのでそれを G から引く
                stop_name = "???"
                phys_key = ("phys", v[1]) if v[0] == "line" else ("phys", u[1])
                if phys_key in G:
                    stop_name = G.nodes[phys_key]["name"]
                
                # 直前の駅と名前が違うなら追加
                if not cur["stops"] or cur["stops"][-1]["name"] != stop_name:
                    cur["stops"].append({"name": stop_name})
            
            # 移動時間加算
            if mode == "rail":
                arr = tm.get_next_train_arrival(u[1], v[1], curr_time)
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
                    # 最後の駅
                    if not cur["stops"] or cur["stops"][-1]["name"] != to_name:
                        cur["stops"].append({"name": to_name, "is_destination": True})
                    else:
                        cur["stops"][-1]["is_destination"] = True
                
                cur["arrival_time"] = min_to_time_str(curr_time)
                flush()
            
            curr_time += 1.0 # 下車/乗換コスト

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
def search_best_routes(G, tm, a_phys, b_phys, mode="cost", start_time="10:00", limit=5):
    """
    ServerとCLI共通のエントリーポイント。
    経路探索 -> 時刻表バリデーション -> セグメント化 -> 結果辞書のリスト作成 までを一気通貫で行う。
    """
    candidates = []
    
    # 1. Timeモード (最速経路1つ)
    if mode == "time" or mode == "fast":
        arr_min, path = find_fastest_path(G, tm, a_phys, b_phys, start_time_str=start_time)
        if path:
            segs = segments_detailed(G, path, tm, start_time)
            lines = list(dict.fromkeys([s["title"] for s in segs if s["kind"] in ("bus", "rail")]))
            
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
                # ★追加: main.dart の Candidate が期待するフィールド
                "total": duration, # Timeモードは所要時間をスコアとする
                "transfers": max(0, num_rides - 1),
                "rides": num_rides,
                "walks": int(walk_dist),
                "boards": num_rides,
            })

    # 2. Costモード (楽な経路トップK)
    else:
        # ジェネレータを作成
        path_gen = find_paths_generator(G, a_phys, b_phys, max_search=2000)
        
        valid_count = 0
        dead_routes = set() # 過去に失敗したルートID (簡易的な学習)

        for cand in path_gen:
            path = cand["path"]
            
            # ブラックリスト(dead_routes) チェック
            # (前のバリデーションで「バスがない」と判明した路線を含んでいたらスキップする等のロジックを入れる場所)
            # 今回は簡易実装としてスキップ
            
            # 答え合わせ (時刻表チェック)
            real_arr = calculate_real_arrival_time(G, tm, path, start_time)
            
            if real_arr is not None:
                # 合格
                segs = segments_detailed(G, path, tm, start_time)
                lines = list(dict.fromkeys([s["title"] for s in segs if s["kind"] in ("bus", "rail")]))
                
                start_min = time_str_to_min(start_time)
                duration = int(real_arr - start_min)
                
                # 統計情報の計算
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
                    # ★追加: main.dart の Candidate が期待するフィールド
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
                pass
                
    return candidates

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

    tm = TimetableManager()
    print(f"[INFO] Loading Timetables...")
    tm.load_bus_timetables(args.bus_timetables)
    tm.load_train_timetables(args.train_timetables)
    tm.build_name_index(G)

    # ★共通関数を呼ぶだけにする
    results = search_best_routes(
        G, tm, a_phys, b_phys, 
        mode=args.mode, 
        start_time=args.start_time, 
        limit=5
    )

    if not results:
        print("No valid route found.")
        return

    # 結果表示
    print(f"\n[INFO] Found {len(results)} Routes")
    for i, res in enumerate(results, 1):
        print("-" * 40)
        print(f"#{i} {res['score_label']} / Arr: {res['arrival_time']}")
        print(f"    Lines: {' -> '.join(res['lines'])}")
        print(f"    Steps:")
        for step in res['steps']:
            if step['kind'] == 'walk':
                print(f"      [徒歩] {step['meters']:.0f}m ({step['minutes']:.0f}分)")
            else:
                print(f"      [{step['kind'].upper()}] {step['title']} ({step['from_']} -> {step['to']})")

if __name__ == "__main__":
    main()