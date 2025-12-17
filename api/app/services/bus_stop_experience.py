import os
import json
import time
import random
import hashlib
from pathlib import Path
from typing import List, Dict, Any

import requests

RADIUS_M = int(os.getenv("ROUTE_EXP_RADIUS_M", "400"))
CACHE_TTL_SEC = int(os.getenv("ROUTE_EXP_CACHE_TTL_SEC", str(7 * 24 * 60 * 60)))

CACHE_DIR = Path(os.getenv("CACHE_DIR", "/tmp/cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]

def _cache_key(lat: float, lon: float, radius_m: int) -> str:
    lat_q = round(lat, 3)
    lon_q = round(lon, 3)
    raw = f"{lat_q}:{lon_q}:{radius_m}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()

def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"overpass_{key}.json"

def _post_overpass(url: str, query: str) -> requests.Response:
    return requests.post(
        url,
        data={"data": query},
        timeout=70,
        headers={"User-Agent": "toei-go-prototype/0.1"},
    )

def fetch_pois_cached(lat: float, lon: float) -> List[Dict[str, Any]]:
    key = _cache_key(lat, lon, RADIUS_M)
    p = _cache_path(key)

    if p.exists():
        st = p.stat()
        if time.time() - st.st_mtime < CACHE_TTL_SEC:
            return json.loads(p.read_text(encoding="utf-8"))

    query = f"""
    [out:json][timeout:50];
    (
      nwr(around:{RADIUS_M},{lat},{lon})["leisure"="park"];
      nwr(around:{RADIUS_M},{lat},{lon})["waterway"~"river|stream|canal|drain"];
      nwr(around:{RADIUS_M},{lat},{lon})["natural"="water"];
      nwr(around:{RADIUS_M},{lat},{lon})["amenity"="place_of_worship"];
      nwr(around:{RADIUS_M},{lat},{lon})["shop"];
    );
    out tags;
    """

    last_err = None

    for endpoint in OVERPASS_ENDPOINTS:
        for attempt in range(5):
            try:
                res = _post_overpass(endpoint, query)

                if res.status_code in [429, 500, 502, 503, 504]:
                    sleep_sec = (2 ** attempt) + random.random()
                    time.sleep(sleep_sec)
                    continue

                res.raise_for_status()
                elements = res.json().get("elements", [])
                p.write_text(json.dumps(elements, ensure_ascii=False), encoding="utf-8")
                return elements

            except Exception as e:
                last_err = e
                sleep_sec = (2 ** attempt) + random.random()
                time.sleep(sleep_sec)

    print(f"overpass failed lat={lat} lon={lon} err={last_err}")
    return []

def score_pois(elements: List[Dict[str, Any]]) -> Dict[str, int]:
    score = {"park": 0, "water": 0, "worship": 0, "shop": 0}

    for e in elements:
        tags = e.get("tags", {})
        if tags.get("leisure") == "park":
            score["park"] += 1
        if tags.get("waterway") or tags.get("natural") == "water":
            score["water"] += 1
        if tags.get("amenity") == "place_of_worship":
            score["worship"] += 1
        if "shop" in tags:
            score["shop"] += 1

    return score

def score_to_tags(score: Dict[str, int]) -> List[str]:
    tags: List[str] = []

    if score["water"] >= 1:
        tags.append("川沿い")
    if score["park"] >= 1:
        tags.append("公園")
    if score["shop"] >= 8:
        tags.append("商店街")
    if score["worship"] >= 2:
        tags.append("歴史")

    return tags[:3]

def tags_to_description(tags: List[str]) -> str:
    if "川沿い" in tags and "公園" in tags:
        return "川沿いをのんびり散歩できるエリア"
    if "商店街" in tags:
        return "昔ながらの商店街をぶらぶら楽しめる"
    if "歴史" in tags:
        return "寺社が点在する落ち着いた下町エリア"
    if "公園" in tags:
        return "近所で気軽にひと休みできるエリア"
    return "静かな住宅エリアを感じられる"

def build_stop_card(stop: Dict[str, Any]) -> Dict[str, Any]:
    elements = fetch_pois_cached(stop["lat"], stop["lon"])
    score = score_pois(elements)
    tags = score_to_tags(score)
    desc = tags_to_description(tags)

    return {
        "stop_id": stop["stop_id"],
        "stop_name": stop.get("stop_name", ""),
        "lat": stop["lat"],
        "lon": stop["lon"],
        "tags": tags,
        "description": desc,
        "score": score,
    }

def group_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}

    for c in cards:
        key = "|".join(c["tags"]) + "||" + c["description"]
        buckets.setdefault(key, []).append(c)

    groups: List[Dict[str, Any]] = []
    for _, items in buckets.items():
        def strength(x: Dict[str, Any]) -> int:
            s = x["score"]
            return s["water"] + s["park"] + s["worship"] + s["shop"]

        rep = sorted(items, key=strength, reverse=True)[0]
        groups.append(
            {
                "tags": rep["tags"],
                "description": rep["description"],
                "representative_stop": {
                    "stop_id": rep["stop_id"],
                    "stop_name": rep["stop_name"],
                    "lat": rep["lat"],
                    "lon": rep["lon"],
                },
                "stop_count": len(items),
                "stops": [
                    {"stop_id": i["stop_id"], "stop_name": i.get("stop_name", "")}
                    for i in items
                ],
            }
        )

    groups.sort(key=lambda g: g["stop_count"], reverse=True)
    return groups

def build_route_experiences(stops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cards = [build_stop_card(s) for s in stops]
    return group_cards(cards)
