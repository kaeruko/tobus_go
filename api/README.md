# ローカルAPIの起動

`api/` を作業ディレクトリにし、Python 3.11以降の仮想環境に
`requirements.txt` をインストールしてください。Rust版を使う場合は
[Rust SearchCoreの手順](native/transit_search_core/README.md)で拡張もビルドします。

PowerShellで仙台のローカルデータを使用する例：

```powershell
$env:APP_CITY = 'sendai'
$env:ROUTE_SEARCH_CORE = 'rust'
$env:SENDAI_GTFS_DIR = (Resolve-Path 'data/sendai/2026-08-22').Path
$env:SENDAI_GTFS_EXPECTED_SERVICE_DATE = '2026-08-22'
python -m uvicorn local_server:create_local_app --factory --host 127.0.0.1 --port 8001
```

`local_server` はローカル起動モードを使用します。`server.py` はLambda用です。
`api/.env` も読み込みますが、シェルで設定済みの環境変数を優先します。
GTFSのパス・日付は、手元の検証済みデータに合わせてください。

他都市の環境変数：

| APP_CITY | データディレクトリ | 検証する版・日付 |
| --- | --- | --- |
| nagoya | NAGOYA_GTFS_DIR | NAGOYA_GTFS_EXPECTED_REVISION |
| yokohama | YOKOHAMA_BUS_GTFS_DIR | YOKOHAMA_BUS_GTFS_EXPECTED_SERVICE_DATE |

横浜はリアルタイムプロバイダーの初期化に `ODPT_API_TOKEN` も必要です。

起動後は `http://127.0.0.1:8001/docs` でリクエストを試せます。
`GET /healthz` と `GET /warmup` で起動状態を確認できます。
`POST /route` の経路検索例：

```json
{
  "alat": 38.260,
  "alon": 140.882,
  "blat": 38.268,
  "blon": 140.869,
  "pref": "time",
  "start_time": "09:00",
  "target_date_str": "2026-08-22",
  "limit": 5
}
```

検索日はGTFSの運行期間内を指定してください。運行期間外は経路が返りません。
終了するときはサーバーを起動したターミナルで `Ctrl+C` を押します。
