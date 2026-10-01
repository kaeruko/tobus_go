# 東京の経路探索・高速化検証

検証日: 2026-10-02（日本時間）。東京だけを対象に調査した。製品コード・設定・デプロイは変更していない。改善版は計測プロセス内で関数のコピーを差し替えた。

## 結論

最優先は **cost / fewTransfers で、採用されない候補を時刻表検索の前に除外すること**。徒歩上限と既存候補のコストを先に比較するだけで、新宿→浅草の fewTransfers は中央値 897.7 ms → 444.7 ms（約50%短縮）になった。

取得済みの辺の再利用、検索内の距離推定キャッシュ、DEBUG_BUS の検索開始時の固定を合わせると、同じ条件は **401.1 ms（約55%短縮、2.24倍）**。通常2区間とバスのみ1区間の3モード、計9条件・135回の比較で、候補順・経路・発着時刻・詳細行程を含む返却辞書が一致した。変更版に対する東京の既存テスト19件も成功した。

座標の準備・仕上げ・契約検証・明示的GCを含む `TokyoRouteEngine.search()` と応答の変換でも、新宿→浅草 fewTransfers は **1,041.6 ms → 534.4 ms（約49%短縮）** だった。HTTP通信や起動時間は含まない。

## 計測条件

- Windows 11、CPython 3.12.10、既存の `api/.venv-route` を使用。
- 手元の `api/data/app_data.pkl`（148,550,621 bytes）を使用。18,984ノード・63,970辺。
- ローカルの都営バスGTFS 61,324便を読み込み、2026-10-02・10:00・静的時刻表で検索。リアルタイム遅延、運休、HTTP通信はこの速度比較に含めない。
- 各条件を1回実行してから、現行版と4種類の実験版を3回ずつ測定。実行順を回転して中央値を比較した。
- 以下は `search_best_routes_once()` の時間。データ読み込み、座標からの近傍選択、TokyoRouteEngine の仕上げ処理と明示的GCは含まない。詳細行程の生成・発着時刻の検証は含む。ログはメモリに取り込んだ。
- 3回の測定であり、本番のp95やLambda上の改善率を示す値ではない。

## 探索本体の比較

「先行判定」は徒歩上限と、cost / fewTransfers の既存最良コストを `advance_time()` の前に確認する実験。「併用版」はこれに辺の再利用、cost の距離推定キャッシュ、DEBUG_BUS の固定を合わせた実験。

| 条件 | モード | 候補数 | 現行中央値 | 先行判定のみ | 併用版中央値 | 併用版の短縮率 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 東京駅→豊洲 | time | 1 | 219.6 ms | 214.6 ms | 171.3 ms | 22% |
| 東京駅→豊洲 | cost | 5 | 75.2 ms | 43.0 ms | 36.3 ms | 52% |
| 東京駅→豊洲 | fewTransfers | 5 | 292.9 ms | 159.5 ms | 138.7 ms | 53% |
| 新宿→浅草 | time | 1 | 203.3 ms | 200.2 ms | 165.4 ms | 19% |
| 新宿→浅草 | cost | 5 | 124.5 ms | 72.7 ms | 69.1 ms | 45% |
| 新宿→浅草 | fewTransfers | 5 | 897.7 ms | 444.7 ms | 401.1 ms | 55% |
| 東京駅→豊洲・バスのみ | time | 1 | 94.6 ms | 92.1 ms | 74.7 ms | 21% |
| 東京駅→豊洲・バスのみ | cost | 5 | 82.1 ms | 51.6 ms | 43.7 ms | 47% |
| 東京駅→豊洲・バスのみ | fewTransfers | 5 | 289.1 ms | 188.4 ms | 156.9 ms | 46% |

生の測定値と各回の一致判定: [fast_variants.json](../api/benchmarks/tokyo_investigation_2026_10_02/fast_variants.json)。

## 応答生成・GCまで含めた比較

新宿→浅草を `TokyoRouteEngine.search()` と `serialize_route_result()` で測定した。初期徒歩・近傍選択・英語名検証・メタデータ・ステップIDの付与・明示的GCを含む。条件ごとに1回実行した後、3種類の実装を3回ずつ測り、順序を回転した。

| モード | 現行中央値 | 併用版中央値 | 短縮率 | GC省略の診断値 |
| --- | ---: | ---: | ---: | ---: |
| time | 293.9 ms | 243.4 ms | 17% | 155.9 ms |
| cost | 214.4 ms | 153.7 ms | 28% | 58.7 ms |
| fewTransfers | 1,041.6 ms | 534.4 ms | 49% | 429.2 ms |

27回すべて成功し、毎回生成されるUUIDの `step_id` だけを比較から除いて全返却項目が一致した。GC省略は効果の切り分けのための診断で、採用確定の値ではない。結果: [adapter_variants.json](../api/benchmarks/tokyo_investigation_2026_10_02/adapter_variants.json)。

## 効果の根拠と実装候補

### 1. 時刻表を引く前に不要な候補を除外する

`api/toei_engine.py:1913` / `:2143` は `advance_time()` を呼び、その後に徒歩距離上限と `g_score` を比較している。徒歩量・乗車回数・候補キー・候補コストは時刻表を引く前に算出できる。現行と同じ比較で除外し、`g_score` の更新は時刻計算に成功した後に残す。

新宿→浅草 fewTransfers のプロファイルでは、併用版で次のように変わった。

| 処理 | 現行 | 併用版 |
| --- | ---: | ---: |
| `advance_time()` 呼び出し | 422,341回 | 94,036回 |
| バスの次発検索 | 145,162回 | 25,968回 |
| キュー取り出し | 61,191回 | 61,191回 |
| 経路チェーン生成 | 78,094回 | 78,094回 |

探索した候補を減らさず、同じ探索に必要のない時刻評価を省けた。現行のプロファイルでは `advance_time()` が累積時間の約53%を占めた。プロファイル自体の計測負荷があるため、その秒数は上の速度比較には用いていない。

### 2. 重複アクセスと検索内の固定計算を減らす

- `api/toei_engine.py:1902` / `:2132` / `:2354`: `G[u]` の辺を取得した後、`advance_time():1347` で `has_edge()` と `G.edges[u,v]` により同じ辺を取得し直している。辺を一度取り出して渡すことが候補。単独効果は条件によってばらつき、東京駅→豊洲 time では遅くなった。先行判定より優先度は低い。
- `:1798`: cost の距離推定は同じノード・目的地なら固定。キャッシュを1回の検索内に限定すると、目的地変更・グラフ更新による古い値の利用を防げる。
- `:899`: バスの次発検索ごとに `os.getenv("DEBUG_BUS")` を呼んでいる。現行の新宿→浅草 fewTransfers では145,162回。検索開始時に値を固定して渡せば繰り返し取得を省ける。実験は同じ設定値で比較した。デバッグ設定を反映するタイミングを検索開始時に揃える設計が必要。

各実験の個別値は `fast_variants.json` に保存した。heuristic と DEBUG_BUS は組み合わせて測定しており、個々の寄与率は分離していない。

### 3. 検索ごとの明示的GCの頻度を見直す

`api/tokyo_route_engine.py:394` は検索の終了ごとに `gc.collect()` を実行する。グラフを読み込んだだけの状態でも、7回の中央値58.4 ms、範囲52.5〜82.6 msを要し、全回で回収対象は0だった。結果: [gc_probe.json](../api/benchmarks/tokyo_investigation_2026_10_02/gc_probe.json)。

実際の応答生成を含む比較では、明示的GCの18回の中央値94.5 ms、範囲88.2〜154.6 ms、全回で回収対象0だった。検索の繰り返しによる索引・キャッシュが載った状態の固定費として無視できない。

頻度を減らす余地はあるが、今回の短時間試験だけでは長時間運転時のメモリ量を判断できない。削除・間引きの採用前には連続検索時の常駐メモリとピークを比較する。

### 4. 鉄道候補の初回通信・後処理をまとめる

探索後の鉄道便ID確定では、`api/app/train_routes.py:70` の `get_static_gtfs()` と `:71` の `get_active_train_trip_ids()` が、別々のキャッシュから同じGTFS ZIPを取得する。実API関数とパーサーを通し、ネットワーク境界だけをモックにした検証で **初回2回・2回目の追加取得0回** を確認した。便と運行日を同一版のロードから生成すれば初回の取得・解凍を1回省ける。

また、`lib/services/route_search_service.dart:89` は `/route` を待った後、鉄道候補があると `:102` で便ID解決を待つ。便の厳密照合を同じ応答に含めればHTTP往復を1回省ける。本番の通信時間は未測定。

同じ条件の検索連打の合流も候補。現行の世代チェックはサービス終了後で、古い検索にも鉄道便ID解決が行われる。APIの探索ロックは同時3件でもエンジンの最大同時実行数1だった。まず重複呼び出しを抑止する方が、ロック解除より効果を説明しやすい。

詳細と再現条件: [endpoint_notes.md](../api/benchmarks/tokyo_investigation_2026_10_02/endpoint_notes.md)、[endpoint_probe_results.json](../api/benchmarks/tokyo_investigation_2026_10_02/endpoint_probe_results.json)。

## 優先度を下げた候補

列車時刻表の駅・次駅別索引化は可能だが、今回の新宿→浅草 fewTransfers では列車検索が441回、プロファイル累積約16 ms（全体の約0.5%）。バスを含む不要な時刻評価の削減を先に進める方が有効だった。

索引化の計算結果については、静的検索・遅延・運休・週末・深夜など5,184条件で現行との不一致0を確認した。リアルタイム検索に元の発車時刻の二分探索を使うと遅延便を見落とす反例も確認した。遅延反映時は元の順番を保つ別の処理が必要。

東京の近傍探索は既にSpatialIndexを使用している。バス時刻表も次発時刻の二分探索と日付別キャッシュを持つため、これらを新設する提案は優先しない。

## 正確性の検証

- 9条件 × 5実装 × 3回 = 135回、返却辞書の比較で不一致0、例外0。
- 応答生成・GC込みの3モード × 3実装 × 3回 = 27回、UUIDの `step_id` を除いた比較で不一致0、例外0。
- 現行版の東京関連既存テスト19件成功。併用版をメモリ上で適用した状態でも同じ19件成功。記録: [combined_tests.json](../api/benchmarks/tokyo_investigation_2026_10_02/combined_tests.json)。
- 鉄道便ID・運行日・HTTP取得の関連既存テスト12件成功。
- 列車時刻表の軽量検証5,184条件・不一致0。記録: [timetable_validation.json](../api/benchmarks/tokyo_investigation_2026_10_02/timetable_validation.json)。
- GTFS未ロードの準備時記録には `without_gtfs` を付け、採用評価には使用していない。

## 再現

リポジトリのルートから、手元の同じデータを使用する。外部通信・製品ソースの変更は行わず、同じフォルダの結果ファイルを更新する。

```powershell
& .\api\.venv-route\Scripts\python.exe -X utf8 .\api\benchmarks\tokyo_investigation_2026_10_02\investigate.py --stage baseline
& .\api\.venv-route\Scripts\python.exe -X utf8 .\api\benchmarks\tokyo_investigation_2026_10_02\investigate.py --stage fast
& .\api\.venv-route\Scripts\python.exe -X utf8 .\api\benchmarks\tokyo_investigation_2026_10_02\investigate.py --stage adapter
& .\api\.venv-route\Scripts\python.exe -X utf8 .\api\benchmarks\tokyo_investigation_2026_10_02\gc_probe.py
& .\api\.venv-route\Scripts\python.exe -X utf8 .\api\benchmarks\tokyo_investigation_2026_10_02\timetable_validation.py
& .\api\.venv-route\Scripts\python.exe -X utf8 .\api\benchmarks\tokyo_investigation_2026_10_02\endpoint_probe.py --output .\api\benchmarks\tokyo_investigation_2026_10_02\endpoint_probe_results.json
```

実験スクリプトは現在の関数ソースからコピーを作る。対象の実装が変わった場合は置換箇所と比較条件を見直す。

入力データ・製品ソースのSHA256と計測スクリプトの説明は [検証用README](../api/benchmarks/tokyo_investigation_2026_10_02/README.md) に保存した。
