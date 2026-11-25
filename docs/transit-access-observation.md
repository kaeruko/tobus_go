# 東京版の経路検索・リアルタイム利用状況

既存の Lambda / CloudWatch に `event=transit_access` の JSON ログを追加する。
アプリ更新、新規DB、外部API呼び出し、キャッシュ、探索条件変更は不要。
対象は次の HTTP リクエストで、1リクエストにつき1行を記録する。

| メソッド・パス | feature |
| --- | --- |
| POST /route | route_search |
| GET /bus/location | realtime |
| GET /train/location | realtime |
| GET /bus/next | timetable |
| POST /train/resolve-route-identities | train_identity |

鉄道便照合と時刻表取得はリアルタイムとして数えない。現在位置取得の自動ポーリングや
手動更新、失敗応答も取得要求として計測する。画面の閲覧やナビ開始操作そのもの、
実際に表示された車両数、ODPTへの上流呼び出し回数を測るものではない。
Lambda が強制終了した場合は完了ログが残らないことがある。

## 接続元の概数

[Places 観測の設定](places-access-observation.md)と同じ
`PLACES_ACCESS_LOG_HMAC_KEY` を利用する。AWS v2イベントの接続元IPを
日本時間の日付ごとにHMACで仮名化する。鍵が未設定・不正、または接続元が
取得できない場合は null と理由を記録し、APIの応答は変えない。
住所、座標、生IP、検索内容、便ID、認証情報、リクエスト・レスポンス本文は
この追加ログには出力しない。既存の他のログは変更しない。

接続元の概数は実人数・端末数ではない。共有IP、VPN、IPの切り替え、監視や
自動アクセスの影響がある。日をまたいで同一人物として追跡しない。
ログアクセス権と保持期間は既存のPlaces観測と同様に管理する。
CloudWatchの取り込み・保存・検索料金は発生し得る。

## CloudWatch Logs Insights

東京APIの既存ロググループで、デプロイ後の期間を指定する。

件数・エラー・処理時間（全接続元）:

```sql
filter event = "transit_access"
| stats count(*) as requests, pct(duration_ms, 95) as p95_ms by day_jst, endpoint, status
| sort day_jst desc
```

識別子の取得状況:

```sql
filter event = "transit_access"
| stats count(*) as requests by day_jst, client_hash_status
```

日ごとの機能別接続元概数（両機能を使う接続元は両方に数える）:

```sql
filter event = "transit_access" and client_hash_status = "ok"
| filter feature in ["route_search", "realtime"]
| filter status != 409 and status != 422
| stats count_distinct(client_hash) as sources, count(*) as requests by day_jst, feature
| sort day_jst desc
```

同日の経路検索のみ・リアルタイムのみ・両方の接続元の分類:

```sql
filter event = "transit_access" and client_hash_status = "ok"
| filter feature in ["route_search", "realtime"]
| filter status != 409 and status != 422
| stats max(strcontains(feature, "route_search")) as searched, max(strcontains(feature, "realtime")) as realtime_used by day_jst, client_hash
| stats count(*) as sources by day_jst, searched, realtime_used
| sort day_jst desc
```

searched=1 / realtime_used=0 が検索のみ、1 / 1 が両方、0 / 1 が
リアルタイムのみ。分母はこれらのAPIにアクセスした接続元であり、
全DAUではない。400等のエラーも利用試行として含む。409/422は除外する。
実利用傾向を観測するための集計で、課金件数やキャッシュ必要性の確定値ではない。
本番反映とログ発生の確認は別途必要。
