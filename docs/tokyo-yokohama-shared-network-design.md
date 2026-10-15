# 東京・横浜の徒歩・乗換ネットワーク共通化 — 設計調査（RFC）

- 状態: **方式Bを採択。東京の探索本体を抽出し、共通データ/横浜比較アダプターを追加。本番runtimeの切替・デプロイは未実施**
- 調査したリポジトリ: `kaeruko/tobus_go` の `main`、`9522377009bedc617597a4a999f76057b9f0f0b2`（2026-10-14）。このSHAを基準に第一段階を実装。第二段階の基準は `9d3c3840b7b8a6e3a00cafca27afa99cc2a37e36`（2026-10-15 JST）
- 関連: [横浜でGO Issue #241](https://github.com/kaeruko/tobus_go/issues/241)
- **今回の対象は東京版と横浜版のみ**。仕掛かり中の他都市は、設計・探索比較・変更の対象にしない。
- 横浜の初回公開（市営バス＋市営地下鉄、無料対象を検証した便のみ）はこの大規模共通化の完了を待たせない。

## 1. 実コードから確認した現在の差

| 項目 | 東京 | 横浜 |
| --- | --- | --- |
| 経路探索 | `api/tokyo_route_engine.py` → `api/toei_engine.py` → `api/tokyo_search_labels.py`（東京の接続層）→ `api/transit_search_labels.py`（共通ラベル探索） | `api/gtfs_route_backend.py` の既存 `SearchCore` による各GTFSフィードの時刻表検索 |
| バス⇄地下鉄の徒歩乗換 | `walk` / `board` / `ride` / `alight` 等を同じグラフで扱う | `api/yokohama_municipal_backend.py` がバス・地下鉄を別に検索し、審査済みの徒歩リンクで**最大1回**つなぐ |
| 探索目的 | 最速 `time`、少乗換 `fewTransfers`、東京独自の `cost`（快適さ系の重み） | 共通 `SearchCore` は `fastest` / `fewest_transfers`。東京 `cost` と等価ではない |
| 候補 | 複数経路、実乗車便の連続性と循環路線の検証、時間・徒歩上限、部分結果/探索上限 | バス・鉄道の静的な具体便、フィード別探索、専用結合ロジック |
| 運行情報 | ODPT、バスGTFS、時刻表とリクエスト単位のRealtime情報 | ピン留めした市営バスGTFS/市営地下鉄GTFS、静的時刻表が初回公開条件 |
| 本番構築 | `api/app/tokyo_runtime_fast.py` は**コンパイル済みグラフ/時刻表**をLambda起動時に読込む | `api/app/yokohama_runtime.py` がピン留めされた各GTFSと審査coverage・徒歩リンクを読む |
| 運賃条件 | 東京の交通条件は既存の都営向け検索・fare scopeを維持 | 福祉／敬老パスの**確認できた0円対象**のみを探索対象にする。対象外/種別不明を含めない |

既存の共通部品:

- `api/transit_dataset.py`: フィード別ID、停留所、路線、便、時刻、運行日。
- `api/transit_adapters/gtfs.py` と `api/transit_adapters/odpt.py`: GTFS/ODPT→共通 `TransitDataset`。ただし**東京の本番がこのODPTアダプターを使用しているわけではない**。移行に実データ比較が必要。
- `api/transit_engine.py`: `SearchCore` 契約、Python版時刻表探索。`BatchSearchRequest` には出発/到着端点の徒歩時間があるが、**経路途中の徒歩遷移は未対応**。`TransitItinerary.legs` も乗車情報だけ。
- `api/search_core_factory.py`, `api/rust_transit_search_core.py`: Python/Rust/shadowによる同じ静的SearchCore契約。
- `api/route_engine.py`, `api/app/route_endpoint.py`: 共通API入力・候補出力の契約。
- `api/reviewed_walk_time.py`: 徒歩距離・時間の共通検査。ただし**ネットワーク探索全体の共通化ではない**。
- `api/route_fare_scope.py`, `api/fare_policy.py`: 都市・パス条件を分離する仕組み。

**結論**: 共通のデータ構造とAPIはあるが、経路途中の「徒歩→別路線へ乗車」の検索は東京グラフ側にしか一般化されていない。東京を現行SearchCoreへ単純に切り替えると機能が失われる。

## 2. 共通ネットワーク仕様案

以下は実装済みクラス名ではなく**内部モデルの候補**。既存APIへの破壊的変更を直ちに要求しない。

| 概念 | 内容 |
| --- | --- |
| `TransitNetworkSnapshot` | バージョンを固定した複数 `TransitDataset` と、有効と審査された**方向別**徒歩辺の不変スナップショット |
| `DirectedWalkLink` | 出発地点ID、到着地点ID、実際の徒歩m、保守的な分数、駅構内・ホーム到達が含まれるか、審査根拠/状態、対応する両feed版 |
| `RideEvent` | その運行日の具体 `trip_id`、上下車標柱/駅ID、便の停車順序、発着時刻 |
| `WalkEvent` | 経路途中の徒歩（方向・時間・距離・根拠と未確認表示を保持） |
| `Wait/BoardEvent` | 乗車準備時間、待機時間、乗車便。徒歩や改札移動と二重計上しない |
| `SearchScope` | 都市・パス・operator・路線・**便種別/区間**について検索前に適用する条件 |
| `RealtimeSnapshot` | 東京の検索ごとに凍結した遅延/運休の任意入力。静的時刻表と矛盾しない具体便を選択する |

概念上の流れ:

```text
東京: ODPT/GTFS（元データ） ──→ source adapter ─┐
                                                ├─→ TransitNetworkSnapshot
横浜: バスGTFS + 地下鉄GTFS ─→ source adapter ───┤        + DirectedWalkLink（審査済みのみ）
                                                │        + Fare/SearchScope
                                                └─────────────┐
                                                              ↓
                          共通の「実時刻表乗車 + 方向別徒歩」探索
                                                              ↓
                                都市固有の名称/運賃/表示アダプター
                                                              ↓
                           既存 RouteCandidate → Flutter（契約維持）
```

### 徒歩辺の厳格な取り扱い

1. **方向別審査**: バス→地下鉄を確認しても逆方向を自動承認しない。現在の横浜 `ExplicitTransferLink` は`_connections()`で両方向に使っているため、旧データを機械的にv2の相互リンクへ変換しない。
2. **座標＝経路ではない**: 停留所の代表点と地下鉄駅のGTFS座標だけで、入口・改札・ホームやエレベーター動線は確定しない。距離による近接は**調査候補**とし、本番の徒歩辺の自動作成に使わない。
3. **時刻は独立**: 公式の歩行距離、標準歩行時間、駅のホーム到達・列車乗車準備を分けて検証。標準3分などからバリアフリーの到着時間を断定しない。
4. **版の拘束**: stop/pole ID、両feedの版、審査根拠、審査日、動線/方向、アクセシビリティ審査状態を保持。GTFS更新で関係する版が変われば再審査まで保留。
5. **リスク封じ**: 未審査・距離だけ推定・不明ID・矛盾した距離/時間・不明な運賃条件は公開用の徒歩辺/乗車遷移から除外。閲覧用auditだけに残す。
6. **距離集計**: 出発地→停留所、交通間徒歩、到着駅→目的地、駅入口→ホーム準備の範囲を分けて合計する。経路表示と実際の乗車可能時刻を同じ値で計算する。

実例（**未承認のまま**）: 2026-09-04の手元の実GTFS監査で`yokohama_bus:3018_02`⇄`yokohama_subway:B19`は直線65.6m、`2014_12`⇄`B18`は直線83.6m。公式乗換検索では、それぞれ別方向の2番のりばに関する392m/10分、12番のりばに関する約97m/3分という案内が見つかっているが、GTFS標柱との完全同定・地下鉄ホームまでの動線・逆方向の時間が揃っていない。これらを製品用 `DirectedWalkLink` に自動登録しない。

## 3. 共通探索のアルゴリズム契約

- **具体便のみ**: ある運行日の許可された`trip_id`と乗降順を使用。別々の便を合成した存在しない「乗車」は禁止。循環系統の同便・同一方向・終端の検証を維持。
- **途中徒歩を探索**: `ride → walk → ride → walk → ride` を任意の許容上限まで扱う。徒歩の分数を次の出発便の発車前に加算し、間に合わない便を選ばない。
- **運行日/跨日**: GTFSの24:xx以降、ODPT運行日判定と到着日時の境界を明示。横浜現行の「徒歩乗換後に1440分以上なら拒否」はv2で検討すべき制限であり、制限のない解探索を暗黙に約束しない。
- **探索状態**: 最低限、物理ノード、時刻、直近/選択済み便、実移動済みの有無、乗車数、連続徒歩m、総徒歩m、探索目的のコストを保持。将来の取り得る遷移が異なる状態を同じキーとして誤除去しない。
- **探索優先順位**: 東京の`time`、`fewTransfers`、独立した`cost`、既存の候補順と生候補予算を保持。現行のcost/fewTransfersは詳細化・重複排除前の候補数を制限するため、異なる有効経路の厳密なtop-Kを保証する契約は追加しない。異なる快適性スコアを最少乗換に読み替えない。
- **下界と枝刈り**: 探索用ヒューリスティックは真の最短残時間/コストを**上回らない**。方向別補正で不正なA*下界や乗換候補の欠落を起こさない。走行していない「乗車→降車」で徒歩上限をリセットしない。
- **無料乗車条件**: 横浜の福祉/敬老のポリシーで未知の便種別・除外路線等は、**候補生成前に除外**。普通の経路を見つけた後で0円ラベルを後付けしない。各返却候補をもう一度独立の運賃検証器で照合。
- **Realtime**: 東京の実時間情報を「表示だけ変更」せず、具体便の選択に反映できること。新しい共通接続層で取得失敗時に別形式・単位・バックエンドへ暗黙に切り替えない。既存東京のRealtime方針は今回変更せず、今後の静的実行は入力として明示し、別途その契約を検証する。
- **診断**: 探索状態数、時間、キュー、上限に達した理由、部分結果、未確認の路線/徒歩辺によるカバレッジ不足を区別。「候補なし」と「存在しない」を同一視しない。
- **出力**: 到着時刻、待ち時間、歩行時間、距離、移動経路・方向、具体便、徒歩の審査根拠、都市別の公式表示名を同じ旅程から生成。既存`RouteCandidate`の契約を維持。

## 4. エンジン統合の選定 — 方式Bを採択

### A. 共通SearchCoreを拡張

`api/transit_engine.py`の静的便探索をv2として拡張し、途中歩行状態・方向別徒歩辺・複数候補・東京のcost・実運行/Realtimeを段階的に追加する。

- 強み: 共通`TransitDataset`/Python・Rust比較ツール/横浜の現在のバックエンドを再利用しやすい。
- リスク: 現行探索状態が実質`(stop_id, rides_used)`で、前提が大きく変わる。東京の`SelectedPath`・便連続性・歩行資源・順位付けに追いつく必要がある。

### B. 東京のラベル探索を交通事業者非依存へ切り出す

`api/tokyo_search_labels.py`のグラフ状態・徒歩遷移・選択便・複数候補を共通化し、ODPT/GTFSを同じインターフェースで評価する。

- 強み: 途中徒歩、東京の独立した3目的、複数候補、選択便・乗車前の待機を扱った実績。
- リスク: Tokyo`TimetableChoices`・NetworkX・前処理・大量メモリ/性能との結合を分離する必要がある。現在のRust`SearchCore`をそのまま再利用できるわけではない。

**採択: B。** 東京のラベル探索を共通Python SearchCore v2の土台とする。現行静的SearchCore v1に徒歩辺を追加するだけでは、具体便内の通過順・乗車直後/走行後・正確な総徒歩/連続徒歩・3目的・候補集約・期限を維持できない。Aではこれらの状態と契約を再構築する必要がある。Bなら蓄積した回帰テストと探索処理を維持して接続層を交換できる。

性能がAより優れるという実証ではない。A/Bの実データ性能比較は未実施。現行Python/Rustのv1 `SearchCore.search(BatchSearchRequest)` は変更せず、v2をv1の設定へ暗黙に割り当てない。Rust v2は将来の明示的な契約・実装・同値検証を必要とする。

`transit_network_experiment.py` は第三の本番エンジンとして採用しない。方向別リンク・許可便集合・合成fixtureを再利用し、共通本体への接続が検証できた後に探索ループの重複を整理する。既存ファイル名は維持する。

## 5. 実装の段階と合格条件

| フェーズ | 変更の範囲 | 明確な合格条件 |
| --- | --- | --- |
| **0: 調査・選定** | 方式Bを選定し、互換性・データ不足・都市別条件を明文化 | コード上の事実と提案・未検証事項を分離 |
| **1: 東京と同じ入力で抽出（今回）** | `transit_search_labels.py`へfrontier・展開を抽出。東京の既存ファイルを接続層として維持 | 既存東京テスト、都市非依存の合成便、例外・期限・SelectedPath互換性。データ変換なし |
| **2: 共通データ/横浜比較基盤（今回）** | パターン共有グラフ、GTFS具体便、元秒/乗降条件、方向別リンク、横浜scope/運賃再検証 | 合成比較と既存回帰。秒精度時計・東京ODPT/公式表示情報の移行は未完了 |
| **3: 横浜接続の比較** | 審査済み便集合・徒歩リンクを共通グラフ/具体便検索器へ接続 | 福祉/敬老の検索前除外と返却時0円再検証。現行で扱えない複数徒歩は独立に妥当性確認 |
| **4: 東京入力の移行比較** | ピン留めした実ODPT/GTFSと凍結Realtimeで現行入力と比較 | 具体便・時刻・候補順・英語名・循環・バスのみ・3目的・部分結果が同等 |
| **5: 性能・Rust・切替** | 明示的なv2契約、必要なNative実装、都市別の原子的prebuilt版検証 | 同環境の時間/RSS、必要なPython/Rust同値性、Lambda冷起動・warm検索。承認された都市だけ切替 |
| **6: 重複整理** | 共通本体への委譲へ統一 | 東京の機能・横浜の公開条件を維持し、別の都市別探索ループを恒久維持しない |

横浜 Issue #241の初回公開と、東京エンジンの全面統合は**別ゲート**。このRFCは初回公開を遅らせない。

### 必須の合成回帰テスト

1. **方向と乗り遅れ**: 09:20バス到着→審査済み徒歩10分→09:25電車には乗れない／09:31には乗れる。逆方向は別承認なしに使えない。
2. **途中徒歩2回**: バス→徒歩→地下鉄→徒歩→バス。各徒歩距離・乗換準備・待ち時間を一度だけ計上する。
3. **名前だけ同じ別標柱**: `platform_code`や末尾`_02`から乗り場を推測しない。
4. **不許可リンク**: 範囲外の公式URL、未審査、版不一致、リンク方向違い、座標近接のみ、階段/ホーム未審査は公開探索に一切現れない。
5. **無料乗車**: 福祉/敬老パスごとに、対象便0円だけを選ぶ。未審査・除外便が「見つかった経路」の後払い確認をすり抜けない。
6. **境界条件**: 23:59→24:xx、曜日/祝日例外、運休、同時刻乗換、終電、見つからない場合、循環系統、分岐/終点、GTFS更新。
7. **目的/候補**: 東京`time`/`fewTransfers`/`cost`で同一の正解経路・並び・候補件数、探索上限到達時の部分結果。
8. **運行情報**: 凍結した遅延の有無で乗換可否と具体便を確認。指定された静的/Realtime入力を区別し、例外時に別データ・単位・バックエンドへ暗黙に切り替えない。
9. **安全/効率**: 300m近接で大規模な全件歩行辺を自動生成しない。探索上限で安全に停止、Python/Rustの等価テスト。

### 実データ/性能の比較（ローカルの非公開GTFSはコミットしない）

- 東京: 既存`docs/tokyo-route-performance-review.md`のテストOD・運行日・時刻・3優先度、実便ID、循環便、探索上限、静的/リアルタイムの差分を保存。東京のLambdaはビルド済みグラフを読むため、**事前ビルド工程と起動後適用のどちらで新版リンクを取り込むか**を明示しなければ、本番の反映が漏れる。
- 横浜: 手元のピン留めGTFS（例: 2026-09-04）を**読取り専用**で監査し、承認済み徒歩リンクが無ければ本番0件のまま。違う版の歩行リンクに自動フォールバックしない。
- 最低限、候補の具体便/順/出発・到着時刻/徒歩距離・時間/乗換数/無料対象/運行日/選択根拠の差分を機械可読で出す。利用者のローカルデータや認証鍵は出力・pushしない。
- 速度/メモリは同一入力・同一環境・ウォームアップ付きで比較し、p50・p95（十分なサンプルがある場合）、ピークRSS、探索状態数、上限達成率を明記。改善値を測る前に「共通化したら速くなる」と主張しない。

## 6. 改修対象と改修しないもの

**第一段階の変更**: `api/transit_search_labels.py`（新規共通本体）、`api/tokyo_search_labels.py`（既存名の接続層）、`api/tests/test_transit_search_labels.py`（新規テスト）、本設計書。東京の下界・丸め補正・具体便評価・降車時間を明示的に渡す。探索本体に東京モジュールのimportを持たせない。

**次段階の候補**: `transit_dataset.py`とsource adapters、共通グラフ/具体便検索器/下界、横浜の接続層、Python/Rustのv2契約、prebuilt生成と起動版検査。新規ファイルの候補は `transit_network.py`、`transit_timetable_choices.py`、`transit_search_bounds.py`。第二段階で `transit_network.py` と `transit_timetable_choices.py` を比較用に実装。共通A*下界は未実装。

**今回変更しない**: `toei_engine.py`、既存Python/Rust SearchCore v1、東京/横浜runtime、Flutter、GTFS・coverage・徒歩審査ファイル、既存API、デプロイ・Lambda設定。横浜の現行バックエンドを共通本体へまだ切り替えない。

## 7. 第一段階の接続契約と次の一手

共通 `search_labels()` は既存のグラフ・時計・徒歩/安全上限に加え、以下を**必須引数**で受ける。別のproviderやゼロ下界へ例外時に自動切替する仕組みは設けない。

| 引数 | 契約 |
| --- | --- |
| `choices` | `can_wait_offboard`、全ての乗車可能な具体便を返す`board_options`。同時刻の将来状態を便・通過順・実移動済みで区別できるRideState |
| `ride_options` | `(u,v,time,ride,edge)`から同じ便の次の通過順・到着時計を返す。サービス日・許可便・時刻の整合性はproviderが保証 |
| `alight_minutes` | 選択便の降車時間。東京は走行後バス0分、その他1分の既存規則。未走行便の降車拒否は共通本体で維持 |
| `prepare_bounds` | 探索開始後の`check_deadline`と`deadline`を受け、`(bounds,cost_estimator,arrival_estimator)`を返す。前処理時間も安全期限に含める |
| `path_signature` | 完成経路の同一性。東京の現行完成経路集約を変更しない |
| `path_factory` | ノード列・選択時計・便・query-local choices・開始分から出力を構成。東京のSelectedPathはmanager/Realtime情報を保持 |
| `compact_queue` | 無効/展開済み項目だけを除去し、priority・sequence・親参照を維持 |
| `walk_meters` | 正確な徒歩資源。東京の旧0m辺は従来の1m規則を明示して維持 |

単位は既存東京と同じPythonの分（float可）・距離m。Rust v1のu32整数分へ暗黙に変換しない。グラフの`walk/board/ride/alight/xfer`と`bus/rail`はこの段階の内部契約であり、任意のGTFSをそのまま渡せる公開APIではない。

東京の `TimetableChoices` 自体を交換しないため、`tokyo_time_bounds` が型/メソッド同一性を検査する高速化条件を維持する。丸め補正の生成・ValueErrorの原因付き契約例外・旧graph-only fixtureの時計評価も東京側に残る。新しい共通SelectedPathは東京managerを要求せず、既存東京SelectedPathのmodule/class名と詳細化用属性は維持する。`TimetableManager`のpickle位置・既存prebuiltのschema/ファイル名・起動方式も変えない。

第一段階だけでは横浜は共通探索を利用しない。第二段階で比較用接続を追加したが、公開runtimeは未切替。引き続き、共通入力の不足（祝日/運行日例外、ODPT跨日、元pattern/run情報、pickup/drop-off、公式英語名）と、横浜の許可便集合・方向別審査の契約を固定する。既存ラッパーを再利用しつつ、静的時計全体の整合性をロード時に検証する。共通グラフを生成した後の切替前には非公開の実データ比較が必要。

第一段階のローカル検証: 変更前・変更後の東京既存テスト220件、共通本体の追加テスト9件が成功。固定した変更前mainとの合成比較36入力で候補順・cost・実時計・選択便・徒歩距離が完全一致。横浜のcoverage/無料対象/乗換と既存SearchCoreの関連テスト105件は99件成功・Native拡張が必要な6件スキップ（Rust検証はCIで実施）。実GTFS/ODPTの結果一致、Lambda実環境のメモリ/速度、横浜v2の公開可否は未検証。ローカル合成テストの成功を本番切替の承認に読み替えない。


## 8. 第二段階 — 共通データと横浜の比較接続（2026-10-15 JST）

### 実装した接続

- `transit_network.py`: `TransitNetworkSnapshot`と`build_transit_network()`。静的Dataset、明示した許可便集合、`DirectedWalkLink`からグラフを作る。方向・exact stop ID・両feed版・審査した距離/時間を検証する。近接リンク/逆方向を自動生成しない。
- `transit_timetable_choices.py`: `DatasetTimetableChoices`と`search_network()`。共通label本体へ委譲し、別のfrontier/探索ループを作らない。具体便・service date・乗車位置・元stop_sequenceを維持し、同便だけを継続する。静的比較用でRealtime取得は行わない。
- `yokohama_shared_network.py`: 福祉/敬老の明示したpassと現行coverage v1/v2から許可便を作る。返却する全乗車区間を元coverageと現行fare policyで0円再検証する。空の便単位審査からv1の路線単位承認へ戻さない。新たな無料認定や徒歩認定は行わない。
- Dataset/GTFS adapterにpickup/drop-offと元service-day秒を保持し、ODPT adapterも元の秒を保持する。GTFSで省略/空の乗降条件は仕様上の0。1は禁止、2/3は予約/申出を実装していないため新接続の乗降点にはせず、通過は維持する。既存Python/Rust v1の検索ロジック・整数分・Native入出力は変更しない。

### 状態・時計・都市別目的

lineノードは便ごとでなく、路線と順序付きstop ID/乗降条件のパターンごとに共有する。循環の同じstopもpositionを分ける。合成100便・同じ2停留所では物理2＋line2の4ノードを共有した。ただし便索引は全許可便/停車分を保持するため、実GTFSのメモリ削減の実証ではない。

後発早着を含む乗車可能便を保持し、停車中のarrival→departureの待ち時間を失わない。完成出力は具体trip/source trip ID、feed version、service date、元乗降sequence、実時計、通過stop列と方向別徒歩根拠を保持する。Dataset mappingと時刻列はコピーしてread-only化し、グラフの公開構造/属性更新も拒否する。queryのサービス/例外・有効便の準備を共通wall-clock期限の開始後に行い、途中で期限を検査する。乗車候補の成功/空結果だけを正確なready時計でquery内にキャッシュし、例外時に別providerへ切り替えない。

東京fewTransfersの二次目的はcost、横浜の既存fewest_transfersはarrival。新しい`few_transfers_tiebreak`で明示して区別し、東京の既定costを維持する。横浜のfewTransfers比較にはarrivalを明示する必要がある。乗車上限`max_boardings`がある最速では乗車数をfrontierキーへ保持し、早着だが上限を使い切ったprefixが乗換可能な遅着prefixを消さない。東京の上限なし最速は従来のキーを維持する。

確認済み徒歩0mは新接続では正確に0m、東京の旧0m辺は従来の1m規則とする。審査済み徒歩分数と準備/降車bufferは別の明示設定であり、駅アクセス確認のフラグから準備時間を自動上書きしない。比較用の`NetworkSearchParameters`の既定bufferは0分。`ExplicitTransferLink`や実験用`PinnedWalkLink`を本番の方向別審査へ自動変換しない。

### 検証と未達のゲート

構築前に全source時計のarrival≤departure≤次arrival、必要な発着時刻、ID/service参照、カレンダー/例外、座標を検証する。許可便以外の破損も要求したfeedの不整合として停止する。第二段階の初期接続では秒端数を拒否していたが、後述の入力契約完成作業で正確な分数時計へ対応した。東京ODPTのHoliday/跨日/公式英語名等の本番入力移行は引き続き未完了である。

現在の新接続は正しさ比較のため**明示した0下界**を使う。下界の失敗後の0切替を新設しない。東京の既存A*と型同一性条件は維持する。共通A*、Native v2、snapshotのpickle/manifest、Lambda v2冷起動、実GTFS/ODPTの時刻/候補/性能比較は未実装・未検証。

StopTimeの4追加slotはCPython 3.12の単体shallow sizeを72→104B（+32B/row）に増やす。GTFS読込内で同じ原文時計のimmutableな分/秒を共有し、秒整数を行ごとに重複生成しない。これはプロセスRSSの測定ではなく、source読込と索引/graph/queryを合わせた実データのpeak RSS/速度を保証しない。計測前にデプロイしない。

東京の既存220件が成功。共通接続/モデル/既存v1関連71件は65件成功・Nativeが必要な6件スキップ。横浜coverage/無料対象/乗換の既存関連92件が成功。新しい共通接続テスト22件は循環・具体便・後発早着・徒歩2回・乗降禁止・時刻不整合・24時以降/サービス例外・未承認の除外・乗車上限・二次目的の違いを確認する。CIでは新共通テストをPython 3.11/3.12双方で実行する。

公開切替には、許可された非公開GTFSの読取り専用比較、両パスの全候補の独立確認、方向別の実審査、性能測定が必要。本番runtimeは既存v1のままで、横浜初回公開はこの統合完了を待たせない。

## 9. 入力契約の完成 — 秒精度のscheduled時計（2026-10-15 JST）

方式Bを維持する。変更前mainは`a598a653fd3ee923e481c0f7a6ec97d4a15b0839`。本節はPhase 2入力契約のうち時計の実装であり、東京本番入力の完全な移行を意味しない。

### 単位・精度・互換性

- `transit_time.py`の明示契約に従い、新scheduled接続の時計・時間は**分単位のFraction**とする。元service-day秒を`Fraction(seconds, 60)`へ変換し、暗黙の丸めを行わない。単位を秒へ取り替えることもない。
- queryの整数分/Fraction分はそのまま正確に扱う。float分は有限の十進表記を値とする契約を固定する（`0.1`分は正確に6秒）。任意の十進値をfloatの演算で先に合算すると入力時点で誤差が残るため、厳密な呼出しにはFractionを使う。bool・文字列・NaN・無限大・負値を拒否する。
- sourceのlegacy整数分と元秒の対応を検査し、不一致はtrip/sequence付き例外で停止する。元秒なしのDataset行は明示した分精度の入力形式として扱い、欠損・解析エラーの回復経路として使わない。
- source Datasetのlegacy丸め分と元秒は保持する。追加の`ScheduledStopTime`はimmutable sourceを参照し、正確なarrival/departureだけを持つ。時刻の前後・停車中待機を秒精度で検査する。同じ秒時計はsnapshot構築内で共有する。
- 東京の接続層、共通frontier本体、Python/Rust v1の整数分入力・出力を変更しない。横浜の許可便/パス検査・方向別公式徒歩審査・公開runtimeを変更しない。
- `NetworkJourney`とイベントの時計もFractionとし、元秒を保つ。現在の接続はoffline/opt-inであり既存HTTP出力へ未接続。JSONへの暗黙float化は行わず、将来の公開出力には単位・精度を明示したserializer契約を別途定義する。

### 検証と残課題

GTFS/ODPTの秒端数保持、1秒早い発車の除外と等時刻乗換、0.1分の降車と0.2分の乗車準備、徒歩との合算を3目的で確認する。source時計不一致、同じlegacy分内の逆転/負のdwellを拒否し、23:59:59→24:00:01でも元service dateを保つ。queryの発車直前/一致/直後、未知型・非有限値も確認する。

CPython 3.12のshallow sizeは追加scheduled行56B、Fraction48B。整数payload・索引・辞書等はこの値に含まれず、source保持分に加算される。時計共有はメモリ削減保証ではなく、実データpeak RSS・冷起動・検索速度は未計測。性能結果なしに公開切替しない。

秒時計の合成回帰成功後も、ODPT運行日例外/深夜表現、公式表示情報、東京Realtime接続、共通A*、Native v2、prebuilt manifest、非公開実GTFS/ODPT差分は残る。次の入力契約作業ではこれらのsource意味を既存東京コードと固定してから移行する。未対応データを別providerや旧snapshotへ自動切替しない。

ローカル検証: 東京既存220件、横浜関連92件が成功。共通/v1関連77件は71件成功・Native拡張が必要な6件スキップ。共通接続28件を含み、秒精度の新規境界テスト6件とGTFS/ODPTの既存精度テスト2件を更新した。Nativeの実検証はmainのGitHub Actionsで行う。

## 10. 入力契約の完成 — ODPTの明示した運行日例外と深夜規則

変更前mainは`1ae54bc3a7520cae875665bd59fac80104db3098`。秒時計のコミットはGitHub ActionsでAPI全件、Python 3.11/3.12のRust parity、3.11 Lambda image/smokeが成功した。

`OdptCalendarRule`へ`added_dates`/`removed_dates`と`service_day_start_second`を追加する。曜日7値・有効期間・例外日・境界秒を厳密検査し、重複・追加/除外の矛盾・期間外・型/単位不一致は停止する。サービスごとに一度だけnamespaced ServiceExceptionを生成し、共通Datasetの既存例外機構で曜日より優先する。Holidayという文字や日本の祝日を推測して日付を追加しない。初期値は空例外・境界0で、既存入力の結果を維持する。

境界を明示したsourceでは、その秒より前のcivil時計だけを同じservice dayの翌civil日へ置く。元時計の秒精度を失わず、24:xx表記にはさらに24時間を足さない。規則なしの23:59→00:00は自動補正せず、network構築の逆転検査で停止する。合成テストの03:00境界は実ODPTの公式規則ではなく、本番へ登録しない。東京の既存読み込みは便内の前後関係から日を進める処理を持つため、新契約の境界方式だけで全東京便が同等とは断定しない。複数日便・例外的な深夜表記は今後の実入力比較で契約を確認する。

ODPTの不正なclock型を「時刻欠落」とみなす処理を除き、trip/sequence/fieldを伴う例外で停止する。解析ValueErrorはcauseを保持する。正当な欠落/空時計は従来どおり残し、必要な発着時刻はnetwork構築で検査する。busのbool indexも拒否する。source wrapper、既存runtime、v1 SearchCore、運賃認定、徒歩審査データを変更しない。

追加5テストは追加/除外日、設定なし逆転、明示境界と24:xx、bus/rail両形式、カレンダー不正値、不正clock型/元例外保持を確認する。共通/v1/source関連87件は81件成功・Nativeが必要な6件スキップ、うちnetwork33件は成功。東京220件・横浜92件の直前回帰も成功した。新mainのGitHub Actionsで全APIとNative parityを再検証する。

Phase 2全体はまだ完了ではない。公式英語名・元pattern/run/便種別メタデータの契約、実ODPTへの運行日規則の対応、東京Realtimeの接続、非公開実データ比較、性能・prebuilt起動は残る。本番切替・デプロイを行わない。

## 11. 入力契約の完成 — 元便の識別情報

変更前mainは`0119351f00f19f100483447929b219dbbce4a871`。前段のODPT規則はGitHub ActionsでAPI全件・Python 3.11/3.12 Native parity・Lambda image/smokeが成功した。

`TransitTrip`に元ODPTのpattern ID、train number、train type、operator IDをoptionalなimmutable文字列として保持する。欠落はNoneのまま、整数の番号・空の種別・配列のoperatorを文字列化して埋めない。これらは元sourceの識別情報であり、種別名から無料承認や実運行状態を生成しない。GTFS既存入力の既定値はNoneで、既存v1の検索・Native入出力は変更しない。

ODPT bus/train adapterからsnapshotまで保持し、選択したNetworkRideEventにも引き継ぐ。同じ列車番号の異なるtimetable IDを合成便として統合しない。busの元patternはsource IDとして保存し、共通graphの共有pattern番号とは区別する。Realtime対応のための情報保存であり、Realtime取得・遅延適用を有効にしない。

追加3テストで同番号の別具体便、元bus pattern/事業者、欠落情報、型不正を確認した。共通/v1/source関連90件は84件成功・Nativeの6件スキップ、network36件成功。東京220件と横浜92件も成功した。CPython 3.12のTransitTrip shallow sizeは80→112B（+32B/trip）で、source文字列やプロセスRSSを含まない。

公式表示情報、実ODPT運行日の対応、Realtime接続、実データ性能/結果比較は残る。本番runtimeと無料/徒歩認定を変更しない。

## 12. 入力契約の完成 — 公式表示情報の保持

変更前mainは`785fc09668aec1972936489ea85ef4bb91048121`。元便識別情報の段階はGitHub ActionsでAPI全件・3.11/3.12 Rust parity・Lambda image/smokeが成功した。

TransitStop/TransitRouteへoptionalな公式英語名を保持し、選択イベントへ上下車名・鉄道路線名を渡す。ODPTのbus poleは東京が使用している`title.en`、stationは`odpt:stationTitle.en`、railwayは`odpt:railwayTitle.en`という明示したsource欄から読む。異なるlanguage mapへ順に切替しない。GTFS英語stop名は既存`gtfs_loader._load_english_stop_translations`のrecord_id/field_value検査を再利用し、両指定の不一致は停止する。既存東京ローダーを変更せず、新adapterだけでtranslations.txtの未対応schemaを明示拒否する。これはGTFSに定義された明示的selectorであり、解析失敗後の代替入力ではない。

未提供の英語名はNoneのままとし、翻訳・ローマ字化・IDで埋めない。sourceのlanguage mapが不正なら停止する。全フィードへ英語必須を課さず、東京の公開出力は既存の公式名検査を引き続き使う。GTFS英語route名や多言語一般対応はこの実装の契約外。

同じbusrouteの別patternの元titleをTransitTripとNetworkRideEventへ保持する。routeへ集約した最初のtitleだけで別方面のラベルを作らない。元pattern ID重複は拒否する。東京のbus方面英語ラベル生成・SelectedPath詳細化は現行接続層に残し、今回の情報保存で完全に移植したとは扱わない。

追加5テストでGTFS/ODPT公式名の保持、翻訳selector矛盾/未対応schema、不正map、欠落時の非生成、同一路線の別pattern title・重複ID拒否を確認した。共通/v1/source関連95件は89件成功・Nativeの6件スキップ。network41件、東京220件、横浜/v1関連118件が成功した。新mainのGitHub ActionsでNativeを含む検証を行う。

追加slotのCPython 3.12 shallow sizeはStop72→80B、Route72→80B、Trip112→120B。この数値は文字列・全索引・RSSを含まない。公開HTTP serializer、東京詳細化/Realtime接続、非公開実データ比較・性能・prebuilt起動は引き続き未完了。本番切替・デプロイを行わない。

## 13. Windows実データ比較 — 目的値一致と乗換地点の差（2026-10-15 JST）

ユーザーのWindows Python 3.12.10、main `0207bb06b00d7c326163839a2d372f8ef1a780a3`で読み取り専用の検証を実行し、返却された出力を解析した。実GTFS/ODPT・認証情報・生の出力ログはリポジトリへ追加しない。

横浜バスはv3.0_20260727、149 routes/35,329 trips/709,448 stop_times。地下鉄は20251226、25 routes/1,901 trips/37,131 stop_times。両manifestのvalidated_service_dateは2026-09-04。秒端数のある行は両feedとも0で、実データでの秒境界検証の代替にはならない。既存coverage.jsonを使用し、両パスで許可便2,544、nodes3,035/edges1,335のsnapshot構築が成功。徒歩リンクは明示的に0件で、新たな認定をしない。東京バスのfeed_infoは20260828_030922、期間2026-08-28〜2029-08-27だが、東京の実経路比較は未実施。

比較はバス/地下鉄×両パス×8/12/18時台×最速/少乗換の24ケース。元の許可便からODを決定し、同一feedのv1と共通探索の先頭候補を比較した。到着時刻・乗車数・便ID列は24/24一致した。乗降地点/時刻/停車列まで含む比較は20/24一致であり、候補完全一致の合格とは扱わない。新探索の各候補は既存のpass別0円検査を通過した。これは同じsourceによる整合性検証で、公式時刻表の独立確認や全OD/top-Kの証明ではない。

4差分は両パスのバス最速、12時台/18時台の同じ2つのODで、同じ2便を使う乗換地点が変わったもの。到着と乗車数は同じだが、待ち時間はv1の15/8分に対して共通では27/20分。共通timeの同到着時cost比較が、乗車区間の短いprefixを優先することを、private ID/原データを含まない合成循環2便で再現した。v1は同時刻時にTransitPathKeyで比較する。この差を例外時のv1切替や時計/候補の丸めで隠さない。

追加の合成回帰は、同到着/同便/同乗車数でも乗換地点が異なることと待ち時間の差を固定する。東京の既定cost tie-breakは変更しない。共通/v1/source関連96件は90件成功・Nativeの6件スキップ、network42件は成功。main CIでNativeを含む検証を行う。

**残る切替ゲート**: 横浜の同到着時順位を明示した都市別契約にする。既存v1の候補を維持するならpriorityだけでなく、prefix dominance・goal選択・具体便区間の辞書式キーも同時に検証する必要がある。待ち時間を新しい目的に採る場合は別の製品仕様変更で、今回自動採用しない。東京の順位や既存v1本体を変更せず、本番切替・デプロイを行わない。実徒歩/複数候補/別運行日/東京入力移行/性能のゲートも未達である。

## 14. 横浜の明示した同到着時順位 — v1具体便区間キー

変更前mainは`fbc2ec9724473b0dd62d13f28403c4f0411f0272`。前段のGitHub ActionsではAPI全件、Python 3.11/3.12 Rust SearchCore、3.11 Lambda image/smoke、Androidが成功した。確認時点のiOSは実行中だった。

`search_network`に明示的な`arrival_tiebreak="v1_path"`を追加する。timeは到着→乗車数→既存TransitPathKey相当、fewTransfers/arrivalは乗車数→到着→同キーで比較する。キーはtrip ID、route ID、乗降stop ID、具体区間の発着時計、順序付きstop列を含む。時計はsnapshotのFraction MINUTESのままで、既存v1の整数時計契約を変更せず、新契約の秒精度を丸めない。cost目的・fewTransfers/costへのv1_path指定と未知profileは拒否する。

横浜のopt-in接続層はtime/fewTransfersへこのprofileを明示指定する。共通探索の既定profileはcostのまま、東京facadeの呼び出し・順位・ラベルslotを変更しない。v1 Python/Rust本体・公開runtime・無料承認/徒歩審査データも変更しない。失敗時に既存v1へ探索をやり直す処理は追加しない。

優先queueだけでなく、同時計prefixのdominanceを区間キーで比較する。未来の具体便/board occurrenceと乗車数を同じgroupに保ち、open legの延長に対して順序を維持する。strictly earlierのoffboard prefixは、v1同様に後続便を待てるため優越する。未完成区間の辞書式キーはgoal順位の下界ではないので、同じ目的値へ到達できるqueueを消化してから、完成した候補を順序付けてyieldする。所要0の区間で途中の降車stop順序が変わる場合も、最初にpopしたgoalを即返さない。未確定の候補をsafety limit到達時に返さず、既存例外で停止する。

v1にない内部徒歩を含む同順位は、乗車区間キー→徒歩回数→方向/発着時計/距離の徒歩列という明示した拡張で決定する。徒歩回数を列より先に比較し、同じ乗車groupでprefix延長に対して順序を維持する。この拡張を既存v1と同等とは主張しない。徒歩はsnapshotにあるversion-pinnedの審査済み方向だけを利用し、逆方向生成や推定リンクの採用をしない。選択後のpass別0円再検査を維持する。

合成回帰8件を追加し、前段の循環便/待ち時間差のテストにもv1_path比較を追加した。安い同時刻prefixとの合流、乗車数のsecondary順位、所要0の未完成区間、limit超過、不正profile、複数候補の目的値順序、両パスでの接続層指定、審査済み徒歩を確認する。生成した循環時刻表32組×入力順2通り×目的2通りの128比較は、先頭候補の全区間キーがv1と一致した。秒境界の既存回帰にも新profileを適用した。network50件成功、共通/v1/source関連98件は92件成功・Nativeが必要な6件スキップ。東京220件、横浜/v1関連118件も成功した。新mainのCIでNativeとLambdaを検証する。

**未検証**: Windowsの同じ24ケースの再実行前なので、実データの4差分が解消したとは扱わない。区間キーとlabelのcacheはquery内だけで保持し、終了時に解放するが、inactive labelや区間stop列も保持する追加メモリがある。同目的値を確定するまでの追加展開もある。Tokyoの既定profileはcache/確定待ちを使わない。横浜実GTFSのピークRSS/応答時間・全OD/top-K・別日/徒歩・東京入力移行/Realtime/prebuiltの測定は残る。Phase 2全体の完了や本番切替を宣言しない。


## 15. Windows再比較 — 24ケースの選択区間一致（2026-10-15 JST）

順位profile追加後にユーザーから提供された読み取り専用ログを解析した。バス/地下鉄×福祉/敬老パス×8/12/18時台×最速/少乗換の24ケースを確認し、集計はcomparisons=24、primary_differences=0、selection_differences=0、walking_links=0だった。各ケースの便ID・route ID・乗降地点・発着時計・順序付きstop列を独立に比較し、乗車数も全件一致した。前段の同じ24ケースにあった4つの乗換地点差は、この提供ログでは解消している。PowerShellの差分検査はREAL_DATA_RANK_GATE_OKで終了した。非公開のstop/trip ID、GTFS本体、生ログはリポジトリへ保存しない。

ログはPython実行以降の抜粋であり、git rev-parse HEADやfeed version/hashの出力を含まない。後続のユーザーによるpullなしのgit rev-parse HEAD出力で、Windowsの実行SHAは指示した`a60c10bdc0e932f7a2cde6b412a6e9b8e3928ab1`と確認できた。結果の一致と検証したコード版を確認した。前段で確認したデータ版/hashを、この抜粋で再検証したとは主張しない。

上記mainのGitHub ActionsでAPI全件、Python 3.11/3.12 Rust SearchCore parity、3.11 Lambda image/smoke、repository safetyが成功した。確認時点ではAndroid/iOSビルドは実行中で、全workflow成功とは扱わない。

今回の合格範囲は提供された同一feed・先頭候補・徒歩0件の24ケースである。公式審査済みの実徒歩、別運行日、全OD/複数候補順位、東京ODPT入力移行/Realtime、snapshot構築を含むピークRSS/応答時間は未検証。debug elapsed_secだけでエンドツーエンド性能を認定しない。Phase 2全体の完了、本番切替、デプロイは行わない。

## 16. 別運行日・複数候補・速度/メモリの読み取り専用検証器

変更前mainは`e7d6acb042ee3ee8e8e62193fbfaf656c99041bb`。前段のWindows実行SHAはユーザーによるpullなしのHEAD出力で`a60c10bdc0e932f7a2cde6b412a6e9b8e3928ab1`と確定した。24ケースの全区間一致を維持し、今回の変更は検証器・テスト・CI・本書だけで、製品探索コードを変更しない。

`scripts/check_shared_yokohama_local.py`を追加する。既存のDownloadsの同名比較ファイルは変更/移動せず、以後はリポジトリのこの明示したpathから実行する。clean mainと完全なexpected SHAを確認し、取得・stash/reset/pull・GTFS/coverage/manifest書換え・ファイル出力を行わない。bytecode生成も止める。入力のGTFS txt一式とmanifest、選択したbus coverageのSHA-256を実行前後/子プロセス間で比較する。version・コードSHA・Python版・条件・測定値をstdoutへ出す。成功時の出力は具体stop/trip IDや元便の行を含まず、差分時はローカルの診断として選択区間を含む例外で停止する。非公開入力/出力をGitHubへ追加しない。

manifestのvalidated_service_dateは`--manifest-date`で明示し、query dateを別に指定する。元loaderの版/審査/manifest検査を維持して入力を一度読み、各query dateがeditionのvalid期間・元feed_infoの提供された期間内であることを確認する。カレンダー/運行日例外からその日の承認対象便だけでODを決定する。指定hourに承認便がない場合は、別のhour/date/coverageへ変更せず診断付きで停止する。v1との比較は承認対象便のminute-aligned時計に限り、秒端数を丸めて比較しない。新探索の秒対応を削減する制約ではなく、この旧v1比較器の適用範囲である。

v1 Python、共通の先頭候補のみ、共通の最大K候補を3つの独立したOSプロセスで実行する。同じ入力・case・乗車上限6・両パス・time/fewTransfers-arrivalで、先頭の全選択区間を比較する。追加候補はactiveな元tripの具体sequence/発着時計/停車列、乗降制約、承認scope、接続時刻、候補の目的値/区間キー順、重複なし、repeatの全候補順一致を確認する。元のpass別0円再検査は接続層に残る。徒歩リンクは明示的に0で、実徒歩のゲートを合格にはしない。v1は先頭だけを返すので、K件の網羅性・v1相当のtop-K一致は未検証と明示する。K件未満も候補数を記録し、複数候補が得られたqueryの件数を集計する。

計測は、読み込み、case作成、index/snapshot構築、各queryのrepeat別秒数、子プロセス全体のwall timeを区別する。query秒数は新探索の時刻表prepare・探索・選択イベント/無料検査を含み、検証器による区間再検査を除く。全体wallにはPython起動/import・読み込み/検査・hash・構築・全query・JSONの処理も含む。Windowsは明示した`windows-psapi`でGetProcessMemoryInfoのWorkingSetSize/PeakWorkingSetSize、Linuxは明示した`linux-proc`でVmRSS/VmHWMをbytesへ変換する。OS/API不一致やAPI失敗は別providerへ切り替えない。現在RSSとプロセス寿命全体の高水位を区別し、stage前後のピーク差をstage自身の使用量とは解釈しない。OSのworking set指標をPython allocatorやLambda課金メモリと同一視しない。sharedのsnapshotはパスごとに構築し参照を解放するが、GCやallocatorの残存もプロセス全体の測定に含む。v1 Pythonとの比較であり、Rust v1の性能比較ではない。

合成10テストは元calendarの除外日、hour欠落、秒端数拒否、先頭差分/hash差分、元例外stderr/return code保持、誤SHAで子プロセス開始前に停止、元入力非変更、追加候補の順位/再現性、実子プロセス3種類のJSON protocolを確認した。共通/v1/source関連108件は102件成功・Nativeの6件スキップ。既存API CIに加えWindows Python 3.12のjobを追加し、WindowsメモリAPIと合成子プロセス比較を実行する。実GTFSはCIへ入れない。

次のWindows実データ計画は、manifest stamp2026-09-04、query2026-09-04/05/06（平日/土曜/日曜）、8/12/18時台、両feed/両パス/両目的、repeat3、最大候補3。各worker72ケースで、先頭比較72件を予定するが、元データでその日時に承認便があることは実行まで未確認。測定結果と追加候補件数を解析してから性能/順位のゲートを評価する。閾値を未設定のまま速度合格やK件網羅性を宣言しない。東京ODPT/Realtime/prebuilt、実徒歩、全ODは残り、Phase 2完了や本番切替/デプロイを行わない。

## 17. 実データmatrixの停止 — 確定済み最速goal後の不要な展開

変更前mainは`93a5a4aae644f118b69a0d0dfc45ea7ed0bef492`。提供されたWindowsログに同じSHA、Python3.12.10、3日/3時台、repeat3、max_candidates3、windows-psapiが記録されている。最後はshared workerのtimeでmax_visitedに到達し、visited100,001、yielded1、queue2,749、frontier_labels102,750、elapsed2.203秒、max_search3で停止した。元RouteSearchLimitErrorとCalledProcessErrorを保持して終了し、成功markerや最終集計は出ていない。matrix全体の成功や実データ性能合格とは扱わない。mainの制御フローではv1/shared_head比較を通過後にこのworkerへ進んでいるが、それらの計測行も後段停止で表示されなかったため、性能値をこのログから集計できない。生ログや非公開便IDは保存しない。

コード上の原因は、time goalの既存groupが最後のsegment_walkの25m区間であること。徒歩edgeと仮想徒歩connectionがともに無いgraphでは、どの完了goalもsegment_walk=0で同じgroupに入る。v1_pathの同目的値waveを消化して完成順位を確定した後は、未来のgoalがこの代表を改善できず、他のgroupも作れない。それでもmax_searchの件数まで達しようとして、後続の循環便/乗換labelを全展開していた。探索を制限無しで完了した場合も、そのgroupの代表1件だけが残る現在の候補選択規則である。

共通label coreに、time/v1_path、空のvirtual connection mapping、walk edge無しを確認した場合のgroup完了判定を追加する。graph確認は元deadlineへ計上し、同目的値waveの確定後だけ終了する。max_candidates3、max_visited100,000、15秒、運行日、入力版、scope、時計、無料/徒歩審査を変更しない。候補件数の上限に満たなくても、既存groupの全代表を確定できた場合はそれらを返す。未確定時のlimit例外を捕捉して結果へ変換しない。これはgoal frontierの同じ選択結果を保つ終了条件で、真の最速top-K列挙の実装ではない。

Tokyoの既定cost tie、fewTransfers/cost、fewTransfers/arrival、歩行edgeまたは仮想connectionがあるtimeにはこの終了条件を適用しない。徒歩で異なるgoal groupが生まれる場合の候補を維持する。Python/Rust v1を変更しない。元の同時計順位、秒時計、具体便区間、boarding capの比較規則も変更しない。

追加3回帰は、先頭を確定できるが後続の循環で上限を超える合成graphを使い、max_candidates1/3の同じ代表を上限20以内で返すこと、既定cost tieの元のlimit例外、実walkの別group、仮想walkの別groupを検証する。既存の所要0区間の順位確定前limit例外も通過した。検証器は完了したworkerの計測を順にstdoutへ出し、後続失敗時も既存計測と元例外を保持する。queryごとのengine/pass/feed/day/hour/mode/repeatをstderrの診断へ出し、候補区間のprivate IDを通常の集計に含めない。追加1テストで後段worker失敗時の部分report保持と成功marker非出力を確認した。

ローカル共通/v1/source関連112件は106件成功・Nativeの6件スキップ、network52件・検証器11件が成功。東京220件、横浜/v1関連118件も成功した。新mainのWindows/API/Native/Lambda CIと、同じ条件の実データ再実行で評価する。72ケース全体、実メモリ/速度、fewTransfersの追加候補、真のtime top-K、東京ODPT入力移行/Realtime/prebuilt、実徒歩は未完了。本番切替・デプロイを行わない。


## 18. Windows実データmatrix完了 — 72ケースの一致と性能測定

提供ログのコードSHAは`a9fd3477255fdf748182c8fd573c5cbea377a327`、Windows Python3.12.10 64bit、memory sourceはwindows-psapi。query dateは2026-09-04/05/06、8/12/18時台、両feed/両パス/両目的、repeat3、max_candidates3を維持した。全3workerが完了し、comparisons72、selection_differences0、shared_queries_with_multiple_candidates36、walking_links0、top_k_completeness_verified=false、READ_ONLY_SHARED_MATRIX_OKを確認した。各worker72行/各3repeat（216query、全worker648query）を独立に集計した。バス版v3.0_20260727、地下鉄版20251226、入力23ファイルのhash辞書が3workerで完全一致した。最終markerにより元検証器の実行前後の入力hash/SHA/clean main検査も通過した。hash値・生ログ・private stop/trip ID・元GTFS行は保存しない。

v1とshared_headは全72ケースで先頭の到着/乗車数/具体便/乗降地点/区間発着時計/停車列が一致。shared（上限3）も先頭は全72ケースで一致した。time36ケースは各1候補、fewTransfers36ケースは各3候補。追加候補はactiveな承認対象便の具体sequence/時計/停車列、接続、乗降条件、pass別0円、目的値/区間キーの順序、重複なし、3repeatの全候補順一致を元検証器で検査した。これは選択区間の整合性と現在の候補選択規則の再現性であり、意味のある異なる経路の網羅性や真の上位K件を証明しない。timeの上限3を3件列挙の実装済みとは扱わない。

各profile216queryの秒をmsに換算して集計した。p95は昇順のceil(0.95*n)番目で補間せず、profile/processの反復ではない。

| 測定profile | query中央値 | query p95 | query最大 | query計測合計 | process peak working set |
| --- | ---: | ---: | ---: | ---: | ---: |
| v1 Python / 先頭のみ | 4.64 ms | 465.94 ms | 630.56 ms | 20.58 s | 781.87 MiB |
| 共通 / 先頭のみ | 5.05 ms | 426.51 ms | 530.21 ms | 14.83 s | 782.07 MiB |
| 共通 / 上限3 | 10.17 ms | 471.91 ms | 629.29 ms | 20.03 s | 781.38 MiB |

profile全体wallはv1 24.52秒、shared_head 21.29秒、shared 27.46秒。入力読み込みは3.37/3.27/3.85秒、v1 index構築は0.043秒、shared_head snapshot構築は福祉1.400秒/敬老1.293秒、sharedは1.661/1.393秒。snapshotは両パスとも許可便2,544、nodes3,035/edges1,335だった。各profileは別processで順番に一度ずつ実行したため、OS file cache、GC、スケジューリング、warm-upなどを統制したbenchmarkではない。total時間差や全体中央値だけで一律に共通探索が速い/遅いとは判定しない。上限3のworkloadはv1先頭のみと同じ出力件数ではない。

同じ目的のqueryを区別すると、最速（各profile108samples）の中央値はv1 11.65ms、shared_head 12.86ms、shared 15.26ms。少乗換の中央値はv1先頭3.01ms、shared_head先頭2.07ms、shared3候補8.21msだった。先頭のみのquery p95は最速v1 535.85ms/共通478.09ms、少乗換v1 104.57ms/共通16.70ms。これらも今回のOD sample/Windows環境の観測である。

メモリは2^20 bytesを1MiBとしたOS working set。全profileでloaded_memoryのprocess_peakとfinal_memoryのprocess_peakが等しく、約782MiBのピークは入力読込終了時点で既に記録されていた。query後の現在RSS最大はv1 318.23MiB、shared_head 319.57MiB、shared 320.40MiBで、query最中のstage別peakを直接分離した数値ではない。約782MiBをlabel coreだけの使用量とは扱わず、CSV/GTFS loader・adapter・入力検査のどの段階で発生するかは未切り分け。Windows working setをLambdaの実メモリと同一視しない。snapshotの再利用/prebuilt、cold-start、並列query、実Lambda RSSは残る。

検証したcode SHAのGitHub ActionsはAPI全件、Windows probe、Python3.11/3.12 Rust parity、3.11 Lambda image/smoke、repository safetyが成功した。確認時点のAndroid/iOSは実行中。今回のsampleの先頭互換性と追加候補の整合性は合格とするが、未設定の性能閾値を満たしたという合格、真のtop-K、実徒歩、東京ODPT/Realtime移行、Phase 2全体完了は宣言しない。本番切替・デプロイを行わない。

## 19. GTFS読込の一時メモリ — 通常stop_timesのストリーム処理

変更前mainは`0a656e2b3cb0ad2ffeb908d726a84118499894eb`。コード上、GtfsTransitAdapterはstop_times.txtの全行をdict listへ読み、全リストを保持したままTransitStopTime列・Datasetの重複検査setを構築していた。実バス709,448行で大きな一時メモリになり得るが、前段のWindowsピーク782MiBをすべてこのlistへ帰属させたとは扱わない。

通常（skip_untimed_intermediate_stops=False）のstop_timesだけをcsv.DictReaderから1行ずつ処理する。UTF-8-sig、新行/引用符のCSV解釈、元行順、namespaced ID、秒精度のsource時計、既存v1のminute欄、乗降flag、重複/未知参照検査は同じ。元の解析/変換/検査bodyはindentと入力reader以外一致することを旧SHAと比較確認した。_read_rowsのlist契約と、stops/routes/trips/calendarの読込は変更しない。未対応schema・decode・clockのエラーを別encoding/型/データで回復しない。複数の不正箇所がある入力では、全file読込より先に最初のrow解析エラーが発生し得るが、失敗を隠して継続しない。

横浜地下鉄の明示した時刻欠落互換モードは、全rowでtripごとのfirst/last・ID/重複sequenceを検査してから未時刻/乗降禁止条件を確認する従来の2段階を維持し、raw listを残す。error時にこのmodeへ切り替えない。csv fileはcontext managerで正常/例外の両方でcloseする。strict/互換modeとも解析/validation例外をそのまま伝播させる。公開runtime、SearchCore v1/v2の入力型、無料scope、徒歩review、探索順位、ファイル名・データ版を変更しない。東京の現行GTFS repository loaderは別のgtfs_loader.pyで、この変更を東京本番loaderの最適化済みとは扱わない。

合成5回帰は、最初の不正rowを検査する前に残りのCSVをmaterializeしないこと、元ValueError causeとclose、BOM/CRLF/未ソートsequence・24時超・秒とminuteの独立保持、duplicate/未知stop、空header/不正UTF-8、consumer例外の保持を確認した。既存地下鉄13テストの未時刻・first/last・乗降禁止・duplicate/unknown検査も成功。共通/v1/source関連117件は111件成功・Nativeの6件スキップ。東京220件、横浜/v1関連118件も成功した。Windows CI jobへ同じstreaming回帰を追加する。

非公開データを使わず、Linux Python3.12.14、5,000便×20行の合成GTFSを旧SHAのadapterと新adapterで別processへ読み込ませた。全100,000 TransitStopTime recordのdigestが一致し、順番に実行した各1回のprocess peak working setは110.72→71.50MiB（約35.4%減）、load wallは0.587→0.563秒だった。並列に行った事前の各1回も同じrecord digestでpeak110.73/71.49MiB。これは合成データ/少数実行での観測で、実Windows GTFS・Lambda・速度SLAの証明ではない。消去したraw list以外のDataSet本体、ID string、重複検査setは残る。

次は同じ72ケース/3repeat/max_candidates3/元23ファイルでWindows matrixを再実行し、全選択区間・候補順位/再現性・版/hash、load/snapshot/query時間、loaded/final process peakを比較する。地下鉄のmodeを変えずに測り、データを更新/削減して改善量を作らない。snapshotの検証/copy/prebuilt、東京ODPT/Realtime、真のtop-K、実徒歩、LambdaでのRSS/cold-startは未完了。本番切替・デプロイを行わない。

## 20. Windows再測定 — 入力・候補を維持して読込ピークを削減

提供された読み取り専用ログのSHAは`bfb55837c476245430f163ddf7e3e36a89d262bc`。Python3.12.10 64bit、windows-psapi、3日/3時台、両feed/両パス/両目的、repeat3、max_candidates3は前段と同じ。旧測定SHA `a9fd3477255fdf748182c8fd573c5cbea377a327`と新測定の全3profileで、23入力ファイルのhash辞書が一致した。データ削減や版変更による改善ではない。生ログ・入力hash値・非公開GTFS行・認証情報は保存しない。

comparisons72、selection_differences0、shared_queries_with_multiple_candidates36、walking_links0、top_k_completeness_verified=false、READ_ONLY_SHARED_MATRIX_OKを確認した。各profile72ケース/216query。先頭の具体区間はv1と全件一致し、fewTransfersの36ケースでは各3候補が返り、元検証器の承認対象便・具体sequence/時計・接続・乗降条件・無料判定・候補順位/重複/3repeat再現性検査が成功した。timeは各1候補という既存group規則を維持する。全OD、実徒歩、真のtop-Kの合格とはしない。

| profile | 旧process peak | 新process peak | 新query中央値 | 新query p95 |
| --- | ---: | ---: | ---: | ---: |
| v1 Python / 先頭のみ | 781.87 MiB | 340.13 MiB | 4.37 ms | 466.78 ms |
| 共通 / 先頭のみ | 782.07 MiB | 353.11 MiB | 4.80 ms | 426.93 ms |
| 共通 / 上限3 | 781.38 MiB | 353.03 MiB | 8.42 ms | 441.57 ms |

MiBは2^20 bytes、p95は216samplesの昇順ceil(0.95*n)番目。共通profileのprocess peakは約55%低下した。loaded時点のpeakは全profile約340MiBで、共通profileはsnapshot構築後に約353MiBとなった。query後の現在RSS最大はv1 291.22MiB、shared_head 310.18MiB、shared 310.41MiB。high-water markと現在RSSの差をsnapshot/labelの単独使用量とは解釈しない。Windows working setをLambda使用量へ置き換えない。

入力読込はv1/shared_head/sharedで3.107/3.025/3.153秒。snapshot構築はshared_head福祉1.262秒/敬老1.407秒、shared福祉1.193秒/敬老1.324秒で、両パスの許可便2,544・nodes3,035/edges1,335を維持した。各profile全体wallは24.043/20.963/24.445秒。OS cache・GC・スケジューリングを統制した反復process benchmarkではなく、query時間の差から速度SLA合格や一般的な速度向上を宣言しない。

検証対象SHAのGitHub Actions run `38663097030`でWindows probe/streaming回帰、API全件、Python3.11/3.12 Rust parity、3.11 Lambda image/smoke、repository safety、Androidが成功した。確認時点のiOSは実行中。本節追加は測定記録のみで製品コードを変更しない。

今回のGTFS読込変更はこの実データsampleで互換性とピーク改善を確認できた。次の入力契約ゲートは東京ODPTの明示calendar/便identity/秒時計と既存TimetableChoicesの実入力比較、およびprebuilt起動との接続確認である。snapshot構築の再検証/copyの費用、リアルタイム統合、公式審査済み実徒歩、真のtop-K、Lambda実メモリ/cold-startは引き続き未検証。Phase 2全体完了・本番切替・デプロイを宣言しない。

## 21. 東京ODPT入力の読み取り専用ゲート — 原JSON・具体便・prebuilt

変更前mainは`b51e5067d7ae560619c734ea0a66001032eb4cc5`。`scripts/check_tokyo_odpt_local.py`と合成11回帰を追加し、Windows CIでも実行する。変更は検証器・テスト・CI・本書であり、東京/横浜の公開runtime、探索順位、SearchCore v1/v2、GTFS/無料/徒歩審査データを変更しない。

コード上、東京TimetableManagerの列車ローダーはHH:MMを整数minuteへ変換し、便内の前区間の到着より早い次の出発や、出発より早い到着へ1440分を加算する。元run_key、0始まりstop_sequence、calendarを保持する。共通ODPT adapterは元秒時計を保持し、明示したOdptCalendarRule.service_day_start_secondで境界未満のcivil clockを翌日側へ置く。両規則の実入力における対応を未検証のまま共通calendarや日付境界を自動採用しない。

検証器は非emptyのlist、単一record、result listという現行load_jsonの入力envelopeを明示的に受け付ける。UTF-8のみで原JSONを読み、明示run identityの重複/欠落、駅とrailwayのidentity、異なる到着/出発駅、clock型/構文、calendar/train number/stop objectを検査する。既存ローダーへHH:MM:SSを丸めたりSS=00を削って渡したりしない。HH:MM:SSがあれば秒を保ったまま比較未対応として停止する。未知calendar文字列の公式意味は推測せず、既存weekday/weekend格納とTimetableChoicesのweekday/saturday/holiday絞り込みを観測するだけで、公式運行日検証とは扱わない。

原JSONから現行のminute/rollover契約に従う全区間を構成し、ローダーの全区間とのmultiset一致を検査する。次に原区間に基づく徒歩無しの合成接続graphで、既存TimetableChoicesのboard_options/ride_options/metadataを通して全boardable occurrenceのrun、sequence、乗降駅、発着時計、train numberを比較する。同じ駅を再訪する便や同じ番号の別calendar便も独立に保持する。このgraphは本番graphの代替ではなく、入力処理の検証専用。到着clock欠落等で現行ローダーが構成しない区間はその明示した既存規則を反映し、欠落件数も記録する。共通Datasetがその欠落を受理できるとは主張しない。

`--trusted-prebuilt`を明示した場合だけユーザーの信頼済みlocal pickleを読み、そのTMと原JSONの全区間/各day profileの具体便選択を同じ条件で検査する。graph、SI、compiled GTFS、Lambda実起動の一致はこの検査の範囲外。古いrun/calendar/occurrence metadata、異なるsource、型不一致は停止し、ensure_train_run_metadataによる修復/原JSONへの差替えを行わない。pickleは取得/作成/更新/再保存しない。指定なしの場合はprebuilt_verified=falseであり、prebuiltへアクセスを試みて失敗を回避した結果ではない。

clean mainと完全expected SHAを実行前後に検査し、指定原JSON/任意prebuiltのhashも前後比較する。git pull/fetch/stash/reset、通信、credential読込、データ取得、bytecode/出力ファイル生成を行わない。成功markerはREAD_ONLY_TOKYO_RAIL_INPUT_OK。正常出力はcalendar件数、source dateの範囲/件数（版の証明ではない）、source時計範囲、03時未満clock件数、rollover加算/反復駅/時刻欠落の件数と比較区間数を含む。private駅/便IDは通常reportへ出さず、不正入力時だけlocal例外の診断へ保持する。未検証項目shared adapter/公式calendar/経路順位/Realtime/Lambda起動をfalseで明示する。原例外と診断を保持し、成功markerを出さない。

合成11回帰は日付跨ぎ/循環/同番号別calendar、24時超/内部到着clock欠落、source秒非変換、parse cause、重複/identity/schema、元UTF-8/JSON例外、任意prebuilt一致/古いmetadata/区間差と非変更、誤SHA/変更inputで成功marker非出力、正常CLIのhash/未検証gate出力を確認した。新検証器・既存横浜probe/GTFS streaming・東京train migration/Lambda startup関連34件がローカルで成功した。実データのこの新ゲートはユーザーWindowsでの実行待ち。非公開GTFS/ODPT/pickle・hash値・生ログはリポジトリへ追加しない。

次は`api/data/odpt_TrainTimetable.json`とユーザーの信頼済み`api/data/app_data.pkl`を再取得/修復せず比較し、実calendarと時計表記/欠落/反復occurrenceを確認する。その結果に基づき、版固定した明示calendarと境界の契約、共通ODPT adapter→DatasetTimetableChoices比較器を実装する。現時点で共通ODPT実経路移行、Phase 2全体完了や本番切替/デプロイを宣言しない。

## 22. 東京実入力の一致と明示した便内時計契約

ユーザーのWindows Python3.12.10 64bit、main `46a73d38c9d15cebafe0e176cc16744dbc5ad996`で前段の検証器がREAD_ONLY_TOKYO_RAIL_INPUT_OKで完了した。原列車JSONは5,600便/116,658区間。calendarはWeekday2,818、Saturday344、Holiday322、SaturdayHoliday2,116便。原JSONと現行ローダーの区間multisetが一致し、具体便選択は平日57,804、土曜50,418、休日49,850区間で差分0。指定した信頼済みprebuiltのTMと各profileの具体便選択も一致した。実行前後の指定2ファイルhash、clean main/SHA検査も通過した。hash値/原JSON/pickle/生ログは保存しない。

原clock範囲は0〜86,340秒（23:59）、03時未満は2,440clock、legacyの24時間加算は1,718回、同じ駅を再訪する便709。到着欠落/出発欠落は各5,600clock。欠落件数だけで全てが端点と判断せず、次の共通network構築でも個々の位置を検査する。dc:dateは6種類、2023-11-25〜2026-06-15だが、収録日付をfeedの版/運行有効期間と同一視しない。今回の結果は原入力・既存具体便・prebuilt TMの一致であり、共通adapter、公式calendar、経路順位、Realtime、Lambda実起動は未検証。

変更前mainは上記`46a73d38`。OdptTransitAdapter.buildへ`train_clock_convention`を追加する。既定calendar_boundaryは従来のまま。東京の現行意味を移すため、明示的にordered_runを選べるようにする。最初のclockは元のcivil-day時計のまま、以後の到着→出発の各eventは前のevent以上になる最初の整数service dayへ置く。秒を維持して86,400の整数倍のみ加算し、等時刻/24時超/複数日跨ぎを保持する。03時未満の最初の便を一律に翌日へ移さない。この規則は元ローダーの順序によるrolloverを秒へ拡張した入力契約で、parse/validation失敗時の修復や再試行ではない。

ordered_runと非zeroのservice_day_start_secondは矛盾として停止する。未知convention、内部到着/出発の欠落、端点の必須clock欠落、不正clock/型は診断と元causeを保持して停止する。始点arrival/終点departureの欠落は元のままNone。元clockの秒精度はv2 service_seconds/Fraction MINUTESへ保持し、既存v1 minute投影の丸め契約だけを従来通り残す。bus側と既定calendar_boundaryの処理、既存東京/横浜runtime、Python/Rust SearchCore v1を変更しない。便ごとのclock配列はその便のrow数に比例し、性能/メモリ改善済みとは主張しない。

検証器へ明示した`--shared-rail --stations ... --railways ...`を追加する。両ファイルを必須とし、指定3原JSON/任意prebuiltの前後hashを検査する。原JSONを共通adapterのordered_runで読み、元ID/具体順序を保持したnetworkを徒歩0/全source tripという検証専用scopeで構築する。全隣接区間のrun、sequence、駅、Fraction時計、列車番号を既存区間と比較する。schema/未知参照/座標/欠落等の不正は元adapter/networkで停止し、座標生成やsourceの除外をしない。

公式運行日の推測を避けるため、calendarは初めに全曜日falseの比較専用日2000-01-01へ固定する。各legacy weekday/saturday/holiday profileが選ぶcalendarだけ、その比較日に明示した追加運行例外を与える。既に検証済みgraph/clock索引を保持したまま、immutableな比較用Datasetの例外列だけを差し替え、DatasetTimetableChoices.prepare/board_options/ride_optionsの全区間を旧profileと比較する。これは明示した旧day profileの投影テストであり、2000年の実運行、日付から祝日判定、公式運行期間/例外を実装したとは扱わない。reportへcalendar_projection=legacy_day_profile_test_only、operational_calendar_verified=falseを必ず残す。Realtime/経路順位/Lambda実起動のgateもfalseのまま。

ordered clockの合成7回帰は秒/深夜/dwell/反復駅、最初の深夜便非シフト、24時超/複数日、同時計、既定convention非変更、矛盾/不正/欠落/元causeを確認した。比較器の追加4回帰は全day profile区間一致、最初の00時便、座標欠落を除外しないこと、明示input set必須/元入力非変更を確認した。新旧入力契約・共通network/label・東京具体便/cache・横浜probe・GTFS streaming・東京migration/Lambda startup関連128件がローカルで成功した。新mainのGitHub ActionsでAPI全件、Windows、Rust parity、Lambdaを検証する。

追加で東京/横浜のtest moduleをunittest discoverし397件が成功した。比較用metadata.versionは3原JSONの名前付きhash辞書から作るbundle digestで固定し、fetched_atはlocal読込時の観測時刻で、公式取得時刻や運行版の認定ではない。

次の実データは同じ列車JSON/prebuiltに`api/data/odpt_Station.json`と`api/data/odpt_Railway.json`を加え、再取得/修復せず実行する。この共通adapter/具体便比較の実測はまだ未実施。成功しても公式calendar/サービス期間/祝日例外、東京本番graphと候補順位/快適さ/徒歩/Realtime、compiled GTFSを含むLambda起動/メモリ、Phase 2全体の完了を自動認定しない。本番切替・デプロイを行わない。

## 23. 東京共通入力の実データ一致と実日付比較ゲート

ユーザーのWindows Python3.12.10、main `60fbcc62c0b9f9a64a1baf6606870b85b68f666a`で共通入力比較がREAD_ONLY_TOKYO_RAIL_INPUT_OKで完了した。列車5,600便/116,658区間とcalendar/反復駅/深夜補正の件数を維持し、原JSON→共通ordered_run adapter/networkの全区間multisetが一致した。DatasetTimetableChoicesは平日57,804、土曜50,418、休日49,850区間で差分0。旧選択器/prebuiltの各profileとも一致し、shared_adapter_verified=trueだった。列車JSON/prebuiltの2hashは前段のユーザーログとも一致し、指定4ファイルの実行前後hashとclean main/SHA検査も通過した。徒歩0件、比較用日2000-01-01の旧profile投影であり、operational_calendar/route_ranking/realtime/lambda_startup_verifiedはfalseのまま。raw JSON/pickle/hash値/生ログを保存しない。

次の変更前mainは同じ`60fbcc62`。製品コードを変更せず、検証器へ反復可能な`--query-date YYYY-MM-DD`を追加する。shared-railと両原JSONの明示が必須で、日付はzero-paddedの実date、重複無しを要求する。既定の日付は採用せず、指定なしは前段のprofile比較だけを行う。

コード上、既存determine_day_typeは不正/未指定入力を今日へ置き換え、jpholidayのImportError時は祝日なしで継続する。検証器では日付を事前に厳密parseしてdate型で渡し、指定実日付がある場合はjpholidayとそのinstalled distribution versionを必須にする。依存不足は元例外で停止し、別の祝日判定やweekday-onlyへ切り替えない。返却profile/保持service_dateと明示入力の整合性も検査する。現行runtimeの日付処理を今回変更したとは扱わない。

原JSONローダーの旧具体便、任意prebuiltの旧具体便、共通DatasetTimetableChoicesについて、指定各dateの全選択区間を比較する。対応calendarは実入力で確認したWeekday/Saturday/Holiday/SaturdayHolidayの4IDに限り、未知IDから意味を推定しない。共通側は選択した旧date profileだけを指定実日に明示exceptionで有効化し、全曜日falseの比較用calendarの範囲をその日だけへ設定する。immutableな比較用Dataset/calendar/exceptionを新しく構成し、検証済みsource clock/graph索引を再利用する。実日付のstate.service_dateも一致を要求する。clockは前段の秒/Fraction時計のままで、運行dateを変えて元便のclockを丸めたり異なるfeedへ切り替えたりしない。

date_choices/prebuilt_date_choices/shared_date_choicesへ各date/profile/区間数/差分を出し、成功時はlegacy_date_policy_verified=trueとholiday_dependency_versionを記録する。これは現行東京のdate/祝日policyと共通側の明示exception・service_dateの互換性検証であり、元時刻表の公式有効期間や独自臨時運行の確認ではない。operational_calendar_verified=falseを維持する。前段のprofile用projection_day=2000-01-01と、今回の実query dateを区別する。

追加3合成回帰は通常平日/土曜/日曜/祝日の旧・prebuilt・共通の区間一致とprebuilt非変更、dateの不正/重複/依存欠落/旧policy矛盾、未知calendar拒否を確認した。新検証器・横浜probe・GTFS streaming・ordered clock・東京migration/Lambda startup関連48件、dataset/networkを含む選択83件がローカルで成功した。Windows CIは既に検証器moduleを含むため同じ追加回帰を実行する。今回の変更対象は検証器・回帰テスト・本書である。

実データでの次の指定日は2026-09-04/05/06と2026-09-21。前段と同じ4ファイルを更新/再取得せず使い、通常weekday/saturday/holidayと既存libraryの祝日profileを比較する。実日付比較はまだ未実施で、公式運行版/有効期間/例外、本番graph/候補順位/快適さ/徒歩/Realtime、compiled GTFS/Lambda実起動・性能は残る。Phase 2全体完了・本番切替・デプロイを宣言しない。

## 24. 東京実日付の一致とバスGTFS入力比較

ユーザーのWindows Python3.12.10、main `5d61aa461c9919cc503e75e59f2c51689babbfbc`でREAD_ONLY_TOKYO_RAIL_INPUT_OKを確認した。jpholiday1.0.3、query2026-09-04/05/06/21でprofileはweekday/saturday/holiday/holiday。各57,804/50,418/49,850/49,850区間が原JSON/旧具体便/prebuilt/共通具体便で差分0。legacy_date_policy_verified=true、shared_adapter_verified=true、prebuilt_verified=trueで、指定4ファイルhashは前段とも一致し、実行前後の入力hash・clean main/SHA検査を通過した。公式有効期間/臨時運行、production graph/経路順位/Realtime/実Lambda起動は未検証。raw入力/hash値/生ログを保存しない。

次の変更前mainは同じ`5d61aa46`。`scripts/check_tokyo_gtfs_local.py`と合成回帰を追加する。指定GTFSの全txtとfeed_infoをhashで固定し、完全expected SHA・clean mainを実行前後に検査する。feed_infoの1行と明示したexpected-feed-version、start/endの形式・順序・query date範囲を要求する。query dateは明示/厳密parse/重複無し。非empty frequenciesは未対応として停止し、頻度便を合成したり別feedへ切り替えたりしない。取得/書換え・ネットワーク・credential読込・出力ファイル生成を行わない。

GtfsTransitAdapterを通常strict modeで読み、全stop_timeのarrival/departure source secondsが存在してminute-alignedであることを確認してから旧GtfsRepositoryを読む。旧minute投影との比較のために秒端数を丸めない。秒データの不正ではなく、旧比較器との精度互換性未確認として診断で停止する。共通v2の秒対応は維持する。bus-onlyの全source tripを明示scopeにして徒歩0のnetworkを構築し、全時計/停車順序を検査する。旧/共通でstop/route/trip集合、stop名/公式英語/座標、route表示名、tripのroute/service/headsign/direction、全sequence/stop/発着時計を比較する。例外だけで運行するserviceも元IDで扱い、calendarを捏造しない。

コード上、現行東京TimetableChoices._bus_optionsはpickup_typeを参照せず、ride後のalightにもGTFS drop_off_typeを渡していない。共通networkは乗降flagを保持し、制約に従う。新検証器は乗車可能positionのnonzero pickup、降車可能positionのnonzero drop-offがあれば、既存結果維持の契約が未確定として停止する。始点drop-off/終点pickupの制限は乗降positionと矛盾しないので元のまま保持し検証する。flagの削除/無効化・未確認便の除外で比較を通過させない。実Toei feedのその条件は実行まで未確認。

旧具体便の比較graphはsource route/stopの全隣接区間から作る検証専用のcanonical GTFS graphで、ODPTのbuspat graphや標柱→GTFS ID対応の代替ではない。旧TimetableChoicesと共通DatasetTimetableChoicesについて、指定各dateのactive service/trip集合と全boarding occurrence→次停車区間のtrip、sequence、乗降stop、発着時計を比較する。同じstopの再訪をsequenceで区別し、時刻表prepare後に列挙する。無料対象範囲やYokohamaの審査dataを変更せず、元GTFS transfersや推定徒歩を自動有効化しない。ODPT graphの方面/terminal絞り込み、全経路候補順位・快適さ・徒歩・Realtime、compiled GTFS/Lambda実起動・メモリ/速度の一致はこのgateの範囲外とfalseで明示する。

合成8回帰はsource全行/metadata/運行例外/具体便一致と入力非変更、秒非丸め、pickup差で停止、始終端の乗降制約保持、例外だけのservice、誤版/不正・重複・期間外date/非empty frequencies/承認日便無し、誤SHA・hash変更で成功marker非出力、正常CLIのhash/未検証gateを確認した。Windows CIへ新moduleを追加する。成功markerはREAD_ONLY_TOKYO_BUS_INPUT_OKで、正常reportはfeed版/期間/件数、pickup/drop-off件数、date別active service/trip/具体区間数/差分だけを出し、private stop/trip IDを通常出力に含めない。不正入力のlocal例外には診断IDを保持する。原GTFSやログをリポジトリへ追加しない。

次の実入力は既にユーザーが確認した`api/data/ToeiBus-GTFS`、feed_version20260828_030922（2026-08-28〜2029-08-27）。query2026-09-04/05/06/21を同じ版で読み取り専用比較する。新bus gateの実データはまだ未検証で、Phase 2全体完了・本番切替・デプロイを宣言しない。
