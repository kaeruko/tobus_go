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

# 設定 (Defaults)
DEFAULT_ODPT_API_TOKEN = os.getenv("ODPT_API_TOKEN")
DEFAULT_DATA_DIR = os.getenv("DATA_DIR", "api/data")
API_URL_BASE = "https://api.odpt.org/api/v4"

def download_json(endpoint, save_filename, data_dir, token, params=None):
    """ 単発のJSONデータをダウンロード """
    url = f"{API_URL_BASE}/{endpoint}"
    default_params = {
        "acl:consumerKey": token,
        "odpt:operator": "odpt.Operator:Toei"
    }
    if params:
        default_params.update(params)

    print(f"Downloading {save_filename} ... ", end="")
    try:
        res = requests.get(url, params=default_params)
        res.raise_for_status()
        data = res.json()
        
        save_path = os.path.join(data_dir, save_filename)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"OK ({len(data)} records)")
    except Exception as e:
        print(f"Failed: {e}")
        raise e

def download_and_extract_gtfs(data_dir, token):
    """ 都営バスGTFS(ZIP)をダウンロードして解凍 """
    gtfs_dir = os.path.join(data_dir, "ToeiBus-GTFS")
    url = f"{API_URL_BASE}/files/Toei/data/ToeiBus-GTFS.zip"
    params = {"acl:consumerKey": token}
    
    print(f"Downloading GTFS ZIP from {url} ... ", end="")
    try:
        res = requests.get(url, params=params, stream=True)
        res.raise_for_status()
        print("OK")

        print(f"Extracting to {gtfs_dir} ... ", end="")
        if not os.path.exists(gtfs_dir):
            os.makedirs(gtfs_dir)
            
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            z.extractall(gtfs_dir)
        print("Done")
        
    except Exception as e:
        print(f"GTFS Download Failed: {e}")

def main(data_dir=None, token=None):
    if data_dir is None:
        data_dir = DEFAULT_DATA_DIR
    if token is None:
        token = DEFAULT_ODPT_API_TOKEN

    if not token:
        print("Error: ODPT_API_TOKEN is not set (and not passed)")
        sys.exit(1)
        
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    print(f"Initializing data in {data_dir}...")

    print("=== 1. ODPT Master Data (JSON) ===")
    download_json("odpt:BusstopPole", "odpt_BusstopPole.json", data_dir, token)
    download_json("odpt:BusroutePattern", "odpt_BusroutePattern.json", data_dir, token)
    download_json("odpt:Station", "odpt_Station.json", data_dir, token)
    download_json("odpt:Railway", "odpt_Railway.json", data_dir, token)

    print("\n=== 2. Timetables (Robust Fetch) ===")
    # HACK: Pass arguments via sys.argv for fetch_robust scripts
    sys.argv = ["prog", "--token", token, "--out", data_dir]
    
    try:
        print("--- Fetching Bus Timetables ---")
        fetch_robust.main() 
    except Exception as e:
        print(f"Bus Timetable Fetch Error: {e}")

    try:
        print("--- Fetching Train Timetables ---")
        fetch_train_robust.main()
    except Exception as e:
        print(f"Train Timetable Fetch Error: {e}")

    print("\n=== 3. GTFS Data (ZIP) ===")
    download_and_extract_gtfs(data_dir, token)

    print("\n=== 4. Generate App Timetable ===")
    # Ensure generate_app_timetable uses the correct data dir via env var
    os.environ["DATA_DIR"] = data_dir 
    try:
        generate_app_timetable.main()
    except Exception as e:
        print(f"Generation Error: {e}")

    print("\n[SUCCESS] All data initialized.")

if __name__ == "__main__":
    main()
