# 仙台版の保留（2026-10-18）

現在の開発・配布対象は東京版と共通機能。仙台版は保留中です。
保留前のmainは `47d70a39c85433ff9828d49dc826cd13af6d778f` です。

## 通常のビルド・CI

- Androidの有効flavorとiOSの共有schemeは `tokyo` のみ。
- 仙台専用ワークフロー5本は `.github/pending/sendai/workflows/` に退避。
  自動実行・手動実行・GTFS取得の対象になりません。
- Chrome E2Eと共通ドライバーは `.github/pending/sendai/integration_test/` と
  `.github/pending/sendai/test_driver/` に退避。
  これらだけが使用していた `integration_test` SDK依存と専用の推移依存は、
  通常アプリの `pubspec.yaml`・`pubspec.lock` から外しています。
  東京のプラグイン登録・release AABに保留中のテスト用プラグインを含めません。
- 通常CIとTestFlightのテストは `scripts/run_active_tests.py` を使用。
  仙台専用スイートを収集せず、Python側では共通テストからの仙台実装のimportもエラーにします。
- Flutterの共通ファイル内に残る仙台用テストは `sendai` タグで識別し、
  `dart_test.yaml` で既定除外。東京のテストと共通探索エンジンのテストは継続します。
- 仙台専用Dartソース・テスト・E2Eは通常のanalyze対象から除外。
  東京のホーム画面は仙台専用ウィジェットをimportしません。
- 東京用API Dockerイメージには仙台専用Pythonモジュールをコピーしません。
- `APP_CITY=sendai` のアプリ/API起動と、仙台のAAB作成・共通デプロイスクリプトは
  保留中の理由を示して停止します。既存の `SENDAI_REVIEWED_COORDINATES` では解除できません。

通常のローカル検証もリポジトリ直下から次を使用します。

```sh
python scripts/run_active_tests.py python
python scripts/run_active_tests.py flutter
```

`--list` を付けると、実行・importせず対象ファイルを確認できます。
`python -m unittest discover` の直接実行は保留中スイートも収集するため、保留期間中は使いません。
共通テストの都市名やfixtureに残る仙台の識別子は、都市分離・運賃契約などを確認する小さな固定値です。
仙台の経路探索・ランタイム・実GTFSを読み込むテストとは分離しています。

## 保存するもの

仙台のAPI・Flutter画面・交通アダプター・テスト・fixture・設計資料・素材は維持。
共通v2の仙台依存テストは `api/tests/test_sendai_v2_delegation.py` に保存しました。
iOSの既存ビルドconfigurationは維持し、schemeは
`ios/Runner.xcodeproj/xcshareddata/xcschemes/sendai.xcscheme.pending` に退避しています。
既存AWSリソース・公開済みアプリ・外部データはこの保留変更では操作しません。

## 再開するとき

1. この保留コミットの差分を確認し、仙台の起動・ビルド・配布ガードを解除する。
   Androidの `sendai` flavor（applicationId `jp.cloxs.go.sendai`）を復元し、
   iOS schemeの `.pending` を外す。iOS生成スクリプトの `PENDING_CITIES` から仙台を外す。
2. 保留前mainを参照して、ホーム画面の仙台ウィジェットへの接続を戻す。
   API Docker・Dart analyzeの除外も戻す。
3. 専用テスト・混在テストのタグ除外とactiveテスト選択を見直す。
   起動拒否のテストは再開後の仕様に合わせて更新する。
   退避した `integration_test/` と `test_driver/` をリポジトリ直下へ戻し、
   `dev_dependencies` に `integration_test: {sdk: flutter}` を復元して
   `flutter pub get` を実行する。再開するテストのanalyze対象も戻す。
4. GTFS・manifest・レビュー資料の版・日付・SHA・利用条件を再検証する。
   過去データや別ソースへ暗黙に切り替えない。
5. 仙台の単体テスト・実データ検証・Chrome E2E・Android/iOSビルドを確認してから、
   退避ワークフローを `.github/workflows/` に戻し、通常CIへの組み込みを判断する。

リポジトリ全体を過去の状態へ戻す操作や、保留後に進んだ東京・共通機能の巻き戻しは行いません。
