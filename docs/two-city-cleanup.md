# 東京＝公開版・仙台＝開発版への整理（2026-10-16）

## 開始状態と依存調査

開始mainは `863410ff60beb65924cf787a4234e6582b491e8b`。作業ツリーはclean、開いているPRと実行中CIは無し。直近の成功CIは [38836806011](https://github.com/kaeruko/tobus_go/actions/runs/38836806011)（code `bc120251`、mainとの差は結果記録のみ）。push前にもmain SHAを確認し、他の変更が入れば上書きしない。

名古屋でGO・横浜でGOは未公開のため開発中止し、専用機能を削除する。後方互換alias・無効化された分岐・旧設定を残さない。

| 撤去対象 | 調査した依存と対応 |
| --- | --- |
| Python都市runtime/routes/backend、横浜subway/Realtime/coverage/運賃Policy | app factory、共通route endpoint、fare registryとGTFS bundleの都市分岐を除去。東京/仙台の入口・既定値は維持 |
| 両都市専用テスト、取得・監査・coverage提案・アイコン生成スクリプト | 専用呼出元ごと削除。共通GTFSテストが使っていたraw fixtureは `api/tests/transit_gtfs_fixture.py` へ移し、Policy依存を除去 |
| Flutter都市定義・ローカライズ・パス選択と静的時刻表専用画面 | 2都市のenum/profileへ縮小。東京/仙台で使わないパス必須検索gate、保存済み旧normalの互換処理、専用カードを削除。共通の車両位置/表示テストは独立fixtureで保持 |
| Android/iOS専用flavor・scheme・build configuration・ID設定・アイコン | 実行flavor/schemeは `tokyo` / `sendai` のみ。冗長なstock Runner schemeも削除。両都市の既存設定IDとbundle/application IDは維持 |
| ストア素材・都市別文書・benchmark corpus | 名古屋store、両都市corpus・固有文書を削除。共通契約と東京監査履歴は先に `docs/shared-network-design.md` へ移設 |
| Actionsとインフラ補助設定 | 2都市分のAndroid/iOSビルド、横浜アイコン生成・専用workflowを削除。AWSスクリプトの名古屋分岐と廃止v1 selector生成を削除。スクリプト実行やAWS変更は無し |

## 保持した共通資産と設定

- 東京のAPI・本番runtime/prebuilt、`toei_engine`、`tokyo_*`、Realtime、データ、探索順位・guard、公開アプリ資産とTestFlight workflow。
- 共通SearchCore v2本体、Dataset/GTFS/ODPT Adapter、運行日・秒時計・通過/乗降制約、方向別徒歩検査、共通DTO、時刻表探索と独立oracle。
- 仙台のバスGTFS/manifest/版・SHA検査、runtimeとRT、地下鉄の厳密/実用Adapter、標準乗換、ふれあい乗車証scope/再検証、独立oracle、固定ケース、原資料・検証ツール。既存の実用profileや試験入口の条件は緩和しない。
- 東京Android `jp.cloxs.toeigo`、東京iOS `jp.cloxs.go.tokyo`、仙台Android/iOS `jp.cloxs.go.sendai`。東京Firebaseと両都市のDrive設定も維持。

本番デプロイ、S3操作、ストア/TestFlight提出は実施しない。実データ認定の範囲や仙台の開発段階をこの整理で引き上げない。

## コミットと検証

アプリflavor/CI整理は `dd103a80`、Python/依存・文書整理は `6509c858` の別コミット。Flutter analyzeで検出した撤去箇所の残存参照は `4a243045` / `925956ad` で削除した。[PR #245](https://github.com/kaeruko/tobus_go/pull/245) にまとめた。

検証対象codeは `925956ad1362ea6cb0c6fc9757bd258209b04498`。[CI 38854101108](https://github.com/kaeruko/tobus_go/actions/runs/38854101108) は **全7ジョブ成功**。

| 検証 | 結果 |
| --- | --- |
| Python全テスト（CI、Python 3.12） | **823件成功、78.195秒** |
| ローカルPython全テスト（専用venv、fail-fast） | **823件成功、69.071秒** |
| Flutter analyze | 既存コマンド `flutter analyze --no-fatal-infos --no-fatal-warnings` 成功。既存warning/infoを含む97件は変更前と同数 |
| Flutter test | **654件成功**（変更前667件。廃止都市専用のケースを削除） |
| Android | `tokyo` / `sendai` のdebug APKを実ビルド成功 |
| iOS | `tokyo` / `sendai` のsimulator debugを実ビルド成功。各bundle ID・名称・翻訳と東京Firebase保持/仙台Firebase分離の検査成功 |
| Xcode生成設定 | `configure_ios_flavors.rb --check` 成功。実行schemeは2都市のみ |
| Windows read-only/東京入力・仙台モデル回帰 | **277件成功** |
| 共通v2委譲・仙台独立回帰 | Python 3.11 / 3.12で **各89件成功** |
| Lambda image | CI内のDocker build/import検査成功。デプロイ無し |
| 構文・資産整合 | ARB JSON、Python compile、shell/PowerShell構文、`git diff --check` 成功 |

東京と仙台のFlutter profile・既存Xcode configuration block、残す翻訳値は変更前と一致。東京の `toei_*` / `tokyo_*`・Realtime・TestFlight workflow・両都市のnativeアイコンと、仙台のAdapter・原入力fixture・oracle・取得検証ツールに差分は無い。実行コード・設定・翻訳に廃止都市参照が無いことを確認した。残る都市名は拒否回帰と過去の共通監査記録/撤去記録の記述だけである。

資料中の古い仙台ID表記は、現行コードの `jp.cloxs.go.sendai` へ合わせた。Android/iOSのアプリID自体は変更していない。

## CI時間比較

基準は [38836806011](https://github.com/kaeruko/tobus_go/actions/runs/38836806011)、整理後は [38854101108](https://github.com/kaeruko/tobus_go/actions/runs/38854101108)。同じCI workflowの実測時刻で、開始待ちを含む全体時間と各jobの開始〜終了を比較した。Flutterは双方3.47.7。runner/cache/待ち時間の差を含む1回比較であり、恒常的な短縮保証とはしない。

| 指標 | 変更前 | 変更後 | 差 |
| --- | ---: | ---: | ---: |
| CI全体（run開始〜完了） | 18分05秒 | **8分54秒** | **9分11秒短縮（50.8%）** |
| Windows shared-network probe | 1分45秒 | 1分48秒 | 0分03秒増加 |
| Python API tests | 1分41秒 | 1分55秒 | 0分14秒増加 |
| Shared SearchCore v2 (Python 3.12) | 0分28秒 | 0分30秒 | 0分02秒増加 |
| Repository safety checks | 0分11秒 | 0分16秒 | 0分05秒増加 |
| Flutter analyze and Android flavors | 8分40秒 | 7分24秒 | 1分16秒短縮 |
| Shared SearchCore v2 (Python 3.11) | 0分53秒 | 0分59秒 | 0分06秒増加 |
| iOS flavor builds and isolation | 16分41秒 | 8分08秒 | 8分33秒短縮 |
| 全7jobの実行時間合計（並列実行） | 30分19秒 | 21分00秒 | 9分19秒短縮 |

iOS jobは8分33秒短縮、Flutter/Android jobは1分16秒短縮。一方Python API jobは14秒増加したため、全jobが高速化したとはしない。変更前984件→整理後823件というテスト数の削減と、job時間は別の指標である。

変更前の撤去対象ビルドstepはAndroid 34秒＋38秒、iOS 212秒＋226秒。廃止都市のビルド・アイコン生成自体を削除し、東京/仙台のビルドや回帰を省略して短縮したものではない。
