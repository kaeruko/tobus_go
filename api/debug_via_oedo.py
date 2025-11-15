#!/usr/bin/env python3
# debug_via_oedo.py

import math
import networkx as nx
from networkx.algorithms.simple_paths import shortest_simple_paths

from toei_reach_min_transfers import (
    build_graph,
    nearest_phys,
    haversine,
    WALK_COST,
    WALK_SPEED_M_PER_MIN,
)

DATA_DIR   = "data"
BUSSTOP    = f"{DATA_DIR}/busstop_poles.json"
BUSROUTE   = f"{DATA_DIR}/busroute_patterns.json"
STATIONS   = f"{DATA_DIR}/stations.json"
RAILWAYS   = f"{DATA_DIR}/railways.json"

# 平井七丁目 / 水道橋（さっきの curl と同じ）
A_LAT, A_LON = 35.71525225496033, 139.83992152883587
B_LAT, B_LON = 35.7020484,        139.7535016

def summarize_with_walk_base(G, path):
    """base_w を使って total と walk_max_m だけ見る簡易版"""
    total = 0.0
    walk_w_total = 0.0
    walk_w_cur_seg = 0.0
    walk_w_max_seg = 0.0

    for u, v in zip(path, path[1:]):
        e = G.edges[u, v]
        w = float(e.get("base_w", e.get("w", 0.0)))
        total += w
        et = e.get("etype")

        if et == "walk":
            walk_w_total += w
            walk_w_cur_seg += w
        else:
            if walk_w_cur_seg > 0:
                walk_w_max_seg = max(walk_w_max_seg, walk_w_cur_seg)
                walk_w_cur_seg = 0.0

    if walk_w_cur_seg > 0:
        walk_w_max_seg = max(walk_w_max_seg, walk_w_cur_seg)

    walk_total_min = walk_w_total / WALK_COST
    walk_max_min   = walk_w_max_seg / WALK_COST
    walk_total_m   = walk_total_min * WALK_SPEED_M_PER_MIN
    walk_max_m     = walk_max_min * WALK_SPEED_M_PER_MIN

    return dict(
        total=total,
        walk_max_m=walk_max_m,
        walk_total_m=walk_total_m,
    )

def line_chain(G, path):
    chain = []
    seen  = set()
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
    print("[DBG] nodes=", G.number_of_nodes(), "edges=", G.number_of_edges(), "|", st)

    a_phys, ad = nearest_phys(G, A_LAT, A_LON, station_only=False)
    b_phys, bd = nearest_phys(G, B_LAT, B_LON, station_only=True)
    if not b_phys or bd > 500:
        b_phys, bd = nearest_phys(G, B_LAT, B_LON, station_only=False)

    print("[DBG] A=", a_phys, "name=", G.nodes[a_phys]["name"], "dist=", f"{ad:.1f}m")
    print("[DBG] B=", b_phys, "name=", G.nodes[b_phys]["name"], "dist=", f"{bd:.1f}m")

    gen = shortest_simple_paths(
        G,
        a_phys,
        b_phys,
        weight=lambda u, v, d: float(d.get("base_w", d.get("w", 0.0))),
    )

    found = 0
    for idx, path in enumerate(gen):
        lc = line_chain(G, path)

        # ★ 「上２３ -> 大江戸線 -> 三田線」だけに絞る
        #   全角→半角の揺れもあるので、雑に "浅草線" を含まない という条件も付けるとよさそう
        if ("大江戸線" in lc and "三田線" in lc
                and "浅草線" not in lc):
            met = summarize_with_walk_base(G, path)
            print(f"[FOUND {found:02d}] idx={idx} lines={lc}")
            print(
                f"    total={met['total']:.1f}, "
                f"walk_max={met['walk_max_m']:.1f}m, "
                f"walk_total={met['walk_total_m']:.1f}m"
            )
            found += 1

            # 何本か見れば十分なら 5 本くらいで break
            if found >= 5:
                break

        # 念のため無限ループ防止で上限
        if idx >= 2000:
            break

    if found == 0:
        print("[RESULT] 『上２３ -> 大江戸線 -> 三田線』だけの経路は見つからず")

if __name__ == "__main__":
    main()
