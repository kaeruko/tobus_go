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

アプリflavor/CI整理とPython/依存・文書整理を別コミットにした。

- ローカルPython: `python -m unittest discover -s tests -p 'test_*.py' -f -v`、**823件成功、69.071秒**（Python 3.12、専用venv）。
- ARB JSON、Python compile、shell構文、`git diff --check` 成功。
- GitHub ActionsによるFlutter analyze/test、東京・仙台のAndroid debug APKとiOS simulator debug、東京API回帰、仙台独立回帰・共通v2委譲、Windows/Lambda imageをこの後確認する。結果は確定後追記する。

## CI時間比較

基準runは上記38836806011。同じCI workflowの実測時刻を使い、開始待ちを含む全体時間、各jobの開始〜終了、実行時間合計を区別する。runnerやcache条件の差も含まれるため、1回比較を恒常的な短縮保証にはしない。

| 指標 | 変更前 | 変更後 |
| --- | ---: | ---: |
| CI全体（run開始〜完了） | 18分05秒 | 検証中 |
| iOS job | 16分41秒 | 検証中 |
| Flutter/Android job | 8分40秒 | 検証中 |
| Python API job | 1分41秒 | 検証中 |
| 全7jobの実行時間合計（並列実行） | 30分19秒 | 検証中 |

変更前の削除対象ビルドstepはAndroid 34秒＋38秒、iOS 212秒＋226秒。これらは基準runの観測値であり、変更後の短縮量として先取りしない。
