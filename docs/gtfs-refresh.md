# 都営バスGTFSの週次更新

公式ODPTのGTFS ZIPを条件付きGETし、ZIP全体を検証してから既存S3バケットへ保存します。バージョンZIPは不変オブジェクトとして保存します。

Tokyo APIのcold startでは81MB前後の `stop_times.txt` を毎回CSV parseしないよう、更新Lambdaが同じGTFSからversion付きの `gtfs_state.pkl.gz` も生成します。raw ZIPとcompiled stateの両方を保存・検証した後、最後に `state.json` を置き換えることで現在版を原子的に切り替えます。

## ローカル確認

`api/.env` に `ODPT_API_TOKEN` が設定されている環境で、リポジトリのルートから実行します。

```powershell
.\api\.venv\Scripts\python.exe scripts\refresh_toei_gtfs.py
```

初回は `api/data/gtfs-refresh/versions/<sha256>.zip` と `state.json` を作成します。同じデータで再実行すると、ODPTが対応している場合はHTTP 304で終了します。

API/compiled-state関連のテストは外部サーバーへアクセスせず、HTTP応答と保存先を差し替えて実行します。

```powershell
Set-Location api
.\.venv\Scripts\python.exe -m unittest `
  tests.test_gtfs_refresh `
  tests.test_gtfs_refresh_compiled `
  tests.test_gtfs_state `
  tests.test_lambda_data_download `
  tests.test_tokyo_runtime_fast `
  tests.test_day_type -v
```

## AWSデプロイ

更新Lambdaは標準ライブラリとLambda組み込みのboto3だけを使います。compiled state生成には既存の `GtfsRepository` をそのまま使うため、デプロイZIPには次の4ファイルを含めます。

- `api/gtfs_refresh.py`
- `api/gtfs_refresh_compiled.py`
- `api/gtfs_state.py`
- `api/gtfs_loader.py`

```powershell
$region = "us-west-2"
$bucket = "toeigo"
$artifactDir = "api/build/gtfs-refresh"
$zipPath = "$artifactDir/gtfs-refresh.zip"

New-Item -ItemType Directory -Force $artifactDir | Out-Null
Copy-Item api/gtfs_refresh.py "$artifactDir/gtfs_refresh.py" -Force
Copy-Item api/gtfs_refresh_compiled.py "$artifactDir/gtfs_refresh_compiled.py" -Force
Copy-Item api/gtfs_state.py "$artifactDir/gtfs_state.py" -Force
Copy-Item api/gtfs_loader.py "$artifactDir/gtfs_loader.py" -Force

if (Test-Path $zipPath) {
  Remove-Item $zipPath -Force
}
Compress-Archive -Path "$artifactDir/*.py" -DestinationPath $zipPath
$hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$codeKey = "deployments/gtfs-refresh/$hash.zip"

aws s3 cp $zipPath "s3://$bucket/$codeKey" --region $region
aws cloudformation deploy `
  --region $region `
  --stack-name toeigo-gtfs-refresh `
  --template-file infra/gtfs-refresh.yaml `
  --capabilities CAPABILITY_IAM `
  --parameter-overrides `
    CodeS3Bucket=$bucket `
    CodeS3Key=$codeKey `
    DataBucketName=$bucket `
    OdptApiToken=$env:ODPT_API_TOKEN
```

compiled state生成ではGTFSを一度だけメモリ上へparseするため、refresh Lambdaは2048MBです。週1回の実行だけで、Tokyo APIの常時メモリ設定は変更しません。

## compiled state導入時の順序

既存の `state.json` にはcompiled stateへのpointerがないため、APIを先に更新しないでください。新しいTokyo APIはcompiled stateがない場合にraw CSVへ暗黙fallbackせず、起動を停止します。

まずrefresh Lambdaを上記CloudFormationで更新し、1回手動実行します。

```powershell
aws lambda invoke `
  --region us-west-2 `
  --function-name toeigo-gtfs-refresh `
  api/build/gtfs-refresh/compiled-backfill.json
Get-Content api/build/gtfs-refresh/compiled-backfill.json
```

現在のstateにcompiled pointerがない場合、この実行はODPTから再取得せず、stateが指す既存の不変GTFS ZIPをS3から読み、compiled stateを生成します。生成・upload・checksum検証が完了した後だけ `state.json` を更新します。

次にstateを確認します。値そのものは公開せず、必要フィールドが存在することを確認します。

```powershell
aws s3 cp `
  s3://toeigo/gtfs/toei/state.json `
  api/build/gtfs-refresh/current-state.json `
  --region us-west-2

$state = Get-Content api/build/gtfs-refresh/current-state.json -Raw | ConvertFrom-Json
foreach ($name in @(
  'sha256',
  'object_key',
  'compiled_state_key',
  'compiled_state_sha256',
  'compiled_state_schema_version',
  'compiled_state_record_counts'
)) {
  if ($null -eq $state.$name -or [string]::IsNullOrWhiteSpace([string]$state.$name)) {
    throw "GTFS state is missing required field: $name"
  }
}
if ([int]$state.compiled_state_schema_version -ne 1) {
  throw "Unexpected compiled GTFS schema version: $($state.compiled_state_schema_version)"
}
```

この確認が成功してから、`scripts/deploy_api.ps1 -City tokyo` でTokyo APIを更新します。

API Lambdaには次が必要です。

```text
S3_GTFS_STATE_KEY=gtfs/toei/state.json
```

API用の `app_data.pkl` にはODPT時刻表の正確なサービスID索引を含める必要があります。必要時はリポジトリのルートから再生成し、既存のデプロイ手順でS3へアップロードして `S3_PREBUILT_KEY` を更新します。

```powershell
.\api\.venv\Scripts\python.exe api\prebuild.py
```

## ODPT APIトークンのローテーション

ODPT APIトークンを再発行した場合は、ローカルだけでなくAWS上のTokyo API Lambdaと週次GTFS更新Lambdaも更新します。Lambdaの環境変数は更新APIで全体置換されるため、手作業で `ODPT_API_TOKEN` だけを指定しないでください。

リポジトリの `scripts/rotate_odpt_token.ps1` は次をfail-fastで行います。

- 現在の `ODPT_API_TOKEN` が認証付きODPT APIで有効なことを確認
- `toeigo-api` の既存環境変数をすべて保持したまま `ODPT_API_TOKEN` だけ更新
- CloudFormation stack `toeigo-gtfs-refresh` の `OdptApiToken` parameterを更新
- stack管理のrefresh Lambdaと`toeigo-api`の両方で新トークンが設定されたことを値を表示せず検証

実行前に現在のPowerShellへ新しいトークンを設定し、リポジトリルートから実行します。

```powershell
if (-not $env:ODPT_API_TOKEN) {
    throw "ODPT_API_TOKEN is not set"
}

.\scripts\rotate_odpt_token.ps1

if ($LASTEXITCODE -ne 0) {
    throw "ODPT token rotation failed"
}
```

スクリプトはトークンを標準出力へ表示しません。またCloudFormation管理下のrefresh Lambdaを直接編集せず、stack parameterを更新するため、次回stack deployで古いトークンへ戻るドリフトを作りません。

## AWS上の構成

- 保存先バケット: 既存の `toeigo`
- state: `s3://toeigo/gtfs/toei/state.json`
- raw GTFS ZIP: `s3://toeigo/gtfs/toei/versions/<source-sha256>.zip`
- compiled GTFS: `s3://toeigo/gtfs/toei/compiled/<source-sha256>.pkl.gz`
- Scheduler: 毎週月曜 04:00（`Asia/Tokyo`）
- Lambda: `toeigo-gtfs-refresh`（2048MB、最大3分）
- ログ保持: 14日

GTFSの現在版が変わった場合、更新Lambdaはraw ZIPとcompiled stateの両方をversioned objectとして保存し、最後に `state.json` を切り替えます。その後 `toeigo-api` の `GTFS_DATA_VERSION` だけを更新します。これにより既存のwarm実行環境が入れ替わり、次のcold startで新しいcompiled stateを読み込みます。既存のAPI環境変数は保持します。

compiled artifactのschema、source SHA-256、artifact SHA-256、record countのいずれかが一致しない場合、Tokyo APIはraw GTFSへのfallbackを行わず起動を停止します。

新規のDynamoDBやS3バケットは作りません。
