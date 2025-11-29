#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# fetch_all_toei_data.py

import os
import sys
import json
import requests
import argparse
import time

# ODPT APIのエンドポイント
API_URL = "https://api.odpt.org/api/v4"

# 取得するデータタイプ一覧
TARGETS = [
    # マスターデータ系
    "odpt:BusstopPole",      # バス停
    "odpt:BusroutePattern",  # バス路線（系統）
    "odpt:Station",          # 駅
    "odpt:Railway",          # 鉄道路線
    
    # 時刻表系（ここが重いが重要）
    "odpt:BusstopPoleTimetable", # バス時刻表
    "odpt:TrainTimetable",       # 列車時刻表
    "odpt:StationTimetable",     # 駅時刻表（念のため）
]

def fetch_data(data_type, consumer_key, output_dir):
    print(f"[{data_type}] Downloading...")
    
    # 都営 (Toei) のデータに絞り込んで全件取得
    # ODPT APIはパラメータなしだと件数制限がかかることがあるが、
    # operatorを指定すればその事業者の全データが取れることが多い
    params = {
        "acl:consumerKey": consumer_key,
        "odpt:operator": "odpt.Operator:Toei" 
    }
    
    try:
        url = f"{API_URL}/{data_type}"
        res = requests.get(url, params=params, stream=True)
        res.raise_for_status()
        
        # データ量が多いのでチャンクで読んでJSONデコード
        data = res.json()
        
        # 件数確認
        count = len(data)
        print(f"[{data_type}] Success. Got {count} records.")
        
        if count == 0:
            print(f"  [WARNING] 0 records found. Check operator filter or API key.")
        
        # 保存
        filename = f"{data_type.replace('odpt:', 'odpt_')}.json"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"  -> Saved to {filepath}")
        
    except Exception as e:
        print(f"[{data_type}] FAILED: {e}")

def main():
    parser = argparse.ArgumentParser(description="Fetch all Toei data from ODPT API")
    parser.add_argument("--token", required=True, help="Your ODPT API Consumer Key (Access Token)")
    parser.add_argument("--out", default="data", help="Output directory")
    args = parser.parse_args()

    if not os.path.exists(args.out):
        os.makedirs(args.out)

    print(f"Start fetching Toei data to '{args.out}/' ...")
    print("This may take a while depending on your network.")
    
    for t in TARGETS:
        fetch_data(t, args.token, args.out)
        time.sleep(1) # サーバーに優しく

    print("\nAll done. Now your data is ready for strict search!")

if __name__ == "__main__":
    main()