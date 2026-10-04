# 東京探索：上限余裕とRSSの追加測定

2026-10-05。十間橋→渋谷区役所、2026-10-04 20:40出発、バス・鉄道、limit=5。基準3モードをそれぞれ独立プロセスで初回＋再実行2回、入力変動6ケースを各独立プロセスで1回測定した。全結果は [rss_results.json](rss_results.json)、再現手順は [rss_probe.py](rss_probe.py)。

## 今回の修正

1. 同じバス便・停車順序・時刻でも、新規乗車直後と継続乗車後では降車時間が1分／0分となる。従来の未来状態キーがこれを区別せず、合法な終便乗換を消す反例を3モードで確認し、段階をキーに追加した。これは探索状態の修正であり、ナビゲーションの降車確認は変更していない。
2. 1,000popごとに既に無効なheap要素を整理する。有効な要素のpriority・sequence・label・親参照とfrontierは保持する。歩行・旅行時間・pop・展開・15秒の上限は維持し、整理時間も時間制限に含める。
3. `time` では待機可能な同じ非乗車状態の厳密な早着が、同等以下の徒歩資源を持つなら、高いprefix costでも後着状態を支配できる。同時刻ではcost比較を残す。公開目的の最速到着に対する規則であり、同着時の全行程costや乗車回数の最適性まで保証しない。

逆向きA*、costの乗車回数key統合、非支配集合の件数制限は導入していない。

正式APIテスト350件PASS。今回の追加は [バス乗車段階3件](../../tests/test_tokyo_bus_board_phase_regression.py)、[キュー整理4件](../../tests/test_tokyo_heap_compaction.py)、[到着時刻優先の支配3件](../../tests/test_tokyo_time_dominance.py)。修正前や不適切なcost条件へのin-memory復元で対応テストがFAILすることも確認した。`git diff --check` はPASS。

## 基準経路の結果

時間は検索アダプター・コア内の便索引前処理・詳細化・整形・鉄道便ID照合を含む3回の中央値。データ起動時間・HTTP・ライブRTは含まない。

| モード | pop | 展開 | 最終active frontier label | 時間中央値 | 有効候補 |
| --- | ---: | ---: | ---: | ---: | ---: |
| cost | 89,986 | 88,745 | 109,555 | 3.54秒 | 5 |
| time | 88,663 | 85,532 | 111,378 | 3.66秒 | 1 |
| fewTransfers | 99,822 | 99,079 | 147,490 | 5.25秒 | 5 |

cost／fewTransfersのpop上限は100,000、timeはpop 200,000／展開100,000のまま。costの残りは10,014pop、fewTransfersは178pop。各入力で5候補を得ても、fewTransfersの余裕は不足しており、目的地下界で探索順を改善する必要は残る。

キュー整理で除いた要素はcost 23,581、time 42,224、fewTransfers 8,259。これらは全て従来popでも展開されない要素であり、実際に展開する状態数を直接減らすものではない。

基準の候補と順序はUUIDのstep_idを除き、過去の `implementation_*_route.json` と3回とも一致した。cost／fewTransfersは22:14、22:16、22:26、22:19、22:28到着、全て3回乗車・2回乗換。timeは22:14到着。公式鉄道GTFSの2026-10-04運行便で全候補が便照合を通り、拒否は0件、鉄道便IDは `432009A0`。候補5件は現在の取得・重複除去契約による結果であり、厳密な上位k件保証ではない。

## RSSと保持メモリ

Windows 11、Python 3.12.10、64bit。Windows working setをRSS相当の常駐メモリ指標として計測した。MiBは2^20 bytes。OSのPeakWorkingSetSizeはプロセス生涯の正確な最大値、クエリ中の値と増分はサンプリング値である。

| モード | OS生涯ピーク（3回終了時の最大） | クエリ中サンプル最大（3回の範囲） | クエリ開始からのサンプル増分 |
| --- | ---: | ---: | ---: |
| cost | 1,249.0MiB | 1,248.0〜1,248.3MiB | 33.4〜40.4MiB |
| time | 1,248.7MiB | 1,248.1〜1,248.5MiB | 32.3〜40.1MiB |
| fewTransfers | 1,270.0MiB | 1,268.7〜1,269.6MiB | 56.2〜60.8MiB |

約1,270MiBは約1.24GiB。探索前の保持データだけで約1,203MiBある。costプロセスのロード段階別RSSは次のとおり。

| 段階 | RSS |
| --- | ---: |
| アプリimport前 | 19.5MiB |
| 探索・便照合のimport後 | 58.0MiB |
| 更新済みprebuilt読込後 | 615.3MiB |
| バスcompiled GTFS読込後 | 1,114.2MiB |
| 鉄道GTFS・calendar読込後／GC後 | 1,203.2MiB |

prebuiltとcompiledバスGTFSが常駐量の大部分を占める。labelのメモリを無視できるという意味ではなく、探索前の基礎データとクエリ追加分を分けて改善を測る必要がある。`frontier_labels` はその時点でactiveなfrontier要素数で、展開済みも含む。親から参照される無効label、具体便索引、heap、dict、floatなどを含む全生存オブジェクト数ではない。

結果を解放して追加GCした後のRSSは、3回にわたりcost 1,213.5→1,215.0→1,217.9MiB、time 1,211.2→1,216.2→1,221.3MiB、fewTransfers 1,213.1→1,213.3→1,216.9MiBとなった。短い3回の測定だけでメモリリークの有無は判断できない。CPythonの解放済み領域がOSへ返らない場合もあり、長時間warmプロセスの追加測定は別の確認事項となる。

## 入力の小さな変動

各ケースの候補はcost／fewTransfersとも5件、鉄道便照合の拒否0件、探索未完了なし。OSピークはそのケースの独立プロセスの生涯最大。

| 変更 | cost pop | fewTransfers pop | cost OSピーク | fewTransfers OSピーク |
| --- | ---: | ---: | ---: | ---: |
| 出発20:39 | 89,967 | 99,807 | 1,248.0MiB | 1,269.3MiB |
| 出発20:41 | 90,038 | 99,847 | 1,248.1MiB | 1,269.5MiB |
| 目的地を東へ約20m | 86,238 | 99,773 | 1,246.8MiB | 1,269.1MiB |

今回の3変動だけでは上限へ到達しなかった。fewTransfersは最も厳しい入力で153popしか残らず、任意の小さな変化への安定性を保証しない。

## 測定の範囲と限界

- バスはローカルCSVの61,324便・1,161,955 stop_timesをzip化し、製品コンパイラーで生成したcompiled stateを製品loaderで読む。古い別版のcompiled stateを混ぜない。元CSV・生成物・探索ソース・鉄道zipのSHA-256を各報告に記録した。
- prebuilt、バス、全静的鉄道GTFSとcalendarを保持し、対象日のactive鉄道便ビューで照合する。これは鉄道便照合を一度使ったwarm runtimeのデータ所有形態に近い。`/route` 単独から鉄道GTFSを遅延ロードしていない状態より約89MiB多く、FastAPI・Mangum・boto3・バックグラウンドRTの全起動は含まない。
- 各queryは静的clockを使用し、実HTTPやライブRT、Lambdaは呼ばない。過去の実走行やリアルタイム運行を証明する測定ではない。
- query samplingの目標間隔は10msだが、実測の最大間隔は基準で約239〜300ms。GIL等で短いピークを取り逃すため、サンプル値は下限として扱う。OS生涯ピークも別に記録し、起動前後の値から探索時のピークと混同しない。
- LambdaのDockerfileはPython 3.11。OS・Python世代・allocator・依存物が異なり、Windowsの数値をLambda/Linuxの使用量や設定済みMemorySizeと同一視できない。Docker daemonは利用できず、AWSの読込認証も期限切れのため実機メモリと現行MemorySizeは未確認。本番デプロイ・設定変更は行っていない。

## 過去の測定との関係

`implementation_results.json` の96,932／96,319popと130,945 labelは、バス乗車段階のキー不足が残っていた時点の値。最新の正しい状態量は上表を使用する。

[rss_before_bus_phase_fix/](rss_before_bus_phase_fix/) は修正前のメモリ測定、[rss_before_heap_compaction/](rss_before_heap_compaction/) は段階を修正した後・キュー整理前の測定を保存している。後者ではcostが100,001popで生候補4件、fewTransfersが100,001popで生候補0件、timeが100,001展開で生候補0件となり、APIとしては探索未完了だった。最新の成功は上限を増やした結果ではない。

修正前RSS測定の `same_as_previous_baseline_excluding_step_ids=false` は比較時点の計測不備である。鉄道便照合が共有のstopオブジェクトへ注記を追加した後、照合前の保存候補と比較していた。最新probeでは照合前のコピーで比較しtrueを確認した。過去のfalseを候補変更の証拠として扱わない。

今回のRSSは、キュー整理だけでメモリが大幅に減るとは示していない。次のA*測定では、下界前処理・目的地キャッシュの保持分も加え、最終便照合済み候補、展開・pop余裕、プロセス生涯ピーク、warm保持量を一緒に比較する。costにはfewTransfers用辞書式下界の第2成分を転用せず、独立したcost下界を検討する。[cost削減監査](cost_pruning_audit.md)に安全条件を記録した。

```powershell
& 'api/.venv-route/Scripts/python.exe' -X utf8 api/benchmarks/few_transfers_pruning_2026_10_04/rss_probe.py
```
