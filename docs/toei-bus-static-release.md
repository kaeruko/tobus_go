# 都営バス静的トポロジー更新

都営バスのODPT `BusstopPole` / `BusroutePattern` と、具体便を供給する
GTFSを別々に更新した結果、検索グラフと具体便の停車順が食い違うことを防ぐ手順です。

## 固定中のスナップショット

`api/config/toei_bus_static_release.json` がレビュー済みODPT入力を固定します。
2026-10-26版は、公式公開APIから取得した次の入力です。

- `BusstopPole`: 3,690件、SHA-256
  `afe8e0ad609f917afedc2b880f2cad95c8721a5d80d97aaaba9134cceed26771`
- `BusroutePattern`: 757件、SHA-256
  `a3809dcc76c600290fc1523f758f6bb91201f9d0ac01742c9689826d9641638e`

ライセンスはCC BY 4.0です。東京都交通局および公共交通オープンデータ協議会の
帰属表示を維持します。取得に秘密キーは使いません。

この更新では廃止された枝川一丁目2poleを除き、枝川と枝川二丁目を直接結ぶ
現行パターンへ更新します。レビュー時の都営バスGTFSはfeed version
`20261025_030830`、ZIP SHA-256
`271e59c0a0e1ad629141114edc415c710c9cf614721e5c83c7c53d862efc06e0`
です。

## 取得とビルド

リポジトリのルートから実行します。

```powershell
python scripts/sync_toei_bus_static.py
$env:ENABLE_TOKYO_METRO_STATIC = "1"
python api/prebuild.py
```

東京メトロの固定済みGTFS・駅・路線・レビュー済み乗換manifestは、既存の
東京メトロrelease runbookに従って事前に `api/data` へ配置します。

同期スクリプトは、全ファイルのSHA-256と件数が固定manifestに一致するまで
既存ファイルを置換しません。公式データが更新されてハッシュが変わった場合、
新しい値を自動採用せず、差分・GTFS整合性・代表検索をレビューしてmanifestを
更新します。

`prebuild.py` は次の両方を満たさない限り `app_data.pkl` を生成しません。

1. ODPT入力が固定manifestとバイト単位で一致する。
2. グラフ上の全都営バス隣接区間と、GTFS全具体便の隣接区間が双方向に完全一致する。

生成物には確認した入力ハッシュと整合性件数を記録します。生ODPT JSON、GTFS、
pickleはリポジトリへコミットしません。

## 起動時ゲート

Lambdaの高速起動でも、ダウンロード済みpickleとversion付きcompiled GTFSを
ロードした直後に同じ双方向整合性を確認します。不一致時は起動を失敗させ、
旧時刻表、ODPT時刻表fallback、0分区間などへ暗黙に切り替えません。

GTFS週次更新はトポロジーを変えない限りそのまま通ります。新しい停留所順を含む
GTFSは、対応するODPTスナップショットとpickleが準備されるまで公開対象にしません。

## リリース前の必須確認

- 同期スクリプトの出力に秘密値がないこと。
- `prebuild.py` の隣接区間差分が双方0件であること。
- 都営のみの固定回帰と東京メトロ全7スコープが一致すること。
- 代表性能測定を更新すること。
- 新しいpickleとcompiled GTFSの対応を非本番環境で確認すること。

本書とコードだけではAWS資源は変更されません。S3更新、Lambda検証、本番切替は
それぞれ別の承認と作業記録を必要とします。
