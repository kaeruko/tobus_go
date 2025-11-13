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
    build_graph, nearest_phys, haversine, TRANSFER_PENALTY
)

from dotenv import load_dotenv

load_dotenv()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

if not GOOGLE_MAPS_API_KEY:
    print("[WARN] GOOGLE_MAPS_API_KEY not set")
else:
    print("[DBG] GOOGLE_MAPS_API_KEY loaded")

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
if not GOOGLE_MAPS_API_KEY:
    print("[WARN] GOOGLE_MAPS_API_KEY not set")


# -------------------- 起動時にグラフを1回だけ構築 --------------------
DATA_DIR   = os.getenv("DATA_DIR", "data")
BUSSTOP    = os.getenv("BUSSTOP",   f"{DATA_DIR}/busstop_poles.json")
BUSROUTE   = os.getenv("BUSROUTE",  f"{DATA_DIR}/busroute_patterns.json")
STATIONS   = os.getenv("STATIONS",  f"{DATA_DIR}/stations.json")
RAILWAYS   = os.getenv("RAILWAYS",  f"{DATA_DIR}/railways.json")
WALK_RAD   = int(os.getenv("WALK_RADIUS", "300"))

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")  # Places 用

app = FastAPI(title="Toei Route API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

G = None
STATS = {}

def segments_detailed(G, path):
    """
    各区間を {kind,bus/rail/walk, line, from_, to, edges, minutes, meters, fare_yen, title} で返す
    - bus/rail: edges=停数, minutes≈2分×停数（暫定）
    - walk    : meters=累積距離, minutes≈80m/分（暫定）
    """
    segs = []
    cur = None
    walk_m = 0.0
    walk_from = None
    last_phys = None

    def flush():
        nonlocal cur, walk_m, walk_from
        if not cur:
            return
        if cur["kind"] == "walk":
            cur["meters"] = int(round(walk_m))
            cur["minutes"] = max(1, int(round(walk_m / 80.0)))  # 80m/分
        elif cur["kind"] in ("bus", "rail"):
            cur["minutes"] = max(1, int(round(cur.get("edges", 0) * 2.0)))  # 1停=約2分
        segs.append(cur)
        cur = None
        walk_m = 0.0
        walk_from = None

    for u, v in zip(path, path[1:]):
        et = G.edges[u, v].get("etype")
        if u[0] == "phys":
            last_phys = u

        if et == "walk":
            # 歩行セグメント開始
            if not cur or cur["kind"] != "walk":
                flush()
                walk_from = (G.nodes[u]["name"] if u[0] == "phys"
                             else (G.nodes[last_phys]["name"] if last_phys else None))
                cur = {"kind": "walk", "title": "徒歩", "edges": 0,
                       "from_": walk_from, "to": None}
            cur["edges"] += 1
            # 物理ノード間のみ距離加算
            if u[0] == "phys" and v[0] == "phys":
                walk_m += haversine(G.nodes[u]["lat"], G.nodes[u]["lon"],
                                    G.nodes[v]["lat"], G.nodes[v]["lon"])
                cur["to"] = G.nodes[v]["name"]

        else:
            # ライン層処理
            if cur and cur["kind"] == "walk":
                flush()

            node = v if v[0] == "line" else (u if u[0] == "line" else None)
            if not node:
                continue

            line_name = (G.nodes[node].get("disp")
                         or G.nodes[node].get("name")
                         or G.nodes[node].get("line"))
            kind = "rail" if "Railway" in (G.nodes[node].get("line") or "") else "bus"

            if et == "board" and v[0] == "line":
                cur = {"kind": kind, "title": line_name, "edges": 0,
                       "from_": G.nodes[last_phys]["name"] if last_phys else None,
                       "to": None}
            elif et == "ride":
                if cur and cur["kind"] in ("bus", "rail"):
                    cur["edges"] = cur.get("edges", 0) + 1
            elif et in ("alight", "xfer") and u[0] == "line":
                if cur and cur["kind"] in ("bus", "rail"):
                    to_phys = v if v[0] == "phys" else last_phys
                    cur["to"] = G.nodes[to_phys]["name"] if to_phys else None
                    flush()

    if cur:
        flush()

    out = []
    for s in segs:
        out.append(dict(
            kind=s["kind"], title=s["title"], edges=s.get("edges", 0),
            from_=s.get("from_"), to=s.get("to"),
            meters=s.get("meters"), minutes=s.get("minutes"),
        ))
    return out

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
    pref: str = Query("fewTransfers")  # 使わない場合でも受けておく
):
    a_phys, _ = nearest_phys(G, alat, alon)
    b_phys, _ = nearest_phys(G, blat, blon)
    if not a_phys or not b_phys:
        raise HTTPException(400, "nearby node not found")

    a_phys, ad = nearest_phys(G, alat, alon)
    b_phys, bd = nearest_phys(G, blat, blon)
    if not a_phys or not b_phys:
        raise HTTPException(400, "nearby node not found")

    print(f"[DBG] A_phys: {a_phys}, name={G.nodes[a_phys].get('name')}")
    print(f"[DBG] B_phys: {b_phys}, name={G.nodes[b_phys].get('name')}")


    print("[DBG] A_phys:", a_phys, G.nodes[a_phys].get("name"), f"{ad:.1f}m")
    print("[DBG] B_phys:", b_phys, G.nodes[b_phys].get("name"), f"{bd:.1f}m")

    # 最初の乗車（A地点からの board）は無料、それ以降は乗換扱いという重み関数
    def wfunc(u, v, data):
        if data.get("etype") == "board":
            return 0.0 if u == ("phys", a_phys[1]) else float(TRANSFER_PENALTY)
        return float(data["w"])

    cands = []
    seen  = set()
    try:
        for path in nx.shortest_simple_paths(G, a_phys, b_phys, weight=wfunc):
            segs = segments_detailed(G, path)

            sig_items = []
            for s in segs:
                if s.get("kind") in ("bus", "rail"):
                    name = s.get("line") or s.get("title")
                    sig_items.append(name)
            sig = tuple(sig_items)

            if sig in seen: continue
            seen.add(sig)
            met = _summarize(G, path)
            cands.append({
                "id": f"C{len(cands)+1}",
                "lines": list(sig),
                **met,
                "steps": segs
            })
            if len(cands) >= 3:
                break
    except nx.NetworkXNoPath:
        cands = []

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
