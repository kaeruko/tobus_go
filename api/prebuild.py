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

from toei_engine import build_graph, TimetableManager, SpatialIndex
from app.runtime import _paths
from gtfs_loader import GtfsRepository
from tokyo_static_compatibility import (
    validate_release_sources,
    validate_toei_bus_graph_gtfs,
)
from tokyo_metro_gtfs import add_tokyo_metro_to_graph


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

    api_dir = os.path.dirname(os.path.realpath(__file__))
    data_dir = os.getenv("DATA_DIR", os.path.join(api_dir, "data"))
    output_file = os.getenv(
        "PREBUILT_OUTPUT", os.path.join(data_dir, "app_data.pkl")
    )
    os.environ["DATA_DIR"] = data_dir

    release_manifest_path = os.getenv(
        "TOEI_BUS_RELEASE_MANIFEST",
        os.path.join(
            api_dir,
            "config",
            "toei_bus_static_release.json",
        ),
    )

    # Release inputs are acquired explicitly by the reviewed sync procedures.
    # A build must never replace missing/mismatched inputs behind the operator's
    # back and accidentally combine a new source with an old artifact.
    ensure_required_files(data_dir)
    validate_train_weekend(data_dir)
    release_inputs = validate_release_sources(data_dir, release_manifest_path)

    # 2. パス設定の取得
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
    metro_enabled = os.getenv("ENABLE_TOKYO_METRO_STATIC", "0") == "1"
    if metro_enabled:
        metro_gtfs_dir = os.getenv(
            "TOKYO_METRO_GTFS_DIR", os.path.join(data_dir, "TokyoMetro-Train-GTFS")
        )
        metro_stations = os.getenv(
            "TOKYO_METRO_STATIONS", os.path.join(data_dir, "odpt_Station_TokyoMetro.json")
        )
        metro_railways = os.getenv(
            "TOKYO_METRO_RAILWAYS", os.path.join(data_dir, "odpt_Railway_TokyoMetro.json")
        )
        metro_reviewed_transfers = os.getenv(
            "TOKYO_METRO_REVIEWED_TRANSFERS",
            os.path.join(os.path.dirname(__file__), "config", "tokyo_metro_reviewed_transfers.json"),
        )
        for required in (
            metro_gtfs_dir, metro_stations, metro_railways, metro_reviewed_transfers,
        ):
            if not os.path.exists(required):
                raise RuntimeError(f"Tokyo Metro static input is missing: {required}")
        info = add_tokyo_metro_to_graph(
            g,
            tm,
            gtfs_dir=metro_gtfs_dir,
            stations_path=metro_stations,
            railways_path=metro_railways,
            counterpart_stations_path=p["STATIONS"],
            reviewed_transfers_path=metro_reviewed_transfers,
            walk_radius=p["WALK_RAD"],
        )
        print(
            "Tokyo Metro static GTFS loaded: "
            f"version={info.version} period={info.start_date}..{info.end_date}"
        )
    tm.build_name_index(g)

    toei_gtfs_dir = os.getenv(
        "TOEI_GTFS_DIR", os.path.join(p["DATA_DIR"], "ToeiBus-GTFS")
    )
    toei_gtfs = GtfsRepository("toei_bus").load_data(toei_gtfs_dir)
    compatibility = validate_toei_bus_graph_gtfs(g, tm, toei_gtfs)
    print(
        "Toei Bus ODPT/GTFS topology validated: "
        f"adjacencies={compatibility.graph_adjacencies}"
    )

    # 3. 成果物を辞書にまとめてPickle化
    print("Building Spatial Index...")
    si = SpatialIndex(g)

    print(f"Serializing to {output_file} ...")
    
    export_data = {
        "G": g,
        "TM": tm,
        "SI": si,
        "WALK_RAD": p["WALK_RAD"],
        "TOEI_BUS_RELEASE_INPUTS": release_inputs,
        "TOEI_BUS_GTFS_COMPATIBILITY": compatibility.to_dict(),
    }

    os.makedirs(os.path.dirname(os.path.realpath(output_file)), exist_ok=True)
    with open(output_file, "wb") as f:
        pickle.dump(export_data, f, protocol=pickle.HIGHEST_PROTOCOL)

    elapsed = time.time() - start_time
    print(f"=== Done in {elapsed:.2f} seconds ===")
    print(f"File size: {os.path.getsize(output_file) / (1024*1024):.2f} MB")

if __name__ == "__main__":
    main()
