# Places 利用状況の観測（#258）

東京版の /autocomplete と /details に対して 1 HTTP リクエストにつき
JSON ログを1行出力する。既存の Lambda / CloudWatch を利用し、新規サービス、
リクエスト制限、再試行、API 契約変更は追加しない。

## 接続元識別子の設定

Lambda の環境変数 PLACES_ACCESS_LOG_HMAC_KEY に専用の32バイトのランダムな
秘密鍵（64桁の16進文字列）を設定する。既存の API キーとは別の鍵を使用する。
ローカルで Python の secrets.token_hex(32) などを使って生成し、AWS コンソールの
Lambda 設定 > 環境変数で登録する。鍵をリポジトリ、Issue、ログに貼り付けない。
既存の環境変数を削除しない。

未設定・不正な形式・AWS の接続元情報が得られない場合は client_hash を null とし、
client_hash_status に理由を明示する。これは観測機能の未設定状態であり、Places
リクエスト自体は変更しない。別の識別方法に切り替えない。

AWS が渡す v2 イベントの requestContext.http.sourceIp を使用する。
任意の X-Forwarded-For は信頼しない。HMAC は日本時間の日付ごとに変わるため、
同日内の傾向分析に限る。共有 IP、VPN、プロキシ、IP 変更の影響があり、
端末数・人数・悪意を確定するものではない。ハッシュも仮名化データとして扱い、
アクセス権を限定する。既存ロググループの保持期間は運用者が確認し、必要な期間に
限定する（既存の他のログに影響するので自動変更しない）。

検索語、住所、座標、Place ID、HTTP ヘッダー、API キー、レスポンス本文は
このアクセスログに出力しない。CloudWatch のログ取り込み・保存・検索の費用は
発生し得る。短期間、対象ロググループのみでクエリを実行する。

## CloudWatch Logs Insights

対象は既存の Lambda ロググループ。デプロイ後の期間を指定する。
まずイベントが取得できることと client_hash_status が ok であることを確認する。

```sql
fields @timestamp, endpoint, client_hash_status, status, upstream_attempts, upstream_status, upstream_tier, duration_ms
| filter event = "places_access"
| sort @timestamp desc
| limit 50
```

接続元別の集計（同一日付内）:

```sql
filter event = "places_access" and client_hash_status = "ok"
| stats count(*) as requests, sum(upstream_attempts) as upstream_calls by day_jst, client_hash, endpoint
| sort upstream_calls desc
| limit 50
```

15分ごとの利用量とエラー:

```sql
filter event = "places_access"
| stats count(*) as requests, sum(upstream_attempts) as upstream_calls by bin(15m), endpoint, status, upstream_status
```

upstream_attempts は Google への通信試行数であり、成功・課金対象数ではない。
upstream_status が null で試行数が正なら HTTP 応答を得られなかったケース。
status はアプリ API の応答コードで、Google の 429 が 502 に変換されても
upstream_status に 429 が残る。過去のログは復元できない。

## 選択された場所の種類（東京版 Details）

既存の Place Details (New) の FieldMask に `types` を追加する。
[公式のデータフィールド表](https://developers.google.com/maps/documentation/places/web-service/data-fields)
では types は Essentials のため、既存の Essentials / Pro の SKU は変更しない。
追加のGoogleリクエストは発行しない。Flutterへの応答も変更しない。
生の types や場所名、住所、座標、Place ID は出力せず、成功した Details の
ログに固定カテゴリ `place_category` だけを記録する。

| place_category | 意味 |
| --- | --- |
| rail_station | train_station / subway_station / light_rail_station |
| bus_stop | bus_stop / bus_station |
| transit_unspecified | 両方に該当、または種別不明の transit_station / transit_stop |
| address | street_address / premise / subpremise / route / intersection のいずれかで、establishment / point_of_interest を含まない |
| other | 上記以外の有効な types |
| unknown | types が欠落、空、または形式不正 |
| null | Details 成功以外のリクエスト（旧ログにはフィールドなし） |

分類は Google が返した型に基づく観測上の区分であり、住所と施設が完全に
区別できることや、自前の都営交通データに対応することを保証しない。
欠落・形式不正は分類処理を unknown として終了し、検索語や住所から推測しない。
元の座標取得処理やエラー処理には影響させない。

成功した Details のカテゴリ別回数（新ログのみ）:

```sql
filter event = "places_access" and endpoint = "details" and status = 200
| filter place_category in ["rail_station", "bus_stop", "transit_unspecified", "address", "other", "unknown"]
| stats count(*) as selections by place_category
| sort selections desc
```

分母は上記カテゴリの全件数（unknown も含む）。鉄道駅・バス停の合計割合は
自前候補で代替可能か調べるための目安で、削減率そのものではない。
同じ場所を繰り返し選択した場合はその都度数える。全利用者の割合や
Autocomplete の削減率ではない。既存アプリも Lambda 更新後の成功分から対象。

