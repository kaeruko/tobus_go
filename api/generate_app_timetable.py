import csv
import json
import os
from collections import defaultdict

# GTFSデータのパス
GTFS_DIR = "data/ToeiBus-GTFS"
OUTPUT_FILE = "data/app_timetable.json"

def load_csv(filename):
    path = os.path.join(GTFS_DIR, filename)
    with open(path, 'r', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def main():
    print("GTFSデータを読み込んでいます...")
    
    # 1. カレンダー（曜日）情報の読み込み
    # service_id -> 'Weekday' | 'Saturday' | 'Holiday'
    calendar = load_csv("calendar.txt")
    service_map = {}
    for row in calendar:
        s_id = row['service_id']
        if row['monday'] == '1' and row['friday'] == '1':
            service_map[s_id] = "Weekday"
        elif row['saturday'] == '1':
            service_map[s_id] = "Saturday"
        elif row['sunday'] == '1':
            service_map[s_id] = "Holiday"
        else:
            # 臨時ダイヤなどは一旦Holiday扱いにするか無視する
            service_map[s_id] = "Holiday"

    # 2. 便情報の読み込み
    # trip_id -> {'route_id': ..., 'day_type': ...}
    trips = load_csv("trips.txt")
    trip_info = {}
    for row in trips:
        s_id = row['service_id']
        if s_id in service_map:
            trip_info[row['trip_id']] = {
                'route_id': row['route_id'],
                'day_type': service_map[s_id],
                'headsign': row['trip_headsign'] # 行き先表示用
            }

    # 3. 通過時刻の集計
    # 構造: data[route_id][stop_id][day_type] = ["06:30", "06:45", ...]
    stop_times = load_csv("stop_times.txt")
    
    # ネストした辞書を作成
    timetable_data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    print("時刻表を集計中...")
    for row in stop_times:
        trip_id = row['trip_id']
        dep_time = row['departure_time']  # "06:30:00" 形式
        stop_id = row['stop_id']

        if trip_id in trip_info:
            info = trip_info[trip_id]
            route_id = info['route_id']
            day_type = info['day_type']
            
            # 秒を削って "HH:mm" にする ("25:30:00" -> "25:30")
            time_str = dep_time[:5]
            
            timetable_data[route_id][stop_id][day_type].append(time_str)

    # 4. JSON書き出し用に整形＆ソート
    final_json = {}
    
    for route_id, stops in timetable_data.items():
        final_json[route_id] = {}
        for stop_id, days in stops.items():
            final_json[route_id][stop_id] = {}
            for day_type, times in days.items():
                # 時刻順にソート (文字列比較でOK "06:00" < "25:00")
                sorted_times = sorted(list(set(times)))
                final_json[route_id][stop_id][day_type] = sorted_times

    print(f"JSONを出力します: {OUTPUT_FILE}")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_json, f, ensure_ascii=False, separators=(',', ':'))
    print("完了しました。")

if __name__ == "__main__":
    main()