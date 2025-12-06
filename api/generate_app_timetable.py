import csv
import json
import os
from collections import defaultdict

# GTFSデータのパス
GTFS_DIR = "data/ToeiBus-GTFS"
OUTPUT_FILE = "data/app_timetable.json"

def load_csv(filename):
    path = os.path.join(GTFS_DIR, filename)
    if not os.path.exists(path):
        print(f"Warning: {filename} not found.")
        return []
    with open(path, 'r', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def main():
    print("GTFSデータを読み込んでいます...")

    # 1. Service ID の日付マッピングを作成 (calendar.txt + calendar_dates.txt)
    # service_id -> { 'days': [0,1,1,1,1,0,0], 'start': ..., 'end': ..., 'added': {date}, 'removed': {date} }
    service_dict = {}
    
    # calendar.txt (基本パターン)
    calendar = load_csv("calendar.txt")
    for row in calendar:
        s_id = row['service_id']
        flags = [
            row['monday'] == '1', row['tuesday'] == '1', row['wednesday'] == '1',
            row['thursday'] == '1', row['friday'] == '1', row['saturday'] == '1', 
            row['sunday'] == '1'
        ]
        service_dict[s_id] = {
            'flags': flags,
            'start': int(row['start_date']),
            'end': int(row['end_date']),
            'added': set(),
            'removed': set()
        }

    # calendar_dates.txt (例外パターン: 1=Add, 2=Remove)
    calendar_dates = load_csv("calendar_dates.txt")
    for row in calendar_dates:
        s_id = row['service_id']
        date_val = int(row['date'])
        ex_type = row['exception_type']
        
        # calendar.txtになくてもcalendar_dates.txtだけにある場合を考慮
        if s_id not in service_dict:
            service_dict[s_id] = {'flags': [False]*7, 'start': 0, 'end': 99999999, 'added': set(), 'removed': set()}
            
        if ex_type == '1':
            service_dict[s_id]['added'].add(date_val)
        elif ex_type == '2':
            service_dict[s_id]['removed'].add(date_val)

    # service_id をアプリ用の区分 (Weekday, Saturday, Holiday) に簡易分類
    # ※ 本来は日付ごとに展開すべきですが、アプリの既存ロジックに合わせて簡易化します。
    #    ただし、calendar_datesだけで運行する特殊ダイヤも考慮します。
    service_to_daytype = {}
    for s_id, data in service_dict.items():
        # 土曜フラグがあり、かつ日曜フラグがない -> Saturday
        if data['flags'][5] and not data['flags'][6]:
            service_to_daytype[s_id] = "Saturday"
        # 日曜フラグがある -> Holiday
        elif data['flags'][6]:
            service_to_daytype[s_id] = "Holiday"
        # 平日 (月〜金)
        elif any(data['flags'][0:5]):
            service_to_daytype[s_id] = "Weekday"
        # フラグはないが例外追加がある場合 (臨時ダイヤなど) -> Holiday扱いにしておく
        elif data['added']:
            service_to_daytype[s_id] = "Holiday"
        else:
            service_to_daytype[s_id] = "Holiday"

    # 2. 便情報の読み込み
    trips = load_csv("trips.txt")
    trip_info = {}
    for row in trips:
        s_id = row['service_id']
        if s_id in service_to_daytype:
            trip_info[row['trip_id']] = {
                'route_id': row['route_id'],
                'direction_id': row.get('direction_id', '0'), # 行き先ID (重要)
                'day_type': service_to_daytype[s_id],
                'headsign': row['trip_headsign']
            }

    # 3. 通過時刻の集計
    # 構造: data[route_id][direction_id][stop_id][day_type] = [times...]
    # direction_id の階層を追加しました
    timetable_data = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))
    stop_times = load_csv("stop_times.txt")

    print("時刻表を集計中...")
    for row in stop_times:
        trip_id = row['trip_id']
        dep_time = row['departure_time']
        stop_id = row['stop_id']

        if trip_id in trip_info:
            info = trip_info[trip_id]
            route_id = info['route_id']
            direction = info['direction_id']
            day_type = info['day_type']
            
            time_str = dep_time[:5] # HH:mm
            timetable_data[route_id][direction][stop_id][day_type].append(time_str)

    # 4. JSON書き出し
    final_json = {}
    
    for route_id, dirs in timetable_data.items():
        final_json[route_id] = {}
        for direction, stops in dirs.items():
            # アプリ側でパースしやすいよう、route_idの下に direction をキーとして埋め込むか、
            # あるいは stop_id キーの中に direction を含めるか。
            # ここでは既存アプリの改修を最小限にするため、
            # route_id -> stop_id -> direction_id -> day_type という構造にします
            for stop_id, days in stops.items():
                if stop_id not in final_json[route_id]:
                    final_json[route_id][stop_id] = {}
                
                # direction_id をキーに追加
                final_json[route_id][stop_id][direction] = {}
                
                for day_type, times in days.items():
                    sorted_times = sorted(list(set(times)))
                    final_json[route_id][stop_id][direction][day_type] = sorted_times

    print(f"JSONを出力します: {OUTPUT_FILE}")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_json, f, ensure_ascii=False, separators=(',', ':'))
    
    # --- 追加機能: 路線ごとの行き先リストを作成 (route_id -> direction_id -> headsign) ---
    print("行き先リスト(route_directions.json)を作成中...")
    
    direction_map = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    # trips.txt を再走査して、各方向で最も多い行き先名を採用する
    # (例: "上野行き" が100本、"車庫行き" が5本なら "上野行き" を代表名にする)
    for row in trips:
        rid = row['route_id']
        did = row.get('direction_id', '0')
        headsign = row['trip_headsign']
        direction_map[rid][did][headsign] += 1

    final_directions = {}
    for rid, dirs in direction_map.items():
        final_directions[rid] = {}
        for did, headsigns in dirs.items():
            # 出現回数が一番多い行き先名を採用
            most_common_headsign = max(headsigns.items(), key=lambda x: x[1])[0]
            final_directions[rid][did] = most_common_headsign

    # アプリ用のファイルとして保存
    DIR_OUTPUT = "data/route_directions.json"
    with open(DIR_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(final_directions, f, ensure_ascii=False, separators=(',', ':'))
    print(f"行き先リストを出力しました: {DIR_OUTPUT}")
    
    print("完了しました。")

if __name__ == "__main__":
    main()