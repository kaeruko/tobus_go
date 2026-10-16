# 運賃と FarePolicy の境界

Phase 5 (#135) では、経路探索の評価値と実際の運賃・福祉制度を別レイヤとして扱う。

```text
Route search
  ↓ route candidates
Normal fare calculator
  ↓ normalFareYen (計算可能な場合だけ)
FarePolicy
  ↓ payNowYen / effectiveFareYen / settlementType
```

## `cost` は運賃ではない

東京の既存 RouteEngine に残っている `mode=cost`、探索中の `cand['cost']`、レスポンスの `cost_score` は、徒歩・乗換などを含む「楽さ」の探索評価値であり、円単位の運賃ではない。

既存クライアントとの互換性のため Phase 5 では legacy 名を削除しないが、これを運賃として使用してはいけない。金額は `fare` オブジェクトの次のフィールドだけで表現する。

```json
{
  "normalFareYen": 210,
  "payNowYen": 0,
  "effectiveFareYen": 0,
  "policyId": "tokyo_toei_transport_pass",
  "settlementType": "free_pass",
  "status": "available",
  "unavailableReason": null
}
```

## settlementType

- `normal`: 通常払い。`payNowYen == effectiveFareYen == normalFareYen`
- `discount`: 通常運賃から割引して支払う
- `free_pass`: 対象区間では乗車時の支払額も実質負担額も 0 円
- `reimbursement`: 乗車時はいったん通常運賃等を払い、制度上の支給後の実質負担を別に表す

`reimbursement` を `free_pass` と同一視しない。

## 資格を推定しない

アプリは住所、年齢、障害区分、手帳等から利用可能制度を推定しない。ユーザーが設定画面で、利用する制度・所持乗車証を明示的に選択した場合だけ、その `policyId` を適用する。

SharedPreferences の保存キーは都市別 `farePolicyId:<city>` とする。未保存の初回だけ `normal` を既定値とする。保存済みの値が未知、壊れている、または別都市の policy ID なら `normal` へ自動復旧せずエラーにする。

## API

`POST /route` の共通探索コアは制度を知らない。API境界で
`fare_policy_id` を受け取り、都市Adapterの明示的な探索対象を選ぶ。
省略時の `normal` は既存の探索を維持する。他都市で未実装の探索対象を指定した場合は
422にし、通常探索へ切り替えない。

鉄道便identity解決など、経路そのものの確定後に `POST /fare/apply` を呼ぶ。

```json
{
  "policy_id": "normal",
  "candidates": [ ... ]
}
```

`/fare/apply` は候補をdeep copyして運賃だけを付加するため、FarePolicyがRouteEngineの探索結果や順位を変更しない。
仙台のふれあい試験検索では、許可便・区間でscopeを構築してから共通v2を呼び、返却旅程も元具体便へ戻して検証する。通常検索結果への0円ラベル後付けで代用しない。

`GET /fare/policies` はbackendの `city_key` に対応するpolicyだけを返す。東京のpolicy IDを仙台backendへ渡した場合などは 422 とし、別都市policyへfallbackしない。

## 東京

現在登録するpolicy:

- `normal`
- `tokyo_toei_transport_pass`

`tokyo_toei_transport_pass` は、現在の都営経路候補の bus / rail に対し、明示選択された場合のみ `free_pass` を適用する。

東京の既存候補は都バスと距離制の都営地下鉄を混在できる一方、現行候補JSONだけから全ケースの普通運賃を厳密計算できない。このため、exactなstep fareが揃っていない `normal` は金額を推測せず `status=unavailable` とする。

無料乗車証では、普通運賃が未計算でも対象区間の `payNowYen=0 / effectiveFareYen=0` は制度上確定できるため `available` を返せる。

公式情報:

- 東京都福祉局 精神障害者都営交通乗車証
  - https://www.fukushi.metro.tokyo.lg.jp/shougai/nichijo/jousyasyo

## 今後

- exactな通常運賃Adapterを交通事業者ごとに追加する
- `cost_score` のlegacy aliasをクライアント移行後に `comfort_score` へ整理する
- 実在する割引・reimbursement policyを追加するときは、公式制度の対象区間・支払方法・丸め規則を個別テストする
- RouteEngine内にpolicy条件分岐を追加しない


## 仙台（開発版）

公開バスAPIの選択肢は `normal` のみ。`sendai_shared_network.py` と `sendai_practical_network.py` の `sendai_fureai_pass` は独立した試験入口で、バスGTFS・地下鉄実用Adapter・区間レビュー・独立oracleを保持する。通常運賃が不明なら不明のままとし、実用到着目安・標準乗換を確定値へ読み替えない。詳細は [仙台共通ネットワーク設計](sendai-shared-network-design.md)。
