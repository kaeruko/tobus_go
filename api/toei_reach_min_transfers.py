#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# toei_reach_dijkstra.py

import json, argparse, math, sys, heapq
from collections import defaultdict
import networkx as nx

# -------------------- チューニング定数 --------------------
# 移動そのものの負担（乗ってるだけなら楽）
BUS_RIDE_COST = 0.8     # バスに乗って進むのは安い
RAIL_RIDE_COST = 0.8    # 電車も安い

# 歩きの負担（これは重くする）
WALK_COST = 1.5         # 歩くのは疲れる
WALK_SPEED_M_PER_MIN = 80.0 

# 乗り換え・待ち時間の壁
TRANSFER_PENALTY = 5.0  # 乗り換え行為そのものの面倒くささ
BUS_WAIT_PENALTY = 20.0 # バス待ちのリスク（30分来ないかも、という恐怖）

# ★追加: 「せっかく乗ったバスを降りる」ことへの抵抗感
# これにより「あとちょっと乗っていれば着くのに手前で降りる」のを防ぐ
BUS_ALIGHT_PENALTY = 2.0 

MAX_WALK_SEG_M = 300.0       # デフォルト徒歩上限
MAX_WALK_BUS_BUS_M = 180.0   # バス同士の徒歩上限
MAX_WALK_STATION_M = 600.0   # 駅を含む場合の徒歩上限

# -------------------- 共通ユーティリティ --------------------
def _line_norm(s: str) -> str:
    tbl = str.maketrans("０１２３４５６７８９　（）", "0123456789 ()")
    return (s or "").translate(tbl).replace(" ", "")

def _norm_line(s):
    return _line_norm(s)

# 緯度経度の2点がどれくらい離れてるか（メートル）を返す
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(a))

def is_station_id(pid: str) -> bool:
    return isinstance(pid, str) and pid.startswith("odpt.Station:")

# -------------------- JSON loader & Graph Builder --------------------
# (ご提示のコードと同じロジックを使用しますが、build_walk_capped_graphは不要になるため削除・統合します)

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data if isinstance(data, list) else [data]

def get_id(o): return o.get("owl:sameAs") or o.get("@id") or o.get("id")
def get_lat(o): return o.get("geo:lat")
def get_lon(o): return o.get("geo:long")
def is_toei(op):
    if isinstance(op, list): return any("Toei" in x for x in op)
    return isinstance(op, str) and "Toei" in op

def build_graph(busstop_poles_path, busroute_patterns_path, stations_path, railways_path, walk_radius=300):
    G = nx.DiGraph()

    # --- 物理地点 ---
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
            phys[sid] = {"lat": float(lat), "lon": float(lon), "name": (s.get("dc:title") or sid)}

    for pid, d in phys.items():
        G.add_node(("phys", pid), **d, kind="phys")

    # --- ライン層 ---
    def ensure_line_node(phys_id, line_id, display_name, mode):
        n = ("line", phys_id, line_id)
        if n not in G:
            base = phys[phys_id]
            G.add_node(n, lat=base["lat"], lon=base["lon"], name=f"{base['name']}@{display_name}",
                       line=line_id, kind="line", disp=display_name, norm=_line_norm(display_name), mode=mode)
            
            # board (乗る): ペナルティは別途 main で調整するので一旦デフォルト
            G.add_edge(("phys", phys_id), n, w=TRANSFER_PENALTY, etype="board", minutes=0.0)
            
            # alight (降りる): モードによってコストを変える
            if mode == "bus":
                # バスを降りるのは「権利放棄」に近いのでコストを乗せる
                alight_cost = BUS_ALIGHT_PENALTY
            else:
                # 鉄道は降りてもリカバリ効きやすいのでタダ同然
                alight_cost = 0.0
                
            G.add_edge(n, ("phys", phys_id), w=alight_cost, etype="alight", minutes=0.0)
        return n

    # Bus Patterns
    patterns = load_json(busroute_patterns_path)
    for pat in patterns:
        if not is_toei(pat.get("odpt:operator")): continue
        raw_id = pat.get("odpt:pattern") or get_id(pat)
        disp = (pat.get("dc:title") or raw_id).split()[0]
        norm = _line_norm(disp)
        family_key = f"bus:{norm}"
        
        orders = pat.get("odpt:busstopPoleOrder") or []
        try: orders = sorted(orders, key=lambda x: x.get("odpt:index", 0))
        except: pass
        
        seq = [o.get("odpt:busstopPole") for o in orders if o.get("odpt:busstopPole") in phys]
        for a, b in zip(seq, seq[1:]):
            na = ensure_line_node(a, family_key, disp, "bus")
            nb = ensure_line_node(b, family_key, disp, "bus")
            if not G.has_edge(na, nb):
                G.add_edge(na, nb, w=BUS_RIDE_COST, etype="ride", line=family_key, mode="bus", minutes=2.0)

    # Railways
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
            G.add_edge(na, nb, w=RAIL_RIDE_COST, etype="ride", line=line_id, mode="rail", minutes=2.0)
            G.add_edge(nb, na, w=RAIL_RIDE_COST, etype="ride", line=line_id, mode="rail", minutes=2.0)

    # --- 徒歩 ---
    connect_walk_edges_phys(G, radius_m=walk_radius)
    tie_same_place_busstops(G, radius_m=150)
    
    # 重み保存
    for u, v, data in G.edges(data=True):
        data["base_w"] = float(data.get("w", 0.0))

    return G

# 簡易的な近傍接続（元のロジックを踏襲）
def connect_walk_edges_phys(G, radius_m=300):
    phys_nodes = [(n, d) for n, d in G.nodes(data=True) if n[0] == "phys"]
    # 実際はSpatial Index推奨だがここでは簡略化
    added = 0
    for i, (u, du) in enumerate(phys_nodes):
        for j, (v, dv) in enumerate(phys_nodes):
            if i >= j: continue
            dist = haversine(du["lat"], du["lon"], dv["lat"], dv["lon"])
            if dist <= radius_m:
                # バス-バスは厳しめ(180m), 駅絡みは緩め(600m)等の判定は探索時に行うため
                # ここでは広めにエッジだけ張っておく（重み計算用）
                minutes = max(1.0, dist / WALK_SPEED_M_PER_MIN)
                w = WALK_COST * minutes
                # グラフ上は一旦エッジを追加
                if not G.has_edge(u, v):
                    G.add_edge(u, v, w=w, etype="walk", meters=dist, minutes=minutes)
                if not G.has_edge(v, u):
                    G.add_edge(v, u, w=w, etype="walk", meters=dist, minutes=minutes)

def tie_same_place_busstops(G, radius_m=150):
    # 名前寄せロジック（省略可だが元の挙動維持のため）
    pass # 実装省略（必要なら元のコードからコピーしてください）

def nearest_phys(G, lat, lon, station_only=False):
    best, bestd = None, 1e30
    for n, d in G.nodes(data=True):
        if n[0] != "phys": continue
        if station_only and not is_station_id(n[1]): continue
        dist = haversine(lat, lon, d["lat"], d["lon"])
        if dist < bestd:
            best, bestd = n, dist
    return best, bestd

# -------------------- ★ここが核心のDP探索★ --------------------

# -------------------- 重複排除用のヘルパー関数 --------------------

def get_logical_signature(G, path):
    """
    パスから「物理的な詳細」を捨てて、「論理的な移動（路線名＋乗換地点名）」だけの列を作る。
    これを使って、ポール違いの重複ルートを弾く。
    
    Returns: tuple of (LineName, AlightNodeName)
      例: (('上23', '押上'), ('浅草線', '東日本橋'))
    """
    sig = []
    current_line = None
    
    # パスをたどって「降りた瞬間」を記録する
    for u, v in zip(path, path[1:]):
        e = G.edges[u, v]
        etype = e.get("etype")
        
        if etype == "ride":
            # 乗車中：路線名を記憶しておく
            # ノードに norm (正規化名) があればそれを、なければ disp を使う
            current_line = G.nodes[u].get("norm") or G.nodes[u].get("disp")
            
        elif etype == "alight":
            # 降りた： (路線名, 降りた場所の名前) を記録
            # v は phys ノードなので、その name (例: "押上") を使うことで、
            # ポールID (.3, .5) の違いを吸収する
            stop_name = G.nodes[v].get("name")
            if current_line:
                sig.append((current_line, stop_name))
                current_line = None
                
    return tuple(sig)


# -------------------- Top-K探索 (修正版) --------------------

def find_top_k_paths(G, start_node, target_node, K=5):
    pq = [(0.0, start_node, 0.0, [start_node])]
    
    # 状態訪問カウント (これは探索効率化用)
    count_visited = defaultdict(int)
    
    # ★追加: すでに見つけた「論理ルート」の指紋を保存するセット
    seen_logical_routes = set()

    solutions = []

    while pq:
        cost, u, walk_m, path = heapq.heappop(pq)
        
        # ゴール判定
        if u == target_node:
            # ★ここで「論理的な形」を確認する
            sig = get_logical_signature(G, path)
            
            # すでに同じ論理ルート(例: 上23で押上で降りる)が出ていたら、
            # この「ポール違いルート」は採用せずにスキップ
            if sig in seen_logical_routes:
                continue
                
            # 初めて見るルートなら登録
            seen_logical_routes.add(sig)
            
            solutions.append({
                "cost": cost,
                "path": path,
                "walk_m": walk_m
            })
            
            if len(solutions) >= K:
                break
            continue

        # --- 以下、枝刈りロジックは同じ ---
        walk_bucket = int(walk_m // 10) 
        state_key = (u, walk_bucket)
        
        # K個まで許容するが、そもそも「論理重複」を除きたいので
        # ここは少し緩めに K*3 くらい探索させておくと、
        # 微妙に違うルートが見つかりやすくなる（お好みで調整）
        if count_visited[state_key] >= K * 2:
            continue
        count_visited[state_key] += 1
        
        for v in G[u]:
            edge = G[u][v]
            etype = edge.get("etype")
            w = edge.get("w", 0.0)
            meters = edge.get("meters", 0.0)

            new_walk_m = 0.0
            is_walk_edge = (etype == "walk")
            
            if is_walk_edge:
                step_m = meters
                if step_m == 0 and u[0]=="phys" and v[0]=="phys":
                    du, dv = G.nodes[u], G.nodes[v]
                    step_m = haversine(du["lat"], du["lon"], dv["lat"], dv["lon"])
                new_walk_m = walk_m + step_m
                
                u_is_sta = is_station_id(u[1]) if u[0]=="phys" else False
                v_is_sta = is_station_id(v[1]) if v[0]=="phys" else False
                limit = MAX_WALK_STATION_M if (u_is_sta or v_is_sta) else MAX_WALK_BUS_BUS_M
                limit = max(limit, MAX_WALK_SEG_M if (u_is_sta or v_is_sta) else 180.0) 

                if new_walk_m > limit:
                    continue 
            else:
                new_walk_m = 0.0

            new_cost = cost + w
            heapq.heappush(pq, (new_cost, v, new_walk_m, path + [v]))

    return solutions


# -------------------- 結果表示用ユーティリティ --------------------

def print_solution_summary(G, sol, rank):
    path = sol["path"]
    cost = sol["cost"]
    
    print(f"#{rank} [Cost: {cost:.2f}] ----------------------------")
    
    # 詳細表示用ループ
    current_mode = None
    segment_start_node = None
    segment_dist = 0.0
    
    for i, (u, v) in enumerate(zip(path, path[1:])):
        e = G.edges[u, v]
        etype = e.get("etype")
        
        # 名前取得ヘルパー
        def get_name(n):
            return G.nodes[n].get("name") or G.nodes[n].get("disp") or "???"

        # --- 移動の出力 ---
        if etype == "ride":
            line_name = G.nodes[u].get("disp")
            if current_mode != line_name:
                # 前の区間（徒歩など）があれば出力
                if current_mode == "walk":
                    print(f"  [徒歩] {get_name(segment_start_node)} -> {get_name(u)} ({int(segment_dist)}m)")
                
                # 新しい乗り物区間の開始
                print(f"  [乗車] {line_name} : {get_name(u)}", end="")
                current_mode = line_name
            
            # 乗り続けている間は何もしない（最後のalightで閉じる）

        elif etype == "walk":
            dist = e.get("meters", 0)
            if current_mode != "walk":
                # 前の区間（乗り物）があれば「降車」として閉じる
                if current_mode and current_mode != "walk":
                    print(f" -> {get_name(u)}") # 乗車区間の終わり
                
                current_mode = "walk"
                segment_start_node = u
                segment_dist = 0.0
            
            segment_dist += dist

        elif etype == "alight":
            # 降りた瞬間: 乗車行を閉じる
            print(f" -> {get_name(v)}")
            current_mode = None # フラグリセット
        
        elif etype == "board":
            # 乗った瞬間: 次の ride で処理するのでここでは何もしないが、
            # 徒歩からの切り替えタイミングなら出力が必要
            if current_mode == "walk":
                print(f"  [徒歩] {get_name(segment_start_node)} -> {get_name(u)} ({int(segment_dist)}m)")
                current_mode = None

    # ループ終了後の残処理（最後の徒歩など）
    if current_mode == "walk":
         print(f"  [徒歩] {get_name(segment_start_node)} -> {get_name(path[-1])} ({int(segment_dist)}m)")

    # 所要時間の計算
    total_minutes = 0.0
    for u, v in zip(path, path[1:]):
        total_minutes += G.edges[u, v].get("minutes", 0.0)

    print(f"    (Total Walk: {sol['walk_m']:.0f}m, Est. Time: {int(total_minutes)}min)")
# -------------------- Main --------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--busstop-poles", required=True)
    ap.add_argument("--busroute-patterns", required=True)
    ap.add_argument("--stations", required=True)
    ap.add_argument("--railways", required=True)
    ap.add_argument("--a", required=True, help="lat,lon")
    ap.add_argument("--b", required=True, help="lat,lon")
    ap.add_argument("--walk", type=int, default=300)
    args = ap.parse_args()
    
    global MAX_WALK_SEG_M
    MAX_WALK_SEG_M = float(args.walk)

    alat, alon = map(float, args.a.split(","))
    blat, blon = map(float, args.b.split(","))

    print("[INFO] Building Graph...")
    G = build_graph(args.busstop_poles, args.busroute_patterns, args.stations, args.railways, walk_radius=MAX_WALK_SEG_M)

    # A: 出発地点 (Station優先などは好みで)
    a_phys, ad = nearest_phys(G, alat, alon, station_only=False)
    # B: 到着地点
    b_phys, bd = nearest_phys(G, blat, blon, station_only=True)
    if not b_phys or bd > 500:
        b_phys, bd = nearest_phys(G, blat, blon, station_only=False)

    if not a_phys or not b_phys:
        print("NG: 端点が見つかりません")
        sys.exit(1)

    print(f"[INFO] START: {G.nodes[a_phys]['name']} -> GOAL: {G.nodes[b_phys]['name']}")

    # --- 重みの動的調整 (出発地の初乗り無料化など) ---
    A_ID = a_phys[1]
    for u, v, data in G.edges(data=True):
        if data.get("etype") == "board":
            mode = G.nodes[v].get("mode") if v[0] == "line" else None
            if u == ("phys", A_ID):
                data["w"] = 0.0 # 初回乗車無料
                data["minutes"] = 0.0 # 初回は待ち時間なしとみなす（時刻表連動でないため）
            else:
                base = TRANSFER_PENALTY
                wait_time = 0.0
                if mode == "bus": 
                    base += BUS_WAIT_PENALTY
                    wait_time = 30.0 # バス待ち平均
                else:
                    wait_time = 5.0 # 電車待ち平均
                
                data["w"] = base
                data["minutes"] = wait_time
    
    # --- ダイクストラ探索 ---
    K = 5
    print(f"[INFO] Searching Top-{K} routes...")
    
    results = find_top_k_paths(G, a_phys, b_phys, K=K)
    
    if results:
        print(f"\nFound {len(results)} routes:")
        for i, sol in enumerate(results, 1):
            print("-" * 40)
            print_solution_summary(G, sol, i)
    else:
        print("[FAIL] No route found.")

if __name__ == "__main__":
    main()