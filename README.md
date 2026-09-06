# 都営でGO

FlutterアプリとFastAPIバックエンドで構成された経路検索アプリです。

## 東京版をローカルで起動する

APIとFlutterアプリは別のターミナルで起動します。

### 1. ローカルAPIを起動

`api/` を作業ディレクトリにします。

```powershell
cd C:\Users\mail\work\tobus_go\api

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "requirements install failed: $LASTEXITCODE" }

$env:APP_CITY = 'tokyo'
Remove-Item Env:ROUTE_SEARCH_CORE -ErrorAction SilentlyContinue
Remove-Item Env:SENDAI_GTFS_DIR -ErrorAction SilentlyContinue
Remove-Item Env:SENDAI_GTFS_EXPECTED_SERVICE_DATE -ErrorAction SilentlyContinue

if (-not (Test-Path .\data\app_data.pkl)) {
    throw "Tokyo prebuilt data not found: .\data\app_data.pkl"
}

python -m uvicorn local_server:create_local_app `
    --factory `
    --host 127.0.0.1 `
    --port 8001

if ($LASTEXITCODE -ne 0) { throw "Tokyo local API failed: $LASTEXITCODE" }
```

起動後は `http://127.0.0.1:8001/docs` でAPIを確認できます。

別ターミナルから次でも起動状態を確認できます。

```powershell
Invoke-RestMethod http://127.0.0.1:8001/warmup
```

`status=ready`, `city=tokyo` なら起動成功です。

### 2. AndroidエミュレータでFlutterアプリを起動

リポジトリ直下を作業ディレクトリにします。

```powershell
cd C:\Users\mail\work\tobus_go

flutter run `
  --flavor tokyo `
  --dart-define=APP_CITY=tokyo `
  --dart-define=API_BASE=http://10.0.2.2:8001
```

`--flavor tokyo` は必須です。Android側には `tokyo` / `nagoya` / `sendai` / `yokohama` のproduct flavorがあります。

AndroidエミュレータからホストPC上のAPIへ接続するため、`127.0.0.1` ではなく `10.0.2.2` を使用します。

Flutter側ではnative flavorと`APP_CITY`の不一致をエラーにするため、東京版では両方を`tokyo`に合わせてください。

## APIの詳細

他都市のローカルAPI起動手順は [api/README.md](api/README.md) を参照してください。
