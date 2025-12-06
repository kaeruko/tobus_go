import pandas as pd

# ファイル読み込み
trips = pd.read_csv('data/ToeiBus-GTFS/trips.txt', dtype=str)
routes = pd.read_csv('data/ToeiBus-GTFS/routes.txt', dtype=str)

# 必要な列だけ抽出して重複排除
directions = trips[['route_id', 'direction_id', 'trip_headsign']].drop_duplicates()

# 路線名もくっつける
merged = directions.merge(routes[['route_id', 'route_short_name']], on='route_id')

# 並び替えて表示
merged = merged.sort_values(['route_short_name', 'direction_id'])

print("--- 行き先ID対応表 ---")
print(f"{'系統':<6} | {'ID':<2} | {'行き先'}")
print("-" * 30)

for _, row in merged.iterrows():
    print(f"{row['route_short_name']:<6} | {row['direction_id']:<2} | {row['trip_headsign']}")