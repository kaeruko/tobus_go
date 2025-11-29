#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import sys

# データパス（適宜書き換えてください）
POLE_FILE = "data/odpt_BusstopPole.json"
TIME_FILE = "data/odpt_BusstopPoleTimetable.json"

TARGET_STOP_NAME = "神保町二丁目"
TARGET_ROUTE_PART = "To02Otsu"  # 都02乙のIDの一部

def load_json(path):
    print(f"[INFO] Loading {path} ...")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    poles = load_json(POLE_FILE)
    timetables = load_json(TIME_FILE)
    
    # 1. 時刻表データをIDで引けるようにインデックス化
    # key: PoleID, value: [Entry, Entry...]
    timetable_map = {}
    for entry in timetables:
        pid = entry.get("odpt:busstopPole")
        if pid not in timetable_map:
            timetable_map[pid] = []
        timetable_map[pid].append(entry)

    print("-" * 60)
    print(f"診断開始: '{TARGET_STOP_NAME}' の周辺データを探します")
    print("-" * 60)

    found_poles = []

    # 2. 名前でポールを検索
    for p in poles:
        title = p.get("dc:title", "")
        if TARGET_STOP_NAME in title:
            pid = p.get("owl:sameAs") or p.get("@id")
            found_poles.append((title, pid))

    if not found_poles:
        print("[ERROR] そもそもポールが見つかりません。名前が間違っているか、BusstopPole.jsonが空です。")
        return

    # 3. 各ポールの時刻表状況を表示
    for title, pid in found_poles:
        print(f"\n📍 ポール発見: {title}")
        print(f"   ID: {pid}")
        
        # このIDの時刻表はあるか？
        entries = timetable_map.get(pid)
        
        if not entries:
            print("   ❌ 時刻表データなし (このポールIDはTimetableファイルに存在しません)")
        else:
            print(f"   ✅ 時刻表データあり ({len(entries)}件)")
            
            # 都02乙が含まれているか確認
            matched_route = False
            for entry in entries:
                route_id = entry.get("odpt:busroute")
                direction = entry.get("odpt:busDirection", "???")
                dest = entry.get("odpt:destinationSign", "???")
                
                # ターゲットの路線か？
                mark = " "
                if TARGET_ROUTE_PART in route_id:
                    mark = "🎯"
                    matched_route = True
                
                print(f"      {mark} Route: {route_id:<35} 行先: {dest} (Dir: {direction})")
            
            if not matched_route:
                print("      ⚠️ データはあるが、'都02乙' は含まれていません（逆方向のバス停かも？）")

if __name__ == "__main__":
    main()