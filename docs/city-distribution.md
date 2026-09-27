# 都市別アプリ配布

`tobus_go` は共通コードを使いながら、ストア上は都市ごとの別アプリとして配布する。

## 都市ID

| city | Flutter flavor | Android applicationId | iOS bundle identifier | Firebase |
| --- | --- | --- | --- | --- |
| Tokyo | `tokyo` | `jp.cloxs.toeigo` | `jp.cloxs.go.tokyo` | existing Tokyo project, new iOS app registration |
| Nagoya | `nagoya` | `jp.cloxs.nagoyago` | `jp.cloxs.nagoyago` | disabled until a Nagoya-specific app is configured |
| Sendai | `sendai` | `jp.cloxs.sendaigo` | `jp.cloxs.sendaigo` | disabled until a Sendai-specific app is configured |

Tokyo Androidの既存applicationId `jp.cloxs.toeigo` はGoogle Play更新互換のため変更しない。Tokyo iOSは初回App Store登録前に `jp.cloxs.go.tokyo` へ移行した。

Nagoya / SendaiのIDは新規アプリ登録前のリポジトリ上の識別子であり、ストア登録時に変更する場合はAndroid・iOS・`CityProfile`・store metadataを同一PRで更新する。

## FlavorとAPP_CITY

ストア用ビルドではnative flavorとDart defineを同時に指定する。

```text
--flavor nagoya --dart-define=APP_CITY=nagoya
```

両者が異なる場合は起動時に停止する。大文字小文字・前後空白も自動補正しない。

unflavored buildは既存テスト・従来ローカル開発との互換のためTokyoとして扱う。ストア配布物では必ずflavorを指定する。

## APIの都市分離

Flutter clientは全APIリクエストに `X-App-City` を付ける。

backendは自身の `APP_CITY` とheaderが異なる場合、HTTP 409 / `city_mismatch` を返し、経路データを返さない。

既存clientとの互換のためheaderなしは現時点では許可する。全配布clientの移行完了後、header必須化は別変更として行う。

都市別backendの基本単位:

```text
tokyo-api   APP_CITY=tokyo
nagoya-api  APP_CITY=nagoya
sendai-api  APP_CITY=sendai
```

Tokyoの新しいreleaseアプリは、Google Driveの共有 `api` フォルダにある
`tobus_go_config.json` を起動時に1回取得し、API URLと最低対応アプリバージョンを
同じレスポンスから解決する。旧releaseアプリが参照する `tobus_go_api.txt` は
後方互換のため削除・JSON化しない。

| city | Drive file | file ID | usage |
| --- | --- | --- | --- |
| Tokyo | `tobus_go_config.json` | `1pbE5qFpgDzVhYl8wA1qp4T_7jOsB2s68` | current runtime config |
| Tokyo | `tobus_go_api.txt` | `11eVn1V2mO7x8wPF-Kg9ZExmA-fqTReQ4` | legacy clients only |
| Sendai | `sendaigo_api.txt` | `1Frhq_kZt6kEX_smdSdlcKsmTv4vLnjEf` | current API endpoint |

Tokyo runtime config schema v1 requires:
`schema_version`, `api_base`, `latest_version`,
`minimum_supported_version`, `update_message_ja`, `update_message_en`。
`android_store_url` / `ios_store_url` は任意。AndroidはURL省略時に
applicationIdからGoogle Play URLを構築する。iOSで強制更新時にアプリ内ボタンを
出す場合は `ios_store_url` を設定する。

debug/profileでは開発用の`API_BASE`を明示するとDrive取得と強制更新判定を
スキップできる。releaseでは都市ごとに設定済みのDrive値を使用する。

## Firebase

Tokyoだけ既存Firebaseを利用する。

Nagoya / Sendai route-only appはFirebaseを初期化しない。Tokyo設定へfallbackしない。

今後Firebaseが必要になった都市では、その都市専用Firebase appを登録し、native configと`firebase_options`相当を同一変更で追加してから `firebaseEnabled=true` にする。

## Android store build

```powershell
.\scripts\build_aab.ps1 -City tokyo
.\scripts\build_aab.ps1 -City sendai
.\scripts\build_aab.ps1 -City nagoya -ApiBase 'https://<nagoya-api>'
```

Nagoya / Yokohamaで`ApiBase`を省略した場合は停止する。別都市APIへのfallbackはしない。

## Store metadata

都市ごとの文言は `store/<city>/` で管理する。

政府・自治体・交通事業者の公式アプリであると誤認させないこと。交通データ・福祉制度を説明する場合は公式情報源と非公式アプリである旨を明示する。

## アイコン

各都市のアイコンはbinary assetとして別管理する。ID・名称分離だけを先行させ、別都市のアイコンを暗黙に代用してリリースしない。各都市のリリース前にAndroid/iOS両方のassetを用意し、実機またはstore artifactで確認する。
