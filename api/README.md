# ローカルAPIの起動

> 2026-10-18: 仙台版は保留中です。以下の仙台手順は再開時の参照用です。通常のビルド・CIには含めません。[保留内容と再開手順](../docs/sendai-pending.md) を先に確認してください。

`api/` を作業ディレクトリにし、Python 3.11以降の仮想環境に
`requirements.txt` をインストールしてください。東京は公開版、仙台は保留中です。

PowerShellで仙台のローカルデータを使用する例：

```powershell
$env:APP_CITY = 'sendai'
$env:SENDAI_GTFS_DIR = (Resolve-Path 'data/sendai/2026-08-22').Path
$env:SENDAI_GTFS_EXPECTED_SERVICE_DATE = '2026-08-22'
python -m uvicorn local_server:create_local_app --factory --host 127.0.0.1 --port 8001
```

`local_server` はローカル起動モードを使用します。`server.py` はLambda用です。
`api/.env` も読み込みますが、シェルで設定済みの環境変数を優先します。
GTFSのパス・日付は、手元の検証済みデータに合わせてください。

仙台は共通SearchCore v2を使います。旧 `ROUTE_SEARCH_CORE` が設定されている場合は起動を停止します。明示的に環境設定から除去してから起動してください。東京の本番prebuilt・API・Realtime設定は変更しません。

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
