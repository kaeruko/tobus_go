#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# fetch_robust.py
import json
import requests
import time
import os
import argparse

API_URL = "https://api.odpt.org/api/v4"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--out", default="data")
    args = parser.parse_args()

    # 1. まず路線一覧（BusroutePattern）をロード
    pattern_path = os.path.join(args.out, "odpt_BusroutePattern.json")
    if not os.path.exists(pattern_path):
        raise RuntimeError(
            f"{pattern_path} not found. Run initialize_data.py first to get patterns."
        )

    with open(pattern_path, "r", encoding="utf-8") as f:
        patterns = json.load(f)

    # ユニークな「バス路線ID (odpt:busroute)」を抽出
    bus_routes = set()
    for p in patterns:
        if "odpt:busroute" in p:
            bus_routes.add(p["odpt:busroute"])

    if not bus_routes:
        raise RuntimeError("No bus routes were found in odpt_BusroutePattern.json")

    print(f"Found {len(bus_routes)} unique bus routes. Starting robust download...")

    # 2. 路線ごとに時刻表をダウンロードしてマージ
    all_timetables = []

    for i, route_id in enumerate(bus_routes, 1):
        print(
            f"[{i}/{len(bus_routes)}] Fetching timetable for {route_id} ... ",
            end="",
            flush=True,
        )

        params = {
            "acl:consumerKey": args.token,
            "odpt:operator": "odpt.Operator:Toei",
            "odpt:busroute": route_id,
        }
        res = requests.get(
            f"{API_URL}/odpt:BusstopPoleTimetable",
            params=params,
            timeout=30,
        )
        res.raise_for_status()
        data = res.json()

        all_timetables.extend(data)
        print(f"OK ({len(data)} records)")

        # API制限に引っかからないよう少し待つ
        time.sleep(0.2)

    if not all_timetables:
        raise RuntimeError("ODPT returned zero bus timetables")

    # 3. 保存
    out_path = os.path.join(args.out, "odpt_BusstopPoleTimetable.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_timetables, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCCESS] Saved total {len(all_timetables)} timetables to {out_path}")


if __name__ == "__main__":
    main()
