import os
import sys
import pickle
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 既存モジュールをインポート
import initialize_data
from toei_engine import build_graph, TimetableManager, SpatialIndex
from app.runtime import _paths  # パス設定を再利用

OUTPUT_FILE = "api/data/app_data.pkl"

def main():
    print("=== Pre-building Assets for Lambda ===")
    start_time = time.time()

    # 1. データのダウンロード (initialize_data.py のロジック)
    # 必要なら強制的にデータを取得させる
    if not os.path.exists("api/data/odpt_BusstopPole.json"):
        print("Data missing. Fetching...")
        initialize_data.main()

    # 2. パス設定の取得
    # 環境変数がセットされていない場合を考慮してデフォルトを使用
    os.environ["DATA_DIR"] = "api/data"
    p = _paths()

    print("Building Graph (NetworkX)...")
    g = build_graph(
        p["BUSSTOP"],
        p["BUSROUTE"],
        p["STATIONS"],
        p["RAILWAYS"],
        walk_radius=p["WALK_RAD"],
    )
    print(f"Graph built: {len(g.nodes)} nodes, {len(g.edges)} edges")

    print("Loading Timetables...")
    tm = TimetableManager()
    tm.load_bus_timetables(p["BUS_TBL"])
    tm.load_bus_route_patterns(p["BUSROUTE"])
    tm.load_train_timetables(p["TRAIN_TBL"])
    tm.build_name_index(g)

    # GTFS removed
    # gtfs_dir = os.path.join(p["DATA_DIR"], "ToeiBus-GTFS")
    # if os.path.exists(gtfs_dir):
    #     tm.load_gtfs_mappings(gtfs_dir)

    # 3. 成果物を辞書にまとめてPickle化
    print("Building Spatial Index...")
    si = SpatialIndex(g)

    print(f"Serializing to {OUTPUT_FILE} ...")
    
    export_data = {
        "G": g,
        "TM": tm,
        "SI": si,
        "WALK_RAD": p["WALK_RAD"]
    }

    with open(OUTPUT_FILE, "wb") as f:
        pickle.dump(export_data, f, protocol=pickle.HIGHEST_PROTOCOL)

    elapsed = time.time() - start_time
    print(f"=== Done in {elapsed:.2f} seconds ===")
    print(f"File size: {os.path.getsize(OUTPUT_FILE) / (1024*1024):.2f} MB")

if __name__ == "__main__":
    main()
