# route_common.py
from typing import Any, Callable, Dict, List, Hashable
import networkx as nx
from networkx.algorithms.simple_paths import shortest_simple_paths
from collections import defaultdict


from typing import Any, Callable, Dict, List, Hashable, Optional
import networkx as nx
from networkx.algorithms.simple_paths import shortest_simple_paths


def _sig_from_segments(segs):
    return tuple(s["name"] for s in segs if s["kind"] == "line")

# route_common.py
from typing import Any, Callable, Dict, Hashable, List
import networkx as nx
from networkx.algorithms.simple_paths import shortest_simple_paths

def _debug_path_nodes(
    G: nx.DiGraph,
    path: List[Hashable],
    prefix: str = "",
    verbose: bool = False,
) -> None:
    """ノード列をざっくり文字列化して見る用（デバッグ専用）"""

    def label(n):
        # ノードキーがタプルじゃないもの（何かの特殊ノード）にも一応対応
        if not isinstance(n, tuple):
            return str(n)

        kind = n[0]
        data = G.nodes[n]
        name = (
            data.get("name")
            or data.get("disp")
            or data.get("line")
            or "?"
        )

        if not verbose:
            # 既存と同じ表示
            return f"{kind}|{name}"

        # verbose=True のときだけ ID＋座標も出す
        node_id = n[1] if len(n) > 1 else "?"
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is not None and lon is not None:
            coord = f" ({lat:.6f},{lon:.6f})"
        else:
            coord = ""

        return f"{kind}|{name}|{node_id}{coord}"

    s = " -> ".join(label(n) for n in path)
    print(prefix + s, flush=True)


def fmt_node(G, n):
    kind, nid = n
    name = G.nodes[n].get("name") or G.nodes[n].get("title") or "???"
    oid = (
        G.nodes[n].get("odpt_id")
        or G.nodes[n].get("orig_id")
        or G.nodes[n].get("id")
        or nid
    )
    lat = G.nodes[n].get("lat")
    lon = G.nodes[n].get("lon")

    coord = ""
    if lat is not None and lon is not None:
        coord = f" ({lat:.6f},{lon:.6f})"

    return f"{kind}|{name}|{oid}{coord}"


from typing import Any, Callable, Dict, List, Hashable
import networkx as nx
from networkx.algorithms.simple_paths import shortest_simple_paths

def find_k_candidates(
    G: nx.DiGraph,
    a_phys: Hashable,
    b_phys: Hashable,
    *,
    weight_func: Callable[[Any, Any, Dict[str, Any]], float],
    make_segments: Callable[[nx.DiGraph, List[Hashable]], List[Dict[str, Any]]],
    make_signature: Callable[[List[Dict[str, Any]]], Hashable],
    summarize: Callable[[nx.DiGraph, List[Hashable]], Dict[str, float]],
    max_walk_seg_m: float,
    k: int = 10,
    max_paths: int = 200,
    debug: bool = False,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    backup: List[Dict[str, Any]] = []
    seen_sigs: set[Hashable] = set()

    # どの sig で最初に採用した path かを覚えておく
    first_path_by_sig: Dict[Hashable, List[Hashable]] = {}
    dup_count_by_sig: Dict[Hashable, int] = {}

    gen = shortest_simple_paths(G, a_phys, b_phys, weight=weight_func)

    for idx, path in enumerate(gen):
        if idx >= max_paths:
            if debug:
                print(f"[DBG-K] reach max_paths={max_paths}, break", flush=True)
                print(
                    f"[DBG-K] total_paths={idx+1} unique_sigs={len(seen_sigs)}",
                    flush=True,
                )
            break

        segs = make_segments(G, path)
        sig = make_signature(segs)

        if sig in seen_sigs:
            if debug:
                dup_count_by_sig[sig] = dup_count_by_sig.get(sig, 0) + 1
                dup_no = dup_count_by_sig[sig]
                print(f"[DBG-K-DUP] idx={idx} sig={sig} dup#{dup_no}", flush=True)

                base_path = first_path_by_sig.get(sig)
                if base_path is not None:
                    _debug_path_nodes(G, base_path, prefix="  base: ", verbose=True)
                _debug_path_nodes(G, path, prefix="  dup : ", verbose=True)
                print("  ----", flush=True)
            continue

        # ここで「初めての sig」
        seen_sigs.add(sig)
        first_path_by_sig[sig] = path

        met = summarize(G, path)

        if debug:
            line_chain = " -> ".join(
                (s.get("title") or s.get("name") or "???")
                if s.get("kind") in ("bus", "rail", "line")
                else "walk"
                for s in segs
            )
            print(
                f"[DBG-K] sig={sig} total={met['total']:.1f} "
                f"walk_max={met['walk_max_m']:.1f}m walk_total={met['walk_total_m']:.1f}m "
                f"boards={met['boards']} transfers={met['transfers']} lines={line_chain}",
                flush=True,
            )

        entry = {
            "path": path,
            "segments": segs,
            "metrics": met,
        }

        if met["walk_max_m"] <= max_walk_seg_m:
            candidates.append(entry)
            if len(candidates) >= k:
                break
        else:
            backup.append(entry)

    if not candidates and backup:
        backup_sorted = sorted(backup, key=lambda e: e["metrics"]["total"])
        candidates = backup_sorted[:k]

    return candidates


def bus_cluster_key(phys_id: str) -> str | None:
    # 例: "odpt.BusstopPole:Toei.Oshiage.276.5" -> "odpt.BusstopPole:Toei.Oshiage.276"
    if not phys_id.startswith("odpt.BusstopPole:"):
        return None
    parts = phys_id.split(".")
    if len(parts) < 5:
        return None
    return ".".join(parts[:4])  # 末尾の枝番号を落とす


def compress_bus_poles_into_hubs(G: nx.DiGraph, *, debug=False):
    # 1) クラスタリング
    clusters = defaultdict(list)  # key -> [phys_node]
    for n in G.nodes:
        if not (isinstance(n, tuple) and n[0] == "phys"):
            continue
        nid = G.nodes[n].get("sameAs")  # あなたのコードに合わせて sameAs を使用
        key = bus_cluster_key(nid) if nid else None
        if key:
            clusters[key].append(n)

    for key, phys_nodes in clusters.items():
        if len(phys_nodes) <= 1:
            continue  # 圧縮不要

        # 2) hub ノードを作成
        hub_id = f"hub:bus:{key}"
        hub = ("phys", hub_id)
        if hub not in G:
            # 代表座標（重心）
            lats = []
            lons = []
            for p in phys_nodes:
                lat = G.nodes[p].get("lat")
                lon = G.nodes[p].get("lon")
                if lat is not None and lon is not None:
                    lats.append(lat)
                    lons.append(lon)
            lat = sum(lats)/len(lats) if lats else None
            lon = sum(lons)/len(lons) if lons else None
            # 代表名（最初のノードの名前）
            rep_name = G.nodes[phys_nodes[0]].get("name", "?")
            G.add_node(hub, name=f"{rep_name}(バス停)",
                       lat=lat, lon=lon, kind="phys", kind_detail="bus_hub")

        # 3) 旧エッジ → hub に付け替え（入出力とも）
        #   board/alight/xfer/walk を丸ごと移設。重複は min 重みで1本化。
        def add_or_relax(u, v, data):
            w = float(data.get("base_w", data.get("w", 0.0)))
            if G.has_edge(u, v):
                w0 = float(G[u][v].get("base_w", G[u][v].get("w", 0.0)))
                if w < w0:  # より短い方を残す
                    G[u][v].update(data)
                    G[u][v]["base_w"] = w
            else:
                G.add_edge(u, v, **data)

        # OUT edges: p -> x  を hub -> x へ
        for p in phys_nodes:
            for _, x, data in list(G.out_edges(p, data=True)):
                data2 = dict(data)
                add_or_relax(hub, x, data2)

        # IN edges: x -> p  を x -> hub へ
        for p in phys_nodes:
            for x, _, data in list(G.in_edges(p, data=True)):
                data2 = dict(data)
                add_or_relax(x, hub, data2)

        # 4) クラスタ内の phys は削除（walkの内輪エッジごと消える）
        for p in phys_nodes:
            G.remove_node(p)

        if debug:
            print(f"[BUS-HUB] {key}  ->  {hub}  (nodes={len(phys_nodes)})", flush=True)
