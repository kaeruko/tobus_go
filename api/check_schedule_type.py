import pandas as pd
import os

# 設定
GTFS_DIR = 'data/ToeiBus-GTFS'
ROUTE_ID = '070'  # 上23系統 (上野松坂屋前〜平井)

def main():
    print(f"Route {ROUTE_ID} (上23) の12時台のダイヤを全パターン比較します...")
    
    # 1. データの読み込み
    try:
        trips = pd.read_csv(f'{GTFS_DIR}/trips.txt', dtype=str)
        stop_times = pd.read_csv(f'{GTFS_DIR}/stop_times.txt', dtype=str)
    except FileNotFoundError:
        print("エラー: GTFSデータが見つかりません。apiディレクトリで実行してください。")
        return

    # 2. 上23系統の便を抽出
    route_trips = trips[trips['route_id'] == ROUTE_ID]
    
    # 3. service_id ごとに便IDを分類
    # 予想されるパターン: ...170(平日), ...160(土曜), ...100(日祝)
    service_groups = {}
    trip_to_service = {}
    
    for _, row in route_trips.iterrows():
        sid = row['service_id']
        tid = row['trip_id']
        
        # 簡易分類 (末尾で判断)
        label = "不明"
        if sid.endswith('170'): label = "平日 (Weekday)"
        elif sid.endswith('160'): label = "土曜 (Saturday)"
        elif sid.endswith('100'): label = "日祝 (Holiday)"
        
        if label not in service_groups: service_groups[label] = []
        service_groups[label].append(tid)
        trip_to_service[tid] = label

    # 4. 12時台の「始発」時刻を集計
    # stop_sequence=1 の departure_time を取得
    print("\n--- 12時台の始発時刻一覧 ---")
    
    for label, tids in service_groups.items():
        # このグループの便の stop_times を取得
        mask = (stop_times['trip_id'].isin(tids)) & \
               (stop_times['stop_sequence'] == '1') & \
               (stop_times['departure_time'].str.startswith('12:'))
        
        times = stop_times[mask]['departure_time'].sort_values().tolist()
        
        # 分だけ抽出して表示
        minutes = [t.split(':')[1] for t in times]
        print(f"\n【{label}】の12時台:")
        if minutes:
            print("  " + ", ".join(minutes))
            # 14, 34, 54 が含まれているかチェック
            if '14' in minutes and '34' in minutes:
                print("  🚨 犯人はこのダイヤです！アプリが誤ってこれを表示しています。")
        else:
            print("  (運行なし)")

if __name__ == "__main__":
    main()