
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# toei_reach_min_transfers.py
#
# 使い方（前と同じファイル名でOK）:
#   python toei_reach_min_transfers.py \
#     --busstop-poles data/busstop_poles.json \
#     --busroute-patterns data/busroute_patterns.json \
#     --stations data/stations.json \
#     --railways data/railways.json \
#     --a 35.71516476890729,139.83876403586873 \
#     --b 35.72969438103714,139.71102884253577 \
#     --walk 300
#
# 目的:
#   ・“路線に乗っている状態”の層を作る
#   ・同じ路線上の移動は安く、路線を変える（乗換）は高コスト
#   ・徒歩も有意に重くして、極力乗り換えない経路を選ぶ


import json, argparse, math, sys
import networkx as nx
from networkx.algorithms.simple_paths import shortest_simple_paths
from route_common import find_k_candidates as common_find_k_candidates
from route_common import _sig_from_segments
from route_common import compress_bus_poles_into_hubs

# -------------------- チューニング定数 --------------------
# 時間ベースのコスト設計（分単位で設定）
BUS_RIDE_COST = 2.0    # バス1停留所 ≒ 2分
RAIL_RIDE_COST = 1.6   # 地下鉄1駅 ≒ 1.6分（バスより速め）
WALK_SPEED_M_PER_MIN = 80.0  # 1分 ≒ 80m で計算
WALK_COST = 1.0        # 1分歩く = 1.0 コスト
TRANSFER_PENALTY = 4.0 # 乗り換え1回 ≒ 4分ペナルティ
BUS_WAIT_PENALTY = 15.0  # 2本目以降のバス乗車に追加する待ち時間ペナルティ（分相当）

MAX_WALK_SEG_M = 600.0  # 1区間の徒歩は 300m まで許容


# ===== ここから: 上位3候補を出すロジック =====
def _line_norm(s: str) -> str:
    tbl = str.maketrans("０１２３４５６７８９　（）", "0123456789 ()")
    return (s or "").translate(tbl).replace(" ", "")

def _segments_by_line(G, path):
    """連続する同一路線（lineノードの norm）ごとに圧縮して返す。徒歩は 'walk'。"""
    segs = []
    cur = None
    for u, v in zip(path, path[1:]):
        et = G.edges[u, v].get("etype")
        if et == "ride" or (v[0] == "line" and et == "board") or (u[0] == "line" and et in ("alight","xfer")):
            line = None
            mode = None
            node = None
            if v[0] == "line":
                node = v
            elif u[0] == "line":
                node = u
            if node:
                nd = G.nodes[node]
                line = _line_norm(nd.get("disp") or nd.get("name") or nd.get("line"))
                mode = nd.get("mode")   # "bus" or "rail"
            if line:
                if cur and cur["kind"] == "line" and cur["name"] == line and cur.get("mode") == mode:
                    cur["edges"] += 1
                else:
                    if cur: segs.append(cur)
                    cur = {"kind":"line", "name": line, "mode": mode, "edges": 1}
        elif et == "walk":
            if cur and cur["kind"] == "walk":
                cur["edges"] += 1
            else:
                if cur: segs.append(cur)
                cur = {"kind":"walk", "name":"walk", "edges": 1}
    if cur: segs.append(cur)
    return segs

def summarize_with_walk(G, path):
    rides = walks = boards = xfers = 0
    total = 0.0

    walk_w_total = 0.0
    walk_w_cur_seg = 0.0
    walk_w_max_seg = 0.0

    for u, v in zip(path, path[1:]):
        e = G.edges[u, v]
        w = e["w"]
        total += w
        t = e.get("etype")

        if t == "ride":
            rides += 1
        if t == "walk":
            walks += 1
            walk_w_total += w
            walk_w_cur_seg += w
        else:
            if walk_w_cur_seg > 0:
                walk_w_max_seg = max(walk_w_max_seg, walk_w_cur_seg)
                walk_w_cur_seg = 0.0

        if t == "board":
            boards += 1
        if t == "xfer":
            xfers += 1

    if walk_w_cur_seg > 0:
        walk_w_max_seg = max(walk_w_max_seg, walk_w_cur_seg)

    # 重み → 分 → m に変換
    walk_total_min = walk_w_total / WALK_COST
    walk_max_min = walk_w_max_seg / WALK_COST
    walk_total_m = walk_total_min * WALK_SPEED_M_PER_MIN
    walk_max_m = walk_max_min * WALK_SPEED_M_PER_MIN

    transfers = max(0, boards - 1) + xfers

    return dict(
        total=total,
        rides=rides,
        walks=walks,
        boards=boards,
        xfers=xfers,
        transfers=transfers,
        walk_total_m=walk_total_m,
        walk_max_m=walk_max_m,
    )


def debug_dump_path(G, path, label=""):
    """
    1 本の path について、エッジごとの詳細と累積コストをダンプする。
    - u, v ノード
    - etype / line / mode
    - base_w / w
    - 累積 w
    """
    print("=" * 60)
    print(f"[DEBUG PATH] {label}  (len={len(path)})")
    total_w = 0.0

    def node_label(n):
        d = G.nodes[n]
        if n[0] == "phys":
            return f"phys|{d.get('name','')}"
        else:
            # line ノード
            return f"line|{d.get('disp') or d.get('name','')}"

    for i, (u, v) in enumerate(zip(path, path[1:])):
        e = G.edges[u, v]
        etype = e.get("etype")
        base_w = float(e.get("base_w", e.get("w", 0.0)))
        w = float(e.get("w", 0.0))
        line = e.get("line") or "-"
        mode = e.get("mode") \
               or G.nodes[u].get("mode") \
               or G.nodes[v].get("mode")
        meters = e.get("meters")

        total_w += w

        print(
            f"{i:02d}: {node_label(u)} -> {node_label(v)} | "
            f"etype={etype} line={line} mode={mode} "
            f"base_w={base_w:.2f} w={w:.2f} "
            f"{'(%.1fm)' % meters if meters is not None else ''} "
            f"cum={total_w:.2f}"
        )

    print(f"[DEBUG PATH] {label} TOTAL w={total_w:.6f}")
    print("=" * 60)


def sig_from_segments_cli(segs):
    """
    同じ鉄道パターン（浅草線→新宿線→三田線 など）は 1 本にまとめる。
    バスの差分（門33 / 錦37 / 都08 など）は sig には入れない。
    """
    rails = []
    for s in segs:
        if s["kind"] == "line" and s.get("mode") == "rail":
            rails.append(s["name"])
    return tuple(rails)


def _norm_line(s):
    tbl = str.maketrans("０１２３４５６７８９　（）", "0123456789 ()")
    return (s or "").translate(tbl).replace(" ", "")

# (2) 同所グルーピング：同名±近接を0コスト歩行で束ねる
# build_graphの最後あたりで呼ぶ
def normalize_title(s: str) -> str:
    t = (s or "").replace("　", " ").replace("（", "(").replace("）", ")").strip()

    # 「水道橋駅前」→「水道橋」
    # 「春日駅前」→「春日」
    # みたいに、末尾の「駅前」「駅東口」などを駅本体に寄せる
    for suffix in ("駅前", "駅東口", "駅西口", "駅南口", "駅北口"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
            break

    # もし駅名が「◯◯駅」になっている路線があっても、
    # そのままでも「◯◯駅前」とは同じグループになる（どっちも「◯◯」になる）想定
    if t.endswith("駅"):
        t = t[:-1]

    return t

def tie_same_place_busstops(G, radius_m=150):
    by_name = {}
    for n, d in G.nodes(data=True):
        if n[0] != "phys":
            continue
        key = normalize_title(d.get("name", ""))
        by_name.setdefault(key, []).append((n, d))

    added = 0
    for name, nodes in by_name.items():
        for i in range(len(nodes)):
            ni, di = nodes[i]
            for j in range(i + 1, len(nodes)):
                nj, dj = nodes[j]
                dist = haversine(di["lat"], di["lon"], dj["lat"], dj["lon"])
                if dist <= radius_m:
                    minutes = max(0.25, dist / WALK_SPEED_M_PER_MIN)
                    w = WALK_COST * minutes
                    if not G.has_edge(ni, nj):
                        G.add_edge(ni, nj, w=w, etype="walk", meters=dist); added += 1
                    if not G.has_edge(nj, ni):
                        G.add_edge(nj, ni, w=w, etype="walk", meters=dist); added += 1
    return added


# -------------------- geo utils --------------------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(a))

# -------------------- JSON loader --------------------
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data if isinstance(data, list) else [data]

def get_id(o): return o.get("owl:sameAs") or o.get("@id") or o.get("id")
def get_title(o):
    return o.get("dc:title") or (o.get("odpt:stationTitle") or {}).get("ja") or o.get("title") or ""
def get_lat(o): return o.get("geo:lat")
def get_lon(o): return o.get("geo:long")
def is_toei(op):
    if isinstance(op, list): return any("Toei" in x for x in op)
    return isinstance(op, str) and "Toei" in op

# -------------------- グラフ構造 --------------------
# 物理ノード: ("phys", id)  … バス停/駅の物理地点
# ライン層ノード: ("line", id, line_id) … その地点で「この路線に乗っている」状態
#
# エッジ種別:
#   board:  ("phys",P) -> ("line",P,L)       w=BOARD_PENALTY
#   alight: ("line",P,L) -> ("phys",P)       w=0
#   ride:   ("line",A,L) -> ("line",B,L)     w=RIDE_COST （同一路線の連続地点）
#   xfer:   ("line",P,L) -> ("line",P,L2)    w=TRANSFER_PENALTY （同一点で路線変更）
#   walk:   ("phys",P) <-> ("phys",Q)        w=WALK_COST （近接徒歩接続）

def build_graph(busstop_poles_path, busroute_patterns_path, stations_path, railways_path, walk_radius=300):
    G = nx.DiGraph()

    # --- 物理地点（バス停・駅） ---
    poles = load_json(busstop_poles_path)
    phys = {}  # id -> {lat, lon, name}
    for p in poles:
        pid = get_id(p)
        lat, lon = get_lat(p), get_lon(p)
        if pid and lat is not None and lon is not None:
            phys[pid] = {"lat": float(lat), "lon": float(lon), "name": p.get("dc:title") or pid}

    stations = load_json(stations_path)
    for s in stations:
        if not is_toei(s.get("odpt:operator")): continue
        sid = get_id(s)
        lat, lon = get_lat(s), get_lon(s)
        if sid and lat is not None and lon is not None:
            phys[sid] = {"lat": float(lat), "lon": float(lon), "name": get_title(s)}

    # 物理ノード投入
    for pid, d in phys.items():
        G.add_node(("phys", pid), **d, kind="phys")

    # --- ライン層（バス）: busroute単位で同一路線扱い ---
    patterns = load_json(busroute_patterns_path)
    bus_edges = 0
    # 路線 → その地点のライン層ノードが必要になったら随時作る
    def ensure_line_node(phys_id, line_id, display_name, mode):
        n = ("line", phys_id, line_id)
        if n not in G:
            base = phys[phys_id]
            G.add_node(
                n,
                lat=base["lat"], lon=base["lon"],
                name=f"{base['name']}@{display_name}",
                line=line_id,
                kind="line",
                disp=display_name,                # 表示用（例: 上２３ / 草６４）
                norm=_norm_line(display_name),    # 検証用キー（例: 上23 / 草64）
                mode=mode,                        # "bus" or "rail"
            )
            G.add_edge(("phys", phys_id), n, w=TRANSFER_PENALTY, etype="board")
            G.add_edge(n, ("phys", phys_id), w=0, etype="alight")
        return n

    # BusroutePattern: odpt:busstopPoleOrder の順で ride エッジ
    def bus_orders(pat):
        return (pat.get("odpt:busstopPoleOrder")
                or pat.get("odpt:stopPoleOrder")
                or pat.get("odpt:busStopPoleOrder")
                or [])

    # 置き換え: バスの line_id は「系統ファミリ」キーにする
    for pat in patterns:
        if not is_toei(pat.get("odpt:operator")): 
            continue

        raw_id = pat.get("odpt:pattern") or get_id(pat)
        disp = (pat.get("dc:title") or raw_id).split()[0]  # 例: "上２３ 出入" -> "上２３"
        norm = _norm_line(disp)                             # 例: "上23"
        family_key = f"bus:{norm}"                          # ← ここが line_id

        orders = bus_orders(pat)
        try:
            orders = sorted(orders, key=lambda x: x.get("odpt:index", 0))
        except Exception:
            pass

        seq = []
        for o in orders:
            pid = o.get("odpt:busstopPole") or o.get("odpt:busStopPole")
            if pid in phys:
                seq.append(pid)

        for a, b in zip(seq, seq[1:]):
            na = ensure_line_node(a, family_key, disp, "bus")
            nb = ensure_line_node(b, family_key, disp, "bus")
            if not G.has_edge(na, nb):
                G.add_edge(na, nb, w=BUS_RIDE_COST, etype="ride", line=family_key, mode="bus")
                bus_edges += 1



    # --- ライン層（鉄道）: railway 単位で ride エッジ（双方向） ---
    railways = load_json(railways_path)
    rail_edges = 0
    for rw in railways:
        if not is_toei(rw.get("odpt:operator")): continue
        line_id = get_id(rw) or rw.get("odpt:railway")
        display_line = rw.get("dc:title") or line_id
        order = rw.get("odpt:stationOrder") or []
        try:
            order = sorted(order, key=lambda x: x.get("odpt:index", 0))
        except Exception:
            pass
        seq = [o.get("odpt:station") for o in order if o.get("odpt:station") in phys]
        for a, b in zip(seq, seq[1:]):
            na = ensure_line_node(a, line_id, display_line, "rail")
            nb = ensure_line_node(b, line_id, display_line, "rail")
            G.add_edge(na, nb, w=RAIL_RIDE_COST, etype="ride", line=line_id, mode="rail")
            G.add_edge(nb, na, w=RAIL_RIDE_COST, etype="ride", line=line_id, mode="rail")
            rail_edges += 2

    # --- 物理ノード間の徒歩 ---
    # 1) ふつうの「近い物理ノード」同士を徒歩で結ぶ（〜300m）
    walk_edges = connect_walk_edges_phys(G, radius_m=walk_radius)

    # 2) 同じ名前グループ（春日駅・春日駅前 など）を“ほぼ同じ場所”として 0 コストで束ねる
    #   春日（三田）↔春日（大江戸）が 136m くらい離れてるので、半径は 150m くらいに上げる
    walk_edges += tie_same_place_busstops(G, radius_m=150)

    # 基本の重みを base_w として保存
    for u, v, data in G.edges(data=True):
        data["base_w"] = float(data.get("w", 0.0))


    # build_graph の最後に追加（toei_reach_min_transfers.py）
    cnt_bus_station = 0
    for u, v, e in G.edges(data=True):
        if e.get("etype") == "walk" and u[0] == v[0] == "phys":
            is_u_sta = _is_station_id(u[1]); is_v_sta = _is_station_id(v[1])
            if is_u_sta ^ is_v_sta:  # どちらか片方だけ駅
                cnt_bus_station += 1
    print(f"[DBG] walk edges bus↔station = {cnt_bus_station}")

    # バス停ポールの圧縮（構内うろつき削除）
    compress_bus_poles_into_hubs(G, debug=True)

    return G, {
        "bus_ride":  bus_edges,
        "rail_ride": rail_edges,
        "walk":      walk_edges,
    }

def _is_station_id(pid: str) -> bool:
    return isinstance(pid, str) and pid.startswith("odpt.Station:")

def connect_walk_edges_phys(G, radius_m=300):
    """
    物理ノード間の徒歩を“種別ごと”に張る。
      - バス↔バス:   上限 min(radius_m, 180m)
      - バス↔駅  :   上限 min(radius_m, 600m)  ← 駅に触れやすくする
      - 駅  ↔駅  :   上限 min(radius_m, 350m)
    """
    def pair_radius(a_is_sta, b_is_sta):
        if a_is_sta and b_is_sta:  # 駅-駅
            return min(radius_m, 350.0)
        if a_is_sta or b_is_sta:   # バス-駅
            return min(radius_m, 600.0)
        return min(radius_m, 180.0)  # バス-バス

    # 粗いグリッドで候補探索
    BIN_DEG = max(0.001, radius_m / 111000 * 1.2)
    bins = {}
    def key(lat, lon): return (int(lat // BIN_DEG), int(lon // BIN_DEG))
    phys_nodes = [(n, d) for n, d in G.nodes(data=True) if n[0] == "phys"]
    for n, d in phys_nodes:
        bins.setdefault(key(d["lat"], d["lon"]), []).append((n, d))

    def cand(lat, lon):
        i, j = key(lat, lon)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for item in bins.get((i + di, j + dj), []):
                    yield item

    added = 0
    for n, d in phys_nodes:
        n_is_sta = _is_station_id(n[1])
        for m, dm in cand(d["lat"], d["lon"]):
            if n == m:
                continue
            rad = pair_radius(n_is_sta, _is_station_id(m[1]))
            dist = haversine(d["lat"], d["lon"], dm["lat"], dm["lon"])
            if dist <= rad:
                minutes = max(1.0, dist / WALK_SPEED_M_PER_MIN)
                w = WALK_COST * minutes
                if not G.has_edge(n, m):
                    G.add_edge(n, m, w=w, etype="walk", meters=dist); added += 1
                if not G.has_edge(m, n):
                    G.add_edge(m, n, w=w, etype="walk", meters=dist); added += 1
    return added


def nearest_phys(G, lat, lon, station_only=False):
    """
    station_only=True の場合、駅だけを対象にする
    """
    best = None
    bestd = 1e30
    
    for n, d in G.nodes(data=True):
        if n[0] != "phys":
            continue
        
        # station_only の場合、バス停はスキップ
        if station_only and not n[1].startswith("odpt.Station:"):
            continue
        
        dist = haversine(lat, lon, d["lat"], d["lon"])
        if dist < bestd:
            best, bestd = n, dist
    
    return best, bestd

def collect_candidates_cli(G, a_phys, b_phys, K=10, debug=True):
    """
    CLI 用:
      - weight は単純に data["w"]
      - セグメントは _segments_by_line
      - シグネチャは kind=="line" の name 並び
      - summarize は summarize_with_walk
    """
    def weight_func(u, v, data):
        return data["w"]

    def make_segments(G_, path_):
        return _segments_by_line(G_, path_)

    def make_signature(segs):
        return sig_from_segments_cli(segs)

    def summarize(G_, path_):
        return summarize_with_walk(G_, path_)

    return common_find_k_candidates(
        G,
        a_phys,
        b_phys,
        weight_func=lambda u, v, data: data["w"],   # いま使ってる重み
        make_segments=_segments_by_line,           # or segments_detailed 的な関数
        make_signature=_sig_from_segments,         # 「レールだけ」版の sig 関数
        summarize=lambda G_, path_: summarize_with_walk(G_, path_),
        max_walk_seg_m=MAX_WALK_SEG_M,
        k=10,
        max_paths=5000,
        debug=False,                                # 一旦 True にして挙動を見ると良い
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--busstop-poles", required=True)
    ap.add_argument("--busroute-patterns", required=True)
    ap.add_argument("--stations", required=True)
    ap.add_argument("--railways", required=True)
    ap.add_argument("--a", required=True, help="lat,lon")
    ap.add_argument("--b", required=True, help="lat,lon")
    ap.add_argument("--walk", type=int, default=300)
    ap.add_argument("--ab-test-lines", help="例: '上23,草64|上23,上60'（ケースA|ケースB）")
    args = ap.parse_args()

    alat, alon = map(float, args.a.split(","))
    blat, blon = map(float, args.b.split(","))

    G, st = build_graph(args.busstop_poles, args.busroute_patterns, args.stations, args.railways, walk_radius=args.walk)
    print(f"[INFO] nodes={G.number_of_nodes()} edges={G.number_of_edges()} | "
          f"bus_ride={st['bus_ride']} rail_ride={st['rail_ride']} walk_edges={st['walk']}")

    # A: 出発はバス停も駅もあり
    a_phys, ad = nearest_phys(G, alat, alon, station_only=False)

    # (1) 乗車コストの再定義：最初だけ0、それ以降は=乗換 + バス待ちペナルティ
    A_ID = a_phys[1]

    for u, v, data in list(G.edges(data=True)):
        if data.get("etype") == "board":
            mode = G.nodes[v].get("mode") if v[0] == "line" else None

            if u == ("phys", A_ID):
                base = 0.0  # 最初の乗車は無料（待ち時間は出発時刻調整で吸収する想定）
            else:
                base = TRANSFER_PENALTY

                # バスに乗り換えるときは「待ち時間ペナルティ」を追加
                if mode == "bus":
                    base += BUS_WAIT_PENALTY

            data["w"] = base


    # B: まずは駅だけ見る。500mより遠かったらバス停も含めて探し直し
    b_phys, bd = nearest_phys(G, blat, blon, station_only=True)
    if not b_phys or bd > 500:
        b_phys, bd = nearest_phys(G, blat, blon, station_only=False)

    if a_phys is None or b_phys is None:
        print("[FAIL] 近傍地点が見つからない")
        sys.exit(2)
    print(f"[INFO] A={G.nodes[a_phys].get('name','')} ({ad:.1f}m)  B={G.nodes[b_phys].get('name','')} ({bd:.1f}m)")

    try:
        path = nx.shortest_path(G, a_phys, b_phys, weight="w")
    except nx.NetworkXNoPath:
        print("[NG] 到達不可（徒歩半径やデータを確認）")
        sys.exit(3)

    # 表示（常にフル）
    def label(n):
        d = G.nodes[n]
        if n[0] == "phys": return f"phys|{d.get('name','')}"
        return f"line|{d.get('name','')}"
    print("[OK] 経路 weight=", sum(G.edges[u,v]["w"] for u,v in zip(path, path[1:])))
    print("[PATH]", " -> ".join(label(n) for n in path))

    # 乗換推定: xferエッジ + board回数（最初の1回は除外）
    boards = sum(1 for u,v in zip(path, path[1:]) if G.edges[u,v].get("etype")=="board")
    xfers  = sum(1 for u,v in zip(path, path[1:]) if G.edges[u,v].get("etype")=="xfer")
    transfers = max(0, boards - 1) + xfers
    walks = sum(1 for u,v in zip(path, path[1:]) if G.edges[u,v].get("etype")=="walk")
    rides = sum(1 for u,v in zip(path, path[1:]) if G.edges[u,v].get("etype")=="ride")
    print(f"[INFO] rides={rides} walks={walks} boards={boards} xfers={xfers} -> transfers={transfers}")

    # ===== ここから: 共通 find_k_candidates エンジンで候補取得 =====
    K = 10
    cands = collect_candidates_cli(G, a_phys, b_phys, K=K, debug=True)

    if cands:
        print(f"[CANDIDATES] top {len(cands)} by total weight (distinct line sequences)")
        for i, entry in enumerate(cands, 1):
            pth = entry["path"]
            segs = entry["segments"]
            met = entry["metrics"]

            line_chain = " -> ".join(
                (s["name"] if s["kind"]=="line" else "walk")
                + (f"({s['edges']})" if s["edges"] > 1 else "")
                for s in segs
            )
            print(
                f"[C{i}] total={met['total']} rides={met['rides']} walks={met['walks']} "
                f"boards={met['boards']} transfers={met['transfers']} | lines: {line_chain}"
            )

        # ★ ここで気になる候補の詳細を見たい場合（例: C1, C2）
        for i, entry in enumerate(cands, 1):
            if i in (1, 2):  # 必要なら 3, 4 も追加
                debug_dump_path(G, entry["path"], label=f"C{i}")

    # ===== ここまで =====

    # --- A/B実験: ab_test_lines指定時 ---
    import math
    def _edge_weight_allowed(G, allowed_norm_set):
        def w(u, v, data):
            et = data.get("etype")
            if et == "walk":
                return data["w"]
            # board: phys->line は v が line
            if v[0] == "line":
                if G.nodes[v].get("norm") not in allowed_norm_set:
                    return math.inf
            # alight/xfer/ride: u が line の場合も確認
            if u[0] == "line":
                if G.nodes[u].get("norm") not in allowed_norm_set:
                    return math.inf
            return data["w"]
        return w

    def _summarize(G, path):
        rides = walks = boards = xfers = 0
        total = 0
        for u, v in zip(path, path[1:]):
            e = G.edges[u, v]
            total += e["w"]
            t = e.get("etype")
            if t == "ride":  rides += 1
            if t == "walk":  walks += 1
            if t == "board": boards += 1
            if t == "xfer":  xfers  += 1
        transfers = max(0, boards - 1) + xfers
        return dict(total=total, rides=rides, walks=walks, boards=boards, xfers=xfers, transfers=transfers)

    if getattr(args, "ab_test_lines", None):
        cases = args.ab_test_lines.split("|")
        print("[AB] start")
        for idx, case in enumerate(cases):
            allowed = [s.strip() for s in case.split(",") if s.strip()]
            allowed_norm = {_norm_line(s) for s in allowed}
            try:
                path_ab = nx.shortest_path(G, a_phys, b_phys, weight=_edge_weight_allowed(G, allowed_norm))
                met = _summarize(G, path_ab)
                print(f"[AB] case{idx+1} allow={allowed} -> total={met['total']} "
                      f"rides={met['rides']} walks={met['walks']} boards={met['boards']} "
                      f"xfers={met['xfers']} transfers={met['transfers']}")
                debug_dump_path(G, path_ab, label=f"AB case{idx+1} ({','.join(allowed)})")

            except nx.NetworkXNoPath:
                print(f"[AB] case{idx+1} allow={allowed} -> NoPath")
        print("[AB] end")


def build_walk_capped_graph(
    G, a_phys, b_phys,
    max_walk_seg_m=MAX_WALK_SEG_M,   # 既定 300
    bucket_m=50,
    max_walk_busbus_m=180.0,         # 追加: バス↔バス
    max_walk_with_station_m=600.0,   # 追加: 駅を含むとき
):
    H = nx.DiGraph()

    buckets = list(range(0, int(max(max_walk_seg_m, max_walk_with_station_m)) + 1, int(bucket_m)))
    def ride_state(n): return ("phys-ride", n[1])
    def walk_state(n, b): return ("phys-walk", n[1], int(b))

    # ノード展開
    for n, d in G.nodes(data=True):
        if n[0] == "phys":
            H.add_node(ride_state(n), **d, base=n, last="ride")
            for b in buckets:
                H.add_node(walk_state(n, b), **d, base=n, last="walk")
        else:
            H.add_node(n, **d, base=n, last="ride")

    # エッジ展開
    for u, v, data in G.edges(data=True):
        etype = data.get("etype")
        w = float(data.get("base_w", data.get("w", 0.0)))

        if etype == "walk" and u[0] == "phys" and v[0] == "phys":
            # 距離
            m = data.get("meters")
            if m is None:
                du, dv = G.nodes[u], G.nodes[v]
                m = haversine(du["lat"], du["lon"], dv["lat"], dv["lon"])
            m = int(round(m))

            # 駅を含む徒歩は 600m、バス↔バスは 180m に制限
            def is_sta(n): return isinstance(n, tuple) and n[0] == "phys" and str(n[1]).startswith("odpt.Station:")
            cap = max_walk_with_station_m if (is_sta(u) or is_sta(v)) else max_walk_busbus_m

            # ride→walk（新規徒歩開始）
            if m <= cap:
                H.add_edge(ride_state(u), walk_state(v, m), w=w, etype="walk")
            # walk→walk（継続）
            for b in buckets:
                if b + m <= cap:
                    H.add_edge(walk_state(u, b), walk_state(v, b + m), w=w, etype="walk")
            continue

        # 非徒歩（board/ride/alight/xfer）は徒歩バケットをリセットして ride 側へ
        def to_state(x):
            if x[0] == "phys":
                return ride_state(x)
            return x

        if u[0] == "phys":
            H.add_edge(ride_state(u), to_state(v), w=w, etype=etype)
            for b in buckets:
                H.add_edge(walk_state(u, b), to_state(v), w=w, etype=etype)
        else:
            H.add_edge(u, to_state(v), w=w, etype=etype)

    # 仮想 SRC/DST
    SRC = ("virtual", "SRC")
    DST = ("virtual", "DST")
    H.add_node(SRC); H.add_node(DST)
    H.add_edge(SRC, ride_state(a_phys), w=0.0, etype="virtual")
    H.add_edge(ride_state(b_phys), DST, w=0.0, etype="virtual")
    for b in buckets:
        H.add_edge(walk_state(b_phys, b), DST, w=0.0, etype="virtual")

    return H, SRC, DST



if __name__ == "__main__":
    main()
