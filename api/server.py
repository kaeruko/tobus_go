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
from networkx.algorithms.simple_paths import shortest_simple_paths
from route_common import find_k_candidates
from toei_reach_min_transfers import MAX_WALK_SEG_M  # もしくは server 側に定数コピーでもOK

from toei_reach_min_transfers import (
    build_graph, nearest_phys, haversine, build_walk_capped_graph, TRANSFER_PENALTY,
    WALK_COST, WALK_SPEED_M_PER_MIN, MAX_WALK_SEG_M, BUS_WAIT_PENALTY,
)
from networkx.algorithms.simple_paths import shortest_simple_paths

from fastapi import Query, HTTPException
from fastapi.responses import JSONResponse
from networkx.algorithms.simple_paths import shortest_simple_paths

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
WALK_RAD   = int(os.getenv("WALK_RADIUS", "600"))

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


def summarize_with_walk(G, path, weight_func):
    """
    CLI側と同じロジックで徒歩制約に対応したサマライズ
    walk_max_m を計算して300m制約に使う
    weight_func で見た値を使用
    """
    rides = walks = boards = xfers = 0
    total = 0.0

    walk_w_total = 0.0
    walk_w_cur_seg = 0.0
    walk_w_max_seg = 0.0

    for u, v in zip(path, path[1:]):
        e = G.edges[u, v]
        w = weight_func(u, v, e)
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

    # walk の重みは「分」を想定してるので、そのまま変換
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

    # ここを追加：素の重みを保存しておく
    for u, v, data in G.edges(data=True):
        data["base_w"] = float(data.get("w", 0.0))
from networkx.algorithms.simple_paths import shortest_simple_paths

# ---------- 重み関数（時間ベース + 鉄道優遇） ----------
def make_weight_func(G, A_ID: str, pref: str):
    """
    G: グラフ
    A_ID: 出発 phys ノードの ID (a_phys[1])
    pref: "fewTransfers" / "shortTime"
    """
    def _w(u, v, data):
        base = float(data.get("base_w", data.get("w", 0.0)))
        etype = data.get("etype")

        # どのモードか（bus / rail / None）
        node = None
        if u[0] == "line":
            node = u
        elif v[0] == "line":
            node = v
        mode = G.nodes[node].get("mode") if node else None

        # 最初の乗車だけ無料
        if etype == "board" and u == ("phys", A_ID):
            cost = 0.0
        else:
            cost = base

        # バス待ちペナルティ（2本目以降のバス）
        if etype == "board" and mode == "bus" and u != ("phys", A_ID):
            cost += BUS_WAIT_PENALTY

        # 「少ない乗換」モードのときは board/xfer に追加ペナルティ
        if pref == "fewTransfers" and etype in ("board", "xfer") and not (
            etype == "board" and u == ("phys", A_ID)
        ):
            cost += TRANSFER_PENALTY

        # 鉄道はかなり優遇（時間も早い想定）
        if mode == "rail":
            factor = 0.5 if pref == "shortTime" else 0.6
            if etype in ("ride", "board", "xfer"):
                cost *= factor

        # バス乗換は少し重めに
        if mode == "bus" and etype in ("board", "xfer") and not (
            etype == "board" and u == ("phys", A_ID)
        ):
            cost *= 1.2

        return cost

    return _w


# ---------- デバッグ用（生の path から鉄道有無・路線チェーンを取る） ----------
def has_rail(G, path):
    for u, v in zip(path, path[1:]):
        for n in (u, v):
            if n[0] == "line" and G.nodes[n].get("mode") == "rail":
                return True
    return False


def line_chain(G, path):
    chain = []
    seen = set()
    for n in path:
        if n[0] != "line":
            continue
        disp = (
            G.nodes[n].get("disp")
            or G.nodes[n].get("name")
            or G.nodes[n].get("line")
        )
        if disp in seen:
            continue
        seen.add(disp)
        chain.append(disp)
    return " -> ".join(chain)


# ---------- ライン構成シグネチャ（重複排除用） ----------
def route_signature(steps):
    """
    steps: segments_detailed(G, path) の結果
    鉄道の line/title だけを抜き出してタプルにしたものをシグネチャとする。
    バスは sig に入れない（バスの差分で重複排除しない）。
    例: ("浅草線", "新宿線", "三田線")
    """
    sig = []
    for s in steps:
        if s.get("kind") == "rail":
            lname = s.get("line") or s.get("title")
            if lname:
                sig.append(lname)
    return tuple(sig)

@app.get("/route")
def route(
    alat: float = Query(...),
    alon: float = Query(...),
    blat: float = Query(...),
    blon: float = Query(...),
    pref: str = Query("fewTransfers"),
):
    """
    /route:
      - グラフ G だけを使う（H/T* は使わない）
      - base_w ベースの時間コスト + 鉄道かなり優遇
      - 徒歩1セグメントは MAX_WALK_SEG_M 以内だけ正式候補
      - rail を含む候補があれば rail だけを優先して返す
      - ライン構成が同じ候補（上23→浅草線→新宿線→三田線 等）は1つにまとめる
    """
    if G is None:
        raise HTTPException(500, "graph not ready")

    # ---------- 近傍ノード ----------
    # B: まずは駅だけ見る。500mより遠かったらバス停も含めて探し直し
    b_phys, bd = nearest_phys(G, blat, blon, station_only=True)
    if not b_phys or bd > 500:
        b_phys, bd = nearest_phys(G, blat, blon, station_only=False)

    # A: 出発はバス停も駅もあり
    a_phys, ad = nearest_phys(G, alat, alon, station_only=False)

    if not a_phys or not b_phys:
        raise HTTPException(400, "nearby node not found")

    print(
        f"[DBG] /route A={a_phys}, name={G.nodes[a_phys].get('name')}, {ad:.1f}m",
        flush=True,
    )
    print(
        f"[DBG] /route B={b_phys}, name={G.nodes[b_phys].get('name')}, {bd:.1f}m",
        flush=True,
    )

    A_ID = a_phys[1]

    # ---------- 重み関数（時間ベース + 鉄道優遇） ----------
    weight_func = make_weight_func(G, A_ID, pref)

    # ---------- デバッグ用: 生 base_w での上位経路 ----------
    print("[DBG] raw G top 10 by base_w")
    raw_gen = shortest_simple_paths(
        G,
        a_phys,
        b_phys,
        weight=lambda u, v, d: float(d.get("base_w", d.get("w", 0.0))),
    )
    for idx, path_raw in enumerate(raw_gen):
        met_raw = summarize_with_walk(
            G,
            path_raw,
            weight_func=lambda u, v, e: float(e.get("base_w", e.get("w", 0.0))),
        )
        print(
            f"[RAW {idx:02d}] transfers={met_raw['transfers']} "
            f"rail={has_rail(G, path_raw)} total={met_raw['total']:.1f} "
            f"walk_max={met_raw['walk_max_m']:.1f}m "
            f"| lines: {line_chain(G, path_raw)}",
            flush=True,
        )
        if idx >= 9:
            break

    # ---------- 共通エンジン用のラッパー ----------
    def make_segments_server(G_, path_):
        # API の steps は UI 用のリッチ版を使いたいのでこれ
        return segments_detailed(G_, path_)

    def make_signature_server(steps):
        # ライン構成シグネチャ（上23→浅草線→新宿線→三田線 等）
        return route_signature(steps)

    def summarize_server(G_, path_):
        # server 版 summarize は重みとして weight_func を使う
        return summarize_with_walk(G_, path_, weight_func)

    # ---------- 候補探索（共通エンジン） ----------
    K = 10
    MAX_PATHS = 500

    raw_candidates = find_k_candidates(
        G,
        a_phys,
        b_phys,
        weight_func=weight_func,
        make_segments=make_segments_server,
        make_signature=make_signature_server,
        summarize=summarize_server,
        max_walk_seg_m=MAX_WALK_SEG_M,
        k=K,
        max_paths=MAX_PATHS,
        debug=False,  # [DBG-K] ログ出したければ True
    )

    # raw_candidates: [{ "path", "segments", "metrics" }, ...]
    candidates = []
    for idx, c in enumerate(raw_candidates, 1):
        segs = c["segments"]
        met  = c["metrics"]

        rail_flag = any(s.get("kind") == "rail" for s in segs)
        lc = " -> ".join(
            s["title"] if s.get("kind") in ("bus", "rail") else "walk"
            for s in segs
        )
        print(
            f"[DBG-CAND-FINAL {idx:02d}] rail={rail_flag} total={met['total']:.1f} "
            f"transfers={met['transfers']} walk_max={met['walk_max_m']:.1f}m "
            f"| lines={lc}",
            flush=True,
        )

        # ライン名（UI 用）
        line_names = []
        seen_lines = set()
        for s in segs:
            if s.get("kind") in ("bus", "rail"):
                lname = s.get("line") or s.get("title")
                if lname and lname not in seen_lines:
                    seen_lines.add(lname)
                    line_names.append(lname)

        candidates.append(
            {
                "id": f"C{idx}",
                "lines": line_names,
                **met,
                "steps": segs,
            }
        )

    # ---------- 鉄道優先フィルタ ----------
    def cand_has_rail(c):
        return any(s.get("kind") == "rail" for s in c.get("steps", []))

    rail_cands = [c for c in candidates if cand_has_rail(c)]

    # rail を含む候補があるなら rail だけに絞る
    if rail_cands:
        rail_cands = sorted(rail_cands, key=lambda e: e["total"])
        print(f"[DBG] rail candidates exist, choose top {K}", flush=True)
        candidates = rail_cands[:K]
    else:
        print("[DBG] no rail candidate in final list", flush=True)

    return JSONResponse(
        content={"candidates": candidates},
        media_type="application/json; charset=utf-8",
    )


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


def debug_dump_walk_segments(G, path, label=""):
    print(f"[DBG] --- walk segments detail {label} ---", flush=True)

    seg_idx = 0
    cur_dist = 0.0
    start_node = None

    def flush_seg(end_node):
        nonlocal seg_idx, cur_dist, start_node
        if cur_dist <= 0 or start_node is None:
            return
        start_name = G.nodes[start_node].get("name")
        end_name = G.nodes[end_node].get("name")
        print(
            f"[DBG] walk_seg {seg_idx}: {start_name} -> {end_name} ~{cur_dist:.1f}m",
            flush=True,
        )
        seg_idx += 1
        cur_dist = 0.0
        start_node = None

    for u, v in zip(path, path[1:]):
        et = G.edges[u, v].get("etype")
        if et == "walk":
            if cur_dist == 0.0:
                start_node = u
            du = G.nodes[u]
            dv = G.nodes[v]
            d = haversine(du["lat"], du["lon"], dv["lat"], dv["lon"])
            cur_dist += d
        else:
            if cur_dist > 0.0:
                flush_seg(u)

    if cur_dist > 0.0:
        flush_seg(path[-1])
