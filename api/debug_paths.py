#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import networkx as nx
from networkx.algorithms.simple_paths import shortest_simple_paths

from toei_reach_min_transfers import (
    build_graph, nearest_phys,
    WALK_COST, WALK_SPEED_M_PER_MIN,
)

DATA_DIR   = "data"
BUSSTOP    = f"{DATA_DIR}/busstop_poles.json"
BUSROUTE   = f"{DATA_DIR}/busroute_patterns.json"
STATIONS   = f"{DATA_DIR}/stations.json"
RAILWAYS   = f"{DATA_DIR}/railways.json"

# ===== A, B の座標（いま curl で叩いているやつと同じ） =====
A_LAT, A_LON = 35.71525225496033, 139.83992152883587
B_LAT, B_LON = 35.7020484,        139.7535016


def summarize(G, path):
    """今のサーバと同じ定義で boards/xfers/transfers を数える"""
    rides = walks = boards = xfers = 0
    total = 0.0

    for u, v in zip(path, path[1:]):
        e = G.edges[u, v]
        # build_graph 後は base_w が入っている前提
        w = float(e.get("base_w", e.get("w", 0.0)))
        total += w

        t = e.get("etype")
        if t == "ride":  rides += 1
        if t == "walk":  walks += 1
        if t == "board": boards += 1
        if t == "xfer":  xfers  += 1

    transfers = max(0, boards - 1) + xfers

    # 徒歩最大距離も一応出しておく（連続徒歩セグメント）
    walk_w_total = 0.0
    walk_w_cur   = 0.0
    walk_w_max   = 0.0
    for u, v in zip(path, path[1:]):
        e = G.edges[u, v]
        w = float(e.get("base_w", e.get("w", 0.0)))
        if e.get("etype") == "walk":
            walk_w_total += w
            walk_w_cur   += w
        else:
            if walk_w_cur > 0:
                walk_w_max = max(walk_w_max, walk_w_cur)
                walk_w_cur = 0.0
    if walk_w_cur > 0:
        walk_w_max = max(walk_w_max, walk_w_cur)

    walk_total_min = walk_w_total / WALK_COST
    walk_max_min   = walk_w_max   / WALK_COST
    walk_total_m   = walk_total_min * WALK_SPEED_M_PER_MIN
    walk_max_m     = walk_max_min   * WALK_SPEED_M_PER_MIN

    return dict(
        total        = total,
        rides        = rides,
        walks        = walks,
        boards       = boards,
        xfers        = xfers,
        transfers    = transfers,
        walk_total_m = walk_total_m,
        walk_max_m   = walk_max_m,
    )


def has_rail(G, path):
    """この path に鉄道(lineノード mode=rail)が含まれるか？"""
    for u, v in zip(path, path[1:]):
        for n in (u, v):
            if n[0] == "line":
                if G.nodes[n].get("mode") == "rail":
                    return True
    return False


def line_chain(G, path):
    """lineノードの disp をユニーク順に並べる（サマリ表示用）"""
    chain = []
    seen = set()
    for n in path:
        if n[0] != "line":
            continue
        disp = G.nodes[n].get("disp") or G.nodes[n].get("name") or G.nodes[n].get("line")
        if disp in seen:
            continue
        seen.add(disp)
        chain.append(disp)
    return " -> ".join(chain)


def main():
    print("[DBG] building graph...")
    G, st = build_graph(BUSSTOP, BUSROUTE, STATIONS, RAILWAYS, walk_radius=300)
    print(f"[DBG] nodes={G.number_of_nodes()} edges={G.number_of_edges()} | {st}")

    # build_graph と同じく base_w を確認
    for u, v, data in G.edges(data=True):
        if "base_w" not in data:
            data["base_w"] = float(data.get("w", 0.0))

    # A, B を決める（server.py と同じロジック）
    a_phys, ad = nearest_phys(G, A_LAT, A_LON, station_only=False)
    b_phys, bd = nearest_phys(G, B_LAT, B_LON, station_only=True)
    if not b_phys or bd > 500:
        b_phys, bd = nearest_phys(G, B_LAT, B_LON, station_only=False)

    print(f"[DBG] A={a_phys} name={G.nodes[a_phys].get('name')} dist={ad:.1f}m")
    print(f"[DBG] B={b_phys} name={G.nodes[b_phys].get('name')} dist={bd:.1f}m")

    # ==== 仮説検証：素の G で「時間コスト(base_w)最小の単純路」を上から 30 本見る ====
    print("\n[DBG] top 30 simple paths by base_w (時間) on raw G")
    gen = shortest_simple_paths(G, a_phys, b_phys,
                                weight=lambda u, v, d: float(d.get("base_w", d.get("w", 0.0))))

    min_transfer = None
    first_rail_idx = None
    first_rail_info = None

    for idx, path in enumerate(gen):
        met  = summarize(G, path)
        rail = has_rail(G, path)
        chain = line_chain(G, path)

        if min_transfer is None or met["transfers"] < min_transfer:
            min_transfer = met["transfers"]

        print(
            f"[{idx:02d}] transfers={met['transfers']} "
            f"rail={rail} total={met['total']:.1f} "
            f"walk_max={met['walk_max_m']:.1f}m | lines: {chain}"
        )

        if rail and first_rail_idx is None:
            first_rail_idx = idx
            first_rail_info = (met, chain)

        if idx >= 29:
            break

    print("\n[RESULT] min transfers over these paths =", min_transfer)
    if first_rail_idx is None:
        print("[RESULT] ❌ 30本以内には鉄道を含む経路が出てこなかった")
    else:
        met, chain = first_rail_info
        print(
            f"[RESULT] ✅ 最初に鉄道が出てくるのは index={first_rail_idx}, "
            f"transfers={met['transfers']}, lines={chain}"
        )



    from toei_reach_min_transfers import haversine

    # 「上野松坂屋前」の物理ノードを拾う
    ueno_nodes = [n for n, d in G.nodes(data=True)
                if n[0] == "phys" and d.get("name") == "上野松坂屋前"]
    ueno = ueno_nodes[0]
    print("UENO phys =", ueno)

    # そこから徒歩で行ける物理ノードを列挙
    for v in G.successors(ueno):
        e = G.edges[ueno, v]
        if e.get("etype") != "walk" or v[0] != "phys":
            continue
        name = G.nodes[v].get("name")
        is_station = str(v[1]).startswith("odpt.Station:")
        print("walk ->", v, name, "station?" , is_station, "meters=", e.get("meters"))



if __name__ == "__main__":
    main()
