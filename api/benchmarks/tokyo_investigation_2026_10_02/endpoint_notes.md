# 東京の経路探索前後にある高速化候補（2026-10-02）

本番コードは変更していない。ネットワーク境界をモックに置き換え、既存API関数・ZIPパーサー・運行日フィルター・列車便の厳密照合を実行した。本番の通信時間やLambdaの起動時間は実測していない。

## 確認結果

`endpoint_probe.py` を `api/` から実行し、結果を `endpoint_probe_results.json` に保存した。

- 初回の `/train/resolve-route-identities` は同じ `Toei-Train-GTFS.zip` を直列に2回取得する。2回目以降の追加取得は0回。初回・2回目とも同じ `trip_id=121603T0`、出発時刻 `16:25`、棄却なしを確認した。
- 同時に3件の `/route` 関数を呼んでも、探索エンジンの同時実行数は1。3件とも探索するため、同じリクエストの合流はない。
- 関連する既存Pythonテスト12件が通った（`test_train_route_identity`、`test_train_route_identity_late_night`、`test_train_service_calendar`、`test_train_realtime_http`）。

## 優先度が高い候補

### 鉄道GTFSの初回ロードを1回に共有する

`api/app/train_routes.py:70` が `get_static_gtfs()`、次の71行が `get_active_train_trip_ids()` を待つ。前者は `api/app/services/train_realtime.py:681`、後者は `api/app/services/train_service_calendar.py:275` で同じURLのZIPを取得する。別々のキャッシュを持ち、初回は同じファイルを二重にダウンロード・解凍し、`trips.txt` も二重に読む。

共有する同一版のZIPロード／コンパイル済みデータから、便データとカレンダーを作れば1回分の取得・解凍が省ける。秒単位の効果は未測定。別々のダウンロード間にデータ版が変わる問題も避けられる。便の厳密照合・運行日適用・曖昧一致の棄却は維持する。

### 鉄道identity解決を `/route` 応答までにまとめる

`lib/services/route_search_service.dart:89` で `/route` を待ち、鉄道区間があれば102行で `/train/resolve-route-identities` をもう1回待つ。鉄道候補の便確定を同じ応答内で行えば、APIの往復1回と候補全体の再送・再JSON化を省ける。厳密照合自体は必要なので、チェックの削除で置き換えない。

現状の通信順序は `test/route_search_train_identity_test.dart` にも明示されている。本番通信時間を測っていないため、削減秒数は未算出。別APIへの2回目の呼び出しが別Lambdaインスタンスになる場合の起動も抑えられる可能性がある。

### 同じ探索の連打をまとめ、古い探索の後続処理を省く

`lib/providers/route_search_provider.dart:196` の `triggerSearch()` は毎回サービスを呼び、同じ引数でも重複抑止がない。244行の世代チェックはサービス全体が終わった後なので、古い `/route` 応答にも鉄道identityの追加HTTP・照合が実行される。`lib/pages/home_page.dart:520` の検索ボタンも処理中に押せる。

同じ出発地・到着地・出発分・優先条件・交通モードの実行中リクエストを共有することが候補。入力変更の連続時は短い待ち時間で最後の変更をまとめる、または古い探索に対するidentity解決前に失効をチェックする。同時リクエストは `/route` のロックで直列になるので、不要な処理は後続の有効な探索を待たせる。HTTPの中断だけでは既に実行中のワーカースレッドの計算が止まるとは限らない。

## 追加測定が必要な候補

- `api/app/services/train_route_identity.py:444` は鉄道区間ごとに全便を走査し、駅名列の正規化と部分列比較を繰り返す。静的データロード時に出発駅名・出発時刻で候補便を引ける索引と正規化済み駅名列を用意できる。残った便には現在と同じ全駅列・到着時刻・曖昧性の検証が必要。ローカルに鉄道GTFS全量がないため、本番データでの時間は未測定。
- `api/app/services/train_service_calendar.py:55` は同じ運行日でも全便のサービスIDを走査し、`api/app/train_routes.py:75` で再度全便を絞り込む。同一データ版・運行日のactive-trip集合を限定キャッシュできる。データ版の更新とともに無効化する。
- `api/app/route_endpoint.py:110` はインスタンス内で探索を直列化する。ただしPythonの計算をスレッドで並列にしても高速になるとは限らず、Lambdaで単一リクエストを処理する条件では利点が小さい。まず重複呼び出しの合流を優先する。

## 既に対策されている箇所／探索の通信待ちではない箇所

- 東京のLambda起動は `api/app/tokyo_runtime_fast.py` で事前構築グラフとコンパイル済みバスGTFSを使う。86〜88行のコメントどおり、GTFS-Realtimeの取得を起動完了の待ちに含めない。
- Flutterの `/warmup` は `lib/core/api_client.dart:44` でFutureを共有し、`lib/widgets/place_field.dart:196` で先行開始する。地点入力欄ごとの二重warmupにはならない。
- 東京の近傍探索は既にSpatialIndexを利用する（`api/tokyo_route_engine.py:204`）。他都市の全stop走査の提案は東京には適用しない。
- `/route` の探索中にODPT HTTP取得を待つ経路は見つからなかった。既存の遅延状態のスナップショットを使う。通信を減らす候補は主に上記の鉄道identity後処理。
- `api/tokyo_route_engine.py:394` は検索後に明示的なfull GCを行う。探索本体のprofile担当が実データで測定するため、このプローブでは時間を測っていない。

## 再実行

```powershell
python benchmarks/tokyo_investigation_2026_10_02/endpoint_probe.py --output benchmarks/tokyo_investigation_2026_10_02/endpoint_probe_results.json
python -m unittest tests.test_train_route_identity tests.test_train_route_identity_late_night tests.test_train_service_calendar tests.test_train_realtime_http
```
