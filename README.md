# 都営でGO

FlutterアプリとFastAPIバックエンドで構成された経路検索アプリです。

仙台版は保留中です。通常ビルド・CIは東京と共通機能を対象にします。保存内容と再開手順は [仙台の保留](docs/sendai-pending.md) を参照してください。

## よく使う手順

- [東京版をローカルで起動する](#東京版をローカルで起動する)
- [GitHubとローカルの状態確認](#githubとローカルの状態確認)
- [Androidの言語切り替え](#androidエミュレーターの日本語英語切り替え)
- [Androidの時刻設定](#androidエミュレーターの時刻タイムゾーン)
- [テスト・CI](#テストci)
- [交通データ更新](#東京の交通データを更新する)
- [Lambdaデプロイ](#東京apiのlambdaデプロイ)
- [AAB作成](#androidリリースaabを作る)
- [iOSリリース・強制更新](#iosリリース強制更新)
- [CMS起動・公開](#一本で行くみつける掲載コンテンツのcms)

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

`--flavor tokyo` は必須です。現在有効なAndroid product flavorは `tokyo` です。

AndroidエミュレータからホストPC上のAPIへ接続するため、`127.0.0.1` ではなく `10.0.2.2` を使用します。

Flutter側ではnative flavorと`APP_CITY`の不一致をエラーにするため、東京版では両方を`tokyo`に合わせてください。

### Androidエミュレーター全体が黒い場合

Androidのホーム画面まで黒い場合は、エミュレーターの描画設定を確認してください。

1. エミュレーターを終了します。
2. Android StudioのDevice Managerで対象端末を編集し、Graphicsを **Software** に変更して保存します。
3. 対象端末のメニューから **Cold Boot** で起動します。
4. ホーム画面が表示されたら、アプリを起動します。既定のクラウドAPIを使う場合は次のコマンドです。ローカルAPIを使う場合は上記の`--dart-define`も指定してください。

```powershell
flutter run --flavor tokyo
```

Flutterの`--enable-software-rendering`はFlutter側の描画設定で、エミュレーター自体のGPU設定は変更しません。エミュレーター側のSoftware設定とCold Bootで表示が復旧した環境では、Flutterの描画オプションを追加せずに起動できます。設定の詳細は[Android公式ガイド](https://developer.android.com/studio/run/emulator-acceleration#accel-graphics)を参照してください。

`GoogleApiManager`の`Unknown calling package name 'com.google.android.gms'`は、画面が正常に表示されていても出ることがあります。このログだけで起動失敗の原因と判断せず、端末の表示状態と終了直前のログを確認してください。

## APIの詳細

他都市のローカルAPI起動手順は [api/README.md](api/README.md) を参照してください。

現在の構成は **東京＝公開版、仙台＝保留中** です。都市別IDと配布設定は [都市別アプリ配布](docs/city-distribution.md) を参照してください。

## 普段使う開発・運用コマンド（Windows / PowerShell）

原則として main で作業する。以下の相対パスは、特記しない限りリポジトリ直下から実行する。
各コマンドが失敗した場合はそこで停止し、ログを確認する。別都市・別データ・別APIへ暗黙に切り替えない。
APIキー、ODPTトークン、署名ファイル、Lambda環境変数の秘密値はGitやログへ出さない。

### GitHubとローカルの状態確認

```powershell
git status --short --branch
git fetch origin
if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }
git log -1 --oneline origin/main
git log --oneline HEAD..origin/main
git log --oneline origin/main..HEAD
```

未保存の変更やローカル独自コミットがないことを確認してから更新する。

```powershell
git switch main
if ($LASTEXITCODE -ne 0) { throw "git switch failed" }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw "git pull failed" }
```

GitHub CLIを導入・認証済みの場合は次も使える。

```powershell
gh pr list --repo kaeruko/tobus_go --state open
gh run list --repo kaeruko/tobus_go --branch main --limit 5
```

- [mainのコミット](https://github.com/kaeruko/tobus_go/commits/main/)
- [Pull requests](https://github.com/kaeruko/tobus_go/pulls)
- [Actions](https://github.com/kaeruko/tobus_go/actions)

### Androidエミュレーターの日本語・英語切り替え

日本語版と英語版は別アプリではない。Android端末の言語設定で切り替える。
Android Studioの設定ではなく、起動したエミュレーター内のAndroid設定を開く。

```powershell
adb devices
adb shell am start -a android.settings.LOCALE_SETTINGS
```

System languages（Androidの版によって表示名が異なる）で English (United States) または日本語を追加して最優先にする。
複数端末が接続されている場合は adb -s <serial> で対象を明示する。
adb がPATHにない場合は Android SDK の platform-tools\adb.exe をフルパスで指定する。

### Androidエミュレーターの時刻・タイムゾーン

日本の時刻で経路検索や運行状況をデバッグするとき：

```powershell
adb shell settings put global auto_time_zone 0
if ($LASTEXITCODE -ne 0) { throw "disable automatic time zone failed" }
adb shell cmd alarm set-timezone Asia/Tokyo
if ($LASTEXITCODE -ne 0) { throw "set time zone failed" }
adb shell date
```

端末のタイムゾーン変更であり、PCやAPIの時刻は変更しない。
元の自動設定に戻す場合は adb shell settings put global auto_time_zone 1 を明示的に実行する。

### 本番APIを使ってFlutterをデバッグする

ローカルAPIを使わず、公開中のAPIに接続する場合：

```powershell
flutter pub get
if ($LASTEXITCODE -ne 0) { throw "flutter pub get failed" }
flutter run --flavor tokyo --dart-define=APP_CITY=tokyo
```

API_BASE を指定しない場合、東京版はGoogle Driveの runtime config を利用する。
ローカルAPIで試す場合は上の「東京版をローカルで起動する」の手順を使用する。
デバッグ用API_BASE指定はreleaseの接続先を変更するものではない。
flutter devices で端末を確認でき、複数端末がある場合は flutter run -d <device-id> で対象を指定する。

### テスト・CI

現在の通常テストは東京と共通機能を対象とする。保留中の仙台専用スイートを混ぜない。

```powershell
flutter pub get
if ($LASTEXITCODE -ne 0) { throw "flutter pub get failed" }
flutter analyze --no-fatal-infos --no-fatal-warnings
if ($LASTEXITCODE -ne 0) { throw "flutter analyze failed" }
python scripts/run_active_tests.py python
if ($LASTEXITCODE -ne 0) { throw "Python tests failed" }
python scripts/run_active_tests.py flutter
if ($LASTEXITCODE -ne 0) { throw "Flutter tests failed" }
```

対象だけ確認する場合は python scripts/run_active_tests.py python --list または python scripts/run_active_tests.py flutter --listを使用する。
Pythonの通常テストに unittest discover を直接使用すると、保留中のテストも収集されるため使用しない。
リリース前には対象mainのCI成功と、日英それぞれの実機確認を行う。

## 東京の交通データを更新する

### app_data.pkl の再生成

APIコードのみの変更で、prebuiltの契約・入力・内容に変更がない場合は、毎回データを作り直す必要はない。
グラフ、時刻表、公式交通名、静的データの変更では、対応するprebuiltが必要かを確認する。

現行prebuildは以前と違い、不足・不一致のODPT入力を自動取得しない。
[都営バス静的トポロジー更新](docs/toei-bus-static-release.md) と
[東京メトロGTFSリリース手順](docs/tokyo-metro-gtfs-release-runbook.md) に従って、
検証済みのODPT・GTFS・乗換manifestを用意する。

東京メトロを含むレビュー済み構成を再生成する場合の例：

```powershell
python scripts/sync_toei_bus_static.py
if ($LASTEXITCODE -ne 0) { throw "Toei static sync failed" }
$env:ENABLE_TOKYO_METRO_STATIC = '1'
python api/prebuild.py
if ($LASTEXITCODE -ne 0) { throw "prebuild failed" }
```

通常の出力は api/data/app_data.pkl。PREBUILT_OUTPUT や DATA_DIR を明示している場合はその設定を確認する。
本番リリースでは検証用の作業領域と出力を分離し、既存の承認済み成果物を上書きしない。
東京メトロの有効/無効は対象リリースの構成に合わせて明示する（無効にすることで検証失敗を回避しない）。
都営バスのODPTグラフとGTFS具体便の停車順の双方向一致が必須。GTFS更新とprebuiltの版が不整合のまま本番切替しない。

### S3のprebuiltをバージョン管理する

以下は承認済みの成果物に対する手動本番操作の手順。単なるデバッグでは実行しない。
同じS3キーに別内容のpickleを上書きせず、SHA-256付きのキーへ保存してから、
Lambdaの S3_PREBUILT_KEY を変更する。バケット名は現在のLambda設定から取得する。

まずローカル成果物・本番設定を確認する（環境変数全体は表示しない）。

```powershell
$ErrorActionPreference = 'Stop'
$region = 'us-west-2'
$function = 'toeigo-api'
$file = (Resolve-Path 'api/data/app_data.pkl').Path
$hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLowerInvariant()
$key = "deployments/prebuilt/$hash/app_data.pkl"

$raw = aws lambda get-function-configuration --region $region --function-name $function --output json
if ($LASTEXITCODE -ne 0) { throw "get-function-configuration failed" }
$config = $raw | ConvertFrom-Json
$bucket = [string]$config.Environment.Variables.S3_BUCKET_NAME
$oldKey = [string]$config.Environment.Variables.S3_PREBUILT_KEY
if ([string]::IsNullOrWhiteSpace($bucket) -or [string]::IsNullOrWhiteSpace($oldKey)) {
    throw "S3_BUCKET_NAME or S3_PREBUILT_KEY is missing"
}
Write-Host "Bucket: $bucket"
Write-Host "Previous key: $oldKey"
Write-Host "New key: $key"
```

前のキーを作業記録に残す。新しいキーが既に存在する場合は上書きせず、内容を検証してから別途判断する。
新規キーへのアップロード例（条件付きPUT対応のAWS CLIを使用）：

```powershell
aws s3api put-object --bucket $bucket --key $key --body $file --if-none-match '*' --checksum-algorithm SHA256 --region $region --query '{ETag:ETag,ChecksumSHA256:ChecksumSHA256}'
if ($LASTEXITCODE -ne 0) { throw "prebuilt upload failed" }

# S3から取得したバイト列のSHA-256を確認する
$verifyFile = [System.IO.Path]::GetTempFileName()
try {
    aws s3 cp "s3://$bucket/$key" $verifyFile --region $region
    if ($LASTEXITCODE -ne 0) { throw "prebuilt verification download failed" }
    if ((Get-FileHash $verifyFile -Algorithm SHA256).Hash.ToLowerInvariant() -cne $hash) {
        throw "prebuilt SHA-256 mismatch"
    }
} finally {
    Remove-Item -LiteralPath $verifyFile -Force
}
```

アップロードは公開切替ではない。非本番で新しいprebuilt・APIイメージ・compiled GTFSの組を確認し、
本番切替を別途承認してから次を実行する。旧コードと新データ（または新コードと旧データ）が互換でない場合、
この逐次変更をそのまま実行しない。切替・復旧の計画を先に用意する。

Lambda環境変数は全体置換されるため、直前の設定から全変数を保持し、対象キーだけ変更する。
JSONは一時ファイルで渡し、値を端末に表示しない。RevisionIdで並行変更を拒否する。

```powershell
$raw = aws lambda get-function-configuration --region $region --function-name $function --output json
if ($LASTEXITCODE -ne 0) { throw "get-function-configuration failed" }
$config = $raw | ConvertFrom-Json
if ([string]$config.Environment.Variables.S3_BUCKET_NAME -cne $bucket -or
    [string]$config.Environment.Variables.S3_PREBUILT_KEY -cne $oldKey) {
    throw "production data configuration changed; inspect before continuing"
}
$vars = @{}
$config.Environment.Variables.PSObject.Properties | ForEach-Object {
    $vars[$_.Name] = [string]$_.Value
}
$vars['S3_PREBUILT_KEY'] = $key
$environmentJson = @{ Variables = $vars } | ConvertTo-Json -Depth 10 -Compress
$tmp = [System.IO.Path]::GetTempFileName()
try {
    [System.IO.File]::WriteAllText($tmp, $environmentJson, [System.Text.UTF8Encoding]::new($false))
    aws lambda update-function-configuration --region $region --function-name $function --revision-id $config.RevisionId --environment "file://$tmp" --query RevisionId --output text
    if ($LASTEXITCODE -ne 0) { throw "update-function-configuration failed" }
    aws lambda wait function-updated --region $region --function-name $function
    if ($LASTEXITCODE -ne 0) { throw "lambda configuration update failed" }
} finally {
    Remove-Item -LiteralPath $tmp -Force
}

$actual = aws lambda get-function-configuration --region $region --function-name $function --query 'Environment.Variables.S3_PREBUILT_KEY' --output text
if ($LASTEXITCODE -ne 0) { throw "prebuilt pointer verification failed" }
if ($actual.Trim() -cne $key) { throw "S3_PREBUILT_KEY mismatch" }
Write-Host "Verified: $key"
```

復旧時も現在の全環境変数を維持して、記録した旧キーに明示的に戻す。
コード・GTFS・prebuiltの互換性を確認し、必要なら対応する旧イメージも戻す。
GTFSの週次更新は [GTFS更新手順](docs/gtfs-refresh.md) を参照する。

## 東京APIのLambdaデプロイ

GitHub Actions の `Tokyo API deploy` は、`main` の CI が成功したコミットを対象にします。本番の初期設定、ドライラン、自動化の有効化は [東京 API 自動デプロイ手順](docs/tokyo-api-github-actions-deploy.md) を参照してください。

### 手動デプロイ

本番のデータ契約と対象mainのCIを確認し、AWS CLIの認証・Docker Desktop起動を済ませる。
承認後にリポジトリ直下で実行する。

```powershell
.\scripts\deploy_api.ps1 -City tokyo
```

既存の東京用ECR/Lambda toeigo-api（us-west-2）に対して、Docker build、ECR push、Lambdaイメージ更新、更新完了待機を行う。
prebuiltの生成・S3キーの切替やストアへの配布は、このスクリプトの処理に含まれない。

本番APIの確認：

```powershell
$url = aws lambda get-function-url-config --region us-west-2 --function-name toeigo-api --query FunctionUrl --output text
if ($LASTEXITCODE -ne 0) { throw "get-function-url-config failed" }
$apiBase = $url.Trim().TrimEnd('/')
if (-not $apiBase.StartsWith('https://')) { throw "invalid API URL" }
$ready = Invoke-RestMethod "$apiBase/warmup"
$ready
if ($ready.status -cne 'ready' -or $ready.city -cne 'tokyo') {
    throw "Tokyo production API is not ready"
}
```

warmupだけでは検索の正常性は保証されない。日英地点検索、都営・東京メトロの対象経路、運賃、停留所名、リアルタイム表示を確認してからストア版を配布する。
認証トークンの更新は scripts/rotate_odpt_token.ps1 を使用する。詳細は [GTFS更新手順](docs/gtfs-refresh.md)。

## AndroidリリースAABを作る

Google Play上の最大使用済みversionCodeを確認し、pubspec.yaml のbuild番号と整合させる。
Android Maps用の制限済みキーを環境変数 GOOGLE_MAPS_ANDROID_API_KEY に設定し、
android/key.properties と署名用keystoreを手元に用意する。秘密値をコミットしない。

```powershell
.\scripts\build_aab.ps1 -City tokyo
```

このスクリプトは clean、pub get、analyze、署名付きrelease AAB作成を行い、
pubspec.yaml のbuild番号を +1 してビルドする。AAB生成成功時だけ pubspec.yaml を更新する。
手動でさらに+1する必要はない。ただしPlay Console側の既使用番号との照合は必要。
成功後は pubspec.yaml の変更を確認し、リリース記録としてコミットする。

出力先：

```text
build/app/outputs/bundle/tokyoRelease/app-tokyo-release.aab
```

東京版では API_BASE を指定せず、Google Driveのruntime configを使用する。
AAB作成だけではPlay Consoleへのアップロードや公開は行われない。
Android applicationId は jp.cloxs.toeigo のまま維持する。
詳細は [Android Maps APIキー](docs/android-google-maps-key.md) と [都市別配布](docs/city-distribution.md)。

## iOSリリース・強制更新

iOSは [App Storeリリース手順](docs/ios-app-store-release.md) と
[現在のiOSワークフロー](.github/workflows/ios_testflight.yml) を参照する。
東京のbundle IDは jp.cloxs.go.tokyo。
App Store Connectの既存version/buildを確認し、署名・成果物・アップロードを区別する。

東京の新しいreleaseアプリはGoogle Driveの tobus_go_config.json を使用する。
schema_version、api_base、latest_version、minimum_supported_version、update_message_ja、
update_message_en が必須。android_store_url / ios_store_url は任意。
旧クライアント用の tobus_go_api.txt は削除・JSON化しない。
最低対応versionの引き上げは、対象バージョンが実際にストアで取得可能になった後に別途判断する。
API URLを変更する場合も旧クライアントの互換性を確認する。
詳細は [都市別配布](docs/city-distribution.md)。

## 「一本で行く」・「みつける」掲載コンテンツのCMS

初回のみ依存をインストールする。

```powershell
python -m pip install -r scripts/requirements_explore_cms.txt
if ($LASTEXITCODE -ne 0) { throw "CMS dependencies install failed" }
```

起動：

```powershell
python -m streamlit run scripts/explore_cms.py
```

停留所名と系統を選択し、写真、日本語・英語コメント、画像ごとのキャプションを編集する。
正本は content/explore/tokyo/ のCSVと画像。英語文が空欄の場合は日本語へ自動フォールバックしない。
保存内容を確認してから、CMSの「S3へ公開」ボタンまたは次を実行する。

```powershell
python scripts/publish_explore_content.py
if ($LASTEXITCODE -ne 0) { throw "explore content publication failed" }
```

公開スクリプトは入力を検証し、画像を先に送って最後に spots.json を更新する。
これはコンテンツ公開であり、APIのDockerデプロイやAAB作成とは別の操作。
詳細は [掲載コンテンツREADME](content/explore/tokyo/README.md)。

## 仙台の再開時に確認すること（過去の調査メモ）

仙台は現在保留中。通常の開発・起動・CI・デプロイに含めない。
以下は過去の d52c0b51 時点の調査メモであり、現在のmainで未修正かどうかを示すものではない。

- 長町南駅の異なる標柱間（市営バス2番のりば→地下鉄駅→7番のりば）など、徒歩だけの接続で0乗車が選ばれ得る。同一標柱の正確な座標を指定した場合にも除外条件に抜けがあると調査された。
- 無料乗車証の運賃処理は最低1乗車を要求するため、0乗車選択時に例外・HTTP 422へ至る可能性が指摘された。具体ODの実データHTTP再現は当時未実施。
- 0乗車を無料公共交通として扱わず、検索全体をエラーにせず、有効な1乗車以上の別経路も失わないことを共通SearchCore v2の仕様を維持して確認する。単純な結果除外だけでは有効経路を失うおそれがある。
- 少乗換モードは人工データのテストがある一方、調査対象の新施設3経路では最早到着中心で、少乗換の独立した実データ期待値が当時未固定だった。
- 再開時には実データ再現、修正の有無、回帰テスト・再CI、設計資料第24節の完了記録を確認する。

調査時点の参照箇所：
[同一標柱の除外条件](https://github.com/kaeruko/tobus_go/blob/d52c0b5/api/sendai_coordinate_routes.py#L144-L164)、
[運賃変換](https://github.com/kaeruko/tobus_go/blob/d52c0b5/api/sendai_practical_network.py#L333-L375)、
[0乗車拒否条件](https://github.com/kaeruko/tobus_go/blob/d52c0b5/api/sendai_shared_network.py#L42-L49)。
現行の保留・再開手順は [仙台の保留](docs/sendai-pending.md) を正とする。

## 詳細資料

| 内容 | 参照先 |
| --- | --- |
| 都市別API構成 | [API bootstrap](docs/city-api-bootstrap.md) |
| 共通経路探索 | [共有ネットワーク設計](docs/shared-network-design.md) |
| 運賃 | [運賃方針](docs/fare-policy.md) |
| 乗車中の案内 | [共有ナビ設計](docs/active-trip-navigation-shared-architecture.md) |
| 東京メトロの静的データ | [静的データ設計](docs/tokyo-metro-static-data.md) / [リリースロードマップ](docs/tokyo-metro-release-roadmap.md) |
| 東京の経路性能 | [性能レビュー](docs/tokyo-route-performance-review.md) |
| 英語表示 | [多言語負荷レビュー](docs/multilingual-load-review.md) |
