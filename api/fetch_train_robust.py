#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# fetch_train_robust.py
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
    
    # 1. 鉄道路線一覧（Railway）をロード
    railway_path = os.path.join(args.out, "odpt_Railway.json")
    if not os.path.exists(railway_path):
        print(f"[ERROR] {railway_path} not found. Run fetch_all_toei_data.py first.")
        return

    with open(railway_path, "r", encoding="utf-8") as f:
        railways = json.load(f)

    # 路線IDを抽出 (例: odpt.Railway:Toei.Asakusa)
    target_railways = []
    for r in railways:
        if "odpt:railway" in r: 
             target_railways.append(r["odpt:railway"])
        elif "owl:sameAs" in r:
             target_railways.append(r["owl:sameAs"])

    print(f"Found {len(target_railways)} railways. Starting download with calendar split...")

    # 2. 路線ごとにTrainTimetableをダウンロード
    all_timetables = []
    # Note: Asakusa line and others often use 'SaturdayHoliday' combined
    calendars = ["odpt.Calendar:Weekday", "odpt.Calendar:Saturday", "odpt.Calendar:Holiday", "odpt.Calendar:SaturdayHoliday"]
    
    for i, rail_id in enumerate(target_railways, 1):
        print(f"[{i}/{len(target_railways)}] Railway: {rail_id}")
        
        for cal in calendars:
            print(f"    - Fetching {cal} ... ", end="", flush=True)
            try:
                params = {
                    "acl:consumerKey": args.token,
                    "odpt:operator": "odpt.Operator:Toei",
                    "odpt:railway": rail_id,
                    "odpt:calendar": cal
                }
                res = requests.get(f"{API_URL}/odpt:TrainTimetable", params=params)
                res.raise_for_status()
                data = res.json()
                
                all_timetables.extend(data)
                print(f"OK ({len(data)} records)")
                
                # Check for pagination or truncation
                if len(data) >= 1000:
                    print(f"      [WARN] Hit 1000 limit for {rail_id} / {cal}. Data might be truncated.")
                
                time.sleep(0.1)
            except Exception as e:
                print(f"ERROR: {e}")

    # 3. 保存
    out_path = os.path.join(args.out, "odpt_TrainTimetable.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_timetables, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCCESS] Saved total {len(all_timetables)} train timetables to {out_path}")

if __name__ == "__main__":
    main()
