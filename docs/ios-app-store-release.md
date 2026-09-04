# 都営でGO iOS App Store リリース

Issue #155 の引き継ぎを、都営でGO (`jp.cloxs.go.tokyo`) 固有の実行手順として固定する。

## 固定する値

- App: `都営でGO`
- Bundle ID: `jp.cloxs.go.tokyo`
- Apple Developer Team ID: `H5B52RL9R2`
- Distribution identity: `Apple Distribution: CLOXS LLC`
- Flutter flavor / Xcode scheme: `tokyo`
- Xcode archive configuration: `Release-tokyo`
- `APP_CITY`: `tokyo`
- Tokyo production API source: Google Drive `tobus_go_api.txt`
- iOS deployment target: `15.0`

Version/build numberはApp Store Connectの既存状態を確認してから決める。リポジトリの `pubspec.yaml` は現在 `1.0.0+11` だが、workflowはこの値から次のbuild numberを推測しない。

## Apple側で先に確認するもの

以下はGitHubだけでは確認・作成できないため、release workflow実行前にApple Developer / App Store Connectで確認する。

1. Apple Developer Identifiersに `jp.cloxs.go.tokyo` が存在する。
2. App Store Connectに同Bundle IDのApp recordが存在する。
3. `jp.cloxs.go.tokyo` 用のmanual App Store provisioning profileを作成している。
4. そのprofileが `Apple Distribution: CLOXS LLC` 証明書を含む。
5. App Store Connect上の既存buildを見て、今回使うversion/build numberを決めている。

## GitHub Actions secrets

署名ビルド用:

- `IOS_DISTRIBUTION_CERTIFICATE_BASE64`
- `IOS_DISTRIBUTION_CERTIFICATE_PASSWORD`
- `IOS_PROVISIONING_PROFILE_BASE64`
- `IOS_GOOGLE_MAPS_API_KEY`

App Store Connect upload用:

- `APP_STORE_CONNECT_API_KEY_ID`
- `APP_STORE_CONNECT_ISSUER_ID`
- `APP_STORE_CONNECT_API_KEY_P8_BASE64`

秘密値本体はGitへcommitしない。

## 1. 署名IPAを作る

Actionsから `iOS Tokyo App Store Build` を手動実行し、App Store Connectで確認した `build_name` と `build_number` を入力する。

workflowは次をfail-fastで検証する。

- Xcode 26.6 / Flutter 3.47.0 / CocoaPods 1.16.2
- `tokyo` schemeが `Release-tokyo` をarchiveする
- Google Drive上のproduction APIがHTTPSかつlocalhostではない
- `APP_CITY=tokyo` がFlutterの生成設定に入り、`API_BASE`が埋め込まれていない
- provisioning profileのTeam ID / application-identifier / `get-task-allow=false`
- profileがCIでimportしたApple Distribution証明書を実際に含む
- profileが期限切れではない
- signing設定はRunnerの `Release-tokyo` だけに適用する
- IPAのBundle ID / 表示名 / version / build number
- Tokyo Firebase resourceのBundle ID / Project ID
- `NSLocationWhenInUseUsageDescription` の存在
- App Store成果物で `NSAllowsArbitraryLoads` が有効になっていない
- codesign / Authority / TeamIdentifier

成功するとartifact名は次になる。

```text
toeigo-ios-<build_name>-<build_number>
```

この段階ではApp Store Connectへ送信しない。

## 2. 成功済みIPAをApp Store Connectへ送る

Build workflowの成功したrun IDを確認し、Actionsから `iOS Tokyo App Store Upload` を手動実行する。

入力:

- `source_run_id`: 成功したBuild workflow run ID
- `build_name`: Build時と同じversion
- `build_number`: Build時と同じbuild number

Upload workflowは指定runのartifactだけを取得する。別run、別version、別build numberへfallbackしない。ダウンロード後にBundle ID / 表示名 / version / build number / Firebase / privacy purpose string / ATS / codesignを再検証してから `xcrun altool --upload-app` を実行する。

## 3. Upload後

App Store Connectでprocessing完了を確認する。Buildが表示されない場合はAppleから届くITMSメールも確認し、エラー内容を残したまま原因を修正する。upload失敗を別build number生成で回避しない。

TestFlightにBuildが出た後、App Store versionへBuildを紐付け、App Privacy / Age Rating / Review Information / Export Compliance / screenshots / support・privacy URL / 非公式表記を確認して審査提出する。

## ATS方針

本番APIはHTTPSで、Firebase/Google系通信もHTTPSを使用する。アプリ自身の平文HTTP既定値はローカル開発用 `127.0.0.1:8000` だけなので、App Store向けに全通信を許可する `NSAllowsArbitraryLoads` は使用しない。

ローカル開発を維持するため `localhost` / `127.0.0.1` の個別ATS exceptionだけを残す。別のHTTP通信先が必要になった場合は、通信先と用途を明示してから個別に扱い、全通信許可へfallbackしない。
