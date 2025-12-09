#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# fetch_all_toei_data.py

import os
import json
import requests
import argparse

# ODPT API Endpoint
API_URL_BASE = "https://api.odpt.org/api/v4"

def fetch_data(endpoint_name, file_name, token, output_dir):
    url = f"{API_URL_BASE}/{endpoint_name}"
    params = {
        "acl:consumerKey": token,
        "odpt:operator": "odpt.Operator:Toei"
    }

    print(f"Fetching {endpoint_name}...")
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        
        data = response.json()
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        file_path = os.path.join(output_dir, file_name)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            
        print(f"[SUCCESS] {file_name} を保存しました。 ({len(data)} records)")
        
    except Exception as e:
        print(f"[ERROR] {endpoint_name} の取得に失敗: {e}")

def main():
    parser = argparse.ArgumentParser(description="Fetch Toei Railway and Bus data")
    parser.add_argument("--token", help="ODPT API Access Token", default=os.getenv("ODPT_API_TOKEN"))
    parser.add_argument("--out", default="data", help="Output directory")
    args = parser.parse_args()

    if not args.token:
        print("Error: Token is required. Set ODPT_API_TOKEN env var or use --token")
        return

    # 1. 鉄道情報 (odpt:Railway -> odpt_Railway.json)
    fetch_data(
        endpoint_name="odpt:Railway",
        file_name="odpt_Railway.json",
        token=args.token,
        output_dir=args.out
    )

    # 2. バスルートパターン (odpt:BusroutePattern -> odpt_BusroutePattern.json)
    fetch_data(
        endpoint_name="odpt:BusroutePattern",
        file_name="odpt_BusroutePattern.json",
        token=args.token,
        output_dir=args.out
    )

    # 3. 駅情報 (odpt:Station -> odpt_Station.json) - 追加で取っておくと安全
    fetch_data(
        endpoint_name="odpt:Station",
        file_name="odpt_Station.json",
        token=args.token,
        output_dir=args.out
    )

    # 4. バス停情報 (odpt:BusstopPole -> odpt_BusstopPole.json) - 追加で取っておくと安全
    fetch_data(
        endpoint_name="odpt:BusstopPole",
        file_name="odpt_BusstopPole.json",
        token=args.token,
        output_dir=args.out
    )

if __name__ == "__main__":
    main()