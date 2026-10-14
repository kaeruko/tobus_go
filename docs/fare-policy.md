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
  "policyId": "nagoya_welfare_special_pass",
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

`POST /route` の共通探索コアは制度を知らない。横浜ではAPI境界で
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
横浜の福祉パス検索では、これに先立ち、レビュー済みの市営バス路線から対象外路線を除いて
探索する。通常検索の最速候補に0円を付けるだけでは、遅い無料経路を取り落とすためである。

`GET /fare/policies` はbackendの `city_key` に対応するpolicyだけを返す。東京のpolicy IDを名古屋backendへ渡した場合などは 422 とし、別都市policyへfallbackしない。

## 名古屋

Phase 5 の名古屋backendは、市バスの普通料金を成人 1 乗車 210 円の均一運賃として計算する。各bus stepにも canonical な `fare_yen=210` を付与する。

現在登録するpolicy:

- `normal`
- `nagoya_welfare_special_pass`

`nagoya_welfare_special_pass` は、このアプリが現在探索対象としている名古屋市バスの無料乗車区間に対し `free_pass` を適用する。

名古屋市の制度には、一部の対象交通で「いったん支払い、後日支給」となる範囲もある。Phase 5 の共通 `ReimbursementFarePolicy` はそのsettlementを表現できるが、現在の名古屋市バスのみの経路探索に私鉄等を含めていないため、実運用policyとしてはまだ登録しない。

公式情報:

- 名古屋市交通局 市バス料金
  - https://www.kotsu.city.nagoya.jp/jp/pc/BUS/TRP0000290.htm
- 名古屋市 福祉特別乗車券
  - https://www.city.nagoya.jp/kenkofukushi/shougaisha/1016573/1016578.html

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

## 横浜の時刻表専用起動（#241）

横浜APIの `YOKOHAMA_REALTIME_MODE` は `disabled`（既定）か `enabled` のみ。
`disabled` では静的GTFSの起動・経路検索をRealtime APIキーなしで利用でき、
`/healthz` の `realtime.vehicle_positions` は `false` を返す。
`/bus/location` は `bus_realtime_unsupported` を返し、位置情報を捏造しない。
`enabled` は従来のODPT Realtime providerを使い、トークン欠落・初期化失敗を隠さない。
起動後の設定モード変更はエラーとして扱う。東京・名古屋・仙台の起動設定は変更しない。

## 横浜（#241、第一段階）

横浜は通常運賃モードを提供せず、検索時に `fare_policy_id` を必ず指定する。
対応IDは `yokohama_welfare_special_pass`（福祉パス）、
`yokohama_senior_special_pass`（敬老パス）の2種類のみ。
初回未選択・旧 `normal` 保存値は自動変換せず、ユーザーに選択し直してもらう。
検索条件が変われば既存結果・処理中検索は無効化する。

現段階で探索できるのは**レビュー済みの横浜市営バス路線**だけ。
市営バスの対象外路線は検索前に除外する。市営地下鉄と民営バスについては
制度判定関数だけで完成扱いしない。特に**敬老パスの市外↔市外の民営バス**は、
運行系統が横浜市内の停留所を含む事実を別途確認しない限り無料にしない。

`yokohama_welfare_special_pass` を明示選択した場合だけ対象区間を無料にする。
障害者手帳の所持だけで福祉特別乗車券の所持を推定しない。
設定画面の名称・利用条件は既存の日本語・英語・韓国語・簡体字・繁体字に対応する。

### 現在の接続範囲

- 市営バスの既存GTFS backendへ、レビュー済みの路線区分を結び付ける。
- 福祉パス検索時に市営バスの対象外路線を探索前に除外し、応答に運賃を付加する。
- アプリは保存済みの横浜のpolicy IDを検索リクエストに載せ、応答の運賃を表示する。
- 通常検索は既存の市営バス探索を維持する。

**地下鉄・民営バスのデータ接続と複数事業者の乗換はまだ未実装。**
判定関数に地下鉄・シーサイドライン・対象民営バスのルールがあっても、それらを現在の
探索で利用できる意味ではない。民営バスの無料限定検索には、乗降場所に応じて各乗車区間を
制約する探索を後続で実装する。市営交通用の路線フィルターを民営バスへ使うとエラーにする。

### ルールと不明データ

- 市営地下鉄・シーサイドラインは対象全線。市営バスはレビュー済みの普通路線・対象外を区別する。
- 対象民営バスの普通路線は、乗車または降車の少なくとも一方が横浜市内である場合に対象とする。
- 空港・高速・深夜急行・観光路線等を、同じ事業者という理由で無料にしない。
- 判定には名前の曖昧一致ではなく、feed ID・operator ID・route ID・乗降stop IDと市コードを使う。
- 対象外区間の正確な運賃が不明なら `unavailable` にし、0円を作らない。
- 乗車の `fare_context` が欠落・不一致ならエラー。modeだけを根拠に市営交通と推定しない。
- 券の年額負担は各乗車の `payNowYen` に加算しない。

### 市営バスのレビュー済みcoverageファイル

`YOKOHAMA_FARE_COVERAGE_PATH` にUTF-8 JSONの絶対パスを設定する。
この設定を省略した場合、既存の通常検索は使えるが福祉パス検索は503になる。
空文字・ファイル欠落・不正JSON・feed版不一致では起動時に停止する。

ファイルの必須フィールドは以下。**この例のroute IDとfeed版は説明用で、本番データではない。**

```json
{
  "schema_version": 1,
  "city": "yokohama",
  "feed_id": "yokohama_bus",
  "feed_version": "reviewed-feed-version",
  "feed_source_uri": "https://api.odpt.org/api/v4/files/odpt/YokohamaMunicipal/Bus.zip?date=current",
  "operator_id": "yokohama_municipal_bus",
  "policy_source_uri": "https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/fukushi/annai/gaishutsu/kotsu/fukushi-jyosyaken/ticket.html",
  "reviewed_on": "2026-10-14",
  "routes": {
    "yokohama_bus:reviewed-local-route-id": "local",
    "yokohama_bus:reviewed-excluded-route-id": "sightseeing"
  },
  "stop_municipalities": {}
}
```

搭載するGTFSの全route IDをレビューして列挙する。新しいroute IDが追加された場合、
普通路線へ自動分類せずレビュー不足として停止する。区分は `local` / `airport` / `highway` /
`midnight_express` / `sightseeing` のいずれか。深夜普通バスと深夜急行を区別する。
市営バスは全線対象のため市コードは省略可能。民営バス用coverageでは全stopの市コードを必須にする。
市コードは5桁の市単位コード（横浜は `14100`）を使い、区コード・座標・停留所名から推定しない。

route・stop・tripの元ID、feed版、出典URLは保持する。coverageは搭載feedとoperatorが一致しなければ拒否する。
レビュー済みcoverageと実交通データでの本番検証が完了するまで、無料対応済みとして公開しない。

### 横浜市営バスGTFSの例外監査（読み取り専用）

実GTFSから例外候補を拾う補助ツールを用意した。coverageファイルは作らない。

```powershell
python scripts/audit_yokohama_bus_gtfs.py --gtfs-dir ".\api\data\yokohama\2026-09-04"
```

- 路線・便の出典はGTFSと同梱manifest。名称や便数・23時以降の時刻を列挙するが、**運賃無料の根拠にしない**。
- 横浜市の公式案内で「あかいくつ」は両パス対象外。ぶらり野毛山動物園BUS、ベイサイドブルー、ぶらり三溪園BUSは敬老パス対象と明記。feed側の名称が変わった場合は検証エラーで停止する。
- 23時以降の時計時刻は、割増便を洗い出すための保守的な調査フラグ。普通運賃の便も含む可能性があるし、23時より前の特別運賃便を検出できるとは限らない。
- `jp_trip_desc` 等が空欄、`fare_attributes.txt` / `fare_rules.txt` がないなど、判定に必要な情報の欠落を報告する。
- 実交通feedから自動生成した結果を、そのまま「人手レビュー済みcoverage」として使わない。路線判定・時刻表・深夜割増の対象区間を別途確認し、根拠と確認日を保存する。
- 福祉パスの公式FAQ: https://www.city.yokohama.lg.jp/faq/kukyoku/kenko/shogaijiritsu/20211015164324433.html
- 敬老パスの公式対象交通と深夜割増: https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/ikigai-shakaisanka/keirou.html

### 3系統だけの保守的な実GTFSテスト用coverage（開発専用）

未確認の149系統をまとめて「無料」とすることはしない。確認済みの089（ぶらり野毛山動物園BUS）・200（ベイサイドブルー）・280（ぶらり三溪園BUS）のみ `local`、271（あかいくつ）を `sightseeing`、残りを `unreviewed` として検索から除外する、部分coverageを作成できる。路線名、GTFS版、manifestの検証が通らなければ中止する。

まず内容だけ調べる（ファイル出力・書き換えなし）:

```powershell
python scripts/build_yokohama_initial_pass_coverage.py --gtfs-dir ".\api\data\yokohama\2026-09-04" --service-date 2026-09-04 --reviewed-on 2026-10-14
```

レビューが済んでから**明示的に**テスト用coverageファイルを作る場合は、上記に `--output <保存先>.json`を付ける。
既存ファイルを上書きせず、出力先ディレクトリも作らない。生成しても確認済みの3系統以外は無料検索に使えない。

**重要:** 実GTFSには `fare_attributes.txt` / `fare_rules.txt`と便単位の深夜割増区分がない。
この3系統でも深夜増料金がないことを便単位で証明したわけではない。
このcoverageによる検索結果は**社内/開発用の検証に限定**し、公開用の無料経路保証には使わない。
敬老パスの深夜割増、特殊便の可否は追加の公式資料との突合・運行事業者への照会等が必要。

### 市営深夜バス廃止の公式根拠と008系統の開発用追加候補（2026-10-14）

横浜市交通局は2024年4月1日のダイヤ改正で**市営深夜バスを廃止**したと公式回答している。2024年3月の市会資料でも、コロナ禍以降休止していた深夜バスの廃止を明記。2026年には廃止された78系統の深夜バス再開を求める要望が掲載されている。これは市営交通局の資料であり、**民営バス等の深夜割増を否定する証拠ではない**。

- 公式回答：https://cgi.city.yokohama.lg.jp/shimin/kouchou/search/data/36003485.html
- 2024年ダイヤ改正資料：https://www.city.yokohama.lg.jp/shikai/kiroku/katsudo/r5/JohninSuikouR05.files/J-SK-20240315-kt-3.pdf
- 008系統（横浜駅前・本牧車庫前）の公式時刻表：https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusDiagram?course=0001600980&date=2026-10-09&orvCode=00091228&stopNo=1
- 福祉パス：https://www.city.yokohama.lg.jp/faq/kukyoku/kenko/shogaijiritsu/20211015164324433.html
- 敬老パス：https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/ikigai-shakaisanka/keirou.html

008系統は実GTFSで全service合計500便、2026-09-04（金）に130便、23時以降の停車時刻を持つ4便（出発時刻22:21／22:21／22:52／23:15）。**「23時以降に走るから深夜割増」とは扱わない**。ただし民営バス混在、特殊系統、2024年以降の運行復活などの確認を省略してよいわけではない。

`scripts/propose_yokohama_route_008_coverage.py` は **008のみ** `unreviewed` → `local` にする開発用案を作る。既存の089／200／280は維持、271「あかいくつ」は除外、残り144系統を未確認のまま保持する。GTFSと既存coverageのfeed identity、全路線、route名、現行分類を検証し、異なる場合は停止する。**現行coverage v1を読み取るだけで、標準動作では一切ファイルを作らない**。

```powershell
python scripts/propose_yokohama_route_008_coverage.py `
  --gtfs-dir ".\api\data\yokohama\2026-09-04" `
  --coverage ".\api\data\yokohama\2026-09-04\coverage.json" `
  --service-date "2026-09-04" `
  --reviewed-on "2026-10-14"
```

実際に**別名ファイルを新規作成**する場合のみ `--output` を付ける。既存coverageの上書きは禁止。開発用の4系統案は**公表可能な運賃保証ではない**。対象の特殊便や現行運行の最終確認、独立時刻表との照合は継続する。

実GTFSで008を検索するときは、必ず元の3系統版とは別ファイルとして4系統版を作る。作成先を限定し、上書きも禁止。

```powershell
python scripts/propose_yokohama_route_008_coverage.py `
  --gtfs-dir ".\api\data\yokohama\2026-09-04" `
  --coverage ".\api\data\yokohama\2026-09-04\coverage.json" `
  --service-date "2026-09-04" `
  --reviewed-on "2026-10-14" `
  --output ".\api\data\yokohama\2026-09-04\coverage_dev_008.json"

python scripts/smoke_yokohama_real_gtfs.py `
  --gtfs-dir ".\api\data\yokohama\2026-09-04" `
  --coverage ".\api\data\yokohama\2026-09-04\coverage_dev_008.json" `
  --manifest-service-date "2026-09-04" `
  --ride-date "2026-09-04" `
  --route-id 008
```

スモークは両パスをテストし、008が採用されなかった場合や対象外系統が入った場合は失敗する。比較には**同じGTFS**を使うので、独立した公式時刻表検証や制度上の無料運賃保証ではない。


#### 系統レビュー台帳と共通の開発用coverage生成（#241）

`scripts/yokohama_municipal_route_reviews.json` が**開発用の根拠台帳**。系統ごとにGTFS feed ID・版、系統番号、GTFS上の完全一致名称、レビュー日、公式参照URL、未完了の確認事項、審査状態を明示する。今後は系統専用スクリプトを増やさず、台帳の差分をレビューしてから共通スクリプトへ渡す。

- `008` / `288`: `development_eligible`（実データテストができる段階。公開用の運賃保証ではない）。
- `272` / `275`: `pending`（両パスの適用条件・現行運賃の個別確認が残るため、**明示指定しても有効化を拒否**）。
- その他の系統は台帳未登録。登録だけでは対象にならず、正式な人手レビューにより `development_eligible` とし、正式feed/路線名・ソースURLを照合する必要がある。

一括生成スクリプト `scripts/propose_yokohama_reviewed_coverage.py` は、現在の部分coverage v1から**台帳に明示され、開発用承認された系統だけ**を追加する。公式サイトURLの形式や日付、GTFS完全一致、既存の対象系統の分類を確認し、不一致ならfail-fast。DRY RUNが既定で、ファイルは生成しない。出力には `--output` を明示し、既存ファイルは上書きしない。

**例：元の3系統版から008・288をまとめて再現（読み取り専用、出力変更なし）**

```powershell
python scripts/propose_yokohama_reviewed_coverage.py `
  --gtfs-dir ".\api\data\yokohama\2026-09-04" `
  --coverage ".\api\data\yokohama\2026-09-04\coverage.json" `
  --service-date "2026-09-04" `
  --reviewed-on "2026-10-14" `
  --route-id 008 `
  --route-id 288
```

**例：既存の4系統版から288だけを追加するDRY RUN**（すでに生成済みの `coverage_dev_288.json` は維持する）。

```powershell
python scripts/propose_yokohama_reviewed_coverage.py `
  --gtfs-dir ".\api\data\yokohama\2026-09-04" `
  --coverage ".\api\data\yokohama\2026-09-04\coverage_dev_008.json" `
  --service-date "2026-09-04" `
  --reviewed-on "2026-10-14" `
  --route-id 288
```

#### 既存の5系統版との内容一致を検証する（書き込みなし）

共通ツールで提案した内容が、以前の個別スクリプトで生成した `coverage_dev_288.json` と**すべてのJSON項目で一致するか**を検証するには、`--verify-against` を指定する。順序や空白は問わず、フィード版、reviewed_on、149系統の分類、その他すべてのフィールドを比較する。1件でも違えば例外で停止し、`differing_route_ids` と食い違いフィールド名を出す。**比較するだけで、ファイルを新規作成・書換・削除しない**。

```powershell
python scripts/propose_yokohama_reviewed_coverage.py `
  --gtfs-dir ".\api\data\yokohama\2026-09-04" `
  --coverage ".\api\data\yokohama\2026-09-04\coverage.json" `
  --service-date "2026-09-04" `
  --reviewed-on "2026-10-14" `
  --route-id 008 `
  --route-id 288 `
  --verify-against ".\api\data\yokohama\2026-09-04\coverage_dev_288.json"
```

一致時のみ `verification: MATCH`、`file_action: VERIFY ONLY: no files written` と表示。存在しない照合ファイルや差分は失敗として扱う。`--verify-against` と `--output` は同時指定不可。これが成功しても実運賃や公式ダイヤを検証したことにはならず、**生成された設定の同等性のみ**を示す。

これは**レビュー台帳による明示的な許可の管理**であり、リンク先の内容が自動検証済みであることも、全便・全区間が運賃制度上0円であることも意味しない。市営交通と各民営交通の現行規程・各乗車区間の個別例外は公開前に独立照合する。既存の `propose_yokohama_route_008_coverage.py`、`propose_yokohama_route_288_coverage.py` は互換性確保のため残す。削除・改名しない。

制度の重要な違い：2025年10月以降、一部の地域型「おでかけシャトル」は**敬老パスで半額程度の自己負担が残る**。市営の272・275「ふれあいバス」と名称が似ていても同一サービスとは断定しない。横浜市公式 [敬老パス対象交通](https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/ikigai-shakaisanka/keirou.html) / [地域公共交通への拡大](https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/ikigai-shakaisanka/tikikotu.html)。

### 288系統の実GTFS／独立公式時刻表照合（2026-10-14）

ローカルGTFS `v3.0_20260727` の2026-09-04（金）に `trip_id=yokohama_bus:28800_01202606011032AO00503` を両パスのAPI検索で確認。
聖隷横浜病院08:22発 → 水道道08:32着、GTFSの停車順1→4、徒歩0m、福祉パス／敬老パスとも検索PASS・追加支払0円。

**独立した公式時刻表でも平日08:22発・水道道08:32発が掲載されている**（2026年に公開された市交通局の改正時刻表）。発車時刻の掲載は到着時刻や実際の運行実績そのものではないが、GTFS/APIの時刻との整合を独立確認できた。

- 聖隷横浜病院の平日時刻表: https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusDiagram?course=0001600784&date=2026-10-11&orvCode=00091288&stopNo=1
- 水道道の平日時刻表: https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusDiagram?course=0001600784&date=2026-10-06&orvCode=00090538&stopNo=4
- 福祉・敬老パス利用可の病院公式案内: https://www.seirei.or.jp/yokohama/outline/access/bus/circulation-bus/index.html

**注意**：同じ便が2026-09-04に実際に運行したか、当該便が2026年の制度下で追加料金なしで乗れるかについては、現行情報と事業者の最終確認が必要。開発用の5系統版が「公開可能な全域検証済みcoverage」になったわけではない。

### 288系統「聖隷横浜病院循環」の追加調査（開発用5系統目）

聖隷横浜病院の公式案内（https://www.seirei.or.jp/yokohama/outline/access/bus/circulation-bus/index.html ）は、「聖隷横浜病院循環」について **通常市営バス運賃であり、敬老特別乗車証と福祉特別乗車券の両方が使用可能**と明記。公式案内は2016〜2017年の時刻表にも言及しているため、2026年の便・停留所・運賃条件との独立照合は残る。

GTFS版 `v3.0_20260727` の棚卸しでは、288系統は全サービス合計24便、2026-09-04（金）8便、2026-09-05（土）0便。この情報は搭載feedに由来し、公式時刻表の独立照合ではない。

`scripts/propose_yokohama_route_288_coverage.py` は、既存の4系統版 `coverage_dev_008.json` を読み、288系統だけを追加した **5系統の開発用coverage案**を提示する。既存の `coverage.json` と `coverage_dev_008.json` は上書きしない。271「あかいくつ」は除外したまま、143系統は未確認。

まずは標準出力に案を出す読み取り専用のDRY RUN：

```powershell
python scripts/propose_yokohama_route_288_coverage.py `
  --gtfs-dir ".\api\data\yokohama\2026-09-04" `
  --coverage ".\api\data\yokohama\2026-09-04\coverage_dev_008.json" `
  --service-date "2026-09-04" `
  --reviewed-on "2026-10-14"
```

新規ファイル出力を許可するときに限り `--output` で `coverage_dev_288.json` 等の別名を指定する。既存ファイルがあれば失敗。生成後は `smoke_yokohama_real_gtfs.py --route-id 288` で2026-09-04の両パスを検証する。名称不一致や期待した4系統版以外のcoverageを渡した場合も失敗する。

**注意**：ここまでのAPI検証は同じGTFSの情報を照合しているだけなので、運賃制度の最新確認・公式時刻表との独立比較・経路上の徒歩の実在性確認なしに本番公開しない。

### 横浜市営バス149系統の一括トリアージ（読み取り専用）

単一系統ずつ確認する前に、展開済みの同一GTFSから**全route IDと運行便数を一括棚卸し**する。\
`scripts/review_yokohama_bus_route_catalog.py` は `api/data/yokohama/2026-09-04` の厳密なfeed metadataと既存coverageを照合してから、以下のレビュー順で分類する。

- **開発用coverageで有効**: 008/089/200/280（4系統版を渡した場合）。これは承認済み本番運賃を意味しない。
- **明示的に除外**: 271（あかいくつ）。路線名称が一致しなければ停止する。
- **要調査・対象外キーワード候補**: 空港、羽田、深夜、高速、直行、貸切、あかいくつ等が路線名称または行先に含まれる場合。**キーワードだけで対象外運賃と決めない**。
- **要調査・特殊名称候補**: 急行、循環、ふれあい、観光などの路線。急行≠直行であり、名称だけで有料扱いにしない。
- **通常系統名の未確認候補**: 規則的な「008系統」等の短名で特殊キーワードがないもの。**こちらも自動的に無料認定しない**。

平日・土曜の双方でservice calendarに合致する便数を表示し、23時以降の停車時刻は割増運賃とは区別して監査フラグとして表示する。
通常系統候補はデフォルトではroute IDの短い一覧のみ表示し、全件詳細が必要なら `--full`。いずれの場合も**読み取り専用**で、通常のcoverageと開発用coverageを変更しない。

```powershell
python scripts/review_yokohama_bus_route_catalog.py `
  --gtfs-dir ".\api\data\yokohama\2026-09-04" `
  --coverage ".\api\data\yokohama\2026-09-04\coverage_dev_008.json" `
  --manifest-service-date "2026-09-04" `
  --ride-date "2026-09-04" `
  --ride-date "2026-09-05"
```

公式根拠（2026-10-14再確認）：

- 福祉パス: [利用交通機関](https://www.city.yokohama.lg.jp/faq/kukyoku/kenko/shogaijiritsu/20211015164324433.html)。「あかいくつ」、羽田空港線、深夜急行は不可。
- 敬老パス: [対象交通機関](https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/ikigai-shakaisanka/keirou.html)。「あかいくつ」、空港連絡、深夜急行、高速、直行は不可。一般路線の深夜バスには割増分が必要。
- 市営バスの2024-04-01深夜バス廃止: [横浜市交通局回答](https://cgi.city.yokohama.lg.jp/shimin/kouchou/search/data/36003485.html)。民営バスまで廃止した証拠ではない。

**出力は調査キューであり、149系統を一括で無料扱いする処理ではない。** 公式資料と運行会社で特殊系統の種別・例外を確認した後、明示的に開発用coverageへ追加して実GTFSで検証する。

### 横浜市営バス・一般系統の運行便レビュー一覧（読み取り専用）

ローカル実GTFSの一般系統を1つずつ調査する。最初の例は008系統。
このツールは**時刻を根拠に0円と認定せず、coverageを書き換えず、ファイルも新規作成しない**。
運行日ごとに有効なGTFS便、service ID、乗降停留所ID、始終時刻、23時以降の停車時刻を持つ便数を報告する。
表示件数は最大30件に制限し、 `--limit` で変更する。

```powershell
python scripts/inspect_yokohama_trip_evidence.py `
  --gtfs-dir ".\api\data\yokohama\2026-09-04" `
  --coverage ".\api\data\yokohama\2026-09-04\coverage.json" `
  --manifest-service-date "2026-09-04" `
  --ride-date "2026-09-04" `
  --route-id 008
```

これは**運賃調査の下準備**。GTFSには深夜割増かどうかの便属性がなく、23時以前の便も一律無料とは判定できない。
制度根拠が確認された便だけ、後にschema v2の `reviewed_free_trips`へ追加する。福祉パスと敬老パスの両方で無条件に追加支払0円となる便に限定する。
横浜市福祉パスFAQ https://www.city.yokohama.lg.jp/faq/kukyoku/kenko/shogaijiritsu/20211015164324433.html
・敬老パス深夜割増FAQ https://www.city.yokohama.lg.jp/faq/kukyoku/kenko/kenko-korei/20211018113823735.html

### 一般系統向けの便単位レビュー（coverage schema v2 / #241）

**現行の開発用 `coverage.json` は schema v1 のまま維持する。自動移行・上書きしない。**
v1の`routes`は**系統単位**なので、同一系統に通常便と深夜割増便が混在すると、系統を`local`にするだけでは無料を保証できない。GTFS-JPにはこのfeedの便ごとの深夜割増フラグがなく、23時以降という時刻だけで運賃を判定することもできない。

そこでschema v2を追加した。v1の必須項目は維持し、下記のような`reviewed_free_trips`を**追加で必須**とする。

```json
{
  "schema_version": 2,
  "...": "v1と同じfeed identity・reviewed_on・全routes・stop_municipalities等",
  "reviewed_free_trips": {
    "yokohama_bus:<GTFS便ID>": "https://<公式路線・運賃または時刻表の照会根拠URL>"
  }
}
```

- 上記は**項目の説明用**であり、そのまま読み込める完成JSONではない。URLはレビュー結果の記録欄であり、コードがリンク先の内容や便の運賃を自動認定するわけではない。
- **掲載した便だけ**が検索候補。未掲載の便は、路線を`local`に分類しても除外する。空の`reviewed_free_trips`は無料候補なし（通常路線への自動フォールバックなし）。
- 各キーはfeedに実在するtrip IDで、その便の系統が`local`か確認する。未知ID・除外系統・非HTTPSの根拠URLは検証エラー。
- 同じ系統の速い未確認便より、遅い確認済み便を探索することを福祉・敬老パスそれぞれのAPI結合テストで検証。
- 現段階のv2は横浜市営バス専用であり、`reviewed_free_trips`は**両パスとも追加支払0円と確認した便のみ**を想定する。片方だけ利用可能な便や民営バス市境区間は別途制度別の設計が必要。
- 便が公式運賃条件を満たすことの人手レビューが済むまでは、一般系統を`local`へ一括昇格しない。合成GTFSのテスト成功は、実路線の運賃正確性の保証ではない。

公式の制度根拠：福祉パス https://www.city.yokohama.lg.jp/faq/kukyoku/kenko/shogaijiritsu/20211015164324433.html 、敬老パス https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/ikigai-shakaisanka/keirou.html 。

### ローカル実GTFSスモークテスト記録（2026-10-14 / #241）

対象: `v3.0_20260727`、manifest検証日2026-09-04。開発用部分coverageは089・200・280のみ`local`、271除外、残り145系統未確認。福祉パス・敬老パスの双方で追加支払0円を確認したが、**同一GTFSによる照合であり独立した運賃・徒歩経路の監査ではない**。

- 089（2026-09-04）: 桜木町駅前08:49発 → 西戸部１丁目08:58降車 → 推定直線166m・徒歩3分で一本松小学校前付近09:01着。バスで目的停留所まで乗ると09:02。徒歩経路の実地検証は未実施。
- 200（2026-09-04）: 横浜駅前09:50発 → パシフィコ横浜**1回目**10:05着。GTFSの同一tripには同停留所の**2回目**10:48も含まれる。後者を「目的地到着」と誤解しないため、スモーク検証は停車順と同一stop IDの複数時刻を報告するよう改善。
- 280（2026-09-05、土曜）: 三溪園10:00発 → 横浜駅前10:33着。平日の非運行と混同しないこと。

200系統の独立した公式案内では、横浜駅09:50発、パシフィコ横浜10:05・10:48、同停留所を2度通過する循環経路が示されている。

- 公式停車順: https://navi.hamabus.city.yokohama.lg.jp/koutuu/smart/location/BusOperationStopPattern?courseIds=0001601424.
- 公式横浜駅前時刻表: https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusDiagram?course=0001601424&date=2026-10-02&orvCode=00091228&stopNo=1
- 公式パシフィコ横浜時刻表（1回目）: https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusDiagram?course=0001601424&date=2026-08-18&orvCode=00090894&stopNo=4
- 公式パシフィコ横浜時刻表（2回目）: https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusDiagram?course=0001601424&date=2026-09-17&orvCode=00090894&stopNo=12

再実行例:

```powershell
python scripts/smoke_yokohama_real_gtfs.py `
  --gtfs-dir ".\api\data\yokohama\2026-09-04" `
  --coverage ".\api\data\yokohama\2026-09-04\coverage.json" `
  --manifest-service-date "2026-09-04" `
  --ride-date "2026-09-04" `
  --route-id 200
```

### 実GTFSによる無料経路の手動正解テスト（#241）

GitHub/CIに含まれる小規模GTFSは**合成データ**であり、横浜の路線網・時刻表を実測検証したものではない。
実データを使う際は、ローカルの `YOKOHAMA_BUS_GTFS_DIR` に相当する展開済みGTFSと、
**そのfeed ID・版と全routeに一致する人手レビュー済み** `YOKOHAMA_FARE_COVERAGE_PATH` を用意する。
実ファイルやODPTキーはGitへコミットしない。

公式路線図と時刻表で個別に確認したOD例をJSONにまとめる。
最上位は `{"cases": [...]}`、各caseに以下を持たせる。

- 必須: `name`, `policy_id`（福祉／敬老）, `origin`・`destination`（緯度・経度の2要素配列）,
  `date`（YYYY-MM-DD）, `start_time`（HH:MM）, `expected_route_id`（feed名付きroute ID）,
  `expected_departure_time`・`expected_arrival_time`（予定発着時刻）。
- 任意: `expected_trip_id`（便が公式時刻表・feedから特定できたとき）。
- 福祉／敬老の両方を含める。日時・便・系統の根拠は公式資料で人間が確認し、
  **検索エンジンの結果をコピーして「正解」にしない**。元資料と検証日を別途管理する。

```powershell
python scripts/verify_yokohama_pass_routes.py `
  --gtfs-dir "<展開済み実GTFSのディレクトリ>" `
  --coverage "<人手レビュー済みcoverage.json>" `
  --service-date "2026-10-14" `
  --cases-json "<公式路線図・時刻表から作成した正解OD.json>"
```

このコマンドはアプリを**Realtime無効／ローカルAPI**で起動して検索し、
返った全候補の追加支払0円と、既知の系統・予定発着時刻・（指定時は）trip IDを照合する。
一致しないケースは終了コード1で失敗し、対象ケース名を標準エラーへ出す。
データを書き換えず、追加ファイルも生成しない。
公式資料との差分は調査対象であり、30〜50件を通過しても全域の経路網羅性は保証しない。


公式根拠:

- https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/fukushi/annai/gaishutsu/kotsu/fukushi-jyosyaken/ticket.html
- https://www.city.yokohama.lg.jp/faq/kukyoku/kenko/shogaijiritsu/20211015164324433.html
- https://cgi.city.yokohama.lg.jp/somu/reiki/reiki_honbun/g202RG00001784.html


### 横浜でGO：市営交通から段階公開する方針（#241、2026-10-14更新）

**優先順位の決定：第1段階は横浜市営バス＋市営地下鉄（ブルー／グリーンライン）。**
神奈中・臨港・小田急・東急・相鉄・川崎市営た83は第2段階以降に回し、
既存の詳細な制度差・GTFS検証・後続の構想は残す。
横浜市への問い合わせは実装・初回公開の前提条件にしない。
網羅的な例外一覧が公開検索で見つからないことは、その一覧が存在しない証明にはならない。

**運賃適用の設計は「市営バス原則対象＋例外・不明便の除外」へ再整理する。**
横浜市公式FAQは福祉パスで「横浜市営バス（全線）／地下鉄（全線）」と案内し、
「あかいくつ」などの除外を明記している。敬老パスも市営バス・地下鉄を原則対象とし、
直行・高速・深夜急行などを例外として案内する。
個別149系統ごとに全件の無料証明を求める方法は採らず、**公式の一般ルールと明示された
例外を基準**に対象を検証する。ただし、通常名称のGTFSルートでも便種別が混在したり、
例外属性の不足が判明した場合に「例外がない」と推測しない。
**曖昧な系統・便は未承認として無料探索から除外する。**

- 例外：271「観光スポット周遊バス・あかいくつ」は明示除外。
  109には急行／特急／直通が混在し、GTFSの便注記では区別できないため
  一括承認不可、台帳の `pending` を維持。特殊13系統も個別運賃が不明のまま
  検索対象には追加しない。
- 実GTFS 149系統／35,329便を一括棚卸し済み。
  従来5系統の開発用coverageは維持し、**未審査143系統＝制度上対象外
  143系統という意味ではない**。現在の5系統対応を「全路線対応」と案内しない。
- 通常名称130系統の実GTFS注記調査では、109が便種別の注意点、
  42系統は23時以降のGTFS時計フラグだけ、87系統は当該フラグなし。
  23時の時刻は深夜割増運賃の証明ではない。どの分類も無料の審査済み判定ではない。
- 第1段階では公開根拠・feed identity・運行日・便種別の突き合わせを維持した上で
  市営バスを段階的に追加。静的なODPT地下鉄時刻表のライセンス・有効日・
  事業者ID・乗継を確認し、地下鉄とバスを統合する。
  **Realtimeと民営バス全事業者網羅は初回公開条件にしない**。
- 初回公開条件は、選択した「福祉パス／敬老パス」で
  追加支払0円と検証済みの経路のみを返すこと。
  検索結果なし・未対応・未確認・データエラーを区別し、
  少数の公式時刻表に照らしたOD正解例で運行日、乗換、境界条件を確認する。
  初回から全事業者横断の30～50例完成は要求しない。

公式制度資料：[福祉パス利用交通機関](https://www.city.yokohama.lg.jp/faq/kukyoku/kenko/shogaijiritsu/20211015164324433.html)、
[敬老パスの利用交通機関](https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/ikigai-shakaisanka/keirou.html)、
[福祉特別乗車券](https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/fukushi/annai/gaishutsu/kotsu/fukushi-jyosyaken/ticket.html)。

実装タスクと後続フェーズの優先関係は [Issue #241](https://github.com/kaeruko/tobus_go/issues/241) 冒頭の新方針を優先する。
以下の系統別レビュー台帳・トリアージは**過去の調査資料・例外探索ツール**として保持する。
当面、149系統を1本ずつ審査し続ける作業を再開しない。


### 横浜市営地下鉄GTFSの事前検証（2026-10-14）

[ODPTの横浜市営地下鉄カタログ](https://ckan.odpt.org/dataset/yokohama_municipal_train)には
2025-12-26版の静的GTFS（有効期間2025-12-26〜2026-12-31）が公開されている。
[リソースUUID](https://ckan.odpt.org/dataset/yokohama_municipal_train/resource/27ed8a34-c89f-4c5c-98af-5950f04183e2)
は `27ed8a34-c89f-4c5c-98af-5950f04183e2`、feed_version は `20251226`。
**ODPT開発者登録／APIキー、基本ライセンスおよび特定利用条件の確認は依然必要**。
データはまだこのリポジトリに取り込んでいない。実データとの照合も未実施。

`api/yokohama_subway.py` に読み取り専用
`load_yokohama_subway_dataset(directory, expected_service_date=...)` を実装。
利用者端末や横浜runtimeへの自動接続は**まだない**。

- 別途用意する `yokohama_subway_gtfs_manifest.json` に
  配布元URL、資源UUID、バージョン、タイムゾーン付き取得日時、
  運行日、版の有効期間、GTFSの各 `*.txt` ファイルのSHA-256を記録する。
- 解凍済みGTFSの実バイトがSHA-256と一致し、`feed_info.txt` の版、
  `agency.txt` のAsia/Tokyo、予定運行日に稼働する便、全routesの
  railモード、有限な停留所座標を満たした場合のみ
  `yokohama_subway:*` namespaceの `TransitDataset` を返す。
- 不一致・欠落・当日の便ゼロは**fail-fast**。ファイル書込みなし。
  合成GTFSに対する回帰テストを `api/tests/test_yokohama_subway.py` に追加。
- manifestの自己申告URLとローカルハッシュ一致は**配布元の真正性・利用許諾の証明にはならない**。
  また公式のGTFS route IDをブルー／グリーンの2個とは仮定しない。
- 次は、正規取得した実GTFSと個別ライセンスを確認した後、
  市営地下鉄の完全なroute-coverageのレビュー、横浜市営バスとの
  複数feed乗換検索を実装・テストする。**現時点では地下鉄を検索対応済みと表示しない**。


### 地下鉄GTFSの認証付きローカル取得（2026-10-14）

既存バスGTFS用の安全な取得処理に倣って、**手元のODPTキーを用いて**
市営地下鉄の静的GTFS（ODPTカタログの2025-12-26版）を取得する
`scripts/fetch_yokohama_subway_gtfs.py` と
`api/yokohama_subway.py::fetch_yokohama_subway_gtfs` を追加。

- `api/.env` の `ODPT_API_TOKEN` をローカルで読む（既存の環境変数を優先）。
  APIキー、認証付きURL、レスポンス本文は標準出力・GitHub・エラー文に含めない。
  **自動HTTPリダイレクトは禁止**し、検証済みのHTTPS転送先への無認証GETだけを許可。
  想定外のHTTPステータスでは停止する。
- **302対応（2026-10-14修正）**：実際のODPT地下鉄ZIP GETがHTTP 302を
  返し、全リダイレクト禁止の旧実装で取得失敗した。認証情報付きのODPT初回リクエスト
  のみ認証し、HTTPSのODPT/既知CDNストレージホストへ限定して最大3段まで
  **新規・無認証GET**で追う。途中のURLの`acl:consumerKey`やAPIキーの
  埋込み、HTTP転送先・未知ホスト・別ポートは拒否。クライアント既定の
  認証ヘッダやCookieも転送先には引き継がない。リダイレクトURL全文を
  ログに出さず、想定外のホストはホスト名だけを診断表示する。
  2026-10-14の実端末ログで **dataodpt.blob.core.windows.net**（Azure Blob Storage）が
  転送先と確認できたため、このホスト**だけ**を明示的に許可した。
  Azure Blob Storageドメイン全体は許可しない。偽装サブドメイン・HTTP・不正ポート・
  APIキー入りLocationは拒否し、SAS等の署名付きクエリは無認証GETに限り保持する。
  ただし実ZIP本体のダウンロード成功・正式GTFS版との一致は再実行まで未確認。
- `--output` は**存在しない新規ディレクトリ**のパスで、親は存在する必要がある。
  同名ディレクトリは上書きしない。ZIPのパス移動、シンボリックリンク、重複
  TXTベース名、不明拡張子、容量上限超過を拒否。検査後に一括で配置するため、
  エラー時に不完全な取得物を最終出力に残さない。
- 必須GTFSテキストの取り込み後、ローカルsha256 manifestを生成し、
  `feed_info.txt` の正規バージョン、適用日、Asia/Tokyo、鉄道route、
  当日の運行便があることなどを**既存の厳格なloaderで再検証**する。
  このmanifestは配布元の真正性やライセンス許諾の証明とは別。
- `api/tests/test_yokohama_subway_fetch.py`で、HTTP 200正常系、401拒否、
  302拒否、破損／別版ZIP、zip slip、重複エントリ、既存フォルダの保護を
  **httpx.MockTransportの合成データ**でテストする。実ODPTとの通信ではない。
- **重要**：カタログ日付 `20251226` とGTFS内のfeed_info版が本当に一致するかは
  実ダウンロードで最終確認が必要。違う場合は勝手に受け入れず停止し、
  データ版・リソースIDの実体と公式更新履歴を調べる。

ローカル実行例（**GTFSおよび個人のキーはGitに加えない**）：

```powershell
cd C:\Users\mail\work\tobus_go
python scripts/fetch_yokohama_subway_gtfs.py `
  --output ".\api\data\yokohama\subway_2025-12-26" `
  --expected-service-date "2026-09-04"
```

**日付合わせが必須**：既存の市営バス開発用GTFS manifestは
`validated_service_date=2026-09-04`なので、直後のバス＋地下鉄の
乗換候補監査に流す地下鉄GTFSも**同じ日付で取得・検証**する。
現行loaderのmanifestは検証日を固定している。先に2026-10-14で
取得した出力を、そのまま監査の2026-09-04に流用してはいけない。

このコマンドは現在まだ実行済みではない。既に出力先がある場合は
**削除・上書きをせず**別の新規パスを指定する。
動作したとしても、地下鉄の経路探索をruntimeに接続したことにはならない。
[ODPT公式カタログ](https://ckan.odpt.org/dataset/yokohama_municipal_train)で
基本ライセンス／特定利用条件を先に確認する。

### 調査結果の訂正：空欄時刻はブルーライン快速通過駅と一致（2026-10-14）

ユーザー実機の既存ローカルGTFS `stop_times.txt` に対して読み取り専用で集計した結果：
全38,805行のうち**到着・出発がともに空欄は1,674行（約4.31%）**。
空欄は下記14駅**だけ**に集中している。港南中央・弘明寺・蒔田・吉野町・
阪東橋・伊勢佐木長者町・高島町・三ツ沢下町・三ツ沢上町・片倉町・岸根公園
（各120行）、舞岡・下永谷・北新横浜（各118行）。
11×120＋3×118＝1,674ですべて説明できる。

**重要な訂正**：この14駅は、確認したブルーラインの**快速通過駅14駅と完全一致**。
したがって以前の「ランダムな欠測・重大なデータ品質不備」という説明は
**確証がなく、快速の通過を示す空欄という解釈が最有力**である。
快速はこれらの駅に停まらないため、検索上は対応便の空欄行を乗降に
使わないのが自然。下記旧節の「欠損」「非準拠データ」の扱いは
**今回の訂正を優先**し、無条件に実用不能と判断しない。

根拠：[ブルーライン快速停車・通過駅一覧](https://trainstation.jp/yokohama-subway-b/blue-line-route-map)、
[横浜市営地下鉄の公式時刻表](https://navi.hamabus.city.yokohama.lg.jp/koutuu/smart/top/Top?force=sp)。
ただし、各空欄行の `trip_id` と `trips.txt` の列車種別、
`pickup_type` / `drop_off_type` は**まだ照合できていない**。
通過列車と完全に確定するには1便の空欄前後・種別・乗降フラグを実データで確認する。
GTFS正規準拠かどうかの判定もそれまで保留。

ローカルダウンロード再実行が `FileExistsError` となった一方、
同じパスの `stop_times.txt` は読み取れた。したがって
**ローカルにデータファイルは存在する**が、manifestの存在・検証成功・
検索への組込みが完了したことを意味しない。既存ディレクトリは削除・上書きしない。

また過去のTransitland「38,805行と9,940行の差28,865」を
空欄時刻行数と同一視する説明は誤り。実際の両時刻空欄は1,674行のみ。
外部取り込みとの差分原因は別途調査が必要。

### ブルーライン快速の乗降禁止フラグ実証（2026-10-14）

ユーザーの実ローカルGTFSを1便確認した結果、`trip_id=b01030b`、
`route_id=br32-01`、あざみ野10:00発・湘南台11:01着で、
**快速通過駅の空欄行にすべて `pickup_type=1` と `drop_off_type=1`**
が入っていた。新羽10:13→北新横浜(通過)→新横浜10:15や、
横浜10:26→高島町(通過)→桜木町10:28など、快速らしい停車パターンも一致。
`timepoint`は表示上空欄。GTFS仕様で1は「乗車禁止」「降車禁止」。
ソースファイルはそのままで、**この便については通過駅と判定できる**。
上記空欄1,674行すべてのpickup/dropoffフラグについては、まだ全件を
機械的に集計していない。14駅の集中と本便の整合から快速の通過表現と推定。

[GTFS stop_times公式仕様](https://gtfs.org/documentation/schedule/reference/)

これを根拠に横浜地下鉄専用の`skip_untimed_intermediate_stops`を
さらに厳格化し、**arrival/departureとも空欄の中間行は、
`pickup_type=1`かつ`drop_off_type=1`の両方が明示されている場合だけ**
通過駅として無時刻のまま除外する。乗降可の可能性がある行、
乗降フラグなしの行は**例外で停止**する。時刻は補間しない。
通過駅でも、普通列車で時刻が設定されていればその便から乗降可能。

`manifestあり=True`もユーザー環境で確認されたが、
ファイルのハッシュと日付をloaderで再検証しない限り
「正式検証済み」とは断定しない。現時点では既存ローカルフォルダを
削除・再ダウンロードせず、**read-onlyのloader検証**を優先する。

### 横浜地下鉄実データの未指定timepoint互換（2026-10-14追補）

実端末の再ダウンロードで`GTFS untimed intermediate stop requires explicit timepoint=0`
が発生した。GTFSの規格では**timepoint未指定はexact扱い**なので、
時刻空欄＋未指定は不完全な入力であり、`timepoint=0`と同等に
扱って「その駅で乗れる時刻」を推測してはならない。

今回、**横浜地下鉄だけ**互換モードを拡張し、時刻空欄の中間停車行が
`timepoint=0`か**未指定（空欄／列欠落）**の場合、時刻を補わず
検索対象の`stop_times`からのみ**省略**する。
`timepoint=1`（確定）や不正値は拒否。始発・終着、未知stop、
重複sequence、時刻付き停留所不足、別feedの取扱いは従来通りfail-closed。
`stops.txt`や取得した`stop_times.txt`の原本は無変更。
検索は時刻が確定している駅のみで成立し、**全駅の利用可能性を意味しない**。

取得成功時には次の件数をコンソールへ表示する：
`source_stop_time_rows`（原本）、
`searchable_stop_time_rows`（検索可能）、
`excluded_untimed_intermediate_rows`（除外総数）、
`excluded_untimed_rows_missing_timepoint`（timepoint未指定による除外数）。
多量に除外された場合は地下鉄を実用と扱わず時刻表供給元や別データを検討。
GTFSを無条件に承認したり、0円の乗車区間を推定したりはしない。

### 地下鉄GTFSの空白stop_times対応（2026-10-14）

実機でAzureからのZIP取得・ZIP展開・ローカルGTFSのSHA-256照合が進み、
`GtfsTransitAdapter.load`の`stop_time requires arrival or departure`で停止。
GTFS仕様では`timepoint=0`の中間停車駅の時刻が省略できる。
`api/transit_adapters/gtfs.py`に**既定off**の
`skip_untimed_intermediate_stops`を追加し、横浜地下鉄loaderだけonにした。

このモードは**最初・最後の駅**では時刻空欄を拒否し、
中間駅でも`timepoint=0`が明示されている場合に限り
到着・出発ともに空欄のレコードを**検索可能なstop_timesから除外**。
時刻の線形補間などの推測は一切しない。除外した駅では**乗降経路を返さず**、
時刻がある前後の駅間の列車乗車だけを検索できる。ソースファイル自体は
一切変更しない。未時刻の中間駅が存在する場合、停車駅表示も部分的になる。

`timepoint`が省略されている空欄行、時刻がない始発/終着、
時刻付き駅が2点未満になる便、stop_id/trip_idの不整合、
stop_sequence重複などはfail-fastで止める。
他都市のGTFS adapterのstrict動作は変更しない。

**重要：** この対応で実ファイルが正常に読み込めたかどうかは
ユーザー手元での再実行まで未確認。GTFSのtimepoint情報が
そもそも無い場合は自動で規則を緩めず、データの実態を調べる。

[GTFS Schedule Reference / stop_times.txt](https://gtfs.org/documentation/schedule/reference/)

### 市営交通の乗換候補トリアージ（2026-10-14）

`scripts/audit_yokohama_transfer_candidates.py` を追加。**read-onlyの調査専用**であり、
実際に通行できる徒歩乗換の承認、追加支払0円の認証、本番の乗換設定変更はしない。

- 実GTFSで検証済みの横浜市営バス側は、ユーザーの開発用coverageで`local`承認済みの
  路線と、その日実際に有効なtripが停車するstopだけが候補に入る。
- 地下鉄は別feed `yokohama_subway` の有効運行日のstopを参照するが、
  **これらの地下鉄路線はまだ福祉・敬老パスで無料承認されたわけではない**。
- 2つのfeedの名前やIDを勝手に一致扱いにしない。同一日、位置座標の直線距離
  （初期300m、最大600m）で候補だけを提示。各ペアに
  `walkable_route_verified=false`、`pass_fare_verified=false`、
  `official_transfer_evidence_url=null`を明記。
- 名前・距離が近くても入口の違い、横断不可、改札やバリアフリー動線で
  歩行時間が大きく変わる。公式の乗換案内と実徒歩経路が裏付けられるまで
  `ExplicitTransferLink`に昇格しない。
- 手元の実地下鉄GTFSで実行できていない。
  合成GTFSの5件の純粋関数テストではread-only、
  未承認バス除外、不正日付・feed-ID・範囲・上限を検証する。

2026-10-14 実GTFS監査で直線300m以内 **11組**（高島町B19・桜木町B18の
2駅、バス乗り場ID11個）を抽出。バス側は審査済み105ポール、
地下鉄側は全42駅から同日有効な時刻を持つ駅を選んだ。
結果はすべて `UNVERIFIED_GEOMETRIC_HINT` で、バス⇄地下鉄の
ゼロ円経路を11件承認したわけではない。

2026-10-14 **高島町候補の扱いを訂正**：
ユーザーのGoogleマップ画像では「高島町（住所・地点）」から地下鉄高島町駅が
**徒歩260m/4分**、「花咲橋（バス）」からが**徒歩280m/4分**、
別の周辺乗り場からが約400m/6分だった。前者は**バス標柱そのものを
起点としたルートと確認できていない**ため、これを
`yokohama_bus:3018_02`の確定徒歩距離と主張しない。
前回の監査の直線**65.6m**と**148.3m**もそれぞれ
**GTFSの停留所座標→GTFS駅座標**であり、実際の駅入口までの徒歩ではない。

横浜市交通局公式の[高島町バス停ののりば地図](https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusAboardMap?stCode=00090598)
と[花咲橋ののりば・系統一覧](https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusCourseSearch?busstopId=00090878)
で**両方とも市営バス停として存在する**ことを確認。
106系統などで方向別に「高島町→花咲橋」「花咲橋→高島町」と
通る順序が異なることも公式時刻表に載っている。
駅周辺バス停一覧は「すべての乗換可能停留所」を保証する情報ではなく、
**掲載されていないことを除外条件や低優先度条件に使わない**。
高島町`3018_02`と花咲橋`5015_03`を、GTFSで
当日の便がある限り並列の未承認候補として保持する。
優先順位を確定するには、実標柱の座標・方向別便の系統/行先、
駅出入口までの徒歩道筋、改札/ホームまでの移動時間を照合する。

2026-09-04の**実GTFSによる方向別調査結果**（2026-10-14確認）：

| バスGTFSポールID | バス停名 | 当日の審査済み便の系統 | `trip_headsigns` | 緯度/経度 | GTFS駅B19への直線 |
| --- | --- | --- | --- | --- | ---: |
| `yokohama_bus:3018_02` | 高島町 | `yokohama_bus:008` / 008系統 | **本牧車庫前 行** | 35.4584547 / 139.6244306 | 65.6m |
| `yokohama_bus:5015_03` | 花咲橋 | `yokohama_bus:008` / 008系統 | **横浜駅前 行** | 35.4576028 / 139.6248422 | 148.3m |

地下鉄`yokohama_subway:B19`のGTFS座標は
35.458576 / 139.623722。地下鉄側の同日有効な
`route_id`は`bn01-27`等のブルーライン運行区間・
行先別レコード10件。営業路線10本を意味しない。

**重要**：GTFS実データで確認できたのは、**審査済み008系統が
高島町ポールでは本牧車庫前行、花咲橋ポールでは横浜駅前行を扱う**
という方向性の違い。どちらの停留所を使うかは利用者の
**出発地・目的地・乗車/降車方向・当日の便時刻**で変わる。
「直線距離最短」や「駅公式の周辺一覧に載るか」では決定しない。
また`active_reviewed_bus_routes`は**運賃審査済みの便だけ**を
表示しており、他の系統が物理的に停車しないことを意味しない。

両ポールとも`stop_code`・`platform_code`・
`parent_station`・`stop_desc`はGTFSでは空欄
（`location_type=0`）。したがってソース側から
**公式バスのりば番号を直接確定できない**。
Googleマップの「高島町」地点の徒歩260m/4分と
「花咲橋（バス）」徒歩280m/4分は参考情報だが、
それらのピンが上記の**ポールIDそのもの**を指すかは未検証。
地下鉄B19座標は駅のGTFS停車位置であり、
**駅出入口・改札・ホームまでの徒歩リンクと同一視しない**。

現在の結果は`candidate_pair_count=11`、
`focus_matching_pair_count=2`、
`shown_pair_count=2`。
両方とも`UNVERIFIED_GEOMETRIC_HINT`で、
`official_transfer_evidence_url=null`、
`walkable_route_verified=false`、
`pass_fare_verified=false`を維持。
方向別の便と実際の乗り場位置に紐づけるまでは
`ExplicitTransferLink`を作らない。

新しい監査オプション：
`--focus-bus-stop yokohama_bus:3018_02 --focus-bus-stop yokohama_bus:5015_03`
で**元の候補11件の算出は変更せず、表示だけ2件に限定**。
`--include-bus-pole-fields`はローカルのGTFS `stops.txt`を
**読み取るだけ**で`stop_code`、`platform_code`、
`parent_station`、`stop_desc`等を出す。任意のsource
`platform_code`が存在しても、**公式地図の番号付きのりばと
同じと推定・自動認証しない**。各候補のGTFS緯度・経度も表示。
焦点表示の`candidate_pair_count`は元の全件11件のままで、
`focus_matching_pair_count`を別途返す。
既存coverage、公式乗換承認、公開経路検索は変更しない。

公式資料の突合：
- [桜木町駅B18の公式駅情報](https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/detail/Station?id=00002909)
  は周辺市営バスに「桜木町駅前」を表示する。
  [桜木町駅前のりば一覧](https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusAboardMap?stCode=00090408)
  には複数の番号付きのりばと路線・行先が掲載されるが、
  GTFSの`2014_12`・`2014_08`などと各番号の対応は不明。
- [高島町駅B19の公式駅情報](https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/detail/Station?id=00002620)
  の周辺バスは「花咲橋」「戸部警察署前」で、
  最短候補の「高島町」`3018_02`は**この公式一覧にない**。
  [高島町バス停のりば一覧](https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusAboardMap?stCode=00090598)
  は別途確認可能だが、駅入口までの連絡を保証しない。
  [花咲橋のりば一覧](https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusAboardMap?stCode=00090878)
  は公式地下鉄駅情報と名称が一致。
- [横浜市の福祉パス対象交通機関](https://www.city.yokohama.lg.jp/faq/kukyoku/kenko/shogaijiritsu/20211015164324433.html)
  と[敬老パス](https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/ikigai-shakaisanka/keirou.html)
  は**市営地下鉄全線**を対象と明記。ただしGTFSの全25`route_id`が
  市営地下鉄の通常運行であるとの識別・承認は未完了。

駅構内図・公式のりば地図を参照しながら、GTFS停留所IDと番号付きのりばの
対応、出入口、横断歩道、徒歩距離と改札/ホームまでの時間を別々に確認する。
`straight_line_distance_m`を歩行距離として転用しない。

監査のJSONに`active_reviewed_bus_routes`と
`active_unapproved_subway_routes`を追加。
両方とも**当日の有効GTFS便がそのポール・駅を使うroute_id/系統名/
行先の候補表示だけ**で、公式のりば番号の証明でも、
地下鉄の無料承認でもない。後続でGTFSの便と公式のりば番号を
照合する材料に使う。既存11組の判定フラグ・sort・limitは変えない。

地下鉄のGTFS内部路線25レコードについて、
`scripts/audit_yokohama_subway_routes.py`を追加した。
これはmanifest/ハッシュ/GTFS版/運行日を検証したうえで、
全25`route_id`ごとの生GTFS路線名・agency_idとagency_nameの対応、
当日有効便数・時刻が記録された駅数を**read-only**で出すツール。
`distinct_source_route_names`はGTFS上の名前の組数であり、
実際の営業路線数（ブルー・グリーンの2路線）と一致する保証はない。
複数agencyの中でrouteのagency_idが欠落していれば判定保留、
未知agency_id参照は拒否する。**全レコードに
`UNREVIEWED_GTFS_ROUTE_ID`を明示**し、現時点で1件も
運賃承認を生成しない。

```powershell
python scripts/audit_yokohama_subway_routes.py `
  --subway-gtfs-dir ".\api\data\yokohama\subway_2025-12-26" `
  --service-date "2026-09-04"
```

実GTFS取得後の読み取り専用例（両路線のデータが存在する場合のみ）：

```powershell
cd C:\Users\mail\work\tobus_go
python scripts/audit_yokohama_transfer_candidates.py `
  --bus-gtfs-dir ".\api\data\yokohama\2026-09-04" `
  --bus-coverage ".\api\data\yokohama\2026-09-04\coverage_dev_288.json" `
  --subway-gtfs-dir ".\api\data\yokohama\subway_2025-12-26" `
  --service-date "2026-09-04" `
  --radius-m 300 --limit 20
```

**公開時のODPT準拠は別作業**。
[公共交通オープンデータ開発ガイドライン](https://developer.odpt.org/terms/data_basic_use_guideline.html)
では静的データの取得日時の利用者への表示、更新通知後の原則1週間以内のデータ更新、
データの出典・精度非保証・利用者の問い合わせ先（アプリ開発者）を画面に明記する旨を規定。
事業者の**特定利用条件が優先・追加適用**される可能性があるため、
ライセンス条件を満たすまでは地下鉄を公開済みと扱わない。
`ODPT_API_TOKEN` や取得した保護対象データをGitへコミットしない。

### 東京の既存検索を横浜で再利用するための実装境界（2026-10-14）

既存コードを調査した結果、`api/toei_engine.py`の
`connect_walk_edges_phys`は**座標から300m半径以内の
物理ノード同士に徒歩エッジを設定**する方式。
東京では「同名の停留所の何番のりばかを公式図で1件ずつ登録」
してから接続する方式ではない。
同名の停留所はGTFS/ODPTの個々の**stop ID/trip**で区別する。
したがって横浜だけ、公式駅の周辺停留所一覧に掲載があることや、
バスの公式のりば番号を手作業で全件登録することを
一般的な検索実装の前提に**しない**。

横浜側の`api/gtfs_route_backend.py`は既存の
`TransitRouteEngine`/`SearchCore`を利用するが、これまでは
**BUS専用のassertと`kind="bus"`固定**が残り、
validな地下鉄のRail datasetを単独でも受け付けなかった。
今回、共通GTFSバックエンドで`TransitMode.RAIL`も受け付け、
実際の便の`route.mode`で`kind="rail"`を出すようにした。
`bus_only=True`かつrail入りdatasetは**railを返さず、
未対応の混合モードフィルタだと明示して拒否**する。
バス専用datasetは従来通り。同名の逆向き停留所が
**別stop ID、別trip**で正しく選ばれることもテストする。

**この段階の成果は単一GTFS feedの鉄道単独検索が共通バックエンドで可能に
なったこと**であり、複数feedを一つの`TransitDataset`に混ぜてよいという
意味ではない。`TransitDataset`はfeed namespaceを検証するため、
バスと地下鉄をID表示名や位置で無理やりマージしない。
次工程は**既存の各feed時刻表検索・乗換探索を横浜`/route`の
契約に接続**すること。徒歩接続は東京版と同様に交通ノードの座標を活用しつつ、
直線推定を実徒歩確定時間と偽装しない。
無料判定は`YokohamaFareCoverage`で便とoperatorを検証してから、
福祉/敬老passの各legが対象と確認された場合のみ0円にする。
**公式のりば番号の全件審査は採用条件ではないが、
時刻表/経路/無料対象の整合確認は必要**。

### 共通検索エンジンによるバス⇄地下鉄の近接乗換試作（2026-10-14）

[Issue #241](https://github.com/kaeruko/tobus_go/issues/241)の段階実装として
`api/yokohama_municipal_transfer.py`に
`search_geometric_municipal_transfers`を追加した。
これは**横浜の方向別停留所を特別扱いせず**、
東京`connect_walk_edges_phys`と同じくGTFS座標から近接する
バス標柱と地下鉄駅を探す**開発用・オフライン**の実装である。

- 市営バス・地下鉄を、それぞれ既存の`TransitRouteEngine`で
  便ID・停車順・運行日・予定時刻に従い探索する。
  stop IDはGTFSのfeed namespace付きで扱い、
  バス停の同名・方向別を名称で統合しない。
- `YokohamaFareCoverage.municipal_free_coverage()`で
  **先に審査済み路線/便だけへ絞って**各feedを探索。
  運賃は2便群の全rideについて既存の
  `YokohamaWelfarePassFarePolicy`または
  `YokohamaSeniorPassFarePolicy`を実行して0円を再確認。
  **地下鉄のroute IDが未審査なら検索結果は空**。
- 当日の有効な停車時刻を持つ駅・標柱のみ近接候補とし、
  既定の直線距離300m（最大600m）で判定する。
  ストップIDの対応を公式のりば番号で手入力する必要はない。
- 徒歩距離は暫定で**直線距離×1.5**、徒歩所要時間は
  **80m/分＋2分**で推定。これは**道路の測量・駅出入口・
  横断歩道・改札までの時間を検証した値ではない**。
  `GeometricTransferEstimate`と
  `MunicipalTransferPlan.walking_connection_verified=False`を
  明示しており、**結果をそのまま本番APIや地図の確定徒歩案内へ渡さない**。
- 一度のバス⇄地下鉄乗換を試す**限定的な検索**であり、
  2回以上のfeed横断乗換、全ネットワークの最適経路、
  日付を跨ぐ乗換、徒歩経路のアクセシビリティは未対応。
  日付跨ぎが必要ならfail-fastで停止する。
- 一度の検索で候補上限（既定40組）を超える場合は
  途中で任意切捨てせず失敗させる。
  **検索の完全性を誤表示しない**。
  2feedの時刻表indexは候補ごとに作り直さず
  **検索当たり各1回**生成する。
- 既存の`ExplicitTransferLink`は根拠付きの手動評価用として
  保持したが、近接検索はこの公式リンクや乗り場一覧掲載を
  前提にしない。根拠付きと未確認の近接リンクを区別している。

`api/tests/test_yokohama_geometric_transfer.py`で、
両パス、バス→地下鉄、地下鉄→バス、速いが対象外の
観光便の除外、近接しない/乗換時刻に間に合わないケース、
未審査地下鉄の排除、入力制限と候補上限、GTFS index再利用を
合成データで確認する。既存の東京版・Flutter・横浜`/route`は
**一切接続変更しない**。

**本番接続に残ること**：
1. 実GTFSに含まれる25の地下鉄route recordsを
   operator/agency/route semanticsで確認し、
   福祉・敬老パスに適用する運賃カバレッジを確定
   （25路線分の別制度を手作業で調べる必要はない）。
2. 実停留所・時刻表で近接乗換の成立性/徒歩アクセスを評価し、
   現在の推定歩行を正規の歩行経路扱いしないこと。
3. 現行`/route`契約へ複数feedの旅程と待機・徒歩・
   rail/bus stepを出力する統合Backendを実装し、
   `bus_only`、無料判定、エラー挙動を回帰検証すること。
4. 静的データ起動・feed更新・運行日・日跨ぎ・Flutter表示を
   実データで合格させること。

### 市営バス⇄地下鉄 位置ベース徒歩乗換のローカル試験モード（2026-10-14）

`api/yokohama_municipal_backend.py`には
`YOKOHAMA_TRANSFER_WALK_MODE`を導入した。
**既定値`reviewed`は変更なし**：別途レビュー済みの
`YOKOHAMA_REVIEWED_TRANSFERS_PATH`内の明示リンクだけでバス⇄地下鉄を接続する。
公式のバス乗り場番号を全件登録する必要はないが、
実用的に歩けることがまだ未確認の区間を公開経路だと見せない。

`estimate_dev`は**`create_app("local")`だけ**で利用でき、
他のbackend実行モード（クラウド本番・Lambda等）では
起動時にfail-fastで拒否する。設定する場合は、検証済みの
`YOKOHAMA_BUS_GTFS_DIR`・`YOKOHAMA_SUBWAY_GTFS_DIR`・
`YOKOHAMA_FARE_COVERAGE_PATH`を揃えること。
運賃検証を回避する機能ではない。

`estimate_dev`では、審査済みのバス・地下鉄それぞれの
GTFS停留所・駅の座標から**300m以内の近接リンクを自動生成**し、
既存のSearchCoreの時刻表で乗り継ぎを検索する。
徒歩は直線距離×1.5、80m/分＋2分という**暫定の推定**で、
`walking_connection_verified=false`、
`walking_route_confirmed=false`、
`distance_basis=straight_line_estimate`と明記する。
**駅入口や道路の通行可能性、信号待ち、段差・エレベーター、
ホーム移動時間を保証しない**。表示用に無印の
確定徒歩案内として利用しない。位置ベースの候補は最大100件、
超える場合は切り捨てず`RouteSearchLimitError`。

このローカル試験機能で東京と同様に「同名・方向別のGTFS ID」
で徒歩接続候補を探索できるが、**実データの計測・公開仕様の最終承認までは
`reviewed`を本番既定値から変更しない**。
合成回帰テストは`api/tests/test_yokohama_municipal_backend.py`。
データ更新・無料審査・アクセシビリティ・実歩行経路の検証は別工程。

### 市営バス⇄地下鉄の明示乗換プロトタイプ（2026-10-14）

`api/yokohama_municipal_transfer.py` は、先に確認した
**バス停IDと地下鉄駅IDの1組**についてだけ、両方向の
時刻表乗換が成立するかを検証する**runtime未接続の内部プロトタイプ**。
実データの横浜路線網や実在の乗換地点をすでに登録したものではない。

- 入力は実運行日を持つJST日時、両パスのいずれか、
  `YokohamaFareCoverage`（バスと地下鉄それぞれ独立、系統の承認必須）、
  `ExplicitTransferLink`（元バス停ID、元駅ID、出典URL、徒歩距離と分数）。
  同名駅・同名バス停の名前から結合せず、feed間IDを統合・変更しない。
- それぞれの既存 `TransitRouteEngine` で運行日と便を検索。
  1本目の到着から**徒歩時間を経過させた後**でしか2本目へ乗れない。
  バス→地下鉄、地下鉄→バス双方を試験済み。1本目／2本目の
  すべての乗車を `FarePolicyContext` で**両パス別に0円検証**する。
  未確認系統・観光バスを探索候補に入れず、不適合なら fail-closed。
- 公式HTTPSの出典、徒歩時間>=距離/80m毎分、両停留所間の
  直線距離 <=600m、および申告徒歩距離が直線距離以上を検証する。
  **これらの機械検査は歩行可能経路の実在証明ではない**。
  駅の改札移動、道順、段差、道路横断、実際の所要時間は個別確認が必要。
- 24時跨ぎの乗換は現状拒否する。複数乗換、経路の全体最適化、
  現在地からの駅検索、APIの /route とFlutterへの接続は**未完成**。
- 合成バス・地下鉄GTFSで乗換時刻、双方向、未承認便の除外、
  不可能な乗継ぎ、地理的に不可能な接続、未知パスをテスト。
  **横浜市交通局公式の駅・バス停の乗換ペアや実地下鉄GTFSでは未検証**。

ODPTの地下鉄ZIPは認証が必要で、GitHubの公開コードからWindowsの
`api/.env` やローカルGTFSにはアクセスできない。機密APIキーを
ログ／コミット／Issueへ記載しない。

### 市営149系統のレビュー台帳照合（#241）

既存のカタログ棚卸しを、単一の
`scripts/yokohama_municipal_route_reviews.json` と照合できる。
`--with-reviewed-registry` は共通提案ツールと同じGTFS名称・feed版・日付・
公式HTTPS根拠の厳格な確認を行い、台帳とcoverageの矛盾があれば停止する。
**出力は標準出力のみ**で、GTFS・coverage・台帳を変更しない。

```powershell
python scripts/review_yokohama_bus_route_catalog.py `
  --gtfs-dir ".\\api\\data\\yokohama\\2026-09-04" `
  --coverage ".\\api\\data\\yokohama\\2026-09-04\\coverage_dev_288.json" `
  --manifest-service-date "2026-09-04" `
  --ride-date "2026-09-04" `
  --ride-date "2026-09-05" `
  --with-reviewed-registry
```

報告の `review_registry` は `pending`・`development_eligible` と、
例外語・特殊名称・通常名称の未登録系統IDを分ける。
2026-10-14時点の検証済み開発用は008/089/200/280/288、271は明示除外、
272/275は個別運賃根拠が不足し `pending` を維持。
2026-10-14に特殊名称11系統（091/092/123/221/326/327/328/329/341/345/346）を、公式時刻表を根拠としてすべて `pending` 登録した。これらは一切 `development_eligible` にしない。
「急行」を「直行バス」と同一視せず、23時以降の時刻を深夜割増とみなさない。
通常名称130系統も名前だけで無条件無料にしない。
制度上の路線一括適用と、便単位の追加支払がある例外を区別して審査する。

公式参照: https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/ikigai-shakaisanka/keirou.html
および https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/fukushi/annai/gaishutsu/kotsu/fukushi-jyosyaken/ticket.html。
「おでかけシャトル」と市営272/275「ふれあいバス」は別途審査する。

### 特殊名称11系統の時刻表調査（2026-10-14）

公式時刻表から実在・路線名を確認できた11系統を共通レビュー台帳に登録。
**全件 `pending`**。GTFS v3.0_20260727との完全名称一致と両パス一般制度ページへの
参照は記録したが、いずれも当該系統の**追加支払0円**を独立保証する資料ではない。

- 急行10系統：091（根岸・三菱本牧工場方面）、092（横浜駅西口・笹山団地方面）、
  123（横浜駅・日産本牧専用埠頭方面）、326（横浜駅西口）、327（桜木町駅前）、
  328（本牧・横浜駅前）、329（三ツ沢上町駅前・横浜駅西口方面）、
  341（本牧・横浜駅方面）、345（十日市場・若葉台中央方面）、
  346（神大寺・横浜駅西口方面）。
- 特殊名称221：「鴨居・東本郷線」。地域・独自運賃制度に該当しないかを
  一般市営系統とは独立に確認する。
- 329はfeed内16便だが2026-09-04/05の探索対象日には0便。
  2026年の公式時刻表に路線名があることと、当該2日間の運行有無は別の検証事項。
- 急行は直行・高速・空港バスと同義ではない。最終承認前に乗車資格、
  便単位の特殊運賃／停車制限、両パスの適用を照会する。

各系統の時刻表URL・レビュー日・残課題は共通台帳の `evidence_urls` と
`remaining_checks` に保持する。現在の `local=5` / `sightseeing=1` /
`unreviewed=143` は変更していない。149系統の実GTFSと新台帳の照合は
台帳変更後のため未実行。合成GTFSのCIテストは別途確認する。

### 通常名称130系統の便メタデータ審査キュー（2026-10-14）

全149系統の実GTFS台帳照合が成功した。未登録は通常名称130系統のみ。
**「109系統特急」には別制度での取扱い例外がある**：
[横浜市営バス定期券の環境定期券制度](https://www.city.yokohama.lg.jp/kotsu/bus/unchin/bus_teiki.html)
では「あかいくつ、109系統特急」が対象外と記載されている。
ただし**環境定期券制度は2026-09-27に終了しており、福祉・敬老パスの対象外を示す証拠ではない**。
109系統の普通名称だけで承認できないことを示す *調査上の例* として用いる。

既存カタログツールに読み取り専用 `--ordinary-triage` を追加。
`--with-reviewed-registry` と同時指定が必須で、次を優先調査順の根拠として表示する。
- 通常名称・未承認の系統に属する便の `jp_trip_desc` /
  `jp_trip_desc_symbol` の有無、`trip_headsign` の例外語（深夜、直行、特急等）、
  23時以降の時刻フラグ、109系統の**別制度の歴史的注意点**
- 便の生IDサンプルは先頭5件に限定。IDは変換せず表示。
- 全routeのGTFS便数と元の全系統カタログの便数が一致しなければ
  fail-fast。既存ファイルへの書込みなし。
- フラグなしも `unreviewed` のまま。深夜時刻や「特急」の文字のみから、
  深夜割増・追加支払の有無を確定しない。

```powershell
python scripts/review_yokohama_bus_route_catalog.py `
  --gtfs-dir ".\\api\\data\\yokohama\\2026-09-04" `
  --coverage ".\\api\\data\\yokohama\\2026-09-04\\coverage_dev_288.json" `
  --manifest-service-date "2026-09-04" `
  --ride-date "2026-09-04" `
  --with-reviewed-registry `
  --ordinary-triage
```

報告の `ordinary_review_triage.priority_route_ids` から公式運賃を優先照合し、
`other_ordinary_route_ids` は無条件承認せず別途制度確認する。
2026-10-14にユーザー実GTFSでこのオプションの照合が正常終了（通常名称130の内、109が個別注意、42系統が23時時刻だけ、87系統がその他）。

### 実GTFSの130系統トリアージ結果と優先度分離（2026-10-14）

実GTFS `v3.0_20260727` を `--ordinary-triage` で照合し、書込みなく成功。
**130系統を以下の3つの審査グループに分割できた**。すべて無料適用は未承認。

| 層 | 実際の系統数 | 意味 |
|---|---:|---|
| `service_or_text_lead_route_ids` | **1（109）** | 制度・運行形態の例外を個別確認する手掛かり |
| `clock_only_informational_route_ids` | **42** | GTFS時刻が23:00以降というだけ。追加運賃の証拠でない |
| `other_unreviewed_route_ids` | **87** | 便説明・時刻から特別な注意点を発見できず、無料認証ではない |

42系統のGTFS23時以降表示は延べ246便、全系統の特別便注記数0・
例外キーワード一致0であった。この条件をまとめて `review_attention_tiers`
として表示する。従来の `priority_route_ids`（43件）は互換性のため保持するが、
実務上はまず `service_or_text_lead_route_ids` を確認し、23時フラグのみの42
系統は情報として分離する。41・105・51・13・301系統等も23時だけでは
有料深夜バスとは言えない。

根拠：
- [横浜市の2024-11-14基準公開回答](https://cgi.city.yokohama.lg.jp/shimin/kouchou/search/data/36003485.html)
  に「令和6年4月1日のダイヤ改正で深夜バスを廃止」と明記。
  これは市営バスについての歴史的事実であり、将来の再開可能性や他事業者の
  深夜割増を否定するものではない。
- [横浜市交通局の2026-03-28ダイヤ改正案内](https://navi.hamabus.city.yokohama.lg.jp/koutuu/smart/diagram/Search/bus?course=0001601091&startId=00090593&stopNo=14)
  に109系統直通の新設と特急便の一部変更が掲載されている。ただし
  「直通」と敬老パス制度上の「直行バス」を機械的に同一視して無料適用を除外しない。
- [横浜市の敬老パス最新案内](https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/ikigai-shakaisanka/keirou.html)
  は深夜割増発生時の差額支払いを規定しているが、現在の特定市営便に割増がある
  証明ではない。

`review_attention_tiers` は**調査順位のみ**で、合格・不合格や金額の自動判定
には使用しない。従来通り `local=5`、除外271、その他143件は未承認。

### 109系統の便種別混在・無料判定保留（2026-10-14）

市交通局の2026年時刻表では、同じ109系統に`急行`・`特急`・`直通`が混在。
2026年3月28日の改正では、`直通`便を新設し、`特急`の一部を移行した。
ただしGTFS `v3.0_20260727` の109系統は通常名称 `109系統` で、
`jp_trip_desc`・`jp_trip_desc_symbol`・行先表示の文面からは
便種別の独立認証に必要な区別を取得できていない（2026-10-14実データトリアージ）。

109を共通台帳の**`pending`**として登録する。全路線を
`development_eligible` にすることは禁止し、既存coverageの109は
`unreviewed` を保持する。109の単純な路線単位の許可は、実際の便種別が異なる
ため不適切。両パスについて便単位で制度適用と追加支払0円の公式根拠、
GTFS便IDと時刻表の対応が得られるまで検索対象に加えない。

- [109系統・急行の公式時刻表](https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusDiagram?course=0001601428&date=2026-09-01&orvCode=00091228&stopNo=1)
- [109系統・特急の公式時刻表](https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusDiagram?course=0001601160&date=2026-06-25&orvCode=00091228&stopNo=1)
- [109系統・直通の公式時刻表](https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusDiagram?course=0001601460&date=2026-09-08&orvCode=00091228&stopNo=1)
- [敬老特別乗車証の制度・対象外種別](https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/ikigai-shakaisanka/keirou.html)
- [福祉特別乗車券の制度](https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/fukushi/annai/gaishutsu/kotsu/fukushi-jyosyaken/ticket.html)

2026-09-27に終了した環境定期券の109特急対象外規則は**別制度**。
敬老／福祉パスの対象外を示す証拠として流用しない。
`直通`と`直行バス`を同一視せず、`高速道路を経由`だけで
`高速バス`と分類しない。2026年の公式時刻表が運行種別を示しても
個別乗車時の特別乗車証の有効性を証明するものではない。

この追記で台帳は16件（開発用2、pending14）となる。
既存の検索対象5系統、除外271、未審査143の分類は不変。
**本変更後の実GTFS名称照合は未実行**のため、成功とは書かない。
