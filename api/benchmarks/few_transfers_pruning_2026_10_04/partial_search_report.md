# 東京探索：候補取得後の安全上限と部分結果

2026-10-05。対象は東京の候補収集層。先行のfewTransfers A*実装を維持し、探索上限は増やしていない。本番への反映は行っていない。

## 添付ログの判定

十間橋→渋谷駅、2026-10-05 07:18発、cost。生候補は12,766／15,501／86,457popで3件得られた。その後も要求数へ向けて探索し、14.125秒・100,001popで `reason=max_visited`、POST /routeは503となった。

直接の失敗原因は候補収集中の安全上限例外である。GTFS-RT DROPの後も探索・3件目のyieldが続き、15秒の時間制限による中断でもない。ただしログの3件は生候補であり、当該ログだけでは3件とも詳細化・後続の鉄道便照合を通るとまでは言えない。DROPが候補内容や探索量へ与える影響も、この例外の原因とは区別する。

## 実装

低レベルの共通label探索は引き続き `RouteSearchLimitError` を送出する。例外には文字列を解析せず `reason` と数値中心の `diagnostics` を付与する。

`search_best_routes()` の候補収集層だけが、既知の安全上限と生候補1件以上という条件で中断を捕捉する。対象理由は `max_visited / max_expanded / time_limit_sec / queue_size / g_score_size / max_search`。次の既存処理はそのまま通す。

- 同じ交通行程の重複排除と、短い徒歩経路からの検証。
- 選択済み時刻・具体便を使う到着時刻検証と詳細化。
- 東京アダプターの英語名検証・徒歩整数化・共通候補契約。

返却可能な候補が残れば、list互換の `TokyoSearchCandidates` で上限通知をアダプターへ渡す。レスポンスの `meta` にだけ以下を追加する。

```json
{
  "truncated": true,
  "termination_reason": "max_visited",
  "search_diagnostics": {
    "mode": "cost",
    "visited": 100001,
    "yielded": 3,
    "max_visited": 100000,
    "time_limit_sec": 15.0
  }
}
```

実際のdiagnosticsはqueue、frontier、展開数、経過秒なども含む。`yielded` は生候補数であり、重複排除・検証後の返却数はレスポンスの `candidates` を数える。

生候補0件、または到着時刻検証・詳細化後に0件の場合は元の上限例外を送出する。空リストに変換してfallback探索へ新たな予算を与えない。未知の理由・一般例外・契約違反も部分成功へ変換しない。通常の要求数到達やqueue枯渇では、追加metaを付けず従来の結果を返す。候補の補充探索は追加していない。

捕捉した例外のtraceback・context・causeは外し、queue／frontier全体を返却結果に保持しない。通常のlimit到達時も、詳細化に入る前にgeneratorを明示的にcloseする。

## 実データの確認

添付ログと同じ出発停留所・目的地座標・日時・cost・limit=5で、製品アダプター→詳細化→整形→公式鉄道GTFS便照合まで実行した。ローカルの保存データを使用し、GTFS-RT feedは添付されていないためリアルタイムを無効化した静的な対照である。

| 指標 | 静的対照の結果 |
| --- | ---: |
| 生候補のyield時点 | 12,728／15,450／86,202pop |
| 中断 | 100,001pop、max_visited |
| 検証・詳細化後の返却候補 | 3 |
| 鉄道GTFS照合後の候補 | 3、拒否0 |
| 到着時刻 | 08:30／08:36／08:39 |
| 前処理・詳細化・便照合込み時間 | 6.572秒 |
| meta | truncated=true、termination_reason=max_visited |

Windows／Python 3.12.10、HTTP・ライブRT・データ起動時間は時間に含めない。この入力でも3候補後に上限へ達し、修正した収集層が3件を保持することを確認できた。添付事故のリアルタイム再生や、当時の候補内容の完全一致を示す測定ではない。

Windows OS生涯working setピークは1,330.9MiB。中断時にactive frontier labelは210,742、queueは115,927まで増えている。今回の変更は既存候補の保持であり、cost側の探索状態数を削減する最適化は含めない。数値をLambdaのメモリへ換算しない。

## 正式テスト

APIテスト全389件PASS。追加した部分結果の回帰17件は、以下を確認した。

- cost／fewTransfersで既知6種の安全上限後に候補を返すこと。
- 生候補0件・到着検証後0件・詳細化後0件で同じ上限例外を送出すること。
- 3生候補から2件だけ検証を通ればHTTP 200とmeta、全件脱落ならHTTP 503でfallback再探索なし。
- 既存の重複排除・候補順、正常なlimitで追加popなし、正常終了時meta無変更。
- 未知の理由・非構造の上限例外・契約違反・一般例外を握り潰さないこと。
- 実label探索の小予算で実際に上限を超えた際、reasonとdiagnosticsが収集層へ伝わること。
- generator内部の状態が詳細化開始時に解放され、返却例外がtraceback等を持たないこと。

全API回帰には、先行A*、歩行資源、具体便、時刻、既存HTTP契約も含む。変更した製品ファイルと追加テストはPython 3.11文法で確認し、静的対照JSONのsource/data hashが現コードに一致することも確認した。

## APIとアプリの境界

HTTPで候補ありの部分結果は200、metaは共通serializerで保持される。候補なしの上限は既存の503／route_search_limit、契約違反は500を維持する。

現行Flutterは `/route` の後で `/train/resolve-route-identities` を呼び、鉄道照合で全候補が失われた場合は明示的なエラーを出す。この別APIと既存の便照合契約は変更していない。`RouteMeta` に新項目の取り込みや画面表示は追加していないため、打ち切り通知は現時点ではAPIレスポンス上の情報である。

## 再現資料

- [静的対照JSON](partial_search_2026_10_05_static.json)
- [実データprobe](partial_search_probe.py)
- [正式回帰テスト](../../tests/test_tokyo_partial_search.py)

```powershell
& 'api/.venv-route/Scripts/python.exe' -X utf8 api/benchmarks/few_transfers_pruning_2026_10_04/partial_search_probe.py
```

事前に既存RSS probeのローカルcompiled GTFSと更新済みprebuiltが必要。probeは探索の優先度・上限を置き換えず、過去の実験JSONを上書きしない。
