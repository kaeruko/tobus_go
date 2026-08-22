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

Sendai backendは未実装の間、Tokyo/Nagoyaを代替提供せず起動時に失敗する。

## Firebase

Tokyoだけ既存Firebaseを利用する。

Nagoya / Sendai route-only appはFirebaseを初期化しない。Tokyo設定へfallbackしない。

今後Firebaseが必要になった都市では、その都市専用Firebase appを登録し、native configと`firebase_options`相当を同一変更で追加してから `firebaseEnabled=true` にする。

## Android store build

```powershell
.\scripts\build_aab.ps1 -City tokyo
.\scripts\build_aab.ps1 -City nagoya -ApiBase 'https://<nagoya-api>'
```

Nagoya / Sendaiで`ApiBase`を省略した場合は停止する。Tokyo APIへのfallbackはしない。

## Store metadata

都市ごとの文言は `store/<city>/` で管理する。

政府・自治体・交通事業者の公式アプリであると誤認させないこと。交通データ・福祉制度を説明する場合は公式情報源と非公式アプリである旨を明示する。

## アイコン

各都市のアイコンはbinary assetとして別管理する。ID・名称分離だけを先行させ、別都市のアイコンを暗黙に代用してリリースしない。各都市のリリース前にAndroid/iOS両方のassetを用意し、実機またはstore artifactで確認する。
