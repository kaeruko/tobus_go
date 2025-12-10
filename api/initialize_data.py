import os
import sys
import json
import requests
import zipfile
import io
import time
from dotenv import load_dotenv

# 既存のスクリプトをインポート(同じディレクトリにある前提)
import fetch_robust
import fetch_train_robust
import generate_app_timetable

load_dotenv()

# 設定
ODPT_API_TOKEN = os.getenv("ODPT_API_TOKEN")
DATA_DIR = "data"
GTFS_DIR = os.path.join(DATA_DIR, "ToeiBus-GTFS")
API_URL_BASE = "https://api.odpt.org/api/v4"

if not ODPT_API_TOKEN:
    print("Error: ODPT_API_TOKEN is not set in .env")
    sys.exit(1)

def download_json(endpoint, save_filename, params=None):
    """ 単発のJSONデータをダウンロード """
    url = f"{API_URL_BASE}/{endpoint}"
    default_params = {
        "acl:consumerKey": ODPT_API_TOKEN,
        "odpt:operator": "odpt.Operator:Toei"
    }
    if params:
        default_params.update(params)

    print(f"Downloading {save_filename} ... ", end="")
    try:
        res = requests.get(url, params=default_params)
        res.raise_for_status()
        data = res.json()
        
        save_path = os.path.join(DATA_DIR, save_filename)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"OK ({len(data)} records)")
    except Exception as e:
        print(f"Failed: {e}")

def download_and_extract_gtfs():
    """ 都営バスGTFS(ZIP)をダウンロードして解凍 """
    # URLは公共交通オープンデータセンターの仕様に基づく
    url = f"{API_URL_BASE}/files/Toei/data/ToeiBus-GTFS.zip"
    params = {"acl:consumerKey": ODPT_API_TOKEN}
    
    print(f"Downloading GTFS ZIP from {url} ... ", end="")
    try:
        res = requests.get(url, params=params, stream=True)
        res.raise_for_status()
        print("OK")

        print(f"Extracting to {GTFS_DIR} ... ", end="")
        if not os.path.exists(GTFS_DIR):
            os.makedirs(GTFS_DIR)
            
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            z.extractall(GTFS_DIR)
        print("Done")
        
    except Exception as e:
        print(f"GTFS Download Failed: {e}")

def main():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    print("=== 1. ODPT Master Data (JSON) ===")
    # 基本マスタデータ
    download_json("odpt:BusstopPole", "odpt_BusstopPole.json")     # server.pyで使用
    download_json("odpt:BusroutePattern", "odpt_BusroutePattern.json") # server.pyで使用
    download_json("odpt:Station", "odpt_Station.json")              # server.pyで使用
    download_json("odpt:Railway", "odpt_Railway.json")              # server.pyで使用

    print("\n=== 2. Timetables (Robust Fetch) ===")
    # 時刻表データ(量が多いので既存のrobustスクリプトを再利用)
    # ※ fetch_robust.py 側で引数処理などをしている場合は、直接関数を呼べるように少し修正が必要かもしれません。
    #   ここでは subprocess 的に実行するか、importしてロジックだけ呼ぶのが簡単です。
    
    # バス時刻表の取得 (fetch_robust.py のロジック)
    # 簡易的に既存ファイルを流用するなら引数を模倣して実行
    sys.argv = ["prog", "--token", ODPT_API_TOKEN, "--out", DATA_DIR]
    try:
        print("--- Fetching Bus Timetables ---")
        fetch_robust.main() 
    except Exception as e:
        print(f"Bus Timetable Fetch Error: {e}")

    # 鉄道時刻表の取得 (fetch_train_robust.py のロジック)
    try:
        print("--- Fetching Train Timetables ---")
        fetch_train_robust.main()
    except Exception as e:
        print(f"Train Timetable Fetch Error: {e}")

    print("\n=== 3. GTFS Data (ZIP) ===")
    download_and_extract_gtfs()

    print("\n=== 4. Generate App Timetable ===")
    # GTFSからアプリ用データを生成
    # generate_app_timetable.py は data/ToeiBus-GTFS を読みに行く設定になっているはず
    try:
        generate_app_timetable.main()
    except Exception as e:
        print(f"Generation Error: {e}")

    print("\n[SUCCESS] All data initialized.")

if __name__ == "__main__":
    main()
