# 仙台市営バス＋地下鉄・ふれあい乗車証の共通ネットワーク設計

## 1. 優先順位・現状（2026-10-15）

開始時mainは `f1900123d03fb0947c52c20aadc07dcbab32a4c5`。次の新規開発は横浜から仙台へ切り替える。横浜の既存コード・データ・監査履歴、既存ファイル名・ディレクトリ名・アプリIDは保持する。本番デプロイ・S3変更・ストア提出は行わない。

- `api/sendai_transit.py`: ODPT公式市営バスGTFS-JPの取得・明示日付のmanifest検証。`SendaiRouteBackend` はこのバスfeedだけを受け入れる。
- `api/app/sendai_runtime.py`: 既存のバスbackendとバスRT3種を起動する。新しい地下鉄は選択しない。
- `api/gtfs_route_backend.py`: 汎用Dataset検索を利用するが、異なるfeed間のレビュー済み徒歩接続を扱う新しい都市wrapperではない。ここへ横浜固有条件を追加しない。
- `api/fare_policy.py`: 仙台の公開選択肢・既定値は `normal` のみ。通常運賃が不明なら不明のまま保持し、0円へ置き換えない。
- `lib/core/city_profile.dart`: 仙台も `normal` のみ。アプリIDは `jp.cloxs.go.sendai`。Issue #148記載の別表記へ改名しない。
- [Issue #148](https://github.com/kaeruko/tobus_go/issues/148): 本番環境・承認済みバスデータ・端末/ストアの作業。今回の実装をデプロイ承認や完了と扱わない。
- [Issue #171](https://github.com/kaeruko/tobus_go/issues/171): 市営バスとRTは既存対応、地下鉄CSVは2023年基準で条件付き、宮城交通データは未確認。今回も宮城交通は未対応とする。

再利用するのは `TransitDataset`、`transit_network.build_transit_network`、`transit_timetable_choices.search_network`、`ReviewedWalkingLink`。横浜wrapper・運賃対象条件・順位互換規則はimportしない。探索・枝刈り・guard・候補順位の処理は変更しない。歩行根拠URLのvalidatorに仙台市の公式3ホストだけを追加し、既存の他都市条件を保持する。

## 2. 公式データ調査と認定の限界

[市の公式一覧](https://www.city.sendai.jp/joho-kikaku/shise/security/kokai/opendata_example.html) が示すデータ基準日は2023-07-01。ページ更新日2026-07-09、カタログ掲載日2025-03-10をダイヤ改正日として扱わない。
[公式ライセンスカタログ](https://www.city.sendai.jp/opendata/index.php?asc=data_upddt&displayedresults=100&p=4_1) の8つの実ダウンロードリンクとCC BY 4.0表示を確認。概要には方向・平休日の誤記があるため、概要文だけでファイルを分類しない。原ファイル名・列の駅順・始発/行先も照合する。帰属は仙台市。

| 原ファイル | 便数 | SHA-256 |
| --- | ---: | --- |
| namboku_w_south_20230701.csv | 157 | 200b9652bd2b6db551c996db74d962c0921979d30a8c83e6e5a4ca67298b81fd |
| namboku_w_north_20230701.csv | 157 | a8f57231a311cc45a76d1f863fa0600a93254aa2333a40b47102116dc083eca2 |
| namboku_h_south_20230701.csv | 113 | 21cdcb666a3e125b83835fd56637d9df37ab9e83419fc50c6473b324566b1d6f |
| namboku_h_north_20230701.csv | 114 | e67011c6c0100e9b00ca3c210bbe99587f028b701bf6bd8aa0e54f9005c5d7aa |
| tozai_w_east_20230701.csv | 140 | 88b1ff652ee9b03ed543dbe476f85f85444fa675d892afdbb6f9e25095c8f460 |
| tozai_w_west_20230701.csv | 140 | 6b03c9c11ac8576316c6e7d4323226042af1b159033ab9695679edc9500ed723 |
| tozai_h_east_20230701.csv | 112 | ff24e68bcfb8c3cf4272bb72b82fdf8f4f80e9b900842fddc0b27642935ee050 |
| tozai_h_west_20230701.csv | 113 | 621a24b8d3a179e49b4f259dd1a8c4d3fcadcdab77770da3e6f938d4b4eef8b6 |

原データはCP932、1行が具体的な便、最初の2列が行先・始発、以降が駅順の時計。南北線17駅・東西線13駅、合計1,046便で、途中空欄の部分便は見つからなかった。公式列車番号は含まれない。識別子にはファイル名・原SHA・原行番号を保存し、別駅の発車時刻同士を推測でつないで便を作らない。10便は23時台から0時台へ跨ぐ。正常化は明示的な1回の `23:xx → 0:xx` のみ認める。他の時計逆転は停止する。

取得した[現行の公式駅時刻表](https://www.navi.kotsu.city.sendai.jp/dia/bustime/sp/)29ページ（仙台駅は両線を同一ページに掲載）を比較した。**終着を除く112組の駅・方向・日種別の発車時計multisetが一致**した。0時台を営業日の24時台へ対応させる。表記差 `旭ヶ丘` / 公式ナビ `旭ケ丘` は6649駅だけの明示対応であり、一般的な駅名正規化は行わない。HTMLは宣言どおりShift_JISでstrict decodeする。最初の一覧HTML取得時にUTF-8を誤指定した中間ファイルは検証入力から除外し、同じ公式URLの原bytesを取り直した。

この比較で認定するのは取得時点の発車時計集合だけ。駅間で同じ便に結び付くことの独立確認、8終着の到着時計、中間駅の到着/停車秒、祝日・年末年始・臨時ダイヤの適用日は未認定。単一時計から到着=発車を仮定しない。時刻表HTMLに見えていない時計を他方向の表から補わない。2023年CSV全体を現行運行用データへ無条件昇格しない。

[公式地下鉄駅GIS](https://www.city.sendai.jp/joho-kikaku/shise/security/kokai/opendata_chikatetsueki.html) から[原CSV](https://www2.wagmap.jp/sendaicity/sendaicity/opendatafile/map_235/CSV/opendata_925.csv)を取得。UTF-8 BOM、名称・住所・経度・緯度等の30行。SHA-256は `7a7fd7cebaa3fafc9e1fe17d51a4e2e065392d1df7f7e2228b2b8b5fb9a282b0`。公開詳細は2025-04-23更新、CC表示。仙台駅（南北線）と仙台駅（東西線）は別座標なので、`namboku/仙台` と `tozai/仙台` を別stopにする。公開された緯度経度の確認と、運行用WGS84/駅出入口・ホーム接続の認定は区別する。CRS・出入口からホームまでの動線/所要時間は追加確認が必要。

市営バスの[ODPT公式カタログ](https://ckan.odpt.org/dataset/sendai_municipal_bus_realtime_information)はCC BY 4.0。現行リソースの説明文に適用年の不整合があるため、説明文から運行日を仮定しない。この環境にODPTキー/承認済みGTFS本体はなく、公式static URLへの無認証取得は403だった。ミラーや旧データへ切り替えて実経路の合格を作らない。

## 3. 独立Adapterの入力契約

`api/transit_adapters/sendai_subway.py` は公開CSVをstrictに検査する `inspect_csv` と、レビュー付きの `SendaiSubwayAdapter.load` を分ける。運行用変換には8ファイルすべてについて原SHA一致、各非終着駅の現行発車比較、**具体便の各停車位置に対応した独立到着秒**、到着時計/現行ダイヤ/運行日/ライセンスの公式証拠URL+hash、明示した適用日集合、30の線別駅座標が必要。証拠レコードは公開資料の人によるレビューの入力契約であり、URLを書くだけで資料の内容を自動的に証明するものではない。

平日・土休日はカレンダーの曜日フラグから推測しない。確認した日だけをServiceExceptionで追加し、未確認日は非運行とする。両線・両方向で日種別が一致し、2種が同日重複しないことを検査する。到着→発車→次駅到着の非減少性、終着の原時計との一致を要求する。秒を保持し、既存のminute欄には既存契約の最近分丸めを併記する。共通ネットワークの計算は原秒からのFractionを使う。metadata.versionは原CSVだけでなく到着時計・運行日・座標・レビュー証拠にも依存する。

現在の実資料はこの契約を満たし切っていない。**実運行用地下鉄Datasetはまだ作成・登録していない**。合成テストの20秒停車等は明示した架空データで、実CSVの到着補完には使わない。部分便・異なる形式の将来CSVも暗黙修復せず停止する。

## 4. 無料Policyと検索前のscope

[ふれあい乗車証の公式制度](https://www.city.sendai.jp/servicekanri/kurashi/kenkotofukushi/shogai/shakaisanka/waribiki/fureai.html)では市営バス・宮城交通バス・地下鉄の市内区間が無料。交付要件/所得制限があり、有効期限は毎年9月30日。利用者が有効な本人の乗車証を持つ前提の運賃Policyであり、アプリが交付資格や更新済みを認定しない。[敬老乗車証](https://www.city.sendai.jp/korekikaku-kikaku/kurashi/kenkotofukushi/korenokata/katsudo/sedo/joshasho/)はチャージに利用者負担が必要なので無料Policyにしない。

`api/sendai_shared_network.py` の `SendaiFureaiPassPolicy` はID `sendai_fureai_pass`、追加支払0円。公開registry/UIにまだ登録しない。通常運賃は不明のまま `None` を保持する。

スコープ構築時、feedを `sendai_bus` / `sendai_subway`、modeをbus / railに固定。便とfeed版、隣接する停車位置番号とstop ID、事業者SendaiMunicipal、確認済みlocal種別、**区間全体が市内04100にあることの原資料レビュー**を要求する。両端が市内でも途中に対象外区間があれば認定しない。停留所座標だけから走行区間全体の市内性を推定しない。欠落した区間は未確認として検索前に除外。明示レビューの矛盾・版違い・対象外は理由付きで停止する。宮城交通は制度対象でもデータ未確認のため、この実装では未対応。

現段階は**全隣接区間が確認できた具体便だけを許可**する保守的なwhole-run方式。途中が未確認の便にある合法な市内部分乗車も、当面は返せないという完全性の制限を明示する。将来の区間scope拡張で便を分割する場合も具体便の連続性・停車位置を壊さない別設計が必要。

許可便集合を `build_transit_network` に渡してから検索するため、対象外の安い/速い経路を検索後だけで除く方式ではない。徒歩は向き・正確なstop ID・両feed版・測定距離・所要時間・駅構内動線を確認した `DirectedWalkLink` だけを使う。近接、同じ駅名、同じ座標からリンクを作らない。逆方向は独立にレビューする。

検索は既存共通coreの `time` と明示した `NetworkSearchParameters` を使う独立opt-in。既存coreの明示ゼロ下界baselineをそのまま使い、新しいA*を導入しない。エラー時のゼロ下界への切替ではない。静的時刻表のみでRealtime指定は拒否する。順位は既存共通coreのtime/同着cost規則で、横浜v1互換の順位を持ち込まない。既存仙台runtimeや東京をこの実装へ切り替えない。

24時台は元の営業日付きで検索する。民生日付00時台の要求から前営業日の24時台と当日を結合する機能は未実装・未認定。UI接続前に別ゲートが必要。時刻表だけから自動的に前日を推測しない。

## 5. 検証・受け入れ条件

合成の独立全列挙oracleは原整数秒と乗車/下車位置・明示徒歩リンクを使い、既存coreのグラフ・priority・dominanceを呼ばず主到着を比較する。市営バス単独、地下鉄単独、双方向の乗換、1分ホーム余裕の境界、逆向きリンクなし、対象外/未確認の便、循環の停車位置、運休日例外、24時台/原秒、候補時計の改変拒否、Realtime拒否、元探索例外の伝播を回帰に含める。小さな24組の乱数固定乗換時刻もoracle比較する。max_visited=1の負例はエラー伝播の検査専用で、本番上限や許容性の認定と混同しない。

実データ回帰は原CP932 bytes+SHAを保持した8ファイル/1,046行の停車時計を独立oracleで照合する。112組の公式発車比較は読み取り専用CLIで実行し、取得日と各HTMLのhashを記録する。**実バス＋地下鉄の正解経路比較は未完了**。東京第50節、合成oracle、発車集合一致だけから全仙台queryの正当性・真のtop-kを認定しない。

UI/通常runtimeへ接続する前に以下をすべて満たす。

1. 現行の具体便・到着/発車秒・運行日（祝日/年末年始/臨時日を含む）と座標CRSを公式資料でレビューし、Adapterの厳格入力を作成する。
2. 承認日付と入力hashを固定した市営バスGTFS本体を既存loaderで検証。各対象走行区間の市内無料性と実際の駅構内/バス停徒歩接続をレビューする。
3. 市営バス単独・地下鉄単独・両方向の実ODを固定し、公式時刻表/独立oracleと具体便・駅順・発着時計・乗換時間を比較。休日/跨日/乗車不可区間/対象外区間を負例で確認する。民生日付跨ぎの統合も検証する。
4. パスPolicyを検索前scopeとAPIへ接続し、公開UIに明示選択肢を追加する。既存 `normal` 保存値・初期値を変換しない。通常運賃と「追加支払0円」を分けて表示する。未確認区間・宮城交通・敬老証を無料へ拡張しない。
5. 仙台独立テストとGitHub Actionsを通過し、認定入力版・日付・対象範囲・未認定flagを記録する。

## 6. ローカル読み取り専用の再検査コマンド

新しい空のローカル保存先を指定する。公開公式URLからレビュー資料を取得するだけで、runtime/S3/本番設定には触れない。失敗した保存先を暗黙再利用せず、新しいディレクトリ名を使う。検査は異常を元例外付きで停止し、部分一致を合格にしない。

```powershell
python -B scripts/fetch_sendai_subway_review_sources.py --output-dir sendai-review-YYYYMMDD
if ($LASTEXITCODE -ne 0) { throw 'Sendai source acquisition failed' }
python -B scripts/check_sendai_subway_sources.py --csv-dir sendai-review-YYYYMMDD --current-html-dir sendai-review-YYYYMMDD
if ($LASTEXITCODE -ne 0) { throw 'Sendai source inspection failed' }
```

成功マーカーは `READ_ONLY_SENDAI_SUBWAY_SOURCE_INSPECTION_OK`。同時に `OPERATIONAL_CERTIFICATION_WITHHELD` を出し、`operational_ready=false` と未認定理由を必ず記録する。これは運行用データ認定CLIではない。現在の資料不足を埋めた成功マーカーは用意しない。成功済み東京/バス監査は一切呼ばない。

## 7. 実行結果

ローカルPython 3.12.14で新規17件成功。原CSVの全1,046便と10跨日便を確認し、現行公式HTMLの112組比較も成功した。公開実データによる混在経路の合格や仙台SearchCore全体の安全性認定は保留。GitHub Actions結果は検証完了後に追記する。
