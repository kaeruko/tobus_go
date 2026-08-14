#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# fetch_robust.py
import json
import requests
import time
import os
import argparse

API_URL = "https://api-public.odpt.org/api/v4"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--out", default="data")
    args = parser.parse_args()
    
    # 1. まず路線一覧（BusroutePattern）をロード
    # まだ持っていない場合はここだけ単発で落とす必要がありますが、
    # さっきの実行で data/odpt_BusroutePattern.json は取れているはずです。
    pattern_path = os.path.join(args.out, "odpt_BusroutePattern.json")
    if not os.path.exists(pattern_path):
        print(f"[ERROR] {pattern_path} not found. Run fetch_all_toei_data.py first to get patterns.")
        return

    with open(pattern_path, "r", encoding="utf-8") as f:
        patterns = json.load(f)

    # ユニークな「バス路線ID (odpt:busroute)」を抽出
    # Patternは「上23 往路」「上23 復路」などで分かれていますが、
    # 時刻表取得時は路線単位でまとめて取ったほうが効率的です。
    bus_routes = set()
    for p in patterns:
        if "odpt:busroute" in p:
            bus_routes.add(p["odpt:busroute"])
    
    print(f"Found {len(bus_routes)} unique bus routes. Starting robust download...")

    # 2. 路線ごとに時刻表をダウンロードしてマージ
    all_timetables = []
    
    for i, route_id in enumerate(bus_routes, 1):
        print(f"[{i}/{len(bus_routes)}] Fetching timetable for {route_id} ... ", end="", flush=True)
        
        try:
            params = {
                "acl:consumerKey": args.token,
                "odpt:operator": "odpt.Operator:Toei",
                "odpt:busroute": route_id  # ★ここがミソ！路線を絞って取る
            }
            res = requests.get(f"{API_URL}/odpt:BusstopPoleTimetable", params=params)
            res.raise_for_status()
            data = res.json()
            
            all_timetables.extend(data)
            print(f"OK ({len(data)} records)")
            
            # API制限に引っかからないよう少し待つ
            time.sleep(0.2)
            
        except Exception as e:
            print(f"ERROR: {e}")

    # 3. 保存
    out_path = os.path.join(args.out, "odpt_BusstopPoleTimetable.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_timetables, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCCESS] Saved total {len(all_timetables)} timetables to {out_path}")
    
    # 鉄道時刻表は数が少ないので、普通に operator指定で取れるはず（まだ1000件超えてないはず）
    # もし鉄道も1000件で切れるなら同様のロジックが必要ですが、Toeiの鉄道はそんなに多くないので多分大丈夫。
    # 必要ならここにも鉄道版ループを追加します。

if __name__ == "__main__":
    main()
