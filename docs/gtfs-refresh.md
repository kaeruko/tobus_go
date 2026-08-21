# 都営バスGTFSの週次更新

公式ODPTのGTFS ZIPを条件付きGETし、ZIP全体を検証してから既存S3バケットへ保存します。バージョンZIPは不変オブジェクトとして保存し、最後に `state.json` を置き換えることで現在版を切り替えます。

## ローカル確認

`api/.env` に `ODPT_API_TOKEN` が設定されている環境で、リポジトリのルートから実行します。

```powershell
.\api\.venv\Scripts\python.exe scripts\refresh_toei_gtfs.py
```

初回は `api/data/gtfs-refresh/versions/<sha256>.zip` と `state.json` を作成します。同じデータで再実行すると、ODPTが対応している場合はHTTP 304で終了します。

テストは外部サーバーへアクセスせず、HTTP応答と保存先を差し替えて実行します。

```powershell
Set-Location api
.\.venv\Scripts\python.exe -m unittest tests.test_gtfs_refresh tests.test_lambda_data_download tests.test_day_type -v
```

## AWSデプロイ

更新Lambdaは標準ライブラリとLambda組み込みのboto3だけを使うため、デプロイZIPには `api/gtfs_refresh.py` だけを入れます。

```powershell
$region = "us-west-2"
$bucket = "toeigo"
$artifactDir = "api/build/gtfs-refresh"
$zipPath = "$artifactDir/gtfs-refresh.zip"

New-Item -ItemType Directory -Force $artifactDir | Out-Null
Copy-Item api/gtfs_refresh.py "$artifactDir/gtfs_refresh.py" -Force
Compress-Archive -Path "$artifactDir/gtfs_refresh.py" -DestinationPath $zipPath -Force
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

初回だけ手動実行し、stateと最初のバージョンを作ります。

```powershell
aws lambda invoke `
  --region us-west-2 `
  --function-name toeigo-gtfs-refresh `
  api/build/gtfs-refresh/first-run.json
Get-Content api/build/gtfs-refresh/first-run.json
```

API Lambdaをこのコードへ更新した後、既存の環境変数を残したまま次を追加します。

```text
S3_GTFS_STATE_KEY=gtfs/toei/state.json
```

API用の `app_data.pkl` にはODPT時刻表の正確なサービスID索引を含める必要があります。リポジトリのルートから再生成し、既存のデプロイ手順でS3へアップロードして `S3_PREBUILT_KEY` を更新します。

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
- GTFS ZIP: `s3://toeigo/gtfs/toei/versions/<sha256>.zip`
- Scheduler: 毎週月曜 04:00（`Asia/Tokyo`）
- Lambda: `toeigo-gtfs-refresh`（256MB、最大3分）
- ログ保持: 14日

GTFSの現在版が変わった場合は、更新Lambdaが `toeigo-api` の `GTFS_DATA_VERSION` だけを更新します。これにより既存のwarm実行環境が入れ替わり、次の起動で新しいmanifestとZIPを読み込みます。既存のAPI環境変数は保持します。

新規のDynamoDBやS3バケットは作りません。
