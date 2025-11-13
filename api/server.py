# server.py
import os
from dotenv import load_dotenv
import json
import math
import sys
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Query, HTTPException
from fastapi.responses import JSONResponse
import networkx as nx

from toei_reach_min_transfers import (
    build_graph, nearest_phys, haversine, TRANSFER_PENALTY,
    WALK_COST, WALK_SPEED_M_PER_MIN, MAX_WALK_SEG_M,
)

from dotenv import load_dotenv

load_dotenv()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

if not GOOGLE_MAPS_API_KEY:
    print("[WARN] GOOGLE_MAPS_API_KEY not set")
else:
    print("[DBG] GOOGLE_MAPS_API_KEY loaded")

# -------------------- 起動時にグラフを1回だけ構築 --------------------
DATA_DIR   = os.getenv("DATA_DIR", "data")
BUSSTOP    = os.getenv("BUSSTOP",   f"{DATA_DIR}/busstop_poles.json")
BUSROUTE   = os.getenv("BUSROUTE",  f"{DATA_DIR}/busroute_patterns.json")
STATIONS   = os.getenv("STATIONS",  f"{DATA_DIR}/stations.json")
RAILWAYS   = os.getenv("RAILWAYS",  f"{DATA_DIR}/railways.json")
WALK_RAD   = int(os.getenv("WALK_RADIUS", "300"))

app = FastAPI(title="Toei Route API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

G = None
STATS = {}

def segments_detailed(G, path):
    """
    各区間を {kind, title, from_, to, edges, minutes, meters, stops} で返す
      kind: 'bus' | 'rail' | 'walk'
      stops: [{name, is_origin, is_destination}, ...]  // bus/rail のみ
    """
    segs = []
    cur = None
    walk_m = 0.0
    walk_from = None
    last_phys = None  # 直近の物理ノード ("phys", id)

    def flush():
        nonlocal cur, walk_m, walk_from
        if not cur:
            return

        if cur["kind"] == "walk":
            cur["meters"] = int(round(walk_m))
            cur["minutes"] = max(1, int(round(walk_m / 80.0)))  # 80m/分 仮

        elif cur["kind"] in ("bus", "rail"):
            cur["minutes"] = max(1, int(round(cur.get("edges", 0) * 2.0)))  # 1停≈2分

            stops = cur.get("stops") or []
            if stops:
                if not any(s.get("is_origin") for s in stops):
                    stops[0]["is_origin"] = True
                if not any(s.get("is_destination") for s in stops):
                    stops[-1]["is_destination"] = True
                cur["stops"] = stops

        segs.append(cur)
        cur = None
        walk_m = 0.0
        walk_from = None

    for u, v in zip(path, path[1:]):
        et = G.edges[u, v].get("etype")

        if u[0] == "phys":
            last_phys = u

        # ---- 徒歩セグメント ----
        if et == "walk":
            if not cur or cur["kind"] != "walk":
                flush()
                walk_from = (
                    G.nodes[u]["name"] if u[0] == "phys"
                    else (G.nodes[last_phys]["name"] if last_phys else None)
                )
                cur = {
                    "kind": "walk",
                    "title": "徒歩",
                    "edges": 0,
                    "from_": walk_from,
                    "to": None,
                }
            cur["edges"] += 1

            if u[0] == "phys" and v[0] == "phys":
                walk_m += haversine(
                    G.nodes[u]["lat"], G.nodes[u]["lon"],
                    G.nodes[v]["lat"], G.nodes[v]["lon"],
                )
                cur["to"] = G.nodes[v]["name"]

            continue  # 次のエッジへ

        # ---- バス/鉄道セグメント ----
        # ライン層ノード（"line", phys_id, line_id）を拾う
        node = v if v[0] == "line" else (u if u[0] == "line" else None)
        if not node:
            continue

        line_id = G.nodes[node].get("line")
        line_name = (
            G.nodes[node].get("disp")
            or G.nodes[node].get("name")
            or line_id
        )
        kind = "rail" if "Railway" in (line_id or "") else "bus"

        # board: 乗車開始
        if et == "board" and v[0] == "line":
            flush()
            from_name = (
                G.nodes[last_phys]["name"]
                if last_phys else G.nodes[u]["name"]
            )
            cur = {
                "kind": kind,
                "title": line_name,
                "line": line_id,
                "edges": 0,
                "from_": from_name,
                "to": None,
                "stops": [],
            }
            # 乗車停
            cur["stops"].append({
                "name": from_name,
                "is_origin": True,
                "is_destination": False,
            })

        # ride: 同一路線上を移動（停留所を1つ進む）
        elif et == "ride":
            if cur and cur["kind"] in ("bus", "rail"):
                cur["edges"] = cur.get("edges", 0) + 1

                phys_id = node[1]  # ("line", phys_id, line_id)
                phys_node = ("phys", phys_id)
                if phys_node in G.nodes:
                    pname = G.nodes[phys_node]["name"]
                else:
                    pname = G.nodes[node].get("name")

                stops = cur.setdefault("stops", [])
                if not stops or stops[-1]["name"] != pname:
                    stops.append({
                        "name": pname,
                        "is_origin": False,
                        "is_destination": False,
                    })

        # alight / xfer: 降車 or 乗換地点でセグメント終了
        elif et in ("alight", "xfer") and u[0] == "line":
            if cur and cur["kind"] in ("bus", "rail"):
                to_phys = v if v[0] == "phys" else last_phys
                if to_phys:
                    to_name = G.nodes[to_phys]["name"]
                    cur["to"] = to_name

                    stops = cur.setdefault("stops", [])
                    if not stops or stops[-1]["name"] != to_name:
                        stops.append({
                            "name": to_name,
                            "is_origin": False,
                            "is_destination": False,
                        })
                    if stops:
                        stops[-1]["is_destination"] = True
                        if not any(s.get("is_origin") for s in stops):
                            stops[0]["is_origin"] = True

                flush()

    if cur:
        flush()

    out = []
    for s in segs:
        out.append(dict(
            kind=s["kind"],
            title=s["title"],
            edges=s.get("edges", 0),
            from_=s.get("from_"),
            to=s.get("to"),
            meters=s.get("meters"),
            minutes=s.get("minutes"),
            stops=s.get("stops", []),
        ))
    return out


def summarize_with_walk(G, path):
    """
    CLI側と同じロジックで徒歩制約に対応したサマライズ
    walk_max_m を計算して300m制約に使う
    """
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


def _summarize(G, path):
    rides = walks = boards = xfers = total = 0
    for u, v in zip(path, path[1:]):
        e = G.edges[u, v]; total += e["w"]; t = e.get("etype")
        if t=="ride": rides+=1
        if t=="walk": walks+=1
        if t=="board": boards+=1
        if t=="xfer":  xfers+=1
    transfers = max(0, boards-1) + xfers
    return dict(total=total, rides=rides, walks=walks, boards=boards, transfers=transfers)

@app.on_event("startup")
async def _startup():
    global G, STATS
    G, STATS = build_graph(BUSSTOP, BUSROUTE, STATIONS, RAILWAYS, walk_radius=WALK_RAD)
    print("[server] graph ready:", STATS)

@app.get("/health")
def health():
    return JSONResponse(content={"ok": True, "stats": STATS}, media_type="application/json; charset=utf-8")

# -------------------- 経路検索（Flutter から呼ぶやつ） --------------------
@app.get("/route")
def route(
    alat: float = Query(...), alon: float = Query(...),
    blat: float = Query(...), blon: float = Query(...),
    pref: str = Query("fewTransfers")
):
    # まず駅で探す
    b_phys, bd = nearest_phys(G, blat, blon, station_only=True)
    
    # 駅が見つからない、または遠すぎる場合はバス停も含めて探す
    if not b_phys or bd > 500:
        b_phys, bd = nearest_phys(G, blat, blon, station_only=False)
    
    a_phys, ad = nearest_phys(G, alat, alon, station_only=False)
    
    if not a_phys or not b_phys:
        raise HTTPException(400, "nearby node not found")

    print(f"[DBG] A_phys: {a_phys}, name={G.nodes[a_phys].get('name')}, {ad:.1f}m")
    print(f"[DBG] B_phys: {b_phys}, name={G.nodes[b_phys].get('name')}, {bd:.1f}m")

    A_ID = a_phys[1]
    
    # ★ 動的に重み関数を定義（リクエストごとにA地点が変わるため）
    def weight_func(u, v, data):
        base_w = float(data.get("w", 0.0))
        etype = data.get("etype")
        
        # 最初の乗車は無料、それ以降の board は乗換ペナルティ
        if etype == "board":
            if u == ("phys", A_ID):
                return 0.0  # 最初の乗車は無料
            
            # ノード v (line layer) からモードを取得（保険付き）
            node = v if v[0] == "line" else u
            mode = G.nodes.get(node, {}).get("mode")
            
            # shortTime モードでは rail への乗換を優遇
            if pref == "shortTime" and mode == "rail":
                return float(TRANSFER_PENALTY * 0.4)  # 鉄道は軽く
            return float(TRANSFER_PENALTY)
        
        # xfer エッジ（line→line の直接乗換）も鉄道同士なら軽くする
        if etype == "xfer":
            mu = G.nodes[u].get("mode") if u[0] == "line" else None
            mv = G.nodes[v].get("mode") if v[0] == "line" else None
            base = base_w if base_w > 0 else float(TRANSFER_PENALTY)
            
            if pref == "shortTime" and mu == "rail" and mv == "rail":
                return base * 0.4
            return base
        
        return base_w

    K = 3
    cands = []
    seen = set()
    backup = []
    
    try:
        # ★ shortest_simple_paths で複数候補を取得
        for path in nx.shortest_simple_paths(G, a_phys, b_phys, weight=weight_func):
            segs = segments_detailed(G, path)

            # 路線の組み合わせで重複排除
            sig_items = []
            for s in segs:
                if s.get("kind") in ("bus", "rail"):
                    name = s.get("line") or s.get("title")
                    sig_items.append(name)
            sig = tuple(sig_items)

            if sig in seen:
                continue
            seen.add(sig)
            
            met = summarize_with_walk(G, path)
            
            entry = {
                "lines": list(sig),
                **met,
                "steps": segs,
            }

            # CLI側と同じロジック：徒歩セグメントが300m以下の経路のみ本命として採用
            if met["walk_max_m"] <= MAX_WALK_SEG_M:
                entry["id"] = f"C{len(cands)+1}"
                cands.append(entry)
                if len(cands) >= K:
                    break
            else:
                backup.append(entry)
                
    except nx.NetworkXNoPath:
        cands = []

    # 300m制約を満たす候補が見つからなかった場合の妥協案
    if not cands:
        for i, e in enumerate(backup[:K], 1):
            e["id"] = f"C{i}"
        cands = backup[:K]

    return JSONResponse(content={"candidates": cands}, media_type="application/json; charset=utf-8")

# -------------------- Places ラッパ（Flutter の PlaceField 用） --------------------
@app.get("/autocomplete")
async def autocomplete(q: str = Query(...)):
    if not GOOGLE_MAPS_API_KEY:
        return JSONResponse(content={"predictions": []}, media_type="application/json; charset=utf-8")
    url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
    params = {"key": GOOGLE_MAPS_API_KEY, "input": q, "language": "ja", "components": "country:jp"}
    async with httpx.AsyncClient(timeout=10.0) as cl:
        r = await cl.get(url, params=params)
    return JSONResponse(content=r.json(), media_type="application/json; charset=utf-8")

@app.get("/details")
async def details(place_id: str = Query(...)):
    if not GOOGLE_MAPS_API_KEY:
        return JSONResponse(content={"result": {}}, media_type="application/json; charset=utf-8")
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {"key": GOOGLE_MAPS_API_KEY, "place_id": place_id,
              "language":"ja", "fields":"geometry,name,formatted_address"}
    async with httpx.AsyncClient(timeout=10.0) as cl:
        r = await cl.get(url, params=params)
    return JSONResponse(content=r.json(), media_type="application/json; charset=utf-8")