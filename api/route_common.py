# route_common.py
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
    """
    G 上で a_phys -> b_phys の最短経路を列挙しつつ、

      - make_segments: path -> セグメント配列（bus/rail/walk など）
      - make_signature: セグメント配列 -> ライン構成シグネチャ
      - summarize: path -> total / transfers / walk_max_m などのメトリクス

    を使って、
      * ライン構成シグネチャごとに 1 本だけ採用
      * 徒歩 1 セグメントが max_walk_seg_m 以内のものを優先
    して最大 k 本返す。

    返り値: [{ "path": path, "segments": segs, "metrics": met }, ...]
    """
    candidates: List[Dict[str, Any]] = []
    backup: List[Dict[str, Any]] = []
    seen_sigs: set[Hashable] = set()

    gen = shortest_simple_paths(G, a_phys, b_phys, weight=weight_func)

    for idx, path in enumerate(gen):
        if idx >= max_paths:
            break

        segs = make_segments(G, path)
        sig = make_signature(segs)

        # 同じライン構成（例: 上23→浅草線→新宿線→三田線）は 1 つだけ
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)

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
