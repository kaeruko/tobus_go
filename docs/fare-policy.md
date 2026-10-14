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


#### 288系統の実GTFS／独立公式時刻表照合（2026-10-14）

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
