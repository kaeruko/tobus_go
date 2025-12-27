import json
import os
import sys
import pickle
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import initialize_data
from toei_engine import build_graph, TimetableManager, SpatialIndex
from app.runtime import _paths

OUTPUT_FILE = "api/data/app_data.pkl"

def ensure_required_files(data_dir):
    required = [
        "odpt_BusstopPole.json",
        "odpt_BusroutePattern.json",
        "odpt_Station.json",
        "odpt_Railway.json",
        "odpt_BusstopPoleTimetable.json",
        "odpt_TrainTimetable.json",
    ]
    missing = [f for f in required if not os.path.exists(os.path.join(data_dir, f))]
    if missing:
        raise RuntimeError(f"Missing required files: {missing}")

def validate_train_weekend(data_dir):
    path = os.path.join(data_dir, "odpt_TrainTimetable.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    sat = 0
    hol = 0
    sat_hol = 0
    for t in data:
        c = t.get("odpt:calendar", "")
        if c == "odpt.Calendar:Saturday":
            sat += 1
        elif c == "odpt.Calendar:Holiday":
            hol += 1
        elif c == "odpt.Calendar:SaturdayHoliday":
            sat_hol += 1

    print(f"[INFO] TrainTimetable weekend counts saturday={sat} holiday={hol} combined={sat_hol}")
    
    has_separate = (sat > 0 and hol > 0)
    has_combined = (sat_hol > 0)

    if not (has_separate or has_combined):
        raise RuntimeError("Weekend train timetable is missing. Refuse to build app_data.pkl")

def main():
    print("=== Pre-building Assets for Lambda ===")
    start_time = time.time()
    
    data_dir = "api/data"
    os.environ["DATA_DIR"] = data_dir

    # 1. データの完全性チェック & 自動取得
    need_fetch = False
    try:
        ensure_required_files(data_dir)
        # 既存ファイルがあっても、中身が壊れてる（土日なし）なら再取得を試みる方が親切なのでチェックに含める
        validate_train_weekend(data_dir)
    except Exception as e:
        print(f"[WARN] Data check failed: {e}")
        need_fetch = True

    if need_fetch:
        print("Fetching missing or incomplete data...")
        initialize_data.main()

    # 最終確認 (ダメなら止める)
    ensure_required_files(data_dir)
    validate_train_weekend(data_dir)

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
