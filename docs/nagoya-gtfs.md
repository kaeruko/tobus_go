# 名古屋市バス GTFS-JP の取り込み

Phase 4 (#134) では、名古屋市バスの公式 GTFS-JP を `TransitDataset` に取り込み、都営 ODPT に依存しない静的乗換検索を行う。

## 公式ソース

- BODIK / 名古屋市オープンデータカタログ
- dataset ID: `c5794008-8053-42ab-99b9-ee7f6fdf9a9e`
- configured resource ID: `125a1d12-7df6-489c-abde-911856e05d1b`
- configured resource label: `2026-03-28` 改正版
- license: CC BY 4.0

2026-08-21 時点でカタログに見えている新しいリソースは 2026-03-28 改正版だが、一部の交通局公式時刻表ページには 2026-07 の日付も表示されている。このため、2026-03-28 をアプリ側で「常に現行」と決め打ちしない。

## revision guard

名古屋 backend は `NAGOYA_GTFS_EXPECTED_REVISION` を必須とする。値は `YYYY-MM-DD` 完全一致で、空白除去や表記変換はしない。

runtime は `NAGOYA_GTFS_DIR/nagoya_gtfs_manifest.json` の `dataset_id / resource_id / revision` を検証し、期待 revision と一致しなければ起動を停止する。古い feed への自動 fallback は行わない。

取得時も CKAN `package_show` の dataset/resource ID を照合し、resource 名から読み取った改正日が `--expected-revision` と一致しなければ ZIP を採用しない。

```bash
python scripts/fetch_nagoya_gtfs.py \
  --output data/nagoya/2026-03-28 \
  --expected-revision 2026-03-28
```

これは取得機構の例であり、`2026-03-28` を公開用の現行版として承認する意味ではない。公開デプロイでは、交通局の現行ダイヤと GTFS resource の対応を確認したうえで `NAGOYA_GTFS_EXPECTED_REVISION` を設定する。

## backend 起動

```bash
APP_CITY=nagoya \
NAGOYA_GTFS_DIR=data/nagoya/2026-03-28 \
NAGOYA_GTFS_EXPECTED_REVISION=2026-03-28 \
python -m ...
```

名古屋 runtime は `ODPT_API_TOKEN` を要求しない。東京用 `runtime.py / routes.py / train_routes.py` は `APP_CITY=nagoya` の app factory 経路では登録されない。

名古屋版の realtime capability は無効で、`/bus/location` と `/realtime/update` は `bus_realtime_unsupported` を明示して 503 を返す。非公開の接近情報 API や HTML scraping へ自動的に切り替えない。

## 現在の範囲

- 名古屋市バス GTFS-JP のみ
- 最寄り停留所候補 + 徒歩 + 静的時刻表による経路検索
- `time` と `fewTransfers` をサポート
- Flutter の legacy default `cost` は、画面上で選択されている「乗換少ない優先」として明示的に定義
- 地下鉄はこの Phase の対象外
- GTFS-Realtime は対象外

Flutter 側は `routeSearchOnly` capability により `RouteOnlyHomePage` / `RouteOnlyDetailPage` を使い、みつける・お気に入り・履歴・おでかけ作成・リアルタイム UI を出さない。
