# 仙台市営バス＋地下鉄・ふれあい乗車証の共通ネットワーク設計

## 1. 優先順位・現状（2026-10-15）

2026-10-16の共通v2への統一・旧実装削除・実用profileの実装状況は第10節を参照。本節〜第9節の「現状」「未実装」は各記録時点の状態である。

開始時mainは `f1900123d03fb0947c52c20aadc07dcbab32a4c5`。2026-10-16の2都市整理後は東京＝公開版、仙台＝開発版。共通入力契約・東京監査履歴は [共通設計](shared-network-design.md) に移設した。仙台のアプリID、データ、原資料、独立oracleと検証資産を保持し、本番デプロイ・S3変更・ストア提出は行わない。

- `api/sendai_transit.py`: ODPT公式市営バスGTFS-JPの取得・明示日付のmanifest検証。`SendaiRouteBackend` はこのバスfeedだけを受け入れる。
- `api/app/sendai_runtime.py`: 既存のバスbackendとバスRT3種を起動する。新しい地下鉄は選択しない。
- `api/gtfs_route_backend.py`: 汎用Dataset検索を利用するが、異なるfeed間のレビュー済み徒歩接続を扱う新しい都市wrapperではない。ここへ都市固有の運賃条件を追加しない。
- `api/fare_policy.py`: 仙台の公開選択肢・既定値は `normal` のみ。通常運賃が不明なら不明のまま保持し、0円へ置き換えない。
- `lib/core/city_profile.dart`: 仙台も `normal` のみ。アプリIDは `jp.cloxs.go.sendai`。Issue #148記載の別表記へ改名しない。
- [Issue #148](https://github.com/kaeruko/tobus_go/issues/148): 本番環境・承認済みバスデータ・端末/ストアの作業。今回の実装をデプロイ承認や完了と扱わない。
- [Issue #171](https://github.com/kaeruko/tobus_go/issues/171): 市営バスとRTは既存対応、地下鉄CSVは2023年基準で条件付き、宮城交通データは未確認。今回も宮城交通は未対応とする。

再利用するのは `TransitDataset`、`transit_network.build_transit_network`、`transit_timetable_choices.search_network`、`ReviewedWalkingLink`。都市固有wrapper・他制度の運賃条件・旧順位互換規則はimportしない。探索・枝刈り・guard・候補順位の処理は変更しない。歩行根拠URLのvalidatorに仙台市の公式3ホストだけを追加し、既存の他都市条件を保持する。

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

追加照合として[同じ公式GISのKML](https://www2.wagmap.jp/sendaicity/sendaicity/opendatafile/map_235/KML/opendata_925.kml)も取得した。SHA-256は `20d3e8b77f80a0c934c29aabe50022a6b9401030f3a073b03384c5926abb238f`、同名の30地点を確認。CSVとKMLの原座標は全地点で異なり、概算差は約0.87〜1.16mだった。同じ公開元だから同じ数値・CRSだと推測しない。SHAPE配布にもPRJは含まれていなかった。[OGC KMLのCRS規則](https://docs.ogc.org/is/12-007r2/12-007r2.html)に従うWGS84座標としてはKMLの原値を別証拠で固定する選択肢がある。CSVへ未確認の変換を適用しない。これは公開代表点の参照系の確認であり、現地測量精度や駅出入口・ホーム接続時間を保証しない。

市営バスの[ODPT公式カタログ](https://ckan.odpt.org/dataset/sendai_municipal_bus_realtime_information)はCC BY 4.0。現行リソースの説明文に適用年の不整合があるため、説明文から運行日を仮定しない。この環境にODPTキー/承認済みGTFS本体はなく、公式static URLへの無認証取得は403だった。ミラーや旧データへ切り替えて実経路の合格を作らない。

## 3. 独立Adapterの入力契約

**適用範囲の改訂（第9節）：本節は独立到着秒を要求する厳密プロファイルの契約である。利用者向けの分単位時刻表検索すべてに、この契約の達成を要求しない。** 既存Adapterを暗黙に緩和せず、到着目安を使う初期版は別の明示プロファイルとして実装・検証する。

`api/transit_adapters/sendai_subway.py` は公開CSVをstrictに検査する `inspect_csv` と、レビュー付きの `SendaiSubwayAdapter.load` を分ける。運行用変換には8ファイルすべてについて原SHA一致、各非終着駅の現行発車比較、**具体便の各停車位置に対応した独立到着秒**、到着時計/現行ダイヤ/運行日/ライセンスの公式証拠URL+hash、明示した適用日集合、30の線別駅座標が必要。証拠レコードは公開資料の人によるレビューの入力契約であり、URLを書くだけで資料の内容を自動的に証明するものではない。

平日・土休日はカレンダーの曜日フラグから推測しない。確認した日だけをServiceExceptionで追加し、未確認日は非運行とする。両線・両方向で日種別が一致し、2種が同日重複しないことを検査する。到着→発車→次駅到着の非減少性、終着の原時計との一致を要求する。秒を保持し、既存のminute欄には既存契約の最近分丸めを併記する。共通ネットワークの計算は原秒からのFractionを使う。metadata.versionは原CSVだけでなく到着時計・運行日・座標・レビュー証拠にも依存する。

現在の実資料はこの契約を満たし切っていない。**実運行用地下鉄Datasetはまだ作成・登録していない**。合成テストの20秒停車等は明示した架空データで、実CSVの到着補完には使わない。部分便・異なる形式の将来CSVも暗黙修復せず停止する。

## 4. 無料Policyと検索前のscope

[ふれあい乗車証の公式制度](https://www.city.sendai.jp/servicekanri/kurashi/kenkotofukushi/shogai/shakaisanka/waribiki/fureai.html)では市営バス・宮城交通バス・地下鉄の市内区間が無料。交付要件/所得制限があり、有効期限は毎年9月30日。利用者が有効な本人の乗車証を持つ前提の運賃Policyであり、アプリが交付資格や更新済みを認定しない。[敬老乗車証](https://www.city.sendai.jp/korekikaku-kikaku/kurashi/kenkotofukushi/korenokata/katsudo/sedo/joshasho/)はチャージに利用者負担が必要なので無料Policyにしない。

`api/sendai_shared_network.py` の `SendaiFureaiPassPolicy` はID `sendai_fureai_pass`、追加支払0円。公開registry/UIにまだ登録しない。通常運賃は不明のまま `None` を保持する。

スコープ構築時、feedを `sendai_bus` / `sendai_subway`、modeをbus / railに固定。便とfeed版、隣接する停車位置番号とstop ID、事業者SendaiMunicipal、確認済みlocal種別、**区間全体が市内04100にあることの原資料レビュー**を要求する。両端が市内でも途中に対象外区間があれば認定しない。停留所座標だけから走行区間全体の市内性を推定しない。欠落した区間は未確認として検索前に除外。明示レビューの矛盾・版違い・対象外は理由付きで停止する。宮城交通は制度対象でもデータ未確認のため、この実装では未対応。

現段階は**全隣接区間が確認できた具体便だけを許可**する保守的なwhole-run方式。途中が未確認の便にある合法な市内部分乗車も、当面は返せないという完全性の制限を明示する。将来の区間scope拡張で便を分割する場合も具体便の連続性・停車位置を壊さない別設計が必要。

許可便集合を `build_transit_network` に渡してから検索するため、対象外の安い/速い経路を検索後だけで除く方式ではない。徒歩は向き・正確なstop ID・両feed版・測定距離・所要時間・駅構内動線を確認した `DirectedWalkLink` だけを使う。近接、同じ駅名、同じ座標からリンクを作らない。逆方向は独立にレビューする。

検索は既存共通coreの `time` と明示した `NetworkSearchParameters` を使う独立opt-in。既存coreの明示ゼロ下界baselineをそのまま使い、新しいA*を導入しない。エラー時のゼロ下界への切替ではない。静的時刻表のみでRealtime指定は拒否する。順位は既存共通coreのtime/同着cost規則で、旧v1互換の順位を持ち込まない。既存仙台runtimeや東京をこの実装へ切り替えない。

今回の入口はstop IDを指定する独立検証用ライブラリである。公開APIの座標入力・起終点の徒歩・既存候補形式へのserializer・`for_fare_policy` 接続・アプリのパス選択は未実装/未接続。Policyの `quote` は確認済みnetworkの具体便eventを要求し、既存の端点だけのFarePolicyContextから無料を推測しない。実データゲート合格後に、これらを別途実装・検証する必要がある。認定flagを反転するだけで本番起動できる状態とは扱わない。

24時台は元の営業日付きで検索する。民生日付00時台の要求から前営業日の24時台と当日を結合する機能は未実装・未認定。UI接続前に別ゲートが必要。時刻表だけから自動的に前日を推測しない。

## 5. 検証・受け入れ条件

合成の独立全列挙oracleは原整数秒と乗車/下車位置・明示徒歩リンクを使い、既存coreのグラフ・priority・dominanceを呼ばず主到着を比較する。市営バス単独、地下鉄単独、双方向の乗換、1分ホーム余裕の境界、逆向きリンクなし、対象外/未確認の便、循環の停車位置、運休日例外、24時台/原秒、候補時計の改変拒否、Realtime拒否、元探索例外の伝播を回帰に含める。小さな24組の乱数固定乗換時刻もoracle比較する。max_visited=1の負例はエラー伝播の検査専用で、本番上限や許容性の認定と混同しない。

実データ回帰は原CP932 bytes+SHAを保持した8ファイル/1,046行の停車時計を独立oracleで照合する。112組の公式発車比較は読み取り専用CLIで実行し、取得日と各HTMLのhashを記録する。**実バス＋地下鉄の正解経路比較は未完了**。東京第50節、合成oracle、発車集合一致だけから全仙台queryの正当性・真のtop-kを認定しない。

以下は当初の厳密プロファイル向け接続条件である。**到着目安を表示する初期版については、第9節の改訂条件を適用する。独立到着秒と全臨時便の取得を初期版全体の必須条件にはしない。** 無料scope、承認済みバス入力、独立経路検証、通常設定の保持は引き続き必要とする。

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

成功マーカーは `READ_ONLY_SENDAI_SUBWAY_SOURCE_INSPECTION_OK`。同時に `OPERATIONAL_CERTIFICATION_WITHHELD` を出し、`operational_ready=false` と未認定理由を必ず記録する。これは運行用データ認定CLIではない。現在の資料不足を埋めた成功マーカーは用意しない。合格済みの東京/バス実データ監査と36ケース比較は一切呼ばない。

## 7. 実行結果

ローカルPython 3.12.14で新規17件成功。原CSVの全1,046便と10跨日便を確認し、現行公式HTMLの112組比較も成功した。公開実データによる混在経路の合格や仙台SearchCore全体の安全性認定は保留。検証した実装SHAは `ace3874ba6b66acf5d1fd999ecbf903b00ee6dfc`。GitHub Actions [38804515065](https://github.com/kaeruko/tobus_go/actions/runs/38804515065) は `completed/success`、全7 jobが成功した。Linux APIは1,018件・skip 6、Windowsは253件で成功し、Windows logでも新規17件すべての `ok` を確認。Repository safety、Rust/Python 3.11・3.12、Flutter analyze/test、Android/iOS全4 flavorとidentity/Firebase分離検査も成功した。仙台runtime・公開fare registry・Dart profileを変更した結果ではない。

取得スクリプトは保存済み公式37入力の再生でも確認し、出力先の上書き拒否と、取得例外をそのまま伝播して完了manifestを残さないことを確認した。この再生を追加の現行ダイヤ認定として数えない。

以上は独立opt-in実装・入力検査・合成固定queryの回帰結果であり、実バス＋地下鉄OD、民生日付跨ぎ、駅構内動線、通常運賃の正確性、真のtop-k、仙台全queryの正当性は未認定のまま。追加資料と実データゲートが必要。公開UI/API・本番切替・デプロイ・S3・ストア提出は実施していない。合格済み東京/バスの実データ監査と36ケース比較は再実行していない。

## 8. 到着時計・運行日・実歩行時間の追加調査と停止（2026-10-16 JST）

**第9節による訂正：以下は厳密到着秒の認定を前提にした当時の調査・停止記録である。これを実用的な時刻表検索の開発停止条件としては適用しない。2026年版公式ガイドには仙台駅の線間乗換を5分として計算する根拠がある。厳密認定の保留と、到着目安を使う初期版の開発再開を区別する。**

**結論：実運行用地下鉄Datasetの必須証拠が揃わず、認定ゲートの実装・実行前に停止する。** 開始時及び記録直前のmainは `00d9178f23ef3dbe8ccc390e96f46547dd6eed38`。以下は資料調査の記録であり、実運行認定の成功結果ではない。途中駅/終着の到着時計を発車時刻・駅間所要時間・停車秒から補完しない。第7節の17回帰及び112組照合の成功範囲は拡大しない。

### 8.1 到着時計の独立資料

調査したのは交通局の駅案内/ナビ、公式の車両別運行予定・装飾列車案内、公開GTFS案内、経営計画のデータ公開項目、運行図表/運転時刻表/業務用時刻表の公開候補である。**現在の両線全便について、具体便と停車位置に対応する到着/発車の別を確認できる、取得可能な独立原資料は確保できなかった。** 公開資料が存在しないと断定したものではない。

- [令和8年4月時点の事業管理シート71](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/04/20260401-071.pdf) は、市バスGTFSと地下鉄の駅位置・乗車人員・駅時刻表の継続公開を記載する。地下鉄の到着/発車付き全便GTFSの取得先を示す根拠にはならない。
- [公式地下鉄アーカイブ](https://www.kotsu.city.sendai.jp/page_category/cat-subway/page/11/) の「金の前立て」編成案内は、各駅の**発車**時刻の掲載と明記し、終了した期間の資料である。南北線3000系の限定便予定表も検索で見つかったが、2025年等の限定日の予定・1駅1時計であり、現行の全便到着時刻を認定できない。対象便の原ダイヤとの対応や終着列の時計意味も別途確認が必要。
- [東西線10周年装飾列車の公式ページ](https://www.kotsu.city.sendai.jp/subway/tozai10th_kinen_ressya/) は取得できたが、掲載期間は2025-12-07〜2026-01-04。リンク先の2025-12-28及び2026-01-01の個別PDFは閲覧ツールで取得不能/404だった。これを現在の時刻表として代用しない。
- 2023年改正の停車秒の説明も、分精度の発車表示から具体便の到着秒を逆算する根拠にはしない。一般所要時間表・「到着時刻指定」検索という機能名だけでも、必要な原到着時計の証明にはならない。

到着時計は途中駅と終着の双方が未認定。終着時計だけを推定上「到着」と読み替え、全便のgateを通したことにもしない。

### 8.2 運行日・祝日・年末年始・臨時

[公式ナビの利用案内](https://www.navi.kotsu.city.sendai.jp/guide.html) で平日/土曜/日祝の検索区分、時刻表を基にした経路表示、臨時運行・道路規制の迂回・不定期便を網羅しない制限を確認した。検索結果の実到着を保証しないという注意と、予定ダイヤの正しい運行日/到着時計を確認する問題は区別する。

- 普通の平日/土休日という分類の存在は既知だが、特定の実日付にどの全便ダイヤ版を適用するかの承認は別に必要。祝日名や土日判定だけで、未確認の臨時日を通常扱いにしない。
- 2023年改正の公式説明は土休日2023-07-01・平日2023-07-03と日付を分けている。これを現行年全体の適用開始/終了日へ外挿しない。
- 2025年度の年末年始について、旧公式URL `https://www.kotsu.city.sendai.jp/bus/news/nenmatsu_nenshi/index_r07-r08.html` が第三者の記事から辿れたが、取得時は404。検索キャッシュや第三者転載だけで例外日を認定しない。2026-2027年の年末年始の適用表も確保できていない。窓口営業時間や一日乗車券の休日料金の規則を運行日規則の代用にしない。
- 2026年お盆の区分表も検索表示にはあったが、直接取得の事前条件（対象告知の識別）が一致せず `AssertionError` で停止した。5日分の運行日を認定した扱いにはしない。特にバスと地下鉄へ同じ休日設定を流用しない。
- [ベガルタ仙台ホームゲーム時の増便についての公式案内](https://www.kotsu.city.sendai.jp/subway/vegalta-zoubin/) は、泉中央→富沢方向に通常便に加えて1〜2本を増便し、開催前に公式Xで本数を告知する運用を説明する。開催日という条件から、増便の全停車時刻や具体便IDを生成してはいけない。ナビだけで臨時を含む完全な運行日閉包を認定できない具体的な理由である。

承認できる日付集合・特別ダイヤ/取消/増便の優先規則・版の有効期間が不足している。既存Calendarの自動拡張や、臨時日の無条件除外/通常扱いで穴を埋める実装は行わない。

### 8.3 仙台駅の線間・市営バスとの徒歩接続

[仙台市の現行乗り換え案内ページ](https://www.city.sendai.jp/kokyo/kurashi/machi/kotsu/annai/noritsugi.html) がリンクする [R8乗り継ぎガイド](https://www.city.sendai.jp/kokyo/kurashi/machi/kotsu/annai/documents/noritsugi_r8_small.pdf) を取得した。原bytes 7,766,939、SHA-256 `b7087122a2b4e1804633ae18d606211125ca8f2664960b1471a59ee7b2c13a00`。全8ページの文字抽出と、7ページ目Dの地下1〜4階図の視覚確認を行った。南北線B3・東西線B4、B2の乗換階、おすすめ/エレベーター経路を区別できる。しかし、現在の方向別に採用する実歩行時分・測定距離・設備待ちの条件を、この調査で確定するには至らなかった。図の存在を計測値の証明として扱わない。

[現行交通局の仙台駅ページ](https://www.kotsu.city.sendai.jp/subway/station/list/sendai/) と直接取得HTMLで、中央2番出入口のエレベーター停止、北5番出入口閉鎖を確認。市の案内ページも2026-09-01から仙台TRビルのエレベーター（市バス60番のりば付近）が利用不可とする。したがって、古い図の当該動線を無条件に有効扱いしない。

2015年12月版の旧駅別資料 `https://www.kotsu.city.sendai.jp/touzaisen/pdf/07_sendai11.pdf` の検索・閲覧キャッシュには、ホーム間移動3〜4分、別箇所に待ち時間込みの乗換5分という異なる値がある。原URLの直接取得は `requests.exceptions.HTTPError: 404 Client Error` で停止した。**現行の徒歩リンクに3分/4分/5分のいずれも登録しない。** 5分を純歩行時間に読み替えたり、待ちを二重計上したりしない。逆方向へ同じ値をコピーせず、エレベーター経路の時間にも置き換えない。

市営バス↔地下鉄は、正確なのりば/降車場→出入口→改札→ホームと逆方向、それぞれの実測/公式標準時分、設備の可用時間、GTFS stop IDと線別station IDの対応が不足している。両線の駅名や代表座標だけで接続を作らない。

取得した現行HTMLのSHA-256は、交通局仙台駅ページ `9cea74f6b4f9a5e5aa26cc16153789d687e117b0bed3de5d9444fe2f79cf5b8a`、市乗り換え案内ページ `716632ecf25f6a476196719f2f2b1b6074c1bf80a05afaad9e998ba7f63b301a`。

### 8.4 取得可能な市営バスとの独立照合

[交通局の2026-03-02の公開案内](https://www.kotsu.city.sendai.jp/bus_news/gtfs-jp_gtfs_data/) は市営バスのGTFS-JP/GTFS-RTをODPTへ公開したとする。[ODPTの当該カタログ](https://ckan.odpt.org/dataset/sendai_municipal_bus_realtime_information) のリソース `20261006` は、2026年の改正説明と2025年の適用期間説明が不整合のまま。メタデータだけで対象期間を認定しない。

この実行環境のファイル一覧とGitHub treeには、承認済み仙台バスGTFS一式/manifestは見つからず、`ODPT_API_TOKEN` の有無だけを確認した結果もfalseだった。ユーザーのWindows端末にファイルが無いという意味ではない。GTFS本体の再取得、認証の迂回、別配布元/過去データへの切替、S3上のデータ探索はしていない。データが承認済みとして利用できないため、実バス＋地下鉄OD比較は未実行。

調査用のODPTカタログ検索API `package_search?q=仙台&rows=100` はJSONとして解釈できず、`requests.exceptions.JSONDecodeError: Expecting value: line 1 column 1 (char 0)` で停止した。HTML等への自動切替はしていない。この失敗から「該当GTFSは0件」や「地下鉄GTFSは存在しない」と結論しない。

### 8.5 不足資料と取得先候補・再開条件

| 必須資料 | 取得先候補 | 確認する内容 |
| --- | --- | --- |
| 両線の現行実施ダイヤ/運転時刻表、又は到着/発車付き公式データ | 交通局営業課管理係→ダイヤ原資料を管理する担当部署への取り次ぎ | 中間/終着の到着・発車の別、原時計の精度、具体便/運行番号、停車順、CSV原行との対応、有効版、アプリでの加工・利用条件 |
| 適用日と全例外の一覧 | 同担当、交通局の年度別運行告知・臨時便の原資料 | 平日/土休日/祝日/年末年始の優先関係、増便・取消・振替日、営業日24時台の所属、特別便の全停車時計 |
| 線間の方向別移動時分/動線 | 交通局営業課/仙台駅、仙台市公共交通推進課 | ホーム間・改札内経路、徒歩と設備待ちの区別、計測条件、推奨/エレベーター別、閉鎖・工事の適用日 |
| 市営バス↔地下鉄の方向別乗換表 | 上記部署と市営バスのりば管理担当 | 正確なのりば/降車場/出入口/ホーム、距離・時間・有効期間、GTFS stop IDの対応 |
| 承認済み市営バスGTFS-JP | 既存の承認済みローカル一式、又は正規権限で取得したODPT公式feed | ZIP/manifestと各入力hash、承認日、calendar/date例外、pickup/drop-off、市内無料区間。カタログの年矛盾は実体と提供元の説明で解消 |

公式の連絡先は [各種お問い合わせ窓口](https://www.kotsu.city.sendai.jp/inquiry/madoguchi/) に掲載される、交通局案内センター **022-222-2256**、地下鉄に関する営業課管理係 **022-712-8329**。市の乗り換え案内ページは公共交通推進課 **022-214-8353** を案内する。問い合わせ・FAX・メールの送信は行っていない。

案内センターのFAX/郵送サービスは「駅やバス停に貼ってある時刻表と同じもの」の提供である。到着/発車付き業務用時刻表まで当然に提供されるとは扱わず、必要な原資料の有無・提供可否を別に確認する。

上記資料の**取得可否と意味の確認**を再開条件とする。資料を確保した後も、まず固定した版・日付・方向・便だけを独立照合し、未知の日付/時計/経路は理由付きで停止する。部分照合を全実運行認定へ拡大しない。

**今回の実行数・変更範囲：** 新しい実運行ゲートの実装0、実データgate実行0、実経路比較0、既存17テスト再実行0、東京A*監査/既存112組ソース照合/36ケース比較の再実行0。変更は本節の文書追記のみ。文書のみのcommitは `[skip ci]` とし、成功済み試験を意味なく再起動しない。`operational_ready=false`、到着時計・運行日例外・実歩行時間・実バス混在経路の認定保留を維持する。公開API/UI・探索処理・既存名・アプリID・本番・S3・ストアは変更していない。


## 9. 公開時刻表による実用初期版の受け入れ条件への改訂（2026-10-16）

### 9.1 決定と根拠の訂正

開始時mainは `a450e3ebe573795ca4a2ef9d5fa71f27fb2f832d`。利用者から示された設計変更案に従い、**利用者向けの予定時刻に基づく検索**と、**独立資料による実列車の到着秒・許容性の厳密認定**を分ける。到着秒付き業務用ダイヤを取得できないことだけで、前者を停止しない。電話での業務用資料取得を実用初期版の再開条件にしない。第8節の調査結果・失敗記録は残し、全開発を止めるという受け入れ条件を本節で改訂する。

[交通局の2026年版「市バス・地下鉄ガイド」](https://www.kotsu.city.sendai.jp/images/guide2026.pdf) の原PDFを取得した。2ページ、2,769,174 bytes、SHA-256 `2154d455ad80d5b8c33b16122352b444a1b97d39b7290efa211cb54c9df76921`。第1ページの表紙で **2026年1月発行**、同ページ「地下鉄所要時間・運賃」の図の注記で **「仙台駅での乗り換え時間を5分として計算しています。」** を視覚確認した。文字抽出ではこの注記が得られないため、原PDFを描画して確認した。

これは現行年の一般利用者向けの公式標準として使える根拠である。一方、注記は純歩行・設備待ち・列車待ちの内訳、方向別実測、車椅子経路の所要時間、最小接続保証を示していない。第8.3節の旧2015年資料と混同せず、内訳を推測して認定しない。バス↔地下鉄に同じ5分を流用しない。

既存の1,046便復元・112組の発車集合照合は、その合格範囲で再利用する。現行駅時刻表は[公式ナビ](https://www.navi.kotsu.city.sendai.jp/dia/bustime/sp/subway/9285/)で平日・土休日別に掲載される。分単位の発車集合の一致を、到着秒や列車番号の独立照合に拡張しない。CSVのCC BY 4.0と帰属・加工表示は維持する。ガイドPDF自体をCSVと同じライセンスだとは推測せず、PDFの再配布ではなく出典・採用した標準値を記録する。

### 9.2 時計と認定プロファイル

| 項目 | 実用初期版の契約 | 認定しないもの |
| --- | --- | --- |
| 発車 | 公式CSVの分単位の原時計。原SHA・ファイル・行・停車順と営業日を保存 | その分の00秒に実際に発車するという保証 |
| 途中駅・終着の到着目安 | 同じ具体便・停車位置の公開時計を到着の代理値として使う明示モデル。出典・推定方式・分精度を各結果へ保持 | 原時計が公式に到着と明示されない場合の「正確な到着時刻」 |
| 接続判定 | 上記モデル時計に明示乗換基準・余裕を加え、実際の次便の公開発車時刻と比較 | 実列車の到着秒・遅延・個別の歩行能力を含む乗換保証 |
| 順位 | 固定したモデル上の予定到着目安による既存time検索 | 実運行の厳密最早到着、真のtop-k、東京監査からの自動認定 |

初期モデルでは各停車位置の公開時計をその位置の到着目安と発車時計の共通の分スロットに置く。これにより駅間の具体便・順序を保存し、根拠のない停車秒の減算・終着所要時間の外挿をしない。同じ時計を使っても、公開された発車と推定した到着は意味・provenanceを別に保持する。分表示しかない時計に `:00` を付けても観測秒の証拠にはならない。到着目安は実到着の上界でも下界でもなく、余裕を足すだけで厳密保証になったとは扱わない。

このモデルは**設計上の採用方針であり、まだ実装・実データ合格していない**。モデル時計の非減少性、同一便の継続乗車と別便への乗換の区別、降車/乗車可能位置、跨日、表示までの推定情報の保持を別ゲートで検証する。根拠のない平均停車秒や線別速度で補完しない。CSV終着時計も到着であるとの原資料が無い間は同じく目安扱いとする。

`SendaiSubwayAdapter.load` の既存の厳密入力契約とテストはそのまま残す。実用版は明示的に選ぶ別Adapter/レビュー型・profile版として実装する。`TransitDataset` へ渡すモデル時計の生成境界で推定根拠を保持し、通常の確定到着時計と混同する経路・serializerへ渡さない。必要な型・metadata伝播を先に設計し、既存のexact-source欄へ無印の推定値を流し込まない。厳密Adapterの失敗を捕捉して実用版に切り替える処理は作らない。旧CLIの `operational_ready=false` や厳密認定flagを反転して代用しない。

### 9.3 仙台駅の線間接続

南北線/東西線の別stop IDを保持する。初期版の線間接続は、**公式標準5分＋アプリ側の明示余裕**を使用する設計とする。初期検証用の余裕案は2分、合計7分であり、2分は公式値でも誤差を覆う証明済み上界でもない。実経路検証で採用値を固定してからprofile版に含める。障害の種別を推測して移動能力に一律の保証を付けない。バリアフリー対応を認定するには別の動線/設備条件が必要である。

この5分は方向別実測の `ReviewedWalkingLink.walk_minutes` とは意味が違う。測定距離や逆方向の独立実測を捏造して既存validatorを通さない。実装前に、版・線別端点・公式標準・余裕・適用期間・根拠を持つ **標準乗換接続の入力型** として、既存の実測徒歩型から区別する。両方向を同じ公式基準に基づくモデルとして明示採用することと、両方向を独立実測したことを区別する。既存の各都市の徒歩条件を緩和しない。

接続のready時計は `到着目安 + 5分 + 採用余裕`。次便はこのready時計以降の具体的な公開発車時刻を検索する。実際の時刻表から生じる待ち時間に、ガイドから推測した平均待ち時間を別途加えない。ガイドの5分の内訳が不明なことは残す。これを物理的最小乗換時間の推定値と呼ばない。既存探索アルゴリズム・guard・順位は変更せず、明示接続入力を作る境界で検証する。既存の実測徒歩契約では表せない場合は型設計で停止し、偽の徒歩データで通さない。

### 9.4 運行日・無料区間・バス接続

通常の平日/土休日と公的な祝日情報を基に、確認日・情報源・開始終了日を固定した有限の対応表を作る。年末年始等の通常規則から外れる可能性がある期間、把握した特別ダイヤ日で適用表が未確認の日は、理由を付けて検索対象から外す。路線/事業者別に扱い、バスと地下鉄の日種別を共用しない。対応表の期間外もunsupportedにする。全将来日の全臨時便が取得できることは要求しない。

臨時増便を網羅しない静的通常ダイヤの案内であること、確認基準日・対象期間を表示できるよう保持する。公式告知で通常便が変更/運休する日は、差分を検証するかその日を除外する。増便の存在だけを理由に通常便すべてが無効とは断定せず、通常便への影響が不明な日は対象外にする。営業日の24時台を保存し、民生日付00時台への結合は前営業日と当日の対応表を明示照合する。未対応の跨日要求を平日の時計へ丸めない。

ふれあい乗車証の市内無料scopeは第4節を維持する。時計を目安にしても、無料性・市内区間・事業者・有効な乗車証の前提を目安にしない。宮城交通は未対応、敬老乗車証は無料扱いしない。利用者の既存normal設定を変換しない。

市営バスとの混在検索には、承認済みGTFS本体/manifestと、のりば/降車場↔改札/ホームに対応する方向別接続の検証を引き続き必要とする。未確認の接続は候補へ含めない。バス接続の資料が揃うまで地下鉄単独の検証を進められるが、それを市営バス＋地下鉄全体の合格として扱わない。既存の承認済み入力を安全に参照できる環境で、読取専用ゲートを実行する。新しい無認証取得や過去feedへの切替で補わない。

### 9.5 実装順序・独立検証・残るゲート

1. 実用profile・分精度/到着目安provenance・標準乗換接続型を定義し、strict profileと分離する。主な対象は `api/transit_adapters/sendai_subway.py` 周辺の独立Adapter、`api/sendai_shared_network.py`、共通入力型の必要最小限の追加である。既存検索・枝刈り・guard・他都市の設定は変更しない。
2. 取得済み8CSV・公式駅時刻表照合記録・KML座標・2026ガイドのSHAをレビュー入力へ固定し、有限の通常運行日表と除外理由を作る。既存112組の照合を無条件に再実行しない。入力版/有効期間が変わった場合に限り対象を絞って再照合する。
3. 独立oracleは元の分時計・明示日付・接続基準から候補便を列挙し、同一便、駅順、乗降条件、モデル上の到着目安、無料scopeを比較する。公式発車の再現性、接続ready直前/一致/直後、2方向、同じ便の継続で余裕を重ねないこと、余裕の二重計上なし、終着目安、24時台、祝日、対象外日、未確認接続・無料区間、推定情報の欠落拒否を新規回帰に含める。既存17件を新profile認定へ読み替えない。
4. 固定した実OD・日付・公式発車便で地下鉄単独から検証し、承認済みバス入力・方向別接続が揃った範囲でバス単独/両方向混在を追加する。正解の具体便・発車・乗換判定は元時刻表と独立に照合する。到着目安そのものは推定方式の再現性として検証し、存在しない実到着の正解で合格数を作らない。観測可能な実到着との精度評価は件数・条件・差を別に報告し、未観測時は誤差保証なしと明記する。
5. 新規の独立回帰・GitHub Actionsと実データゲートが通ってから、公開API/serializer/UIへの接続を別途行う。将来の表示は「予定発車」「到着目安」「乗換余裕」「追加支払0円」を分け、通常運賃と混同しない。今は公開API/UIへ接続しない。

受け入れるのは、確認した入力版・通常運行日・無料区間・接続基準を使う**モデル上の時刻表経路**である。独立到着秒の認定、遅延/Realtime、実運行の乗換保証、バリアフリー全動線、未確認特別ダイヤ、全queryの正当性・真のtop-kは引き続き未認定とする。厳密到着秒が後から得られた場合は別profileの証拠として検証する。

**今回の変更と実行：** 設計書のみ。2026ガイドの取得・発行年月/5分注記の視覚確認を行い、実用版の受け入れ条件を更新した。実用Adapter/接続型/実データゲートの実装・実行はまだ0、合格済み17テスト・112組照合・東京A*監査・36ケース比較の再実行も0。文書commitは `[skip ci]`。厳密認定flag・探索・guard・候補順位・公開API/UI・本番設定・S3・ストア・既存名/アプリIDは変更していない。


## 10. 共通v2への統一・旧実装の整理・実用profileの実装（2026-10-16）

### 10.1 変更前mainと探索境界

開始時及び実装前確認のmainは `836ac54b7f340ba6d5cb0f50666a870c01731ec5`。ユーザーの追加指示により、未公開都市の旧方式との互換維持を目的とした二重経路を廃止した。削除対象と参照元を先に会話で一覧提示し、参照を更新してから削除した。東京の公開runtime・API・順位・設定と、`transit_search_labels.py` の探索・dominance・枝刈り・guard処理は変更していない。

仙台のバス入口は `TransitDataset -> build_transit_network -> search_network -> transit_search_labels.search_labels` へ統一した。既存ファイル名・都市backend名は保持し、feed検証・座標入力・結果直列化だけを接続層に残す。`transit_network_core.py` のendpoint組合せ処理は共通接続層であり、別の時刻表探索ループ・frontier・枝刈りではない。各組合せの検索は同じv2へ委譲し、batch全体の時間予算を減算して次の呼出しに渡す。別backendへの再試行はない。最早1件の範囲で検証し、真のtop-kを認定しない。

東京は `toei_engine._tokyo_label_search -> tokyo_search_labels.search_labels -> transit_search_labels.search_labels` という既存接続を保持する。新しい委譲テストは東京接続層の `_shared_search_labels` とDataset接続層の関数同一性を確認し、仙台の実呼出し及び元例外の伝播も検査する。東京固有の仮想目的地・下界・時計・RTを共通入力層へ移していない。

### 10.2 削除したファイル・機能と残した依存

| 対象 | 変更前の参照元 | 整理内容・理由 |
| --- | --- | --- |
| `api/transit_network_experiment.py` | 専用実験テスト | 独立した複数feed探索ループを削除。共通v2で代替 |
| `api/tests/test_transit_network_experiment.py` | `test_transit_network.py` が入力fixtureを参照 | 実験本体専用テストを削除。必要なGTFS/ODPT原入力fixtureだけを既存 `test_transit_network.py` 内へ保持 |

保持したもの：仙台のGTFS取得/manifest/公式データ照合、Realtime配信、無料scope、共通v2、東京の接続・証明・回帰、`transit_transfer_candidates.py` と読取専用の徒歩候補調査。旧Python/Rust v1本体・selectorは第11節の作業で削除済み。共通GTFS原入力fixtureは2都市整理時に `tests/transit_gtfs_fixture.py` へ移し、都市Policyへの依存を除いた。

### 10.3 実用Adapter・型・標準乗換

`api/transit_adapters/sendai_subway_practical.py` の `SendaiSubwayPracticalAdapter` は `profile=sendai_published_minute_v1` の明示指定を要求する。既存の厳密 `SendaiSubwayAdapter.load` は未変更。原8CSVのSHA、非終着発車集合比較の既存記録SHA/公式HTML証拠、CC BY 4.0、30の線別駅KML座標、有限運行日レビューを必須とする。旧17件や112組照合の成功マーカーを実用版の成功に転用しない。

`PublishedMinuteProvenance` は原URL/SHA・行/列・原時計・営業日分時計・1分精度と、`published_departure_minute` / `published_clock_arrival_proxy` を区別する。Dataset metadata、stop time、`NetworkRideEvent`、実用結果まで根拠を保持する。到着/発車のexact source seconds欄は `None`。終着は到着目安だけを持ち乗車不可、始発は降車不可。原秒であるかのように `minute * 60` をsource secondsへ埋めない。根拠欠落・source profileへの偽装・モデル時計の無印変更は停止する。従来の座標API serializerへ実用profileを渡すことも明示拒否する。

`api/sendai_practical_network.py` は無料区間レビューによる許可便集合を先に作り、共通v2へ渡す。結果は `PracticalRide` の予定発車/到着目安・元具体便/営業日と、`PracticalTransfer` の標準時間/余裕/根拠を分ける。無料quoteは元便・版・停車順・営業日・モデル時計に戻して再検査する。元のclock provenanceと結果の対応も検査する。バスや宮城交通を自動で追加しない。

仙台駅は線別stopを保持し、2026公式ガイドの5分と、明示指定した実験用余裕を `StandardTransferLink` で扱う。今回のモデル境界検証は余裕2分＝合計7分。余裕1分/3分との境界比較も行うが、2分の実測・誤差上界・正式採用を認定しない。両方向とも公式標準を使うモデルであり、方向別実測という意味ではない。ready以降の実際の公開発車便を選び、平均待ち時間を別加算しない。同じ具体便の継続に乗換余裕を重ねない。

標準接続を実測 `ReviewedWalkingLink` へ偽装しない。既存coreへは同じ時間前進の接続辺として入力する。物理距離は不明であり、label上の距離資源へ課す0は「実歩行0m」という認定ではない。`physical_walk_meters=None` と測定/接続保証falseを返す。したがってこの接続を含む結果の物理的歩行距離上限・バリアフリー所要時間も未認定である。未知の距離を制限内と保証するUIは接続しない。

### 10.4 有限日付・営業日24時台

`FiniteOperatingDays` は各日をw/h又は除外理由付きNoneとして保持する。未掲載日はunsupported、未確認特別日も明示除外で停止する。曜日から無期限に延長しない。fixtureは通常ダイヤのモデルとして2026-10-11〜18の8日を明示分類し、10月12日は[内閣府のスポーツの日](https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html)をhとした。内閣府原HTMLのSHAは `565ed19991424566812ce202196adc2a5f7932d9e607940ce28df76456413e43`。2026-12-31は年末特別ダイヤ未確認として除外する。それ以外を年全体へ拡大しない。通常便の全臨時変更/運休を網羅したという認定ではない。

民生日付/分を受け、検索期間の各当日・翌日と、24時台が届く場合の前営業日をすべて対応表で検査する。必要な1日でも未確認なら部分検索せず理由付きで停止する。各具体便を営業日付きのquery-local版へ明示配置し、元のrow ID・営業日時計・provenanceと非負の整数日offsetを保存する。前日をanchorにした共通Datasetへ渡し、結果は元の便/営業日と民生日付へ戻す。旧日付へ自動retryしない。前日w→当日h、当日23時台→翌日0時台、前日除外の負例を回帰に含む。

### 10.5 独立oracleと公開CSVで確認した範囲

新規 `sendai_practical_oracle.py` はraw CP932の行・列・分時計と明示日付から乗降位置を独立に列挙/緩和する。Adapter・Dataset calendar・共通graph・frontier・下界を呼ばず、boarding数を固定したモデルの最早到着を比較する。返却witnessについて、原行、発車時計、同じ便の停車順、営業日、接続ready、到着代理時計、許可便、追加支払0円を独立検査する。

公開8CSV/1,046便を使う新しい固定10経路はすべてoracleと一致した。下表の到着は**公開時計を代理値にしたモデル上の目安**であり実測ではない。通常ダイヤの有限日付モデル、`max_candidates=1`、`max_boardings=2`、`max_travel_minutes=120`、公式標準5分＋実験用余裕2分を固定した。上限を緩めてサンプルを通した結果ではない。

| 民生日付・出発 | OD | 到着目安 |
| --- | --- | --- |
| 10/16 10:00 | 南北線 泉中央→仙台 | 10:16 |
| 10/16 10:00 | 南北線 富沢→広瀬通 | 10:17 |
| 10/16 10:00 | 東西線 八木山動物公園→仙台 | 10:13 |
| 10/16 10:00 | 東西線 荒井→青葉通一番町 | 10:21 |
| 10/16 10:00 | 南北線 広瀬通→東西線 宮城野通 | 10:23 |
| 10/16 10:00 | 東西線 青葉通一番町→南北線 五橋 | 10:18 |
| 10/12 10:00（祝日h） | 南北線 泉中央→仙台 | 10:16 |
| 10/17 10:00（土曜h） | 東西線 八木山動物公園→荒井 | 10:27 |
| 10/16 23:50 | 南北線 仙台→富沢 | 10/17 00:11 |
| 10/17 00:00 | 南北線 五橋→富沢（前営業日w便） | 00:11 |

固定入力のDataset版は `dacb54426e087d8a6a802b4b17410df8e0a36c7f62d81433d77f2c913f1a2351`。レビューfixtureは `api/tests/fixtures/sendai_subway/practical_review_20261016.json`。当該版の両地下鉄線の市内区間・公式路線図に基づくレビューを具体便/区間へ固定する。端点座標だけで無料認定した結果ではない。市営バスの承認済みGTFS/接続根拠がこの環境に無い点は継続し、実バス単独/実バス混在の新しい合格を作っていない。既存の合成バス/混在回帰は共通入力の検査として保持する。

新規profile回帰には、推定情報・秒欄・版・license・明示profile、休日/除外日、跨日、乗換境界、同便継続、無料scopeの検索前除外、元例外/実探索上限の伝播、12seedの独立境界反例探索を含む。別の委譲回帰は東京/仙台の共通本体、未公開3都市のv1非使用、旧cost読み替えの拒否を検査する。合格済みの実データ第1〜第4段階、112組の現行HTML比較、36ケース比較は呼ばない。共通型と接続層を変更したため、CIでは既存の通常合成回帰も実行する。

### 10.6 CIと未認定項目

検証した実装commitは `dbb1d4276ead5e5b28a612beec4b22abd9372c25`。GitHub Actions [38831209934](https://github.com/kaeruko/tobus_go/actions/runs/38831209934) は `completed/success`、**全7 jobが成功**した。Linux APIは **997件・skip 5**、Windows probeは **275件**で成功。両jobのログで **新規22テストすべてのok** を確認した。22件には独立oracleとの実CSV固定10経路比較、12seedの境界反例探索、実core上限の停止、東京/仙台の同一探索本体への委譲、旧cost読み替え拒否、東京/未公開都市のAPI既定値分離を含む。第7節の旧17件/旧CIや112組の成功を新profileの合格へ転用した結果ではない。

Repository safety、Python/Rust参照coreの3.11・3.12 parity/format/clippy、Lambda image内の独立smoke、Flutter analyze/test、Android/iOSの全4flavorビルドとidentity/Firebase分離検査も成功した。Docker内の検証はデプロイではない。合格済みの実データ監査CLI・112組ソース比較・バス36ケースは再実行していない。共通入力型/接続層の変更を検証する既存の通常合成回帰はCIで実行した。

未公開都市の入力型 `SharedNetworkApiRouteRequest` は既定time、東京の既存 `ApiRouteRequest` は既定costを保持する。明示costのfewTransfersへの読替えは廃止した。共通endpoint登録の追加引数は既存型を既定とし、東京のAPI契約を保持することを既存endpoint 11回帰と新規既定値回帰で確認した。公開UIの保存済み設定や通常運賃を変換していない。

ローカル関連回帰及び `git diff --check` も成功。最後のCI結果追記は文書だけの `[skip ci]` commitとし、成功済みjobを再起動しない。CIの認定対象は上記実装SHAであり、文書追記を新たな実運行認定とは扱わない。

認定するのは上記入力版・有限通常日付モデル・固定queryの予定経路とprovenanceの整合性である。独立到着秒、実到着に対する誤差保証、実際の接続保証、余裕2分の正式採用、全特別ダイヤ、物理歩行距離/全バリアフリー動線、仙台全query/真のtop-k、承認済み実バスとの混在、公開API/UI接続は未認定。`exact_arrival_verified=false`、`actual_connection_guaranteed=false`、`experimental_margin_formally_adopted=false` を結果に保持する。厳密版の `operational_ready=false` を反転しない。

公開API/UIへ地下鉄/パスを接続しておらず、通常運賃設定・ファイル名・アプリID・東京本番設定・デプロイ設定・S3・ストアを変更していない。作業開始時から存在したDartの別差分はコミット対象に含めない。

## 11. 市営バス＋地下鉄の限定実経路・検証用API/Flutter・v1削除（2026-10-16）

### 11.1 開始mainと公式バスデータ

変更前mainは `aaccd9bfbaa276c5e5c13f998b5111989364b292`（第10節の最終記録）。作業開始時のDart別差分は保持し対象外とした。承認済み仙台bundle/manifest・ODPTキーはアクセス可能な環境に無かった。過去ZIP・他都市データ・別事業者へfallbackせず、[公式公開告知](https://www.kotsu.city.sendai.jp/bus_news/gtfs-jp_gtfs_data/)が示す[ODPTカタログの20261006リソース](https://ckan.odpt.org/dataset/sendai_municipal_bus_realtime_information/resource/d4aac294-ea89-4c00-b655-af5ffc3fb0f6)を確認した。原HTMLにはキー不要の `api-public.odpt.org` と認証用 `api.odpt.org` の両取得URLがある。前者の**明示された版付きURL**を選び、認証失敗時の自動切替にはしていない。

取得URLは `https://api-public.odpt.org/api/v4/files/odpt/SendaiMunicipal/bus_realtime_information.zip?date=20261006`。3,087,453 bytes、SHA-256 **`53a08400776b3229743b24eb53566eb523b354a5b783dcfffd3e40f39258e6a2`**。`feed_info.txt` の発行者は仙台市交通局、版 **`20261007_20261130`**、期間 **2026-10-07〜11-30**。calendarも同期間、10月12日等の祝日例外あり。従来カタログ説明文の「2025年10月7日〜25日」との矛盾は、内部データを確認して区別した。版名・説明文だけで運行日を認定しない。GTFSの2,149 stops・8,231 trips・215,949 stop timesを厳密Adapterで読み込んだ。ライセンスはカタログ記載のCC BY 4.0。原ZIP・manifestはローカル検証用に保存し、リポジトリには限定した原行subsetと出典・SHA・抽出条件を記録する。

`SendaiGtfsManifest` はschema 2を必須化。原ZIPを `sendai_gtfs_source.zip` として保持し、原ZIP SHA・全入力member SHA・抽出済みbytes・完全な入力一覧・calendar期間・feed_info期間/版を検査する。Dataset版は日付だけでなく原ZIP SHAとした。schema 1を自動昇格しない。既存の未公開仙台bundleは、原ZIP付きで明示再取得が必要である。`fetch_sendai_gtfs.py --source-url --expected-sha256` は明示URLだけを使用し、失敗時に別版/hostへ再試行しない。東京のloader・runtimeには影響しない。

### 11.2 荒井駅の方向別接続と認定境界

公式の[令和8年4月のりば案内](https://www.kotsu.city.sendai.jp/shibus/noriba/arai/)と[駅情報](https://www.kotsu.city.sendai.jp/subway/station/list/arai/)、現掲載の構内図を確認した。

| 根拠原本 | SHA-256 | 確認内容 |
| --- | --- | --- |
| `https://www.kotsu.city.sendai.jp/assets/img/shibus/noriba/arai/arai_r0204.jpg` | `d8f98e5bbace5cfe2b9e589fec9b37ff75ad47158ec706d20223949e95511ff1` | 2番のりばと南2出入口の配置 |
| `https://www.kotsu.city.sendai.jp/assets/img/subway/station/arai/T13_arai_24.pdf` | `737a9f9f31897ebc2f49e74ae04bf5eb10bc6299fb1886b430f7c18fe53568e2` | 南2出入口・改札・ホームの動線。数値所要時間の記載とは扱わない |
| `https://www.kotsu.city.sendai.jp/assets/img/subway/station/arai/13arai.pdf` | `c62a0590d0d78a139750a621357d1e79e6a78a0f68370eebdba122b107c7c539` | 駅周辺/出入口の補助根拠 |
| `https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r0804-4_kasuminome.pdf` | `2b7191d3cc03de50f93ea4bfb3da9766abd8a86ccf624baf9b5c2290e64493e8` | 20/R20の全経路・起終点・経由地。若林区内の荒井〜新浜〜荒浜小学校の経路をレビュー |

GTFSの `5181_11` は `platform_code=2` の出発用。`5181_0` は同駅の到着用具体停留所で、20/R20の降車位置・座標を公式図の南側ロータリー西側と照合した。親停留所や同名だけで同一化しない。到着用→南2→改札→地下鉄ホームと、地下鉄ホーム→改札→南2→2番のりばを別レコードに固定した。駅代表KML座標から歩行距離・所要時間を生成していない。

**バス乗換5分＋余裕2分は、両方とも今回の検証用計画仮定**である。地下鉄間の公式5分をバスにも適用したという意味ではない。2019年等の古い数値を現行認定へ転用していない。`time_basis=experimental_planning_assumption`、距離不明、実測false、接続保証falseで返す。独立した方向別時間レビューや実用精度検証が済むまでは、正式な公開用標準時間に採用しない。`accept_experimental_transfer_model=true` が無ければ検索を受け付けない。地下鉄間の公式標準5分＋実験用余裕2分とは型/結果/UIで区別する。未知の物理歩行距離上限・バリアフリー時間も保証しない。

無料範囲は20/R20の完全な2停車pattern・46具体便・690 stop times・25具体停留所と、既存レビューに固定した地下鉄2線に限定する。具体便集合・全停車順・名前・feed版をレビューJSONへ固定した。全走行区間が市内であるという公式路線図のレビューを使い、端点座標だけで無料認定しない。それ以外の市営系統も自動で追加せず、宮城交通も未対応。ふれあい乗車証の有効な所持を利用者が明示選択する前提であり、敬老乗車証や通常運賃を無料へ変更しない。

### 11.3 共通v2・時計・独立oracle

`sendai_practical_network.py` は複数feedを同じ民生日付anchorへ明示配置し、検索前の無料scope・有限日付・方向別接続を一つの `build_transit_network -> search_network -> transit_search_labels.search_labels` に渡す。前営業日24時台、当日、検索期間が必要とする翌日をすべて検査する。バス日付の明示レビューを地下鉄w/h分類とは別に要求し、exception-only GTFSも扱う。原GTFS秒は整数日offsetを正しく加減して復元し、地下鉄は公式分時計/到着代理値のprovenanceを保持する。別都市の探索ループ・frontier・順位は追加していない。既存core・枝刈り・guard・候補順位は変更していない。

`tests/sendai_municipal_oracle.py` は原GTFSのcalendar/calendar_dates/時刻/乗降条件と原CP932行から独立に乗降位置を列挙し、有限boarding数で最早到着を比較する。Adapter・Dataset calendar・共通graph・本番探索本体は最適値の算出に呼ばない。witnessも具体便、営業日、停車occurrence、公式発車、到着代理値、乗換ready、無料許可patternを独立検査する。

| 固定query（2026-10-16） | 出発 | 到着予定/目安 | 交通 |
| --- | --- | --- | --- |
| 荒浜小学校前 `5099_10` → 荒井駅到着用 `5181_0` | 11:00 | 11:51（GTFS予定） | バス |
| 地下鉄 仙台→荒井 | 10:00 | 10:19（公開時計の代理値） | 地下鉄 |
| 荒浜小学校前→地下鉄 仙台 | 11:00 | 12:14（目安） | バス→地下鉄 |
| 地下鉄 仙台→荒浜小学校前 `5099_0` | 10:00 | 10:58（GTFS予定を含むモデル） | 地下鉄→バス |

固定後の不一致・探索上限・必要交通不在は停止し、別ODへ差し替えない。通常ログはカテゴリ・mode・試行・理由のみで、実ID/経路を出さない。`scripts/check_sendai_practical_local.py` は原ZIP/manifestとsubset抽出の一致も検証し、入力SHA・source main SHAを前後検査する。既存合格済み監査を呼ばない。上表は新規の実データモデル比較であり、実到着精度・実際の接続・都市全query・真のtop-kの認定ではない。

### 11.4 テスト専用API・Flutter

`app/sendai_practical_routes.py` は明示注入されたnetwork/parametersと `environment=test` だけを受ける独立factory。既存 `app_factory`・公開 `/route`・都市runtimeへ登録していない。serializerは `sendai_practical_route_v1` で、東京の契約とは別。公式分発車、地下鉄到着目安、GTFS予定発着、公式地下鉄間標準、バス乗換仮定、追加余裕、追加支払0円、通常運賃不明、所持前提、未対応区間/日付/RTを区別する。非整数分の原GTFS秒も分数と表示時計で保持し、無印に切り捨てない。

Flutterの型・service・検証用pageと `lib/main_sendai_practical.dart` を追加。対応する具体停留所/駅から出発地・目的地・有限対応日・時刻を利用者が選択し、パスと仮設定を明示選択して検索できる。通常運賃の保存設定・既存city profile・公開navigationには接続していない。bus未搭載capabilitiesなら市バス未対応と表示する。失敗時の別endpoint再試行はない。日本語の検証用画面であり、公開向け多言語化・通常navigationへの組込み・一般住所からのアクセス歩行は未対応である。

### 11.5 v1削除と残した依存

対象一覧と参照元を会話で先に提示したうえで、以下を削除した。

| 削除対象 | 変更前参照と理由 |
| --- | --- |
| `api/transit_engine.py` | 共通接続層と複数テスト。必要なDTOのみ `transit_search_dto.py` に分離し、v1探索・旧limits・protocol・互換入口は削除 |
| `api/search_core_factory.py`・`api/rust_transit_search_core.py` | v1 selector/shadow/parity専用。都市runtimeは既に非依存 |
| `api/native/transit_search_core/` のCargo.lock/Cargo.toml/README/pyprojectとsrcのindex/lib/model/reconstruct/search | v1の分単位native参照探索。factory・wrapper・専用CI・旧imageビルドだけが参照。東京v2とは非依存 |
| `api/tests/test_search_core_factory.py`・golden内Rust/v1比較・旧diagnostics専用テスト | 削除実装専用。元のgolden入力・adapter検証・共通v2契約と独立oracle検証を保持 |
| `api/benchmarks/route_search.py` | v1 Python/Rust/shadow専用。corpus・結果・過去READMEは歴史資料として保持 |
| `scripts/set_route_search_core.ps1` | 旧v1 selectorの本番設定更新専用。代替設定や新しい切替scriptは作らない |

`transit_schedule_oracle.py` は小さなadapter fixture向けの新しい独立有限列挙であり、旧探索を移設したものではない。production importは無い。残る現役DTO依存は `transit_network_core.py`・`gtfs_route_backend.py`。東京の接続層/共通v2・制度/公式データ検証・RT配信・元fixture/歴史証拠は残す。既存の名前・app IDは変更しない。

CIのRust専用2jobをPython3.11/3.12の共通v2委譲・独立Sendai回帰へ置換し、image内の共通本体import同一性も検査する。Dockerfileは不要native build/installだけを削除し、Lambda基底/Python版/依存/handlerを維持。deploy scriptは未公開都市に残る旧selectorを明示拒否するpreflightへ整理しただけで、設定値の書込み・deployを実行していない。東京のruntime・順位・API・本番設定は変更しない。

### 11.6 検証結果・未認定項目

新規混在回帰・manifest改変負例・明示public取得/単一source/SHA負例・原秒直列化・テストAPIを検査する。Windowsと共通v2のPython両版CIへ新規moduleを組み込む。Flutterでは専用型・明示pass request・エラー伝播・未対応表示/未選択停止を検査する。実装commitは `0d48b71fb180931f8f755ea65ef80e7eef628208`。読み取り専用実データゲートはローカルsource `c4be364415d020134955e53a4d5c9b7959ccdfec` で固定4件すべてが成功し、`READ_ONLY_SENDAI_PRACTICAL_MUNICIPAL_MODEL_OK` を確認した。canonical実装commitとの変更対象全blob一致・native/v1削除・別Dart差分の非混入も検査した。入力17ファイルの前後SHA検査とmain/source変更検査が成功した。実データを読み込んだ独立テストAPIでも、ASGI TestClientを介した4カテゴリすべてが同じ到着/0円を返し、`TEST_ASGI_REAL_SOURCE_FIXED_FOUR_OK` を確認した。これは実機Flutterからの通し操作やネットワーク越し実測ではない。

新規混在moduleの12回帰が成功。休日のGTFS例外・具体便・時計/metadata・free scope・方向別接続欠落・元探索エラー伝播・test API拒否・ZIP/member/manifest改変・明示public source/不一致SHAを含む。24時台バスと30秒時計の追加ケースは**合成**であり、実在する深夜20系統の認定ではない。既存分欄の丸め契約と原秒を区別したinputを作り、共通v2が原秒・営業日を保持することを独立raw oracleで確認した。

最初のCI [38836542633](https://github.com/kaeruko/tobus_go/actions/runs/38836542633) は新規FlutterテストのUTF-8指定漏れとScrollable finderの曖昧性で停止した。`bc1202512439d571d99c5ba31394ec7f75c22403` はそのテスト2点だけの修正で、探索・serializer・gate・実入力は変更していない。最終CI [38836806011](https://github.com/kaeruko/tobus_go/actions/runs/38836806011) はhead **`bc1202512439d571d99c5ba31394ec7f75c22403`**、`completed/success`、**全7 job成功**。Linux API **984件**、Windows probe **277件**、共通v2 Python3.11/3.12 **各95件**が成功。新規混在12件・v1不存在/DTO分離回帰・Flutter新規4件のokをログで確認した。Flutter analyze/test・Android全4flavor、iOS全4flavor・identity/ATS/privacy/Firebase分離も成功。不要nativeを除いたLambda image buildと、image内の東京/共通v2探索関数同一性smokeも成功し、deployではない。

最後の結果/手順追記は文書だけの `[skip ci]` commitとし、成功済みCIや実データ監査を再起動しない。CIが認定するsource SHAは上記bc12025であり、文書commitを新たな実運行認定に使わない。一般住所/実機操作・実測歩行/到着精度・正式な乗換余裕・公開配信準備は今回の成功から自動認定しない。

既存第1〜第4段階の実データ監査、112組照合、バス36ケースは再実行しない。今回の認定は原データに基づく限定した予定時刻モデルであり、実測到着・方向別乗換精度・余裕の正式採用・全バリアフリー動線・全市営系統・宮城交通・全特別日・SearchCoreの都市全体完全性/top-kは引き続き未認定。公開API切替・本番deploy・S3変更・ストア提出は実施していない。

### 11.7 ローカル再現方法（公開版への切替ではない）

以下は新しい検証環境を構成する場合の例。上記成功済みゲートを無条件に再実行する指示ではない。日付対応は有限の2026-10-11〜18で、前営業日/翌日を要するqueryはその日もレビューが必要。現行保証・無期限の有効期限として表示しない。既存の古いフォルダへ上書きしない。

```powershell
# リポジトリroot。必要ならこの明示版を新しい保存先へ取得する。
python -B scripts/fetch_sendai_gtfs.py `
  --output api/data/sendai/20261006_model `
  --expected-service-date 2026-10-16 `
  --source-url 'https://api-public.odpt.org/api/v4/files/odpt/SendaiMunicipal/bus_realtime_information.zip?date=20261006' `
  --expected-sha256 53a08400776b3229743b24eb53566eb523b354a5b783dcfffd3e40f39258e6a2
if ($LASTEXITCODE -ne 0) { throw 'Sendai official data preparation failed' }

# localhostだけにbindする別テストサービス。既存server.handlerは変更しない。
python -B scripts/serve_sendai_practical_local.py `
  --bus-gtfs-dir api/data/sendai/20261006_model `
  --expected-service-date 2026-10-16 `
  --subway-published api/tests/fixtures/sendai_subway/published_20230701.json `
  --subway-review api/tests/fixtures/sendai_subway/practical_review_20261016.json `
  --municipal-review api/tests/fixtures/sendai_subway/municipal_review_20261016.json `
  --accept-experimental-transfer-model
```

別ターミナルで、明示したテストentry pointを起動する。Chromeのlocalhost originだけをこのテストAPIのCORSで許可し、本番CORS設定は変更しない。

```powershell
flutter run -d chrome -t lib/main_sendai_practical.dart `
  --dart-define=SENDAI_TEST_API_BASE=http://127.0.0.1:8000
```

例えば出発「仙台（東西線）」=`sendai_subway:tozai/仙台`、目的「震災遺構仙台市立荒浜小学校前」=`sendai_bus:5099_0`、対応日2026-10-16、10:00、ふれあい乗車証と仮設定を明示選択すると、表の地下鉄→バス経路が対象となる。停留所suffixで自動接続しているという意味ではなく、これらは固定レビューにある具体IDの選択例である。

読み取り専用ゲートを別環境で再現する必要がある場合は、同じ明示bundleを次のCLIへ渡す。`$sendaiModelSha` は実行するmainの**full SHA**を確認して設定する。CLIはmain/SHA/APIとscriptの未commit変更/入力SHAを検査し、pull・stash・reset・fetch・書込みをしない。Python3.11/3.12・必要依存の整った環境を使い、例外時に別Python/backend/sourceへ自動変更しない。

```powershell
$sendaiModelSha = (git rev-parse HEAD).Trim()
python -B scripts/check_sendai_practical_local.py `
  --bus-gtfs-dir api/data/sendai/20261006_model `
  --expected-service-date 2026-10-16 `
  --subway-published api/tests/fixtures/sendai_subway/published_20230701.json `
  --subway-review api/tests/fixtures/sendai_subway/practical_review_20261016.json `
  --municipal-review api/tests/fixtures/sendai_subway/municipal_review_20261016.json `
  --bus-subset api/tests/fixtures/sendai_subway/municipal_bus_subset_20261006.json `
  --cases api/tests/fixtures/sendai_subway/municipal_fixed_cases_20261016.json `
  --expected-sha $sendaiModelSha `
  --accept-experimental-transfer-model
if ($LASTEXITCODE -ne 0) { throw 'Sendai model gate failed; do not use partial results' }
```

## 12. 2都市構成への整理（2026-10-16）

東京と仙台以外の未公開都市は開発中止し専用コード・資産を削除した。仙台のruntime、GTFS、実用地下鉄Adapter、ふれあいPolicy、原資料・SHA・独立oracle・固定ケースは変更していない。削除依存の移設と検証結果は [2都市整理記録](two-city-cleanup.md) を参照。

## 13. 21系統2地域・泉中央接続・有限通常期間の第1段拡張（2026-10-16）

### 13.1 開始状態・範囲の固定

基準mainは `02e5373de371449cb9ac9e4690cbe4698f590ed8`、通常CI `38866337246` は7job成功、Chrome実データの旧4経路は `38862101398` で成功済み。作業開始・反映前にmain/未マージPR/実行中CIを確認し、変更前SHAをleaseとしてmainへ反映する。旧112組照合・第1〜4段階・36ケース監査は呼ばない。

原ZIP・schema2 manifest・公式版 `20261007_20261130` と第11節のSHAを再利用する。新規候補抽出は `66fce43c` / Actions `38869814470` で成功。原資料の追加SHA取得は `4a082ea2` / Actions `38889687119` で成功。同じ短縮系統番号が複数地域にあるため、番号だけで無料scopeを広げない。

| 対象 | exact route ID | 完全pattern | 具体便 | 採用根拠 |
| --- | --- | ---: | ---: | --- |
| 既存・荒井20/R20 | 10033 / 10255 | 2 | 46 | 既存の霞の目全経路レビューを保持 |
| 荒井21 | 10039 | 2 | 14 | 荒井〜七郷小学校〜神屋敷北〜南長沼〜荒浜小学校、霞の目公式図の若林区内全走行経路 |
| 泉中央21 | 10038 | 2 | 18 | 実沢営業所〜泉ビレジ〜芦沢〜実沢〜野村〜泉中央、実沢公式図の泉区内全走行経路 |

第1段は合計78便・6完全pattern・1,336 stop times・74具体停留所。既存25具体停留所から49を追加する（同名の別poleを統合しない）。市外を含む便の市内部分を切り出す変更は今回不要なので、全隣接区間をレビューしたwhole-run契約を維持する。未知のpattern・同番号の別route・別版の便を自動追加しない。

`municipal_bus_subset_20261006_stage1.json` は4個のexact route IDから原行を選択した追加テスト資料。運行用データの代替ではない。旧subset/review/固定4queryは保持する。新reviewは `municipal_review_20261016_stage1.json`。raw oracleは同一route IDの複数patternを全停車順と具体trip集合で区別するよう修正した（テスト専用。共通探索・枝刈り・guard・順位は未変更）。

### 13.2 泉中央の独立した方向別接続

現掲載の[泉中央のりば図](https://www.kotsu.city.sendai.jp/assets/img/shibus/noriba/izumichuo/izumityuuou_h3004.jpg)はSHA `8a4625fef1bc5a8a414cb88f2e3a42c23ee8d12aaccee0fc6c7c76508516fc69`。ページは令和8年4月改正の案内である。ファイル名にある年を所要時間の根拠にしない。[現掲載構内図](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/09/N01_izumityuuou_25.pdf)はSHA `c5144217169ad2b230686a3eac8225a213c221a6130ca619c1470614ad63a1e5`。全走行経路の[実沢公式図](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r0804-7_sanezawa.pdf)はSHA `1ff06f172c09b6ef8c67c95ace6713799043d076d86b11316c56279a10cdf62d`。

- ホーム→改札→東1出入口→市営2番のりばは `sendai_bus:1085_12`（platform_code=2）へ固定する。
- 到着用 `sendai_bus:1085_0` →東1出入口→改札→ホームは別レコードにする。到着用poleの座標・usageを図の降車位置と照合し、出発用poleや親停留所と同一化しない。

泉中央は**8分＋余裕2分を明示した新しい検証用計画仮定**とする。公式の数値所要時間・方向別実測・物理距離・バリアフリー・接続保証は認定しない。8分は地下鉄間の公式5分を流用した値ではない。荒井の既存2方向5分＋2分はレコードごと保持する。全バス接続は明示した実験モデル選択を要求する。

### 13.3 通常運行日を規則から有限生成

`OperatingPeriodReview` は確認日・公式URL/SHA・祝日一覧・明示除外・通常モデルの限界を保存し、既存 `FiniteOperatingDays` を生成する。バスのactive serviceはGTFS calendar/calendar_datesから決まり、地下鉄w/h分類を流用しない。暗黙の無期限延長・古いfeedへの切替はしない。

内部coverageは **2026-10-11〜11-01**、検索日候補は **10-12〜10-31**。この期間の公式祝日は10/12。10/25は[駅伝に伴う市バス変更](https://www.kotsu.city.sendai.jp/daigaku-jyoshiekiden/)（原HTML SHA `8426ac412c8e2c6bb2dcab43be1350010af105771bc03df9754e7397547984f9`）の便別差分を未認定のため、バス側のレビュー対象から除外する。地下鉄の10/25分類は通常土休日モデルのままで、バスの除外を地下鉄の運行休止へ読み替えない。

APIの候補日は合計19日。10/24深夜・10/26の前営業日を必要とする00時台など、必要な日付に10/25を含むqueryも理由付き422で停止する。一方、10/24・26の日中まで一律に除外しない。日付一覧を全時刻・全ODの検索保証に使わず、その説明をFlutterにも表示する。通常便への将来の運休/変更を全て検知するライブ通知モデルではない。

期間拡張により地下鉄版は `f4cc1bf90b18dea7a214aca5e2da3e9ce9588793cb091d1eef36326db5480c82` へ変わり、無料scopeと接続を同じ版へ固定する。CLIの `--use-reviewed-operating-period` を明示選択した場合だけ適用し、旧レビューのロードを自動切替しない。GTFS取得承認日2026-10-16と各query営業日は別である。

### 13.4 新規の固定実経路と画面入口

新しい固定queryは元GTFS/CP932時計から先に確定し、後から別ODや上限へ差し替えない。`municipal_fixed_cases_20261016_stage1.json` は max_candidates=1・max_boardings=3・max_travel_minutes=180 を固定する。

| 新規query | 出発条件 | 到着予定/目安 | 交通 |
| --- | --- | --- | --- |
| 荒井→荒浜小学校（21必須） | 10/16 07:00 | 07:22 | バス |
| 荒浜小学校→地下鉄仙台（21必須） | 10/12 08:20 | 09:07 | バス→東西線 |
| 地下鉄仙台→荒浜小学校（21必須） | 10/17 07:30 | 08:11 | 東西線→バス |
| 実沢営業所→泉中央 | 10/19 09:00 | 09:30 | バス |
| 実沢営業所→地下鉄仙台 | 10/19 09:00 | 10:00 | バス→南北線 |
| 地下鉄仙台→実沢営業所 | 10/19 08:20 | 09:36 | 南北線→バス |
| 実沢営業所→地下鉄荒井 | 10/19 09:00 | 10:27 | バス→南北線→東西線 |

原行subsetの新規Python回帰と、新7queryの独立oracle・完全witness・ASGI比較を追加した。期間付きレビューでは、除外日とreviewed_daysの矛盾・日付の重複・実GTFS全体coverage外の延長・ロード済み地下鉄日付表との不一致も停止する。これは原ZIP全体を使う新ゲートやChromeの成功を代用しない。新workflowは原ZIP/manifest/member SHA・subset原行一致を再利用し、新7経路だけを検証してから新3queryを実Flutter/Chromeで操作する。旧112組・36ケース・第1〜4段階ゲートは実行しない。共有API/UIの変更に伴う既定の旧4query Chrome workflowはGitHub側で自動起動するが、成功済みrunの手動再実行は指示しない。

通常の仙台検索画面に、debug buildかつ明示 `SENDAI_TEST_API_BASE` がある場合だけ開発用入口を追加した。東京・release build・未設定時には入口が出ない。既存の検証画面/テストAPIを利用し、通常運賃の保存設定、公開 `/route`、都市runtimeの公開選択は切り替えない。一般住所のアクセス徒歩、多言語化、実機/公開配信、本番RTとの混在は未完了である。

宮城交通・その他の市営pattern/接続・11月以降の追加検索期間・全特別ダイヤ・4乗車を必要とする両端バスの全市経路・全query完全性/真のtop-k・到着/接続/バリアフリーの実測保証は今回の範囲外。ふれあい乗車証の有効な所持を明示選択する前提を保持し、敬老乗車証や通常運賃不明を無料へ変換しない。本番deploy・AWS/S3・ストア操作は行わない。

### 13.5 追加された具体停留所

荒井21は既存の具体停留所集合で経由と便を追加する。泉中央21で以下の26名称・49具体IDを追加する。表のIDはGTFSの `stop_id` であり、検索APIでは `sendai_bus:` を前置する。到着専用・出発専用や乗降禁止は原 `stop_times` のまま扱うため、表の全IDで任意の乗降ができるという意味ではない。

| 名称 | 追加したstop_id |
| --- | --- |
| 泉中央駅 | `1085_0`, `1085_12` |
| 泉中央駅北口 | `1093_10` |
| 泉区役所・イズミティ２１前 | `1091_50` |
| 菅間 | `1095_10`, `1095_50` |
| 朴木沢 | `1099_10`, `1099_50` |
| 泉総合運動場・社会福祉センター前 | `1103_10`, `1103_50` |
| 野村 | `1107_10`, `1107_50` |
| 上野前 | `1109_10`, `1109_50` |
| 泉パークタウン入口 | `1111_10`, `1111_50` |
| 八沢川 | `1113_10`, `1113_50` |
| 実沢 | `1115_10`, `1115_50` |
| 小角 | `1117_10`, `1117_50` |
| 鼻毛橋 | `1119_10`, `1119_50` |
| 窪 | `1121_11`, `1121_51` |
| 芦沢 | `1315_10`, `1315_11` |
| 泉ビレジ一丁目南 | `9182_10`, `9182_50` |
| 泉ビレジ一丁目西 | `9183_10`, `9183_50` |
| 泉ビレジ一丁目 | `9185_10`, `9185_50` |
| 泉ビレジ二丁目 | `9189_10`, `9189_50` |
| 泉ビレジ三丁目 | `9191_10`, `9191_50` |
| 泉ビレジ五丁目 | `9193_10`, `9193_50` |
| 泉ビレジ四丁目 | `9195_10`, `9195_50` |
| 水泉荘前 | `9251_10`, `9251_50` |
| 道祖神 | `9252_10`, `9252_50` |
| 二ノ関屋敷 | `9253_10` |
| 市営バス実沢営業所前 | `9260_0`, `9260_10` |

### 13.6 第1段の起動方法

第11.7節の明示版・SHAで準備済みのデータを再利用する。新reviewと期間オプションを明示して起動する。旧4経路用reviewからの自動切替はない。

```powershell
python -B scripts/serve_sendai_practical_local.py `
  --bus-gtfs-dir api/data/sendai/20261006_model `
  --expected-service-date 2026-10-16 `
  --subway-published api/tests/fixtures/sendai_subway/published_20230701.json `
  --subway-review api/tests/fixtures/sendai_subway/practical_review_20261016.json `
  --municipal-review api/tests/fixtures/sendai_subway/municipal_review_20261016_stage1.json `
  --use-reviewed-operating-period `
  --accept-experimental-transfer-model
```

別ターミナルの専用entryは第11.7節と同じ。通常の仙台画面から検証入口を開く場合はdebugで以下を使う（本番API切替ではない）。

```powershell
flutter run -d chrome -t lib/main.dart `
  --dart-define=APP_CITY=sendai `
  --dart-define=SENDAI_TEST_API_BASE=http://127.0.0.1:8000
```

### 13.7 次の優先順

1. **既存拠点に接続できる高頻度の市内完結patternを追加する。** 今回の原GTFS棚卸しを再利用し、同じ泉中央または荒井の具体poleを使う便を先に選ぶ。次に主要地下鉄駅と仙台駅の市営のりばを候補にする。route番号でなく完全stop順・trip集合・全隣接区間の制度対象をレビューし、追加patternごとに新しい具体queryとraw oracleを追加する。既存の成功済み監査一式を再実行する前提にしない。
2. **通常期間を次の有限区間へ更新する。** 原feedの有効期間内で、既存公開地下鉄時計・内閣府祝日一覧・公式運行変更を確認し、未確認の例外だけを明示除外する。まず11月の祝日と既知の臨時変更を扱い、10/25は影響便の具体差分を確認してから再開する。日付単位の実地調査や暗黙の自動延長は要求しない。
3. **公開画面への本接続を準備する。** debug入口での実機確認、対応範囲と期限を保つcapabilities契約、一般住所からの徒歩アクセス、多言語表示、公開用API登録と運用を順に整理する。現段階の限定対象を全市対応と表示せず、本番切替・配信は別の明示作業とする。

市境をまたぐ便を追加する段階では、無料な連続区間を具体trip・営業日・停車occurrenceで許可する設計を検討する。同じ便の途中を別便のように乗り直す辺へ変換せず、既存の具体便連続性と未知運賃を保持する。今回の市内完結pattern追加のために共通探索を変更する必要はない。4乗車や順位変更は、それを必要とする固定queryと具体的な欠落を先に示してから別単位で検討する。

### 13.8 実装・検証の証拠

実装sourceは **`b8a95f67e76776b49e3e9cd7e31813b1ea65d652`**。棚卸し `66fce43c`、有限期間 `4a082ea2`、路線・乗換・画面入口 `cb305338`、期間整合検査 `e1d68592`、Chromeのlazy menu finder修正 `b8a95f67` に分けた。変更23ファイルに共通探索本体・枝刈り・候補順位、東京の公開API、アプリID、Firebase、本番deploy設定の変更はない。

新規workflow [38892415460](https://github.com/kaeruko/tobus_go/actions/runs/38892415460) は上記sourceで **completed/success**。新規Python **29件**、承認済み原ZIP/schema2 manifest/member SHAとsubset原行の一致、新7queryの独立raw oracle・具体便witness・ASGI比較が成功し、`READ_ONLY_SENDAI_STAGE1_NEW_SEVEN_OK` を確認した。同じrunの実Flutter/Chrome UIで、荒井21単独・実沢営業所→地下鉄仙台・地下鉄仙台→実沢営業所の**3query**が成功し、`All tests passed.` を確認した。

最初の新Chrome run [38891145432](https://github.com/kaeruko/tobus_go/actions/runs/38891145432) は再選択中のdate keyがfieldとmenuに重複して停止した。次の [38891669348](https://github.com/kaeruko/tobus_go/actions/runs/38891669348) は `.last` が未生成のlazy itemへ適用されて停止した。最終版では開いているmenu配下へFinderを限定し、未生成の0件状態を保ってスクロールする。経路・日付・上限・source/backendを差し替えて成功させていない。

旧固定4queryの既定Chrome workflow [38891669456](https://github.com/kaeruko/tobus_go/actions/runs/38891669456) も `e1d68592` で **completed/success**。この後のコード差分は新ChromeテストのFinderだけで、旧4query・API・bundle・Flutter画面のblobは同一である。成功済み監査の手動再実行ではなく、共有ファイル変更によるGitHubの自動回帰である。

最終コードの通常CIではPython API **852件**、Windows回帰 **277件**、共通v2 Python3.11/3.12 **各89件**が成功した。Flutter analyze/testでは、通常画面の開発用入口が都市・debug・明示endpointで制限される新規2件も成功した。通常運賃・乗車証設定の自動変更、公開runtime切替、AWS/S3操作、ストア提出、本番deployは行っていない。

通常CI [38892415423](https://github.com/kaeruko/tobus_go/actions/runs/38892415423) は同じ **`b8a95f67e76776b49e3e9cd7e31813b1ea65d652`** で **completed/success・全7job成功**。Flutter解析/テスト、東京・仙台のAndroid/iOS両flavor、iOS identity/privacy/ATS/Firebase分離、repository safety、共通v2の両Python版、Windows、APIを確認した。Lambda imageのbuild/import検査も成功したがdeployではない。

最後は結果・停留所一覧・起動方法・残課題だけの文書commit（`[skip ci]`）で記録する。CIと実データ/Chromeの認定source SHAは上記b8a95f67であり、文書commitを新しいコード検証や実運行保証に読み替えない。作業終了前にもmain/未マージPRを確認し、他の変更を上書きしていない。

## 14. 泉中央〜住吉台20系統の第2段拡張（2026-10-16）

### 14.1 再利用した成果と今回の追加範囲

開始mainは `eb9a535ccdaee180ee73c38da98da8f278dbce7f`。第13節のCI全7jobと新規7経路/Chrome3経路成功を確認し、未マージPR・進行中run・mainの追加変更がない状態で開始した。前回の棚卸し原行、公式GTFS-JP `20261007_20261130`、ZIP/member SHAとschema2 manifest、原地下鉄時計、有限通常期間、方向別泉中央乗換を再利用する。

追加するのは **route ID `10030`、20系統の泉中央〜住吉台西三丁目**。荒井20（10033）や、同じ短縮名20の10032/10034とは別の具体routeである。原棚卸しから2完全pattern・119具体便を選び、全26停車順と[令和8年4月実沢公式図](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r0804-7_sanezawa.pdf)（SHA `1ff06f172c09b6ef8c67c95ace6713799043d076d86b11316c56279a10cdf62d`）の住吉台〜芦沢〜実沢〜野村〜泉中央の全走行経路を確認した。市内完結のwhole-run許可を追加し、便を分割したり同番号の未確認routeを許可したりしない。

| 方向 | GTFS上の具体便合計 | 平日 | 土曜 | 日祝 | 完全停車数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 住吉台西三丁目→泉中央 | 61 | 29 | 17 | 15 | 26 |
| 泉中央→住吉台西三丁目 | 58 | 25 | 18 | 15 | 26 |

119は平日/土曜/休日テンプレートの合計であり、1日119便ではない。10/12のスポーツの日はGTFS例外により平日サービスを止め、休日サービスを使う。新モデル全体は**197具体便・8完全pattern・4,430 stop times・99具体停留所**。前段の74停留所から25具体IDを追加した。

| 追加した停留所名称 | 追加stop_id（APIでは `sendai_bus:` を前置） |
| --- | --- |
| 住吉台西二丁目 | `1293_10`, `1293_50` |
| 住吉台西三丁目 | `1294_0`, `1294_10` |
| 住吉台西四丁目 | `1295_10`, `1295_50` |
| 住吉台東三丁目 | `1296_10`, `1296_50` |
| 住吉台東四丁目 | `1297_10`, `1297_50` |
| 住吉台東五丁目 | `1298_10`, `1298_50` |
| 住吉台東二丁目 | `1299_10`, `1299_50` |
| 住吉台中央 | `1305_11`, `1305_51` |
| 住吉台一丁目 | `1307_10`, `1307_50` |
| 住吉台入口 | `1309_10`, `1309_50` |
| 萱場 | `1311_10`, `1311_50` |
| 大満寺前 | `1313_10`, `1313_50` |
| 芦沢（名称は既存。新しい具体pole） | `1315_50` |

### 14.2 接続・日付・画面の扱い

泉中央到着は既存 `1085_0`、出発は既存2番 `1085_12` であり、第13節の独立した2方向の8分＋余裕2分をそのまま使う。新たな乗換値や逆方向自動生成は追加しない。荒井の既存5分＋2分、地下鉄間の公式標準＋仮の余裕も維持する。

内部coverage 10/11〜11/1、検索候補10/12〜10/31の19日、10/25除外と日付境界の停止条件は第13節と同一である。今回11月の検索候補は追加していない。`municipal_review_20261016_stage2.json` を明示指定した場合のみ新scopeをロードし、stage1/旧4経路用reviewを自動変更しない。`stage_profile=sendai_municipal_stage2` を明示許可するだけで、期間整合検査は前段と同じものを使う。

第13.6節のserverコマンドの `--municipal-review` を **`api/tests/fixtures/sendai_subway/municipal_review_20261016_stage2.json`** へ明示変更して起動する。他のsource/版/SHA/引数は同じである。Flutterは既存capabilitiesを読み込み、新しい対象名と具体停留所を表示する。既存のdebug＋明示endpointの入口から使用でき、公開API・通常運賃設定・releaseのnavigationは切り替えない。通常運賃不明は不明のまま、有効ふれあい乗車証所持を明示選択した場合の追加支払0円だけを扱う。

### 14.3 先に固定した新規6経路

原GTFSと保持済みCP932地下鉄時計を用い、実装探索を呼ぶ前に次の期待値を固定した。max_candidates=1、max_boardings=3、max_travel_minutes=180は前段と同一。到着はGTFS予定・地下鉄到着代理値・仮の乗換モデルに基づく目安であり、実到着や接続保証ではない。

| 経路（いずれも10030必須） | 出発条件 | 到着予定/目安 | 交通 |
| --- | --- | --- | --- |
| 住吉台西三丁目→泉中央 | 10/19 09:00 | 09:49 | バス |
| 住吉台西三丁目→地下鉄仙台 | 10/19 09:00 | 10:16 | バス→南北線 |
| 地下鉄仙台→住吉台西三丁目 | 10/19 08:20 | 09:57 | 南北線→バス |
| 住吉台西三丁目→地下鉄荒井 | 10/19 09:00 | 10:43 | バス→南北線→東西線 |
| 住吉台西三丁目→泉中央（祝日） | 10/12 09:00 | 10:09 | バス |
| 泉中央→住吉台西三丁目（土曜） | 10/17 09:00 | 10:23 | バス |

原行subsetは `municipal_bus_subset_20261006_stage2.json`、固定期待は `municipal_fixed_cases_20261016_stage2.json`。ゲートは明示 `--profile stage2` でこの組だけを読み、別profileへ再試行しない。実運用入力は従来どおり検証済み原ZIPであり、subsetを代用しない。共通SearchCore v2・枝刈り・候補順位は変更しない。

次の優先事項は第13.7節の有限期間更新と既存拠点の追加路線、主要地下鉄駅/仙台駅の方向別接続、公開画面への本接続である。宮城交通、未確認の同番号route、他系統、11月以降の検索候補、全特別ダイヤ、住所アクセス徒歩、実測乗換、全市の全queryは未対応/未認定のまま。本番deploy・AWS/S3・アプリID・Firebase・ストア操作は行わない。

### 14.4 実装と検証の証拠（2026-10-17）

実装sourceは **`3d88bfbd69e76342637d8982e38b378d46ef5376`**。変更9ファイルのうち、運行モデルのローダー変更は明示stage2 profileの許可1行だけである。対象scopeと完全patternは別reviewへ追加し、旧review/固定queryは保持した。共通探索・順位・東京公開API・通常画面の本番設定・native ID・Firebase・deploy設定は変更していない。

追加module `tests.test_sendai_stage2` は**7件成功**。新6固定queryの独立raw最適値・完全witness・ASGIと直列化の具体便/停車順/通常運賃不明、拡張後bundle上での前段7queryの期待値維持、119便・平土日祝の全pattern、片方向reviewの非伝播、便集合/全停車順の改変拒否、合成の未承認同番号20 routeの拒否、既存接続/期間/除外日の等値とcapabilitiesの追加範囲を確認した。旧監査一式を起動したものではない。

共有loader変更で自動起動した旧4query Chrome [38979986810](https://github.com/kaeruko/tobus_go/actions/runs/38979986810) は上記sourceで **completed/success**。保持済みの固定4queryを変更せず、実Flutter UIから同じ結果を確認した。成功済みrunの手動再実行はしていない。

第2段workflow [38979986784](https://github.com/kaeruko/tobus_go/actions/runs/38979986784) は同じsourceで **completed/success**。新規Python7件、指定原ZIP・schema2 manifest・member SHAと新subsetの原行一致、新6queryの独立raw oracle・全具体便witness・ASGI比較が成功し、`READ_ONLY_SENDAI_STAGE2_NEW_SIX_OK` を確認した。続けて実Flutter/Chromeで住吉台→泉中央、住吉台→地下鉄仙台、地下鉄仙台→住吉台の**3query**が固定期待どおり成功し、`All tests passed.` を確認した。

通常CIのPython API **859件**、Windows回帰 **277件**、共通v2 Python3.11/3.12 **各89件**が成功した。今回の7件を加えたAPI回帰は成功しており、旧112組・第1〜第4段階・36ケース監査を新たに起動したものではない。

通常CI [38979986752](https://github.com/kaeruko/tobus_go/actions/runs/38979986752) は **`3d88bfbd69e76342637d8982e38b378d46ef5376`** で **completed/success・全7job成功**。Flutter解析/テスト、東京・仙台のAndroid/iOS両flavor、iOS identity/privacy/ATS/Firebase分離、repository safety、API、Windows、共通v2の両Python版、Lambda imageのbuild/import検査が成功した。Lambda imageの検査はdeployではない。

最後の反映は、この結果記録だけの文書commit（`[skip ci]`）とする。CI・原ZIP6経路・Chrome3経路の認定sourceは上記3d88bfbdであり、文書commitを追加のコード検証や実運行保証として扱わない。反映直前にもmainと未マージPRを確認し、他の変更を上書きしていない。次の作業は、公式祝日/変更案内を使う11月の有限期間更新と追加路線の選定から進める。

## 15. 2026年11月有限通常期間・通常画面内フォーム（2026-10-17）

開始main `357fbeb5d00bf4e30fc87c8c7a78b0166db87ad9`、成功済みsource `3d88bfbd69e76342637d8982e38b378d46ef5376`。作業開始時に未マージPR0件、実行中CI0件を確認した。第13〜14節の公式バスZIP/member SHA・地下鉄8原CSV/112組・接続・全197便/8pattern・旧固定queryと成功済み監査を再利用し、再監査や共通探索の変更をしない。

新規 `municipal_review_20261017_stage3.json` を**明示的に**指定した場合だけ、原GTFS-JP `20261007_20261130` 内の2026-10-11〜11-30の有限日付表、利用者選択2026-10-12〜11-30を扱う。土曜/日曜と11/3「文化の日」・11/23「勤労感謝の日」の地下鉄w/hは内閣府2026年一覧（従来retained SHA `565ed19991424566812ce202196adc2a5f7932d9e607940ce28df76456413e43`）で決め、バスは独立したGTFS `calendar.txt` と `calendar_dates.txt` の11/3・11/23例外を使う。旧review、旧fixture、stage2の固定期待は保持する。

10/25の全日本大学女子駅伝による市バス便別影響未認定は従来どおりバス日付から除外する。**11/22（日）クイーンズ駅伝2026**は宮城県が2026-10-09に交通規制と路線バス一部運休・迂回を告知（https://www.pref.miyagi.jp/soshiki/sports/queens_roadrace/2026_queens_roadrace.html）。便別差分と原HTML SHAを未保持のため、11/22を**共通の検証用通常日付モデル全体**から保守的に除外する。これは地下鉄が運休するとの認定ではない。新告知のSHAを捏造して証拠欄へ入れない。stage3の内部バス日付49日、検索候補48日。候補日であっても当該OD/時刻の完全な運行保証を意味しない。

**11/30が原バスGTFSの末日**。当日日中で必要な営業日が11/30以前なら検索し、最長180分の探索で12/1を必要とする深夜条件は未認定として422停止する。12/1への暗黙拡張・別feed fallbackはしない。公式の臨時運行更新は自動反映されないため実運行・到着・接続は保証しない。

既存の `SendaiPracticalTestPage` に `embedded` を設け、仙台debugかつ明示 `SENDAI_TEST_API_BASE` でだけ通常の検索画面からフォームを**展開**できるようにする。出発地・目的地・日付・時刻・有効ふれあい乗車証の明示選択・乗換仮設定、検索・目安結果を従来と同じテストAPIで表示する。従来の検証ページへの入口も維持する。Release/Tokyo/未指定URLでは入口は表示しない。一般住所・宮城交通・未確認路線は追加せず、通常 `/route` や利用者設定・東京・native ID・Firebase・AWS/S3・deploy・storeも変更しない。

原ZIPを使う新専用CIの `--profile stage3` はstage2と同じ検証済みZIPとschema2 manifestを使い、新しい11月7ケース（平日バス、バス＋地下鉄、地下鉄→バス、2地下鉄、祝日、土曜、地下鉄単独）だけを原行oracle・具体便・APIと照合する。既存4経路と住吉台方面の回帰は通常CIに保持し、Chromeは11月の選択・検索を実画面で検査する。成功が確定する前にCI結果を記載しない。

### 15.1 実装と実データ検証の確定結果

コード・テストの最終認定sourceは **`c95ce0d1c0a1a8ec691dc64a0ab1ac5346324e98`**。第13・14節の197便・8pattern/99具体停留所、検証済み接続、公式GTFS-JP版とmanifestを保持した。第15節の新しいreviewの対象日だけを明示拡張し、共通SearchCore v2・東京API・本番release設定・アプリID・Firebase・AWS/S3・公開deployは変更していない。

[11月専用CI `38985954491`](https://github.com/kaeruko/tobus_go/actions/runs/38985954491) はこのsourceで **completed/success**。新しいPython `tests.test_sendai_stage3` **3件**、承認済み原ZIP/schema2 manifest/member SHAとstage2 subset原行、7件の独立rawオラクル・具体trip witness・ASGI APIが成功し、`READ_ONLY_SENDAI_STAGE3_NOVEMBER_OK` を確認した。独立rawとの照合結果は以下（すべて2026年、出発・到着は計画値、接続/実到着の保証ではない）。

| 検索日 | 原行で固定したOD | 出発条件 | 到着目安 | 利用モード |
| --- | --- | --- | --- | --- |
| 11/19 | 住吉台西三丁目→泉中央駅 | 09:00 | 09:49 | 市営バス |
| 11/19 | 住吉台西三丁目→地下鉄仙台 | 09:00 | 10:16 | 市営バス＋南北線 |
| 11/19 | 地下鉄仙台→住吉台西三丁目 | 08:20 | 09:57 | 南北線＋市営バス |
| 11/19 | 住吉台西三丁目→地下鉄荒井 | 09:00 | 10:43 | 市営バス＋南北線＋東西線 |
| 11/03 | 住吉台西三丁目→泉中央駅（祝日） | 09:00 | 10:09 | 市営バス |
| 11/21 | 泉中央駅→住吉台西三丁目（土曜） | 09:00 | 10:23 | 市営バス |
| 11/19 | 地下鉄仙台→泉中央駅 | 09:00 | 09:20 | 南北線 |

同じrunの実Flutter/Chromeは**6件**（上表の2地下鉄線を使う3乗車経路以外）を、元GTFSから起動したlocalhost APIで選択・検索し、`All tests passed.` を確認。48候補日、10/25・11/22除外、11/03・11/23休日サービス、11/30日中の可否と12/01依存の拒否は新規Pythonテストが確認した。元GTFSをテスト用subsetへ差し替えたり、テストに都合の良いOD・APIや時刻を変更していない。

[通常CI `38985954613`](https://github.com/kaeruko/tobus_go/actions/runs/38985954613) は同じ `c95ce0d1` で **completed/success・全7job成功**。Python API **862件**、Windows回帰 **277件**、共通SearchCore v2のPython 3.11/3.12 **各89件**、Flutterテスト **659件**が成功した。Flutter解析はジョブの既存判定条件で成功し、解析出力には非致命的なissueが97件ある（0件とは扱わない）。東京・仙台Android両flavor、iOS両flavorとidentity/privacy/ATS/Firebase分離、repository safety、Lambda image build/import検査も成功。本番デプロイは一切行っていない。

旧4経路の独立Flutter/Chrome回帰も [`38984747227`](https://github.com/kaeruko/tobus_go/actions/runs/38984747227) で成功。そこからの変更は新規11月テストとフォームエラーテキストに対応するテストのみであり、旧4経路の入力・期待到着値・backendは保持されている。途中のChrome失敗は、直接日付入力後の候補タップ位置、非同期HTTP待ち、ListView遅延描画を原因別に診断し、無関係な経路やデータへ切り替えず最終成功とした。

公開対応の残課題は、宮城交通・未認定市営pattern/駅接続、一般住所からのアクセス徒歩、本番で使える正式な乗換時間、全特別ダイヤの便別影響、12/01以降の新feed/日付レビュー、実端末と多言語・通常公開検索APIへの本接続。11/22の保守的な全検証モデル除外は地下鉄の運休を意味しない。11/30深夜も翌日の未確認サービスへ拡張しない。

この最終反映は、成功の根拠を固定する文書のみの `[skip ci]` commitとする。後続の文書SHAをコードの新しい合格証拠として扱わず、上記 `c95ce0d1` とrun IDに結び付ける。

## 16. 第4段・泉中央30循環と荒井R18の路線網拡張（2026-10-17）

### 16.1 引継ぎと既存拠点への実便数による選定

開始mainは `7ec90ac9c230c46b7d63aca05151406552108054`、検証済みsource `c95ce0d1`、通常CI `38985954613` 全7job成功・11月CI `38985954491` 成功を確認。未マージPR・他の進行中CI/変更は無かった。第13.7〜15節に沿ってreviewへ路線を追加する継続開発であり、共通探索・Adapter・日付処理・無料scope・既存接続・API・フォームを再実装しない。

20/21中心の既存棚卸しを保持し、同じ承認済み原GTFS-JP `20261007_20261130` とschema2 manifest・ZIP/member SHA検証を使って、既存の具体hub poleを通る未承認路線を追加集計した。原ZIP SHAは従来の `53a08400776b3229743b24eb53566eb523b354a5b783dcfffd3e40f39258e6a2`。単なる系統番号や路線全体の便数ではなく、**実際に既存のりばを通る具体便数**で評価した。

| 候補・exact route ID | 11/19平日 | 11/21土曜 | 11/23祝日 | 今回の扱い |
| --- | ---: | ---: | ---: | --- |
| 泉中央30 `10061` | 21 | 12 | 11 | 南吉成・吉成・川平・加茂へ広がる循環便を追加 |
| 荒井R18 `10254` | 15 | 13 | 12 | 堀切・新浜・岡田・陸前高砂方面からの到着便を追加 |
| 荒井15 `10019` | 13 | 8 | 8 | 次候補。今回の無料scopeへ含めない |
| 荒井16 `10022` | 12 | 7 | 7 | 次候補。今回の無料scopeへ含めない |
| 薬師堂70 `10116` | 1 | 0 | 0 | 路線全体は23/5/5便だが既存hub経由はこの数 |
| 長町南77 `10137` | 4 | 0 | 0 | 低頻度かつ新拠点接続が必要なため今回は見送る |
| 仙台駅前207 `10037` | 1 | 0 | 0 | 低頻度かつ新拠点接続が必要なため今回は見送る |

### 16.2 追加した完全pattern・無料範囲・方向別接続

| exact route ID | 対応経路 | 完全pattern | GTFS上の具体便合計 | 完全停車数 |
| --- | --- | ---: | ---: | --- |
| `10061`・30 | 泉中央1番→上谷刈→加茂→川平→国見ケ丘→吉成→南吉成循環→泉中央到着用pole | 1 | 44 | 43 |
| `10254`・R18 | 堀切→新浜→岡田→六丁の目→荒井 | 1 | 37 | 25 |
| `10254`・R18 | 陸前高砂→白鳥→上屋倉→堀切→新浜→岡田→荒井 | 1 | 3 | 33 |

追加は**84具体便・3完全pattern・73具体停留所ID（54新名称）**。平土休日テンプレートを足した84であり1日84便ではない。市営バス全体は**281具体便・11完全pattern・7,346 stop times・172具体停留所ID**となる。30は実沢公式図、R18は霞の目公式図の全走行経路と全停車順を確認し、泉区・青葉区、宮城野区・若林区にそれぞれまたがる仙台市内完結のwhole-run許可を追加した。既存のmap evidence URL/SHAを再利用し、新しい数値根拠を捏造しない。

循環30の「吉成一丁目」やR18長patternの「上屋倉」は同名の複数occurrenceを残し、具体tripと順序を保持する。循環便を途中で分割しない。R18は荒井方向のみの承認で、未確認の逆方向18や同番号の別routeを自動承認しない。JR仙石線は追加していない。

30の出発は `sendai_bus:1085_11`、GTFS `platform_code=1`。現掲載泉中央のりば図の東1出入口→1番のりばを確認し、既存のホーム〜改札〜東1動線に接続した**出発方向1レコードだけ**を追加する。8分＋余裕2分はこの接続にも明示採用する検証用計画仮定で、実測・公式数値・正式認定・接続保証ではない。逆方向は生成せず、到着は従来の `1085_0`→地下鉄接続を使う。既存泉中央2番・荒井の方向別レコードは一切書き換えない。

### 16.3 追加した具体停留所と既存フォーム

以下は前段99停留所に対する73追加ID。APIでは `sendai_bus:` を前置する。同名のpole・経由順を統合せず、乗降可否も元stop_timesのまま扱う。

| 停留所名称 | 追加stop_id |
| --- | --- |
| 上屋倉 | `4069_10`, `4069_51` |
| 上岡田 | `4045_10` |
| 上谷刈一丁目 | `1253_10`, `1253_50` |
| 上谷刈一丁目東 | `1251_10`, `1251_50` |
| 上谷刈三丁目 | `1255_10`, `1255_50` |
| 上谷刈二丁目 | `1254_10`, `1254_50` |
| 上谷刈山添 | `1247_10`, `1247_50` |
| 中野新町 | `9509_50` |
| 八乙女駅入口 | `1250_10`, `1250_50` |
| 六丁の目南町 | `4029_50` |
| 加茂二丁目南 | `1256_10`, `1256_50` |
| 加茂四丁目南 | `1245_10`, `1245_50` |
| 北環状線・南中山一丁目 | `9242_10`, `9242_50` |
| 南吉成一丁目 | `8031_10` |
| 南吉成三丁目 | `8035_10` |
| 南吉成二丁目 | `8033_10` |
| 南吉成五丁目 | `8039_11` |
| 南吉成四丁目 | `8037_10` |
| 南吉成小学校前 | `8027_11` |
| 卸町東五丁目北 | `4039_10` |
| 卸町東四丁目 | `5187_50` |
| 吉成一丁目 | `8023_51`, `8023_52` |
| 吉成一丁目北 | `8029_10`, `8029_51` |
| 吉成二丁目 | `8025_11` |
| 国見ケ丘一丁目北 | `8075_10`, `8075_50` |
| 堀切 | `4055_11` |
| 岡田 | `4053_10` |
| 岡田西町 | `4042_11` |
| 岡田郵便局前 | `4073_10` |
| 川平団地 | `9421_11`, `9421_12` |
| 川平市営住宅前 | `9423_10`, `9423_50` |
| 川平市営住宅東 | `9425_10`, `9425_50` |
| 新浜 | `4059_10` |
| 新浜浦通 | `4063_10` |
| 新浜西 | `4057_10` |
| 東北医科薬科大学病院入口 | `9501_50` |
| 東部工場団地 | `4219_10` |
| 泉中央駅 | `1085_11` |
| 泉警察署前 | `1081_10`, `1081_50` |
| 泉館山高校入口 | `9426_10`, `9426_50` |
| 照徳寺前 | `4061_10` |
| 狐塚 | `4041_10` |
| 白鳥一丁目・軽自動車検査協会前 | `9504_50` |
| 白鳥二丁目 | `9505_50` |
| 白鳥二丁目東 | `3159_50` |
| 若林体育館前 | `4217_10` |
| 荒井五丁目 | `5185_50` |
| 蒲生小田切 | `4065_10` |
| 賀茂皇大神社前 | `4043_10` |
| 道場 | `4049_10` |
| 鍋沼 | `4067_10` |
| 長屋前 | `4047_10` |
| 陸前高砂駅 | `3025_50` |
| 雑子袋 | `4071_10` |
| 高砂二丁目 | `9503_50` |

新reviewは `municipal_review_20261017_stage4.json`、原行subsetは `municipal_bus_subset_20261006_stage4.json`。起動は第13.6節の同じserverコマンドで `--municipal-review api/tests/fixtures/sendai_subway/municipal_review_20261017_stage4.json` を明示指定し、`--use-reviewed-operating-period --accept-experimental-transfer-model` を維持する。旧reviewからの暗黙切替はない。

Flutterは第15節の通常画面内フォーム・従来の検証ページとcapabilitiesをそのまま使い、新しい具体停留所と対象labelを選択表示する。フォームの再設計や別APIは追加しない。Chromeは通常画面が利用する既存Launcherの埋込みフォームを展開し、実localhost APIで新5経路を検査する（住所・地図を含むアプリ全体の実機認定ではない）。

運行期間・地下鉄版・既存接続・10/25と11/22の除外は第15節と同一。48候補日・11/30末日を維持し、12/1や除外日を必要とする条件は422停止する。有効ふれあい乗車証の所持を明示選択する前提、追加支払0円と通常運賃不明の区別を保持する。敬老乗車証を無料化しない。

### 16.4 新規変更部分の固定経路

既存raw oracleを使い、実装探索を呼ぶ前に原GTFS/保持済み地下鉄時計から以下の8期待値を固定した。前段のqueryや期待値を書き換えず、max_candidates=1・max_boardings=3・max_travel_minutes=180を維持する。到着は予定時刻と仮の接続に基づく目安であり実運行保証ではない。

| 経路 | 検索条件 | 到着目安 | 交通 |
| --- | --- | --- | --- |
| 南吉成三丁目→泉中央 | 11/19 09:00 | 09:49 | バス30 |
| 南吉成三丁目→地下鉄仙台 | 11/19 09:00 | 10:16 | バス30→南北線 |
| 地下鉄仙台→南吉成三丁目 | 11/19 08:20 | 09:26 | 南北線→バス30 |
| 堀切→荒井 | 11/19 09:00 | 09:56 | バスR18 |
| 堀切→地下鉄仙台 | 11/19 09:00 | 10:19 | バスR18→東西線 |
| 陸前高砂→地下鉄仙台 | 11/19 10:00 | 11:14 | バスR18長pattern→東西線 |
| 南吉成三丁目→泉中央（祝日） | 11/23 09:00 | 09:34 | バス30 |
| 堀切→地下鉄仙台（土曜） | 11/21 09:00 | 09:55 | バスR18→東西線 |

`tests.test_sendai_stage4` の新規8回帰はローカルで成功した。既存raw oracle・ASGI gateを再利用し、全具体便witness・平土休日・同名occurrence・未知routeの非承認・改変拒否・追加bay接続の必要性・R18逆方向の非生成・前段reviewと有限日付の保持を検査する。既存112組や第1〜第4段階の公式監査、過去全経路の独立検証を再起動しない。Actionsの確定結果は成功後に追記する。

残課題は、今回見送った15/16等の市内完結路線、仙台駅・長町等の公式資料に基づく方向別接続、未確認特別ダイヤの便別影響、12/1以降の新feedレビュー、正式な乗換時間・実端末の確認。宮城交通・一般住所・全路線一括・公開APIへの本接続は今回の対象外。本番API・公開release・東京・アプリID・Firebase・AWS/S3・deploy・storeは変更しない。

### 16.5 実装・検証結果の記録

棚卸しは `73efe295`、既存hubを実際に通る便数と原行順を保持する修正は `61cd8356`、路線追加本体は **`6dd937ff0463b9d2c599e5729c916f5395810e9d`**。本体の変更はreview/fixture/新規回帰・E2Eと既存workflow/gate、明示stage4 profileのローダー許可1行である。共通探索・Adapter・運行日モデル・無料scope判定本体・既存接続レコード・製品UIのコードは変更していない。

最初の専用run [38988585508](https://github.com/kaeruko/tobus_go/actions/runs/38988585508) は、新規Python8件、元ZIP/member SHA・subset原行一致、新8経路の独立oracle・具体便witness・ASGIまで成功し、`READ_ONLY_SENDAI_STAGE4_NEW_EIGHT_OK` を確認した。その後Chromeが2件目の地下鉄仙台メニュー選択で旧160回のスクロール上限に達し停止した。

**`7203b371a6b5119c6fe0b2b509ccbb32d39f82ee`** は新規Chromeテスト1ファイルだけの修正。64pxの独立dragにはtouch slopがあるため、メニューの実scroll extentから有限な操作回数を算出し、元の例外・stackにextent/budgetの診断を付けた。経路・時刻・期待値・探索上限・API・backend・元データを変更していない。

既存4経路のChrome [38988585437](https://github.com/kaeruko/tobus_go/actions/runs/38988585437) は `6dd937ff` で成功。以後のコード差分は新規Chromeテストだけであり、旧4経路・既存フォーム・API・reviewのblobは同じである。共有loader変更によるGitHubの自動回帰であり、成功済みrunの手動再実行ではない。

最終の第4段CI [38989081577](https://github.com/kaeruko/tobus_go/actions/runs/38989081577) は **`7203b371a6b5119c6fe0b2b509ccbb32d39f82ee`** で **completed/success**。新規Python8件、承認済み原ZIP/schema2 manifest/member SHAとsubset全原行順一致、新8経路の独立raw最適値・具体便witness・ASGI比較が成功し、`READ_ONLY_SENDAI_STAGE4_NEW_EIGHT_OK` を確認した。同じ元GTFSから起動したlocalhostサービスを使い、既存Launcherの埋込みフォームをChromeで展開して新5経路を選択・検索し、固定目安値と泉中央1番の出発接続表示が成功、`All tests passed.` を確認した。テスト成功のために元データやqueryを変更していない。

通常CI [38989081576](https://github.com/kaeruko/tobus_go/actions/runs/38989081576) も同じ **`7203b371`** で **completed/success・全7job成功**。API **870件**、Windows回帰 **277件**、共通SearchCore v2のPython3.11/3.12 **各89件**、Flutter **659件**が成功した。Flutter解析は既存ジョブ判定条件で成功し、非致命的な指摘は従来と同じ97件であり0件とは扱わない。東京・仙台のAndroid/iOS両flavor、iOS identity/privacy/ATS/Firebase分離、repository safety、Lambda image build/import検査も成功した。本番deployではない。

終了時にもmain/未マージPRを確認した。最後の反映は、この確定結果だけの文書commit（`[skip ci]`）とし、検証済みコードは上記7203b371とrun IDに固定する。後続の文書SHAをコードの新しい検証や実運行認定へ読み替えず、成功済みの監査・CIを文書追記のために再起動しない。

## 17. 第5段：荒井15・鶴巻循環の既存ネットワークへの追加（2026-10-17）

### 17.1 継続範囲と対象選定

開始mainは `7723edbc15e5172c106586804c7ddd867e71ef89`。第16節の成功済みコード `7203b371`、通常CI38989081576・専用CI38989081577を引き継いだ。開始時の未マージPR・進行中CIはなし。新しい全体設計・共通探索・枝刈り・候補順位・Adapter・運行日モデル・無料scopeエンジン・製品Flutter UIを作り直さない。

第16節の確定棚卸しを再利用した。既に追加した30（平日21便）・R18（15便）の次に、既存荒井hubを通る15（13便）、16（12便）が位置する。15は29具体便・1完全patternで、前段で承認ZIPから原行順のまま保持した `10019` の原行があり、whole-runによる市内完結確認と既存到着用接続を利用できる。16より平日便数が多く、鶴巻・福田町・宮城運輸支局方面を既存沿岸・泉中央方面に加えられるため今回15を追加した。過去の全路線棚卸しや旧全経路監査を再起動していない。

正確なroute IDは **`10019`**（APIでは `sendai_bus:10019`）、短縮番号15。荒井1番 `5181_10` →若林体育館3番 `4217_11` →宮城県印刷会館→宮城運輸支局→扇町→福田町→鶴巻 `4253_10` →岡田西町→東部工場団地→若林体育館1番 `4217_10` →荒井到着用 `5181_0` の25停車完全循環。29便は平日 `O_20_1` 13便、土曜 `O_20_2` 8便、休日 `O_20_3` 8便。系統番号15の他route、逆循環16、途中で分割した仮想便を承認しない。同名の若林体育館等の具体poleと停車順・乗降制約を保持する。

追加は **29具体便・1完全pattern・725 stop_times・14具体停留所ID**。累計 **310具体便・12完全pattern・8071 stop_times・186具体バス停ID**、地下鉄2線。元データは既承認 `20261007_20261130`、ZIP SHA `53a08400776b3229743b24eb53566eb523b354a5b783dcfffd3e40f39258e6a2` と同じmanifest/member SHAのまま。新fixture `municipal_bus_subset_20261006_stage5.json` は既存deriveで元原行順を保持し、稼働サービスはfixtureへのfallbackではなく原GTFSとmanifestを使用する。

### 17.2 全走行経路と方向別接続の根拠

霞の目公式系統図の15の全走行経路（宮城運輸支局→鶴巻→狐塚の循環方向）を全25停車と照合した。若林区・宮城野区内で完結し、市外区間を端点だけから推測しない。第16節で保持済みの同一公式図を利用し、今回の新経路と新のりばのみ確認する。

| 公式資料 | SHA256／確認範囲 |
| --- | --- |
| [令和8年4月霞の目系統図](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r0804-4_kasuminome.pdf) | `2b7191d3cc03de50f93ea4bfb3da9766abd8a86ccf624baf9b5c2290e64493e8`・15の完全循環 |
| [荒井駅現掲載のりば案内](https://www.kotsu.city.sendai.jp/shibus/noriba/arai/) | 15/16は1番。番号以外に原GTFS具体pole・完全patternを照合 |
| [荒井のりば図](https://www.kotsu.city.sendai.jp/assets/img/shibus/noriba/arai/arai_r0204.jpg) | `d8f98e5bbace5cfe2b9e589fec9b37ff75ad47158ec706d20223949e95511ff1`・南側ロータリー東側1番と中央1の位置 |
| [荒井駅構内図](https://www.kotsu.city.sendai.jp/assets/img/subway/station/arai/T13_arai_24.pdf) | `737a9f9f31897ebc2f49e74ae04bf5eb10bc6299fb1886b430f7c18fe53568e2`・ホーム→改札→中央1動線 |

3ファイルは今回も同じURLの原bytesと保持SHAの一致を確認し、図を目視した。新しい接続は **`sendai_subway:tozai/荒井` → `sendai_bus:5181_10`** のみ。GTFS platform_code=1、公式のりば1に対応し、ホーム→改札→中央1出入口→1番とする。既存の到着用 `5181_0` →地下鉄（南2）、地下鉄→2番 `5181_11`（南2）、泉中央各接続はレコードごと同一で保持する。逆向きの5181_10→地下鉄を自動生成しない。

新接続には独立に **仮の乗換5分＋仮の余裕2分** を採用した。図上の出発動線を確認した検証用計画仮定であり、既存2番と無条件に同一視した値、公式所要時間、実測、正式認定、バリアフリー所要時間、実運行の接続保証ではない。既存API/UIの `experimental_planning_assumption` 表示と利用者の明示同意を利用する。

新1番接続を外しても、旧2番バス→共通の荒井六丁目 `5183_10` →後続15という正当な3乗車経路が11:54着で残る。09:55着の新2乗車経路との差119分をraw oracleでも確認する。最初の回帰で「全く経路なし」とした検証仮説は誤りだったため、query・探索上限・データは変えず、rawと実装が同じ11:54着になる検証へ修正した。探索本体を変更して経路を抑止しない。

### 17.3 追加停留所と固定検証条件

以下は前段172 IDに対する14追加ID（APIでは `sendai_bus:` を前置）。15全25停車のうち残り11 IDは既承認の具体poleを共有する。

| 停留所 | 新stop_id |
| --- | --- |
| 六丁の目南町 | `4029_10` |
| 宮城運輸支局前 | `4123_50` |
| 扇町四丁目 | `4125_50` |
| 食肉市場入口 | `4127_50` |
| 福田町四丁目北 | `4129_50` |
| 福田町四丁目 | `4131_50` |
| 福田町三丁目 | `4133_50` |
| 鶴巻保育所前 | `4135_50` |
| 若林体育館前 | `4217_11` |
| 鶴巻 | `4253_10` |
| 荒井駅1番 | `5181_10` |
| 荒井五丁目 | `5185_10` |
| 卸町東四丁目 | `5187_10` |
| 宮城県印刷会館前 | `5189_10` |

以下の期待値を既存raw oracleで先に確定した。max_candidates=1・max_boardings=3・max_travel_minutes=180を維持する。地下鉄の公開時計は到着proxyであり、時刻は仮の接続を含む予定目安である。

| 新規経路 | 検索日・時刻 | 到着目安 |
| --- | --- | --- |
| 荒井1番→鶴巻（バス15） | 11/19 09:00 | 09:55 |
| 鶴巻保育所前→地下鉄仙台（15→東西線） | 11/19 09:00 | 09:39 |
| 地下鉄仙台→鶴巻（東西線→1番15） | 11/19 09:00 | 09:55 |
| 荒井1番→鶴巻（土曜） | 11/21 09:00 | 11:08 |
| 鶴巻保育所前→地下鉄仙台（祝日） | 11/23 09:00 | 09:39 |
| 地下鉄仙台→鶴巻（末日） | 11/30 09:00 | 09:55 |

新reviewは `municipal_review_20261017_stage5.json`。第13.6節の同じserverコマンドで、このファイルを `--municipal-review` へ明示指定し、既存の `--use-reviewed-operating-period --accept-experimental-transfer-model` を維持する。旧reviewを暗黙切替しない。通常画面の既存debug埋込みフォーム・検証ページはcapabilitiesから新しい具体停留所を表示するため製品UI変更は不要。新Chromeは同じLauncher埋込みフォームで上の最初3経路と中央1・1番の仮の乗換表示を検証する。全アプリ・一般住所・実端末の認定ではない。

検索期間48候補日・2026年11月30日まで、10/25・11/22除外、12/1以降や末日23:00から翌日を必要とする検索の422停止を維持する。有効ふれあい乗車証を本人が所持して明示選択する前提、通常運賃不明と追加支払0円の区別も同じ。敬老乗車証は無料化しない。

### 17.4 検証結果と残課題

新規 `tests.test_sendai_stage5` は既存raw oracle・ASGI比較、平土休日の29具体便、完全循環・乗降制約、旧review/接続/日付の保持、1番の方向と接続除去時の原データ期待、改変拒否、同番号・同全停車順の未知route非承認、186/14停留所・有限期間の境界を検証する。専用Actionsは承認元ZIP/member SHA・subset原行順、新6経路、実GTFSから起動したlocalhost APIと既存Flutter埋込みフォームの新3経路を対象とする。通常CIの回帰も実行する。確定SHA・CI成功結果は完了後に追記する。

残課題は16逆循環等の次の市内完結路線、仙台駅・長町の公式方向別接続、未確認特別ダイヤの便別影響、12/1以降の新feedレビュー、正式乗換時間と実端末確認。宮城交通・一般住所・全路線一括・本番公開への接続は未対応のまま。本番API・東京公開機能・release・アプリID・Firebase・AWS/S3・deploy・storeは変更しない。

### 17.5 確定コードと成功CI

路線追加コードは **`a34c7e05c2ffb9bf8dc3d9c4b4db03825cfd45c9`**。第5段専用CI [39016735110](https://github.com/kaeruko/tobus_go/actions/runs/39016735110) は同SHAで **completed/success**。新規Python7件（28.920秒）、承認元ZIP・schema2 manifest・member SHAとsubset全原行順一致、新6経路の独立raw最適値・全具体便witness・ASGI比較が成功し、`READ_ONLY_SENDAI_STAGE5_NEW_SIX_OK` を確認した。同じ原GTFSから起動したlocalhost APIを使うChromeでは、既存Launcherの埋込みフォームから新3経路を選択・検索し、09:55／09:39／09:55の固定到着目安と、仮の5分＋2分・中央1出入口・市営1番のりば表示が成功、`All tests passed.`（08:22:11 UTC）を確認した。失敗時に別経路・別日付・別backendへ切り替える処理は追加していない。

通常CI [39016735104](https://github.com/kaeruko/tobus_go/actions/runs/39016735104) は同SHAで **completed/success・全7job成功**。API **877件**、Windows **277件**、共通SearchCore v2 Python3.11/3.12 **各89件**、Flutter **659件**が成功した。解析は既存CI条件で成功し、従来の非致命的指摘97件は残る。東京・仙台のAndroid/iOS両flavorとiOS identity/privacy/ATS/Firebase分離、repository safety、Lambda image build/import検査が成功した。公開・deployではない。

既存固定4経路のChrome [39016735119](https://github.com/kaeruko/tobus_go/actions/runs/39016735119) も同SHAで **completed/success**、`All tests passed.`（08:19:00 UTC）。共通loaderの明示stage5許可1行に伴う自動回帰であり、過去の成功runを手動再実行したものではない。共通SearchCore v2の探索・枝刈り・候補順位、Adapter・運行日モデル・無料判定本体、既存各接続、製品Flutterコードは変更していない。

終了時に最新mainと未マージPRを再確認し、確定結果追記はこのコードを親とする文書だけの `[skip ci]` commitに分離する。文書追記で成功済みCIを再起動せず、後続文書SHAを新しいコード検証や正式な実運行認定として扱わない。

## 18. 第6段：荒井16（鶴巻逆循環）を既存荒井hubに追加（2026-10-17）

### 18.1 開始状態・差分対象・出典

開始main `5c9c8caaae1187059890d9b8267e5645a9f6ac91`。第17節の第5段コード `a34c7e05c2ffb9bf8dc3d9c4b4db03825cfd45c9` と成功済み通常CI `39016735104`、市営stage5 CI `39016735110`、旧4経路Chrome `39016735119` を確認。開始時の未マージPR0・実行中CIなし。前段の設計や全データ監査を再実施せず、候補棚卸し `scripts/inspect_sendai_stage4.py` と同じ**公式GTFS・schema2 manifest/member SHA**だけを用いる。

対象は荒井16（鶴巻逆循環）・正確なroute ID `sendai_bus:10022`、短縮番号「16」。同番号の泉地区別routeや15（`10019`）の逆向き仮想便を一切自動承認しない。承認元はODPT仙台市営バスGTFS-JP `20261007_20261130`、元ZIP SHA256 `53a08400776b3229743b24eb53566eb523b354a5b783dcfffd3e40f39258e6a2`、第17節の原manifestおよび原member SHAを維持。新しい `scripts/inspect_sendai_stage6.py` は既承認した8 routeの原行順を再現して変化がないことを確認したうえで、route10022の**全26便/全25停車**を抜き出す。新 `municipal_bus_subset_20261006_stage6.json` には元CSVの正確な原行順で9 routeを保持し、**稼働時にはこのfixtureへfallbackせず原GTFSを利用**する。CIは原ZIP・manifestに対してsubset原行の完全一致をチェックする。

16は1完全pattern、26具体便、650 stop_times。サービスごとの便数は平日`O_20_1`12便、土曜`O_20_2`7便、日祝`O_20_3`7便。第5段310便・12pattern・8071 stop_times・186具体bus stop IDから、**336具体便・13完全pattern・8721 stop_times・201具体停留所ID**へ拡張。追加は**15具体stop ID**（`4039_50`, `4041_50`, `4042_50`, `4123_10`, `4125_10`, `4127_10`, `4129_10`, `4131_10`, `4133_10`, `4135_10`, `4217_50`, `4217_51`, `4219_50`, `4253_50`, `5189_50`）。旧レビューの全310便・全接続・日付はレコード単位で同一。

### 18.2 全走行路線・公式のりば・仮の乗換時間

第17節で保持済みの[令和8年4月霞の目系統図](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r0804-4_kasuminome.pdf)（原bytes SHA256 `2b7191d3cc03de50f93ea4bfb3da9766abd8a86ccf624baf9b5c2290e64493e8`）を方向別に引き継ぐ。荒井駅1番 `5181_10` →荒井六丁目→六丁の目南町→若林体育館前 `4217_50` →東部工場団地→狐塚→岡田西町→鶴巻 `4253_50` →鶴巻保育所前 `4135_10` →福田町→扇町→宮城運輸支局前 `4123_10` →宮城県印刷会館→若林体育館前 `4217_51` →荒井到着用 `5181_0` の完全25停車。市内完結のwhole-runのみを採用する。同名の「鶴巻」でも15側の`4253_10`とは別poleで、既存の若林体育館や全乗降制約も具体IDを維持する。

新しい乗換接続は**0件**。第17節で認定済みの `sendai_subway:tozai/荒井` → `sendai_bus:5181_10`（荒井駅1番、中央1出入口、仮の標準5分＋余裕2分）をそのまま共有する。bus5181_10→地下鉄は生成しない。元の到着5181_0→地下鉄と2番5181_11、泉中央の方向別リンクも保持する。5分＋2分は検証用計画仮定で、公式実測・接続保証・正式余裕時間ではない。

### 18.3 固定原データ経路・新しいテスト

`municipal_fixed_cases_20261017_stage6.json` は従来と同じ最早1候補、最大3乗車、180分、2026-11-30までの**通常運行日のみ**。原GTFS `trips/stop_times/calendar/calendar_dates` と地下鉄CP932原時刻表から独立に算出して、SearchCore v2の出力より前に以下の予定値を固定した。

| 種別・OD | 2026年の検索日・時刻 | 到着目安 |
| --- | --- | --- |
| 16単独：荒井駅1番→鶴巻 | 11/19 09:00 | 09:23 |
| 16単独：鶴巻保育所前→荒井到着用 | 11/19 09:00 | 09:42 |
| 16→地下鉄東西線：宮城運輸支局前→地下鉄仙台 | 11/19 09:00 | 10:03 |
| 地下鉄東西線→16：地下鉄仙台→鶴巻 | 11/19 09:00 | 10:51 |
| 土曜16単独：荒井駅1番→鶴巻 | 11/21 09:00 | 09:59 |
| 祝日16単独：鶴巻保育所前→荒井到着用 | 11/23 09:00 | 10:17 |
| GTFS末日・地下鉄→16：地下鉄仙台→鶴巻 | 11/30 09:00 | 10:51 |

新しい `tests.test_sendai_stage6` **7件**は原行oracle・具体便witness/API、平土祝26便、既存310便と全部の有向接続・日付固定、15/16の方向別pole差、改変拒否、同番号の別routeを拒否、201具体pole、対応外日付を検査する。11/3・11/23祝日サービス、48候補日、10/25と11/22除外、12/1・11/30深夜の未認定境界422停止は変更しない。有効ふれあい乗車証を明示選択する利用者のみ追加支払0円（通常運賃は不明）。

製品の通常Flutter UIは変更しない。既存debug・明示localhostテストAPIの埋込みフォームに16の実stop IDsを追加表示し、`integration_test/sendai_stage6_chrome_test.dart` は上記の平日最初・バス→地下鉄・地下鉄→バスの3固定条件をChrome実操作で検証する。SearchCore v2、Adapter、探索/枝刈り/順位、東京公開機能、東京・仙台ID、AWS/S3、本番deploy、ストア提出は変更しない。

### 18.4 検証根拠・残課題

実装commitは **`fb6d7f1196fc11d9ec8ed923613921ac0a278699`**。専用CI [`39018704442`](https://github.com/kaeruko/tobus_go/actions/runs/39018704442) は同SHAで **completed/success**。新規Python7件、既存の公式ZIP/manifest/member SHAとsubset原行完全一致、7件の原行独立oracle・具体便witness/ASGI照合が成功し、`READ_ONLY_SENDAI_STAGE6_NEW_SEVEN_OK` を確認。同じ元GTFSから起動したlocalhost APIを使うFlutter Chromeの3実経路も `All tests passed.`。既存4経路Chrome [`39018704419`](https://github.com/kaeruko/tobus_go/actions/runs/39018704419) も同SHAで **completed/success**。

通常CIは [`39018704501`](https://github.com/kaeruko/tobus_go/actions/runs/39018704501)（同SHA）。Python API884件、Windows277件、共通SearchCore v2 Python3.11/3.12各89件、Flutter659件、Android東京/仙台、repository safetyが成功した。Flutter解析は既存ゲートで成功・非致命的既存issue97件を保持。**通常CIもcompleted/success・全7ジョブ成功**。東京・仙台のiOS両flavorビルドとiOS identity/privacy/ATS/Firebase分離、両Androidビルド、Python API884件、Windows277件、SearchCore v2 Python3.11/3.12各89件、Flutter659件、repository safetyとLambda image build/import検査の成功を最終確認した。Lambda imageの検査はdeployではない。CI成功認定のSHAはコードcommit `fb6d7f1196fc11d9ec8ed923613921ac0a278699` であり、後続の文書のみ[skip ci]のSHAを新たなコード検証とみなさない。

次の難所は仙台駅・長町などの未レビュー乗換拠点（Astra Proへの別作業）。宮城交通、一般住所、全市営バス対応、他の候補route、特別ダイヤ便別確定、12月以降の新feed、正式な乗換実測と実機検証は未対応。現行の検証用運行・乗換は実運行を保証しない。

## 19. 第7段：仙台駅5・60番と308/J308を共通ネットワークへ追加（2026-10-17）

### 19.1 継承と路線選定

開始mainは `a1b96d6df9e345e2f2bd2b55f88265ff438c0fa5`。第18節のコード `fb6d7f1196fc11d9ec8ed923613921ac0a278699`、通常CI39018704501・stage6実データ39018704442・既存4経路Chrome39018704419の成功を確認した。開始時の未マージPR・進行中CIは0。第6段の336具体便・13完全pattern・201具体bus stop ID、有限期間・全既存接続を引き継ぐ。

仙台駅の方向別接続と市内完結路線を追加する。SearchCore v2の探索・枝刈り・順位、GTFS/地下鉄Adapter、運賃判定本体、Flutterフォームの製品コードは変更しない。loaderは同じ有限期間の明示stage7 profile許可だけを1行追加する。通常画面内の既存debugフォームはcapabilitiesの追加pole・coverage labelを表示する。

承認済み公式GTFS-JP `20261007_20261130`、schema2 manifest/member SHA、ZIP SHA256 `53a08400776b3229743b24eb53566eb523b354a5b783dcfffd3e40f39258e6a2` を利用する。ローカル取得は最初に通信前の `socksio` 不足で停止した。専用仮想環境に不足依存を補い、同じ取得スクリプト・URL・SHA・検証日2026-10-16で取得成功した。別feed・取得日・backendへ切り替えていない。過去の全公式監査は再実行しない。

既存棚卸しの方法で、仙台駅を実際に通る具体便・完全pattern・新規poleを比較した。

| 候補の正確なroute ID | 平日便数 | 完全pattern | 追加pole | 今回の判断 |
| --- | --- | --- | --- | --- |
| `10065` 308 / `10219` J308 | 32 / 31 | 1 / 1 | 44 | 5番・60番の公式のりばが明確。既承認の霞の目図で全走行経路を照合でき、新寺・志波町・卸町・蒲町と病院・定禅寺通を追加できるため採用 |
| `10006` 110 / `10258` S110 | 33 / 33 | 1 / 1 | 54 | 有力な次候補。27番と到着用50_0の新動線、東仙台方面の全走行経路の追加レビューが必要 |
| `10180` 899 / `10195` 999 | 29 / 29 | 1 / 1 | 59 | 9番からの2方向循環。今回の5・60番の次にレビューする候補 |

308は交通局東北大学病院前 `1_12` →定禅寺通→仙台駅5番 `50_850` →新寺→志波町→卸町→蒲町→市営バス霞の目営業所前 `5223_0` の全21停車・92具体便（平32/土30/休日30）。J308は営業所 `5223_11` →遠見塚東→蒲町→卸町→志波町→新寺一丁目→仙台駅60番 `50_210` →広瀬通駅→定禅寺通→病院 `1_0` の全23停車・91具体便（平31/土31/休日29）。同じ系統数字や逆順で合成せず、原route・全trip・停車順・乗降可否を使う。青葉区・宮城野区・若林区内の全走行経路を霞の目公式図で照合し、whole-run無料scopeへ追加した。

追加は **183具体便・2完全pattern・4025 stop_times・44具体bus stop ID**。累計 **519具体便・15完全pattern・12746 stop_times・245具体bus stop ID**、地下鉄2線。新原行fixture `municipal_bus_subset_20261006_stage7.json` は既存deriveで11 routeの元原行順を維持する。前段9 routeの原行と保持fixtureが同一であることも確認した。稼働データは同じ原GTFS・manifestであり、fixtureへのfallbackはない。

### 19.2 公式図と8つの方向別接続

| 資料 | 固定したSHA256と確認範囲 |
| --- | --- |
| [現掲載のりば案内](https://www.kotsu.city.sendai.jp/shibus/noriba/sendai/) | 308は5番、J系統の交通局東北大学病院方面は60番 |
| [仙台駅前のりば図](https://www.kotsu.city.sendai.jp/assets/img/shibus/noriba/sendai/r06_sendaieki.jpg) | `271485553fae3e39e47607782104f6ce1761313c959c313b35ff286eec5eb8f7`・5番は南4、60番はTRビル側・北2と同じ道路西側 |
| [N10現掲載構内図](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/08/N10_sendai_26.pdf) | `42456791bc32e04f183a59097f44d281c6368898282cee34ee7197071f445d56`・南北線B3、南/北改札、南4・北2への動線 |
| [T07現掲載構内図](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/08/T07_sendaieki_26.pdf) | `777a70b4752a1b3d417bc39b96c39142a6da45c5dabe884cdba05196f5b0a690`・東西線B4、B2のりかえ階と改札・出入口への動線 |
| [現掲載駅情報・工事注意](https://www.kotsu.city.sendai.jp/subway/station/list/sendai/) | 取得HTML `9cea74f6b4f9a5e5aa26cc16153789d687e117b0bed3de5d9444fe2f79cf5b8a`・中央2エレベーター停止、北5閉鎖。今回の経路はどちらも利用しない |
| [既承認・令和8年4月霞の目系統図](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r0804-4_kasuminome.pdf) | `2b7191d3cc03de50f93ea4bfb3da9766abd8a86ccf624baf9b5c2290e64493e8`・308/J308の全走行経路 |

駅・のりばの原bytesとSHAを保持し、現掲載N10/T07はPNGへ描画して目視した。GTFS具体poleは5番 `50_850`（38.259327,140.880753）、60番 `50_210`（38.260199,140.879581）。双方とも今回の対象便が途中停車し、原stop_timesのpickup/drop_offは0/0で乗車・降車可能。到着用 `50_0` や他のりばへの同名自動接続は追加しない。

以下の8レコードは全て別々に明示追加する。表の時間は標準時間モデルによる検証用計画仮定であり、公式値・実測・正式認定・バリアフリー所要時間・接続保証ではない。

| 出発→到着 | 出入口・動線 | 仮の標準＋余裕（分） |
| --- | --- | --- |
| 南北線仙台→5番 | B3→南改札→南4→5番 | 10＋2 |
| 5番→南北線仙台 | 5番→南4→南改札→B3 | 9＋2 |
| 東西線仙台→5番 | B4→B2→南改札→南4→5番 | 12＋2 |
| 5番→東西線仙台 | 5番→南4→南改札→B2→B4 | 11＋2 |
| 南北線仙台→60番 | B3→北改札への構内通路→北2→60番 | 13＋2 |
| 60番→南北線仙台 | 60番→北2→北改札への構内通路→B3 | 12＋2 |
| 東西線仙台→60番 | B4→B2→北改札への構内通路→北2→60番 | 15＋2 |
| 60番→東西線仙台 | 60番→北2→北改札への構内通路→B2→B4 | 14＋2 |

仮モデルは5番→南北線9分、60番→南北線12分を基準とし、東西線の深い階層・連絡に2分、地下鉄からバスへはのりば確認に1分を加える。全方向に仮の余裕2分を別計上する。対称時間や他poleを自動生成する処理はない。既存API/UIの仮時間・非保証表示と利用者の明示同意を使い、製品の表示機構を作り直さない。荒井・泉中央の旧接続は全レコード同一で保持する。バス停「卸町駅」・「広瀬通駅」も名称だけで新乗換hubにしない。

### 19.3 新たに使える場所と条件付き到達範囲

追加44 IDは以下の24停留所名に対応する。名称は成果の説明に用い、探索では全て具体IDを区別する。

| 停留所名 | 新stop_id（APIではsendai_bus:を前置） |
| --- | --- |
| メディアテーク前 | `4_10`, `4_50` |
| 二軒茶屋・東華中学校前 | `4009_10`, `4009_50` |
| 交通局東北大学病院前 | `1_0`, `1_12` |
| 仙台駅前 | `50_210`, `50_850` |
| 卸町二丁目 | `4021_10`, `4021_50` |
| 卸町駅 | `4019_10`, `4019_50` |
| 商工会議所前 | `65_10`, `65_52` |
| 定禅寺通市役所前 | `80_10`, `80_50` |
| 宮千代三丁目 | `4017_10`, `4017_50` |
| 宮城野三丁目・聖和学園前 | `4011_10`, `4011_50` |
| 市営バス霞の目営業所前 | `5223_0`, `5223_11` |
| 市民会館前 | `3_11`, `3_51` |
| 広瀬通駅 | `60_50` |
| 志波町 | `4015_10`, `4015_50` |
| 新寺一丁目 | `4003_10` |
| 新寺三丁目 | `4005_10`, `4005_50` |
| 新寺三丁目西 | `4006_10`, `4006_50` |
| 新寺四丁目・サンプラザ入口 | `4007_10`, `4007_50` |
| 白萩町 | `4013_10`, `4013_50` |
| 蒲町 | `5063_11`, `5063_51` |
| 蒲町歩道橋前 | `5021_111`, `5021_151` |
| 遠見塚東 | `5222_11` |
| 電力ビル前 | `55_11` |
| ＪＲ東日本前 | `307_10`, `307_50` |

**11/19 09:00、最大3乗車・180分**に限定し、既存独立raw oracleの `optimum` を使って到達可能な具体ODと最早到着値を数えた。仙台駅のバス2 poleと地下鉄仙台2頂点を除き、新エリアの42 bus pole（23停留所名）と残り28地下鉄駅を全組合せで評価する。これにより駅隣接poleから歩いただけの経路を「バス＋地下鉄」の成果に数えない。両交通の利用は新バス経路が旧bus poleと共有を持たない具体IDの構造でも確認する。

| 方向 | 新エリアの利用可能pole／停留所名 | 地下鉄駅 | 新たに成立した具体OD組数 |
| --- | --- | --- | --- |
| バス→地下鉄 | 22 pole／22停留所名 | 28駅 | **616組** |
| 地下鉄→バス | 20 pole／20停留所名 | 28駅 | **560組** |

対象新エリアは前段reviewで未対応なので上記組数は前段0からの追加である。同じ新路線を残して仙台駅8接続だけ外しても、具体poleの共有も旧乗換辺もなく、鉄道と新エリアは接続しないことを確認する。両方向合計1176組は**この固定時刻・範囲の結果**であり、全時間帯・全日付・一般住所・徒歩圏の人口を表さない。反対側poleへの徒歩や名前一致による接続を合成していないため、同じ停留所名でも方向別の検索可否が異なる。

再現用 `scripts/check_sendai_stage7_reachability.py` は共通探索に触れず、既存raw oracleだけを呼ぶ検証専用スクリプト。原時刻の絶対値が09:00〜12:00窓に交わる全runを使用し、前日24時超があれば同じ条件で含める。具体ODと到着値のSHA、pole別・地下鉄駅別の組数を `municipal_reachability_20261017_stage7.json` に固定する。616/560を件数目標として探索を調整する処理ではない。

### 19.4 固定経路・検証範囲・残課題

原GTFS/保持地下鉄時計の独立oracleで、SearchCore v2に先立って新14条件の期待値を固定した。通常運行・仮の接続を前提とする予定目安である。

| 経路（全て09:00検索） | 日付 | 到着目安 |
| --- | --- | --- |
| 仙台5番→志波町（308単独） | 11/19 | 09:25 |
| 志波町→仙台60番（J308単独） | 11/19 | 09:23 |
| 志波町→仙台60番→南北線泉中央 | 11/19 | 10:00 |
| 南北線泉中央→仙台5番→志波町 | 11/19 | 09:55 |
| 志波町→仙台60番→東西線荒井 | 11/19 | 09:55 |
| 東西線荒井→仙台5番→志波町 | 11/19 | 09:55 |
| 病院発308→仙台5番→南北線泉中央 | 11/19 | 09:44 |
| 南北線泉中央→仙台60番→病院 | 11/19 | 10:06 |
| 病院発308→仙台5番→東西線荒井 | 11/19 | 09:44 |
| 東西線荒井→仙台60番→病院 | 11/19 | 10:06 |
| 志波町→仙台→泉中央→既存バス→住吉台西三丁目 | 11/19 | 10:57 |
| 南北線泉中央→仙台5番→志波町（土曜） | 11/21 | 09:42 |
| 志波町→仙台60番→南北線泉中央（祝日） | 11/23 | 09:44 |
| 東西線荒井→仙台5番→志波町（末日） | 11/30 | 09:55 |

`tests.test_sendai_stage7` の新8回帰は、14経路のraw最適値・全具体便witness・ASGI、183便/完全pattern/平土休日、途中停車での乗降、旧336便と全旧接続・日付の保持、8方向全ての実探索witness、接続除去時の両oracle不成立、改変拒否、同番号の未知route非承認、245 pole・有限期間の境界を検査する。ローカルで8件成功（84.794秒）。専用CIは同じ元ZIP/member SHA・subset原行順、14新条件と到達範囲、既存Launcher埋込みフォームから新5実経路のChromeを検証する。通常CIの既存回帰も確認する。成功CI・コードSHAは完了後に追記する。

新reviewは `municipal_review_20261017_stage7.json`。同じ起動コマンドの `--municipal-review` で明示指定し、`--use-reviewed-operating-period --accept-experimental-transfer-model` と、有効ふれあい乗車証の本人所持・明示選択を維持する。48候補日・11/30まで、10/25/11/22除外、12/1および末日深夜の未確認翌日を必要とする検索の422停止を保持する。追加支払0円と通常運賃不明を区別し、敬老乗車証を無料化しない。

今回の仙台駅対応は5/60番と308/J308・地下鉄2線の上記動線に限定する。他のりばの全路線対応や正式な乗換所要時間、バリアフリー保証、実端末の認定ではない。長町・長町南は地下鉄の検索先として利用できるが、同駅の新しいバス乗換接続は今回追加しない。次工程は同駅の公式動線と具体poleのレビュー、仙台駅他のりばと候補路線、特別ダイヤの便別影響、新しい12月以降のfeed。宮城交通・一般住所・全市一括・本番API/公開接続は未対応。本番API・東京・アプリID・Firebase・AWS/S3・deploy・storeは変更しない。

### 19.5 確定コード・実データ・Chrome・通常CI

実装commitは **`0adc169972a1169730c6cb553eb58c8c6125f286`**。第7段専用CI [39023382619](https://github.com/kaeruko/tobus_go/actions/runs/39023382619) は同SHAで **completed/success**。新規Python8件（98.445秒）、承認元ZIP・schema2 manifest/member SHA・subset全原行順一致、新14条件の独立raw最早値・全具体便witness・ASGI照合が成功し、`READ_ONLY_SENDAI_STAGE7_SENDAI_HUB_OK` を確認した。新エリアの固定条件全組合せも616/560組・全OD到着値SHAまで再現し、`SENDAI_STAGE7_NEW_AREA_REACHABILITY_OK` を確認した。

同じ原GTFSから起動したlocalhost APIを使うChromeでは、既存Launcherの埋込みフォームを展開して、308単独、J308→南北線、南北線→308、J308→東西線、東西線→308の**新5経路**を実操作で検索した。09:25/10:00/09:55/09:55/09:55の到着目安、60番の北2・5番の南4、方向別の仮の時間と余裕の表示を確認し、`All tests passed.`（10:17:46 UTC）。フォームやAPI、query、探索上限、元データを失敗時に変更する処理はない。

通常CI [39023382953](https://github.com/kaeruko/tobus_go/actions/runs/39023382953) も同SHAで **completed/success・全7job成功**。API **892件**、Windows **277件**、共通SearchCore v2 Python3.11/3.12 **各89件**、Flutter **659件**が成功した。東京・仙台のAndroid/iOS両flavor（iOS各ビルド10:11:26/10:16:12 UTC）、iOS identity/privacy/ATS/Firebase分離、repository safety、Lambda image build/importも成功した。解析は既存CI条件で成功し、指摘は98件（従来97件＋新規Chromeテストの文字列補間の不要な波括弧info1件）。解析指摘0件とは扱わない。この書式infoの整理は挙動に影響しない小課題として残る。

既存固定4経路のChrome [39023382732](https://github.com/kaeruko/tobus_go/actions/runs/39023382732) も同SHAで **completed/success**、`All tests passed.`（10:05:16 UTC）。共通loaderの明示profile許可に伴う自動回帰であり、旧成功runの手動再実行や過去全経路監査の再実施ではない。SearchCore v2・Adapter・運賃判定本体・Flutter製品フォームは全て同じコードを使っている。

終了時mainは上記コードSHA・未マージPR0を再確認した。確定結果はこのコードを親とする文書だけの `[skip ci]` commitに分離し、成功済みCIを文書追記で再起動しない。後続の文書SHAは新しいコード検証や実運行の正式認定を意味しない。本番公開・deployは実施していない。

## 20. 第8段：長町西口・長町南の58/Z60/N60接続（2026-10-17）

### 20.1 継承・候補比較・採用範囲

開始main `849c9bf2f27d8fa1c96cf07213a38dbbc40aa027`。第19節のコード `0adc169972a1169730c6cb553eb58c8c6125f286`、通常CI39023382953・第7段実データ39023382619・旧4経路Chrome39023382732は全てcompleted/success。開始時の未マージPR・進行中CIは0。第7段519具体便・15完全pattern・245具体bus poleを引き継ぐ。

既に保持している承認GTFS-JP `20261007_20261130`、schema2 manifest/member SHA、原ZIP SHA256 `53a08400776b3229743b24eb53566eb523b354a5b783dcfffd3e40f39258e6a2` を同じローダーで確認して再利用し、再取得や旧成功監査の再実行は行わない。既存deriveで前段11 routeの原行順が保存fixtureと同一であることを確認した。

| 候補 | 具体便・完全pattern・追加pole | 比較と判断 |
| --- | --- | --- |
| 仙台110/S110 `10006`/`10258` | 186便・2pattern・54 pole、平33/33便 | 第19節の有力候補を保持。今回の長町方面よりpole数は多いが、新拠点は仙台駅の追加のりばのみ |
| 長町58 `10102` | 124便・2pattern・30 pole、平29/29便 | 長町西口・長町南の2拠点と芦口小学校方面を高頻度で結ぶため採用 |
| 上記＋Z60 `10357` / N60 `10253` | 合計233便・5pattern・48 pole | 同じ拠点・公式図で西高校・八木山南・日赤病院まで追加できるため、この関連3 routeを採用 |

数だけを最大化せず、新しい南西部2拠点、頻度、住宅地・病院への効果、whole-runを安全に確認できる範囲を優先した。長町南を実際に通る新規便は平99便、Z60の西高校入口始発3便も含む全便では平102便。110/S110の平66便に対して便数が多く、東仙台方面は次の候補に残る。77は既存荒井と長町を結ぶが平日4便のため今回は見送る。

| 正確なroute ID | 完全pattern | 具体便（平/土/日祝） | 原stop_times |
| --- | --- | --- | --- |
| `10102`・58 | 長町駅東口→西口→長町南2番→芦口小学校→八木山動物公園駅、15停車 | 61便（29/18/14） | 915 |
| `10102`・58 | 八木山動物公園駅→芦口小学校→長町南7番→西口→長町駅東口、15停車 | 63便（29/19/15） | 945 |
| `10357`・Z60 | 長町駅東口→長町南2番→西高校→八木山南→日赤病院→八木山動物公園駅、15停車 | 56便（22/18/16） | 840 |
| `10357`・Z60 | 西高校入口→八木山南→日赤病院→八木山動物公園駅、8停車 | 3便（3/0/0） | 24 |
| `10253`・N60 | 八木山動物公園駅→日赤病院→八木山南→西高校→長町南7番→長町駅東口、15停車 | 50便（19/16/15） | 750 |

Z60の短patternは長町南を通らないが、長町南を通る56便だけにrouteを切り詰めず、別の完全patternとして全3便を確認する。全経路は令和8年4月長町営業所図と具体停車順で照合し、仙台市太白区内で完結するwhole-runだけを無料scopeに追加した。原route・全trip・各pole・乗降制約を保持し、同番号の他routeや逆順を合成しない。

追加は **233具体便・5完全pattern・3474 stop_times・48具体bus stop ID**。累計 **752具体便・20完全pattern・16220 stop_times・293具体bus stop ID**、地下鉄2線。新原行fixtureは `municipal_bus_subset_20261006_stage8.json`（全14 route）。稼働時は同じ原GTFS・manifestを使い、fixtureへfallbackしない。共通SearchCore v2、探索/枝刈り/順位、Adapter、無料判定本体、Flutter製品フォームは変更しない。loaderの変更は同じ有限期間の明示stage8 profile許可1行のみ。その他はreview・検証データとテスト/検証用スクリプトである。

### 20.2 公式図・具体pole・方向別の8接続

公式のりば図と構内図を原bytes・SHAで保持し、PDFはPNGに描画して目視確認した。路線図一覧の推測URLは取得エラーとなったため、公式のりばページの掲載リンクから現行 `/shibus/map/` を確認した。旧年の路線図への切替は行わない。

| 現掲載公式資料 | SHA256・確認範囲 |
| --- | --- |
| [長町駅のりば図](https://www.kotsu.city.sendai.jp/assets/img/shibus/noriba/nagamachi/nagamachi_r0408.jpg) | `120fcfb0ec9ddba8196a9a36de81fb5f002f4a419ba369938bdea95402111a9b`・東口4/5番、西口2 pole、たいはっくる前との区別 |
| [N15長町構内図](https://www.kotsu.city.sendai.jp/assets/img/subway/station/nagamachi/N15_%E9%95%B7%E7%94%BA.pdf) | `8cfb20697fa45aa446fd888f24b7c4d56de998be04f43d3d096f305a7b370eb7`・ホーム→改札→南1、たいはっくる側と西口方面 |
| [長町南のりば図](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r06_nagamachi_minami.jpg) | `623fdc87e7f9180adaebf5b2417541ddf8ec8a8ab380b46ef323e0bd5ae0faf7`・道路南側2番と北側7番、各出入口との位置関係 |
| [N16長町南構内図](https://www.kotsu.city.sendai.jp/assets/img/subway/station/nagamachi-minami/N16_nagamachi-minami_24.pdf) | `74ecec26844fe7802309387f160b5060f1ae734d77a1fe374e7493c9c837a5d9`・ホーム→改札→西2/東1 |
| [令和8年4月長町営業所図](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r0804-3_nagamachi.pdf) | `ac72521f732fa55ad9ce53610e973d451757a114a181f5589b2bbb8f7943b99d`・58/Z60/N60の全走行経路と短pattern |

公式現掲載のりば表は、長町駅東口4番が58/60、長町南2番が58/60、長町南7番が長町駅東口方面の58/60等である。長町はGTFSで「長町駅」という単一poleではない。西口 `6008_50`（38.226171,140.884259・長町南/八木山方面）と `6008_10`（38.226158,140.883387・東口方面）を、公式図の西口の2 poleと照合する。東口 `7501_10`/`7501_0` やたいはっくる前 `6007_10`/`6007_50` へ同名接続を作らない。

長町南は2番 `7111_10`（38.224419,140.876138、platform_code=2）と7番 `7111_11`（38.224693,140.876349、platform_code=7）。到着用 `7111_0`、6番・8番等を同一化しない。今回の全対象便では西口と長町南は原stop_times上で途中乗車/降車とも0で利用可能。八木山駅は具体bus poleを追加するが、同名の地下鉄への新接続は今回承認しない。

| 明示する出発→到着 | 動線 | 仮の標準＋余裕（分） |
| --- | --- | --- |
| 南北線長町→西口6008_50 | ホーム→改札→南1→たいはっくる側歩道→西口交差点・歩道→長町南方面pole | 10＋2 |
| 西口6008_50→南北線長町 | 同pole→西口交差点・歩道→たいはっくる側歩道→南1→改札→ホーム | 9＋2 |
| 南北線長町→西口6008_10 | 南1から西口交差点の反対側・東口方面poleへ | 12＋2 |
| 西口6008_10→南北線長町 | 東口方面poleから交差点・歩道→南1→改札→ホーム | 11＋2 |
| 南北線長町南→2番7111_10 | ホーム→改札→西2→道路南側2番 | 6＋2 |
| 2番7111_10→南北線長町南 | 道路南側2番→西2→改札→ホーム | 5＋2 |
| 南北線長町南→7番7111_11 | ホーム→改札→東1→道路北側7番 | 7＋2 |
| 7番7111_11→南北線長町南 | 道路北側7番→東1→改札→ホーム | 6＋2 |

数値は明示的な検証用計画仮定。基準は西口6008_50→長町9分、交差点の反対側6008_10→長町11分、長町南2番→駅5分、7番→駅6分とし、バス出発側はのりば確認1分を加える。全方向で仮の余裕2分を別計上する。公式時間・実測・正式認定・バリアフリー所要時間・接続保証ではない。8レコードは各方向を明示し、対称辺や他poleを自動生成しない。既存の荒井・泉中央・仙台駅接続と全旧reviewは同一で保持する。

### 20.3 追加48具体IDと条件付き到達範囲

以下の名称は成果の説明用で、探索では方向別IDを統合しない（APIでは `sendai_bus:` を前置）。

| 停留所名 | 追加stop_id |
| --- | --- |
| 仙台南年金事務所前 | `7103_10`, `7103_50` |
| 八木山動物公園駅 | `7051_0`, `7051_12` |
| 八木山南三丁目 | `7257_10`, `7257_50` |
| 八木山南五丁目 | `7259_10`, `7259_50` |
| 八木山南六丁目 | `7261_10`, `7261_50` |
| 八木山南団地入口 | `7255_10`, `7255_50` |
| 八木山小学校前 | `7029_10`, `7029_50` |
| 八木山本町二丁目 | `7031_10`, `7031_50` |
| 八木山本町二丁目北 | `7028_10`, `7028_50` |
| 八木山本町二丁目西 | `7251_10`, `7251_50` |
| 土手内一丁目 | `7607_10`, `7607_50` |
| 土手内一丁目南 | `7609_10`, `7609_50` |
| 新道西多賀 | `7269_10`, `7269_50` |
| 日赤病院前 | `7253_10`, `7253_50` |
| 泉崎一丁目北 | `7122_10`, `7122_50` |
| 砂押町 | `7123_11`, `7123_51` |
| 芦口小学校前 | `7605_10`, `7605_50` |
| 若葉町 | `7601_10`, `7601_50` |
| 西の平二丁目東 | `7603_10`, `7603_50` |
| 西高校入口 | `7265_10`, `7265_50` |
| 鉤取寺前 | `7267_10`, `7267_50` |
| 長町南駅・太白区役所前 | `7111_10`, `7111_11` |
| 長町駅東口 | `7501_0`, `7501_10` |
| 長町駅西口 | `6008_10`, `6008_50` |

第7段と同じ **11/19 09:00・最大3乗車・180分**に固定した。長町東/西口、長町南、八木山の駅隣接8 bus poleを除外した新エリア40 pole（20停留所名）と、当該3地下鉄駅IDを除く27路線別駅ID（**実駅名26**。仙台は南北/東西の2頂点）を独立raw oracleで全組合せ評価する。

| 方向 | 成立する新エリア | 相手の地下鉄 | 具体OD組数 |
| --- | --- | --- | --- |
| バス→地下鉄 | 21具体pole・20停留所名 | 27路線別駅ID・実駅名26 | **567組** |
| 地下鉄→バス | 21具体pole・20停留所名 | 27路線別駅ID・実駅名26 | **567組** |

前段では新エリアの具体bus poleは未対応で0組。新8接続を外すと、新路線に旧bus poleの共有や旧rail接続がないため、同じ路線データを残しても鉄道と接続しない。各方向567組は固定時刻の予定値であり、全時間帯・全日付・徒歩圏人口・一般住所の指標ではない。方向による可否は原poleのままとし、対向pole間を歩いたことにしない。仙台南年金事務所の両poleは長町・長町南の間にあるため、どちらも両方向で利用でき、20停留所名に対して21 poleとなる。

到達範囲の計算は既存の第7段カウンターとraw `optimum` を再利用し、対象pole・除外駅・リンク数だけを `municipal_reachability_scope_20261017_stage8.json` で明示する。カウンターに対象scopeを受け取る最小変更を行い、従来の省略時stage7定義・結果形式を保持する。経路計算アルゴリズムや製品の探索には変更がない。第8段wrapperは駅ID数と実駅名数を別々に記録するだけで、駅を探索上で併合しない。`municipal_reachability_20261017_stage8.json` にpole別/駅別組数と全具体OD到着値SHAを固定した。

### 20.4 新規固定経路・2拠点の独立確認・残課題

原GTFS・保持地下鉄時計から、実装探索に先立って以下の予定最早値を固定した。最大3乗車・180分は既存のまま。

| 経路 | 日付・検索時刻 | 到着目安 |
| --- | --- | --- |
| 西口6008_50→芦口小学校（58単独） | 11/19 09:00 | 09:10 |
| 芦口小学校→長町南7番（58単独） | 11/19 09:00 | 09:11 |
| 長町南2番→日赤病院（Z60単独） | 11/19 09:00 | 09:58 |
| 日赤病院→長町南7番（N60単独） | 11/19 09:00 | 09:31 |
| 西高校入口→八木山駅（Z60短pattern） | 11/19 06:30 | 06:39 |
| 芦口小学校→南北線泉中央（58→地下鉄） | 11/19 09:00 | 09:52 |
| 南北線泉中央→芦口小学校（地下鉄→58） | 11/19 09:00 | 10:07 |
| 長町駅東口→南北線仙台 | 11/19 09:00 | 09:52 |
| 南北線長町→長町駅東口 | 11/19 09:00 | 09:16 |
| 南北線長町→芦口小学校 | 11/19 09:00 | 09:37 |
| 芦口小学校→長町南→仙台→既存308→志波町 | 11/19 09:00 | 10:26 |
| 志波町→既存J308→仙台→長町南→Z60→日赤病院 | 11/19 09:00 | 10:58 |
| 芦口小学校→南北線→東西線荒井 | 11/19 09:00 | 10:03 |
| 南北線泉中央→芦口小学校（土曜） | 11/21 09:00 | 10:26 |
| 日赤病院→南北線仙台（祝日） | 11/23 09:00 | 10:32 |
| 南北線仙台→日赤病院（期間末日） | 11/30 09:00 | 09:58 |
| 西口6008_50→南北線仙台（西口poleから徒歩接続） | 11/19 09:00 | 09:20 |
| 南北線仙台→西口6008_50（地下鉄から徒歩接続） | 11/19 09:00 | 09:22 |

全18条件のうち最後2件は長町西口の接続自体を確認する地下鉄＋徒歩の経路であり、バス乗車した経路とは扱わない。到達範囲の567/567集計でもこれら駅隣接poleは除外する。短patternは原trip `30_1_13003970` の全走行と一致することを確認する。

最初のローカル回帰は「南北線長町→長町駅東口」をバスだけと仮定したmode検査で停止した。到着09:16はraw oracleと一致しており、実際の最早witnessは長町南まで地下鉄→58だった。同様に「南北線長町→芦口小学校」も地下鉄→58。元例外・診断と元queryを保持し、日付・時刻・OD・期待到着・探索上限・backend・元データは変えず、原時刻表で確認した乗車構成の誤った検証仮説を訂正した。長町西口の長い仮時間を、最早経路に選ばせるために縮めたり、共通順位を変更したりしない。

2拠点の確認では、長町の4接続だけ/長町南の4接続だけを残す**事前に定義した2つの分離条件**も用いる。各条件でバス→泉中央、泉中央→バス、長町東口発→泉中央、泉中央→長町東口をraw oracle・実装witness・ASGIで照合し、各4方向全てを確認する。失敗時に別条件を順に試す自動fallbackではない。通常modelは両拠点を保持し、時刻によって短い長町南接続が最早として選ばれる。

`tests.test_sendai_stage8` の新8回帰は上記18条件の原行oracle・具体便witness/API、5完全pattern/平土休日と短3便、全旧519便・既存14接続・日付の保持、各hubの有向接続・除去時の不成立、全pattern改変拒否、同番号別route非承認、293 pole・有限期間の境界を検査する。既存原行oracleを作り直さない。新Chromeは既存Launcher埋込みフォームから、Z60単独、祝日のN60→地下鉄、地下鉄→58、長町西口pole→地下鉄・逆方向の5条件を実操作する。後者2つをバス＋地下鉄の件数に混ぜない。

新reviewは `municipal_review_20261017_stage8.json`。既存起動コマンドで `--municipal-review` へ明示指定し、`--use-reviewed-operating-period --accept-experimental-transfer-model` を維持する。debug・明示テストAPIだけで既存フォームに新stop IDを表示する。本人の有効ふれあい乗車証所持・明示選択、通常運賃不明と追加支払0円の区別を保持し、敬老乗車証は無料化しない。48候補日・11/30まで、10/25/11/22除外、12/1・期間末日深夜の未確認翌日に関する422停止は同じである。

残課題は仙台110/S110等の次候補、長町/長町南の他のりばと75/77等、八木山駅の公式方向別接続、特別ダイヤ便別影響、12月以降の新feed、正式乗換実測・実端末確認。宮城交通・一般住所・全市一括・本番API/公開接続は対象外。本番API・東京・アプリID・Firebase・AWS/S3・deploy・storeは変更しない。

### 20.5 第8段の実装SHAと成功結果

実装コミットは [`4d133ca7b6ed8e73b8314dee5439690cd5e34284`](https://github.com/kaeruko/tobus_go/commit/4d133ca7b6ed8e73b8314dee5439690cd5e34284)。以下は全てこの同一SHAでcompleted/successを確認した結果である。

| 検証 | 成功した実行・結果 |
| --- | --- |
| [第8段実データ・Chrome #39025765004](https://github.com/kaeruko/tobus_go/actions/runs/39025765004) | 新8回帰155.138秒、承認原GTFSの18条件でraw optimum・具体便witness・ASGI一致、`READ_ONLY_SENDAI_STAGE8_NAGAMACHI_HUBS_OK`。追加地域の567/567組・到着SHA一致、`SENDAI_STAGE8_NEW_AREA_REACHABILITY_OK`。既存埋込みFlutterフォームの5条件Chrome成功 |
| [通常CI #39025764981](https://github.com/kaeruko/tobus_go/actions/runs/39025764981) | 全7ジョブ成功。API900件、Windows277件、共通SearchCore v2 Python 3.11/3.12各89件、Flutter659件。東京・仙台Android/iOSビルドと分離確認、repository safetyも成功 |
| [既存固定4経路Chrome #39025764992](https://github.com/kaeruko/tobus_go/actions/runs/39025764992) | 原GTFSを使う既存4経路のFlutter Chrome回帰成功 |

新規Chromeの内訳はバス単独1条件、バス→地下鉄1条件、地下鉄→バス1条件、地下鉄＋長町西口徒歩接続2条件。新規5件全てをバス乗継として数えない。Dart解析は既存と同じ98指摘で新規増加なし（解析無指摘とはしない）。ローカル新8回帰も127.776秒で成功し、原GTFS全14 routeからの行選択と追加fixtureの完全一致も確認した。

今回は成功済み旧監査を別途最初から再実行せず、通常CIの既存回帰と新規変更部分の検証を実施した。233便・48具体pole・新2拠点8方向を既存機構へ追加し、代表例の芦口小学校前→泉中央09:52、泉中央→芦口小学校前10:07、志波町→日赤病院前10:58（各11/19 09:00検索）が成立した。無料は有効な本人のふれあい乗車証を前提とする。全市対応・一般公開・実測による乗換保証には拡張していない。

## 21. 事業者単位の市営バス一括統合（2026-10-17）

### 21.1 継承と全件棚卸し

開始main `cc724f8fbe6aaf61b6a1bac663c0fd96b88d77db`、第8段実装 `4d133ca7b6ed8e73b8314dee5439690cd5e34284`。開始時に未マージPR・進行中CIは0、通常39025764981・第8段39025765004・旧4経路Chrome39025764992の成功を確認した。共通設計書の入力・秒時計・具体便・方向別接続・無料scope・主到着1件の契約を引き継ぐ。

既に保持する公式GTFS-JP `20261007_20261130`、原ZIP SHA256 `53a08400776b3229743b24eb53566eb523b354a5b783dcfffd3e40f39258e6a2`、schema2 manifestと全member SHAを既存ローダーで確認して再利用する。再取得した別feed・12月版・過去版・fixtureへの稼働時fallbackはない。実データCIだけは同一の承認URL/SHAを既存fetcherへ明示する。

| 分類 | route ID数 | 完全pattern数 | 具体trip数 | 使用stop ID数 |
| --- | ---: | ---: | ---: | ---: |
| 原GTFS全体 | 339 | 471 | 8,231 | 2,149 |
| 一括登録する市内完結whole-run | 336 | 467 | 8,142 | 2,127 |
| 市外通過のためwhole-run除外 | 3 | 4 | 89 | 84（市内共有poleも含む） |
| この版のパターンで根拠未確認の保留 | 0 | 0 | 0 | 0 |

全原stop_timesは215,949行、承認便は213,118行。事業者はagency `8000020041009`・仙台市交通局のみ、全route_typeは3、サービスIDは7営業所×平土日祝の21。原pattern IDや同じ系統番号で別route・枝線・方向・短便を統合しない。元のpickup/dropoff、sequence、秒時刻、calendar/calendar_datesを保持する。

第8段752便・20pattern・293 poleから **7,390便・447pattern・1,834 pole増**。原8,231便に対する対応率は **98.9187%**（前段9.1362%）。これは当該feedの具体便収録数であり、1日の運行本数や全事業者の市内交通に対する率ではない。宮城交通は統合していない。

### 21.2 路線群レビューと市外通過の分離

`shapes.txt` はヘッダーのみで、道路線形は含まれない。GTFS停留所列の直線補間、両端の市内座標、営業所名だけでは無料認定しない。公式の[基本系統図](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r0804-A_rosenzu_kihon.pdf)・[特殊系統図](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r0804-B_rosenzu_tokusyu.pdf)と、[現行の営業所別図一覧](https://www.kotsu.city.sendai.jp/shibus/map/)の令和8年4月全図を取得・SHA固定・PNG化して、各群の走行道路と枝線を確認した。

| 全走行経路を確認した群 | 固定した承認pattern数 | 確認した範囲 |
| --- | ---: | --- |
| 東仙台 | 92 | 仙台駅・宮町・鶴ケ谷・旭ケ丘・岩切・田子・卸町・高砂。沼田・高橋経由を除く |
| 七北田 | 36 | 北仙台・台原・旭ケ丘・南光台・八乙女・長命ケ丘・桜ケ丘。南光台循環専用図も照合 |
| 霞の目 | 92 | 薬師堂・荒井・若林・六郷・七郷・蒲生・井土・藤塚。沼田・高橋経由を除く |
| 長町 | 84 | 長町・八木山・緑ケ丘・向山・中田・袋原・四郎丸。名取川付近も道路経路を確認 |
| 川内 | 47 | 川内・青葉山・国見・中山・桜ケ丘・折立・茂庭台・生出 |
| 白沢 | 47 | 愛子・白沢・作並・熊ケ根・大倉・定義・秋保・二口。大倉の湖畔公園を川崎町の公園と混同しない |
| 実沢 | 69 | 泉中央・実沢・根白石・朴沢・泉岳・泉川崎・住吉台・中山・国見。泉川崎を川崎町と混同しない |

同じ完全patternを複数営業所が運行する場合は1件として数え、元tripの全営業所IDを棚卸しに保持する。図のURI/SHA、走行範囲の確認記録、承認する全pattern fingerprintを `municipal_bulk_scope_20261017.json` に固定した。基本図SHA `d7883214779e47976d6c75c68c16d00c1f883a96ce90c93e2cc22e3e8f4e7d05`、特殊図SHA `55f4133aec48684cf3339d161fc42bff5a238d7ff24bc8564342fa6601de6c84`。以降の新しいpatternを営業所単位で自動許可する規則ではない。

市境の補助照合には国土交通省[2026-01-01行政区域・宮城県](https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2026/N03-20260101_04_GML.zip)（CC-BY-4.0、原ZIP SHA `2123ed0df27c92ed77e1d9d63ad4b764f3acba667963f37b7f0dd44c20e65f79`）を使用した。県全体のJSON一括展開と距離変換の調査処理はそれぞれメモリ上限で終了137となり、結果を採用していない。同じ原ファイルを逐次読み込みした市内外pole照合は成功。区界の隙間、直線chord、距離の近さを実道路の市外通過証明に使わない。GISの「全poleが市内」だけで上記レビューを置き換えていない。

| 除外route ID | 系統番号 | 完全pattern | 具体便 | 理由 |
| --- | --- | ---: | ---: | --- |
| `10036` | 205 | 1 | 37 | 沼田・高橋を経由する全走行路が多賀城市を通る |
| `10214` | J205 | 1 | 36 | 同経路の逆方向 |
| `10161` | 85 | 2 | 16 | 陸前高砂駅と高砂市営住宅西の両方向が市外を通る |

該当する市外poleは `3253_10`/`3253_50`（沼田）、`3255_10`/`3255_50`（高橋）。**両端が市内でも全区間は市内とは限らない実例**である。市内だけの途中乗車も今回はwhole-run制約により未対応。`10160` の秋保方面85は別route/完全pathとして承認し、系統番号85を一括除外・一括無料化しない。除外3routeだけが使う22 pole（うち市外4）はcapabilitiesに出さない。

### 21.3 既存reviewへの一括登録と最小変更

`scripts/review_sendai_municipal_bulk.py` が全route・完全停車列・具体便・乗降/秒時計/営業日を一括棚卸しし、固定レビューに全471patternの決定が重複なく揃うことを要求する。新pattern・trip・時計・乗降・calendar・事業者が変われば元inventoryのhashと一致せず停止する。全pattern棚卸しSHAは `995cdf6b813d9bc36eb96957b5f738743539b4de10394d0825285d15e697ed1c`。

生成先は既存schema1の `municipal_review_20261017_bulk.json`。最初の20patternと22方向リンクは第8段から同一のまま保持し、後ろに447patternをまとめて追加する。全件の分類と除外理由は `municipal_bulk_inventory_20261017.json`、原CSVは明示した圧縮検証fixture `municipal_bulk_source_20261006.json` に原ZIP/member SHAと展開後SHAを付けて保持する。fixtureはテスト専用で稼働ソースに切り替えない。

市営バス取り込みと駅接続を分け、bus単独経路にも全承認便を使用する。荒井・泉中央・仙台駅・長町・長町南の既存具体pole/方向を使う便だけが地下鉄と接続する。八木山などへの同名/近接自動接続、反対pole間徒歩、逆方向リンク生成は追加しない。通常debugフォームは既存capabilitiesから2,127 bus poleを表示するだけで、製品フォームは変更しない。表示範囲は「336/339路線ID・8,142便」、市外通過便除外と開発検証を明示する。

ローダーの各pattern×全trip再走査・反復sortを、同じ `(route ID, ordered stop IDs)` の一度の索引構築に置き換えた。具体trip集合・名称の完全一致、重複pattern拒否を維持する。無料scope構築でも同じ具体tripの隣接区間集合を一度だけ作る。Policyのquote・whole-run規則、Adapter、共通SearchCore v2・探索順位・枝刈りは変更しない。日付別のnetwork再構築は現行のままで、検索結果cacheや別backendを導入していない。

48検索日の契約と前日便参照用のreview日を保持する。10/25・11/22を除外し、11/30まで、12/1や未確認翌日を必要とする検索は停止する。本人の有効ふれあい乗車証所持・明示選択、推定乗換への明示同意、通常運賃不明None・追加支払0円の区別、敬老非無料を維持する。本番API・東京公開機能・アプリID・Firebase・AWS/S3・deploy・storeには変更しない。

### 21.4 新規検証と到達範囲

新6回帰は全件compiler一致、8,142具体便・213,118停車行のraw/Adapter一致、49の既存review営業日に対するcalendar/例外一致、各分類・同じ85の別route、旧20pattern/22リンク保持、11固定条件のraw optimum・具体便witness・ASGI、2,127 poleと48検索日・除外日・乗車証明示条件を検査する。最初の検証でreview営業日を検索日数48と同一視したassertionが失敗したため、元契約との同一性を検査するよう訂正した。元review・検索期間は変えない。

| 原GTFSから先に固定した条件 | 検索日時 | 期待到着目安 |
| --- | --- | --- |
| 附属小学校前2005_50→東仙台営業所2041_0 | 11/19 09:00 | 09:38 |
| 霞の目5227_10→南北線泉中央 | 11/19 09:00 | 10:56 |
| 南北線仙台→泉岳自然ふれあい館1155_0 | 11/19 09:00 | 10:48 |
| 霞の目5227_10→芦口小学校7605_10 | 11/19 09:00 | 11:07 |
| 定義8755_10→白沢車庫8243_0 | 11/19 06:00 | 06:40 |
| 旭ケ丘2151_50→鶴ケ谷四丁目北2603_10（循環） | 11/19 08:00 | 08:33 |
| 野尻町北8668_10→愛子8226_0（市内の85） | 11/19 10:00 | 11:09 |
| 附属小学校前→東仙台営業所（土曜/祝日/最終日） | 11/21・23・30 09:00 | 09:27 / 09:55 / 09:38 |
| 南北線仙台→恵和町7211_0 | 11/19 09:00 | 経路なし（固定負例） |

恵和町の条件はraw oracleで経路なしとなった。時刻・日付・ODを差し替えて成功扱いせず、同じ条件のraw/core/API不成立を固定する。成功する地下鉄→新バスの泉岳方面は別に宣言した条件で、泉中央の既存3番pole `1085_12` を使用する。

全49日分の巨大raw run配列を繰り返さず、各朝の固定queryに前日の24時超便が重ならず、期限が翌日へ達しないことを確認した同一入力窓を用いる。最初は地下鉄に24時超時計がないという強すぎる検証仮説で停止したため、実際に前日便がqueryへ重なり得るかという条件へ訂正した。時計・calendar・検索上限・元データ・期待到着は変えていない。

到達範囲は11/19 09:00・最大3乗車・180分に固定し、全乗換拠点を除く地下鉄24駅から新規1,834 bus poleへの44,016組を対象とする。既存raw oracleの同じlayer scanを全目的地の最早値として一度返せるよう整理し、24始点について照合した。**新規736具体poleに対応する530停留所名へ15,262組**が成立し、全24始点が少なくとも1つに到達する。530名称のうち502は前段の全164停留所名に存在せず、28は前段と同名の追加標柱である。530全てを新しい場所とは数えない。起点に乗換リンクがなく終点も駅隣接リンクを持たないので、実際のrail乗車とbus乗車を伴う。前段では新pole未登録により0組。逆方向全組・全時刻・徒歩圏人口の成果には読み替えない。固定OD到着SHA `f1f98ca862863e8ed1261898346eebb59d86e11c0da4fc64da339ef00017a978` とpole別件数は `municipal_bulk_reachability_20261017.json` に保存した。

新Chromeは既存フォームで、110のbus単独、霞の目→地下鉄、地下鉄→泉岳、南光台循環の4条件を実操作する。大きな選択一覧では、既存の `scrollUntilVisible` を同じ開いたmenuへ使い、実viewportの半分を進む重なりのあるgestureとextent由来の有限予算を用いる。要素が見つからなければviewport・extent・delta・予算・元例外を残して停止する。別APIで検索を代行したり、入力を変更したりせず、製品フォームも変更しない。

初回実装 `8cdea1cd65ed05e08fa96d4b2c25169cccb50b56` の実データCI [39029293400](https://github.com/kaeruko/tobus_go/actions/runs/39029293400) は原GTFS全件・11条件・到達範囲・性能測定まで成功したが、新Chromeの乗車証選択で `Exact option/fixed row height missing: pass=sendai_fureai_pass; index=0, height=null` と停止した。テストヘルパーが固定行高を想定した誤りであり、成功と記録しない。実フォームの可変行高に合わせて上記の既存スクロール操作へ訂正し、別経路を順に試すfallbackは設けない。全query・期待到着・API・backend・承認データ・製品フォームは同じままである。

ローカル新6回帰は88.394秒で成功。通常CI・実データ/Chrome・同一runnerの性能測定の成功結果は21.6・21.7に記録する。旧112組など成功済み監査を改めて呼び直さず、今回の全件整合性と代表query、通常CIの回帰を実行した。

### 21.5 公開へ残る課題

市外通過89便の市内部分はwhole-run scopeでは検索できない。具体便を分割・合成せず対象区間を扱う改善は別課題とする。全市営busを無条件無料とする入口は設けない。今回の公式版・市内完結patternレビューを別版へ自動継承せず、次版は同じ一括棚卸しとの差分を明示確認する。12月版取得は今回の主作業にしていない。

全駅/全のりばへの乗換、八木山の新接続、一般住所・近接pole間の歩行、宮城交通、臨時ダイヤ・特別日の便別影響、実測乗換・実端末操作・大量停留所の操作性、日付別network構築コスト、本番公開は未完。今回の追加だけで全市・全事業者・任意日・全ODを保証しない。

### 21.6 同一runnerでの性能比較

成功した一括実データrun [39029801537](https://github.com/kaeruko/tobus_go/actions/runs/39029801537)、実装SHA `5ecaf526c2c18ca976dbfbdca2e9d975c72c26ac`、Linux Python 3.12.15で `benchmark_sendai_municipal_bulk.py` を実行した。同じ原GTFS・共通SearchCore・query条件を使い、前段752便scopeと8,142便scopeをそれぞれfreshな別プロセスで起動し、3経路を各3回測った。前段側も今回の同じloader索引を使い、ここでは路線網拡大による増加を比較する。

| 測定 | 前段752便scope | 一括8,142便scope |
| --- | ---: | ---: |
| 元GTFS検証・読込 | 1.597秒 | 1.604秒 |
| 地下鉄読込＋network構築 | 1.311秒 | 3.044秒 |
| 起動合計 | 2.907秒 | 4.648秒 |
| プロセス最大RSS | 201.2 MiB | 329.0 MiB |
| 芦口小学校→泉中央の検索中央値 | 0.350秒 | 1.548秒 |
| 泉中央→芦口小学校の検索中央値 | 0.459秒 | 1.791秒 |
| 志波町→日赤病院の検索中央値 | 0.449秒 | 1.915秒 |

各検索の到着値592/607/658分は全3回・両scopeで同じ。最大RSSはfixture JSONやretained heapのサイズではなく、読込・構築・検索を含むプロセスのhigh-water markである。query時間には現行の日付別network再構築を含み、coreのlabel探索だけの計測ではない。全OD・混雑時・実端末・本番APIの性能保証ではなく、路線増加に伴う処理/メモリ増を確認する代表測定である。数値を検証条件に合わせて丸めて通す閾値は設けていない。

別途ローカルの同一原入力・全467patternについて、変更前と変更後のpattern照合部分だけを比較し、全8,142便の一致を確認した。反復全trip sort方式は8.1995秒、索引方式は0.0390秒。これは照合部分の比較で、API全体が同じ倍率で速くなるという意味ではない。大きくなったnetworkの構築・日付別再構築は残るため、次の性能改善候補として記録する。

### 21.7 最終実装と成功CI

一括データ・loader索引の実装は [`8cdea1cd65ed05e08fa96d4b2c25169cccb50b56`](https://github.com/kaeruko/tobus_go/commit/8cdea1cd65ed05e08fa96d4b2c25169cccb50b56)、Chromeヘルパー訂正後の検証済み実装は [`5ecaf526c2c18ca976dbfbdca2e9d975c72c26ac`](https://github.com/kaeruko/tobus_go/commit/5ecaf526c2c18ca976dbfbdca2e9d975c72c26ac)。後者の変更は新Chromeテストと本書だけで、路線・接続・query・期待到着・製品コードは前者と同じである。

| 成功した実行 | SHA・結果 |
| --- | --- |
| [一括実データ・Chrome #39029801537](https://github.com/kaeruko/tobus_go/actions/runs/39029801537) | `5ecaf526`・completed/success。新6回帰71.810秒、全471pattern分類・承認8,142便/213,118行・49 review営業日整合性、固定11条件（成功10・不成立1）のraw/core/witness/API一致、15,262組の独立到達範囲と到着SHA一致、別プロセス性能比較、同じ既存フォームのChrome4条件成功 |
| [通常CI #39029801540](https://github.com/kaeruko/tobus_go/actions/runs/39029801540) | `5ecaf526`・completed/success、全7ジョブ成功。Python API906件（616.731秒）、Windows277件、共通SearchCore v2 Python 3.11/3.12、Flutter659件、東京・仙台Android/iOSとidentity/privacy/ATS/Firebase分離、repository safety。Dart解析は従来と同じ98指摘、新規増加なし |
| [既存固定4経路Chrome #39029293386](https://github.com/kaeruko/tobus_go/actions/runs/39029293386) | データ/製品コードの実装SHA `8cdea1cd`・completed/success。新Chromeだけを訂正した後者でも、この既存テスト・API・入力は変更していない |

一括gateの成功markerは `READ_ONLY_SENDAI_MUNICIPAL_BULK_OK`、到達範囲は `SENDAI_BULK_NEW_AREA_REACHABILITY_OK`、性能比較は `SENDAI_BULK_PERFORMANCE_MEASURED`。初回のChrome失敗run39029293400は成功へ読み替えない。先行通常CI39029293384は後続SHAの起動時に既存concurrency制御でcancelledとなったため、通常CIの成功根拠には使わない。

行政界の補助照合も、同じN03原ZIP由来のデータを逐次読み込みする単独処理で全2,149 poleを再確認して完了した。市外は上記4 poleだけであり、別の照合で全4点が多賀城市 `04209` に含まれることも確認した。このpole確認を全走行経路の承認規則に置き換えない。

ここで完了したのは、承認済み有限feedの全路線一括評価、確認済みwhole-runの既存共通ネットワークへの登録、原データ/独立oracle/実UI/通常CIによる検証である。本番公開や未確認の駅接続・市外部分区間の追加は行っていない。最後の成功記録コミットは本書だけを変更し、同じ成功済みコードを保持する。

## 22. 通常座標画面と確認済みネットワークの開発接続

開始mainは `1ef5632dc883421e26cad574ed88fca19ad2c2bd`。開始時のGitHub main・open PR（0件）・実行中CI（0件）を確認した。第21節の8,142便・336 route・467完全pattern・2,127 bus pole、地下鉄2線、22方向のbus/subway接続、有限日付reviewをそのまま使う。新しい探索器・検索画面・GTFS Adapter・運賃Policyは作らない。一括GTFS監査や旧112組の独立監査を再実行する工程は追加しない。

### 22.1 既存の通常入口と結果契約への接続

`RouteSearchPage` の `PlaceField`（日本語・英語detailsから同一座標を確定）・`MapPickerPage`・`routeSearchProvider`・`ApiRouteSearchService`・通常 `/route` と運賃scope選択を再利用した。`SendaiCoordinateScope` はこの境界の接続adapterで、許可便・時計の実体は既存 `search_practical_subway -> search_network -> SearchCore v2`。APIの旅程を `Candidate/RouteMeta/FareQuote` へ変換して既存 `RouteCard/RouteDetailPage` に渡す。画面から `/test/sendai/route` を呼ぶ方式にはしていない。

バスの元trip/route/乗降stop IDと具体停車順、地下鉄の公開発車時計・到着proxy、service日・feed版・原資料/行列/SHAを `planning_journey` と各stepの `planning_details` に保持する。各stepへ予定の待機・駅アクセス・乗換・所要時間・余裕・非保証の説明を載せる。整数所要分は表示用で、元Fraction時計はこの明示metadataに保持する。Flutterの先頭待機を徒歩より前へ移す東京の既存表示処理は、この予定モデルのstepには適用しない。地下鉄到着は目安と表示し、距離不明の標準乗換の会計上の0mを実距離0mとして表示しない。地図の線は停車点を結ぶ概略で、実歩行線ではない。

仙台の鉄道便は既に具体ID・公開時計の根拠を持つため、東京専用 `/train/resolve-route-identities` を呼ばない。東京は従来どおり同APIで解決する。仙台の鉄道応答が発車/到着proxyの根拠を失った場合は停止する。予定モデルの経路では未接続の実時間ナビ開始ボタンを出さず、東京・従来仙台バスの実時間機能は保持する。

端末のtime zoneがUTCなどでも仙台の予定時計を維持する。APIの `departure_date` は元のoffset付きinstantとして残し、`sendai_published_minute_v1` に限る派生値で日本時間のcivil clockを既存の詳細再検索pickerへ渡す。予定モデルのpickerを開く際に現在日時へ戻さない。バス時刻表の基準は、旅程の検索日から推測せず各具体rideの `planning_details.departure.date/time` を使い、翌日の便も区別する。時計が欠けた場合は現在日時や旧計算へfallbackしない。東京・従来の非予定モデルの日時処理は保持する。修正SHAは `1f645e911086c8ddcbc26ba637db6746f2fe76a6`。Flutterの追加境界テストは人工的なwire-contractケースであり、実便・実ODの成立証拠には数えない。元の固定5 OD・日付・期待到着は変更しない。

バス限定は同じnetwork builderの許可具体便集合でrail乗車を除外する。駅の物理vertexとレビュー済み構内徒歩は消さない。初期実装で地下鉄Datasetを丸ごと除外すると、空Dataset例外に加えてバスだけの旅程に必要な構内徒歩まで失い、rawの09:24に対して09:48となることを検出した。便の許可集合だけを絞る最小修正で、入力・raw期待到着は変更せず解消した。探索・順位・枝刈りは変更していない。

### 22.2 開発用の明示選択と、今回承認する座標アクセスの限界

APIは `SENDAI_REVIEWED_COORDINATES=1` と明示 `development` runtime、および既存の原データ・地下鉄資料・municipal reviewの各path指定を要求する。Lambdaなど他modeではこのopt-inを拒否する。`scripts/serve_sendai_normal_local.py` は通常city appをlocalhostだけで起動し、比較用の旧ID APIも保持する。Flutterはdebugかつ `--dart-define=APP_CITY=sendai --dart-define=SENDAI_REVIEWED_COORDINATES=true` のときだけ、既存運賃設定に `sendai_fureai_pass` を追加する。通常運賃が既定のままで、本人の有効な乗車証の所持・明示選択・未実測モデルへの同意が必要。開発用の保存keyを分離し、通常構成へ無料選択を持ち越さない。敬老・通常運賃不明・未承認89便を0円に変えない。

近傍候補の幾何計算は既存GTFS backendから共通関数を再利用するが、600m圏にあることを徒歩承認には使わない。今回の座標入口は次の有限な範囲であり、**一般住所から全停留所への徒歩が完成したわけではない**。

- 承認されたbus poleのGTFS位置と同一の入力点。0.01mは数値同一性の許容であり歩行半径ではない。別標柱への歩行辺は作らない。同座標が複数あるときは元の乗降制限で乗車/降車専用が一意に定まる場合だけそのIDを選び、それ以外は拒否する。泉岳自然ふれあい館の `1155_0` と `1155_10` は合併せず、降車専用の元IDを保持する。
- 長町南の道路南側、市営2番 `7111_10` に接する西2側待合歩道の小範囲（緯度38.224360〜38.224405、経度140.876110〜140.876150）。既存の公式[のりば図](https://www.kotsu.city.sendai.jp/wp-content/uploads/2026/03/r06_nagamachi_minami.jpg)（SHA `623fdc87e7f9180adaebf5b2417541ddf8ec8a8ab380b46ef323e0bd5ae0faf7`）の道路南側動線と、固定GTFS pole位置へ保守的に登録した開発用の地上アクセス範囲。出発・到着を別reviewとし、各1分・表示距離8mは未実測の計画仮定。道路横断・区役所建物内・7/8番・駅階段・他出入口は含めない。GPS精度、閉鎖や現場の状況、バリアフリー所要時間は保証しない。

既存の荒井・泉中央・仙台・長町・長町南の方向別駅接続は変更していない。乗車前/最後の乗車後にこのリンクを通る場合は、乗換と区別して駅アクセスとして表示する。地下鉄駅の概略中心座標から出入口を推定しない。病院入口など確認不足の地点や、未承認市外poleは `unreviewed_coordinate_access` と元座標を返して対象外にする。仙台市立病院は公式accessに敷地内バス停の記載があるが、入口から具体poleへの座標動線を今回確定できず追加していない。公式HTMLのローカル取得はReadTimeoutとなり、自動的な別経路取得や推定による承認はしていない。

### 22.3 今回の固定条件・検査範囲

新しい境界の条件は、通常座標adapterを呼ぶ前に既存raw oracleから固定した。全て2026-11-19 09:00、最早到着・最大3乗車/180分。`normal_coordinate_cases_20261017.json` をPython・HTTP・Chromeの共通根拠にする。

| 地点（正確な元pole） | 到着目安 | 確認する内容 |
| --- | --- | --- |
| 附属小学校前 `2005_50` → 東仙台営業所前 `2041_0` | 09:38 | 市営バスだけ、通常UIから選択 |
| 霞の目 `5227_10` → 泉中央駅2番 `1085_12` | 11:06 | bus→南北線→レビュー済み地上出口動線 |
| 仙台駅5番 `50_850` → 泉岳自然ふれあい館降車pole `1155_0` | 10:48 | 駅アクセス→南北線→市営バス |
| 霞の目 `5227_10` → 芦口小学校前 `7605_10` | 11:07 | bus→南北線→bus |
| 長町南西2側の確認済み待合歩道 → 長町駅西口 `6008_10` | 09:24 | 入場徒歩1分、bus限定、具体便・順序維持 |

Pythonの新6境界回帰（遅延構築を含む）はローカルとCIで成功した。全5条件についてraw最適到着と実旅程の全witness（元便・運行日・sequence・乗降・clock・有向接続）を照合する。市外、未確認徒歩、他標柱への非alias、乗車証/同意不正、10/25・11/22・12/1・期間前の拒否、11/30 09:38を追加確認する。通常運賃未選択の同一ODは既存backendへ委譲され、元のmax_visited診断付き503となった。この失敗を無料検索の200に読み替えず保持する。通常運賃側の全OD性能改善は今回の変更対象ではない。

新ChromeはIDフォームを使わず、通常 `RouteSearchPage` のPlaces入力・候補選択、既存運賃設定、同意、検索ボタン、`RouteCard` と `RouteDetailPage` を操作する。キー不要CIではGoogle Placesの上流応答だけをv1契約で固定し、アプリ自身のautocomplete/details変換・HTTP・routingは実装を使う。これは実Placesへの疎通や、実際の施設検索が同じ座標を返す証明ではない。地図の基盤描画SDKは既存Flutter platform契約のCI表示面で置き換え、実 `MapPickerPage` の長押しcallback→選択点→確定→通常検索という契約を確認する。**実Google Maps SDKの地図配信・地図上のhit test・キー設定までをChrome成功と扱わない**。既存IDフォームのChrome4条件も別途維持する。

初回コード `9e22e97d40fa1cdee10251c336444fd092172334` の通常CI [39034453535](https://github.com/kaeruko/tobus_go/actions/runs/39034453535) はFlutterの新しい負例fixtureで停止した。日本語JSONに実APIと同じUTF-8 Content-Typeがなく、期待する時計根拠検査より前に `Contains invalid characters` となっていた。`70f06734052b35abd0fdd6bd32867c6c365269bf` で正しいHTTPメタデータを明記し、意図的に根拠を落とした応答本文と期待するFormatExceptionは維持した。文字コードを順に試すfallbackは追加していない。

新Chromeの先行run [39034453513](https://github.com/kaeruko/tobus_go/actions/runs/39034453513) と診断run [39044327132](https://github.com/kaeruko/tobus_go/actions/runs/39044327132) は、通常画面の最初の4 OD・カード・詳細まで成功したが、地図確定後の「長町駅西口」入力で停止した。診断は入力controllerが空、focus=falseで、autocomplete未送信だった。`0162184aae0f7671f194d2acc6b7e012a7ac586d` では実利用と同じ入力欄tapを行い、画面復帰時のfocus処理を終えてから入力し、focusと元のquery文字列も検査する。providerへ座標を直接代入して成功させる変更や、OD・日付・期待到着・backendの差し替えは行わない。これらの失敗runを成功根拠には使わない。

run [39044787470](https://github.com/kaeruko/tobus_go/actions/runs/39044787470) では通常画面のChromeと地図確定後の09:24着まで成功したが、続く既存一括IDフォームの初期表示で `336/339` が見つからず停止した。開発サーバーが既存test APIへ `coverage_label` を渡しておらず、便数・路線数の表示metadataだけが欠けていた。`89c45aecc651b3198de0c95050a333bb0d518b2f` で同じmunicipal reviewのラベルを渡し、実HTTPにもその同一性検査を追加した。ローカルの実開発app startup/capabilitiesでも既存ラベルの保持を確認した。旧Chromeの期待する路線数・便数や製品フォームは変更しない。`0ee73d45be80ead003c32bf3c932cd02f19dd747` では地図始点の候補カードも実際に開き、同じ候補ID・推定徒歩・通常運賃不明・追加支払0円を詳細へ保持する検査を追加した。

### 22.4 性能と検証結果の記録先

`benchmark_sendai_normal_coordinates.py` は同一原入力・同じ3 OD（上表のbus→rail、rail→bus、複数乗換）・日付/時刻/3乗車/180分・各3回を別プロセスの旧ID入口と通常入口で比較する。最大RSSはLinux high-water markで、保有heapだけの値ではない。最初のローカル比較は旧入口362,256 KiB、通常接続430,452 KiB、起動5.259→6.828秒だった。従来normal bus graphの重複構築が原因であり、開発opt-inのときだけ通常運賃が要求されるまで既存backendの構築を遅延する最小修正を行った。通常構成は従来どおりで、検索途中の代替backend選択はしない。

成功した実データrun [39046157376](https://github.com/kaeruko/tobus_go/actions/runs/39046157376)、実装 `1f645e911086c8ddcbc26ba637db6746f2fe76a6`、Linux Python 3.12の確定値は次のとおり。ローカルASGI/TestClientで通常HTTP契約の変換まで計時し、実インターネット往復・Places待ち・端末描画時間は含まない。

| 同条件の測定 | 旧ID入口 | 通常座標入口 |
| --- | ---: | ---: |
| 起動 | 6.152秒 | 6.267秒 |
| 最大RSS | 369,700 KiB（361.0 MiB） | 371,128 KiB（362.4 MiB） |
| bus→rail→泉中央2番poleの中央値 | 1.935秒 | 2.150秒 |
| 仙台5番pole→rail→busの中央値 | 3.619秒 | 3.570秒 |
| bus→rail→busの中央値 | 1.983秒 | 1.962秒 |

今回の3 ODは第21.6節の1.55〜1.92秒の3 ODとは異なるため、異なる経路同士を回帰倍率として比較しない。通常運賃backendを実際に要求した場合にはそのgraphも保持される。上表のメモリ比較は本人所持passを明示選択した入口の測定であり、全設定・全ODの上限ではない。

通常入口の追加処理も、同じbenchmarkのnormal profile・同じ9検索で計時した。`search_practical_subway` 呼出し時間を外側のHTTP所要から引いた差は6.2〜10.0msで、両端の座標照合は計2.6〜3.4ms、Candidate変換は0.5〜0.7msだった（ローカルLinux、2026-10-17）。原関数をそのまま呼ぶ計時だけを加え、全期待到着を維持した。残る主な負荷は既存の日付別network構築・共通探索であり、別探索器や新しい結果cacheは追加しない。代表OD間やrunner間の秒数差を、座標境界だけの遅さや全OD性能の保証に読み替えない。

別プロセスのCI比較ではbus→railだけ通常入口が約0.21〜0.30秒大きい結果が続いたため、同じ読込済みreviewed networkを同一プロセスで使い、normal/IDの先後を交互にした3回ずつの追加計時も行った。OD・日付・180分/3乗車・元期待到着は同じで、GC callbackは所要時間の観測だけを行い、回収実行やthreshold変更はしない。bus→rail中央値はID1.660404秒、normal1.660428秒、rail→busは3.003893/2.573932秒、複数乗換は1.846420/1.729619秒だった。各検索のGC所要は約0.07〜1.30秒と変動し、恒常的な入口だけの約0.3秒増は再現しなかった。この補助比較はローカル・同一プロセスであり、CIのfresh-process起動/RSS測定を置き換えない。日付別構築とGC負荷は今後の改善対象として残す。

本番公開前には、一般住所/施設の実ジオコーディング点から具体標柱/出入口までの徒歩根拠の拡張、登録範囲の現場確認・利用者検証、実Google Places/Mapsのキー付き疎通と地図操作、通常運賃側の探索上限、未接続の実時間ナビ、公開表示・サポート範囲の整理が残る。東京、アプリID、Firebase、AWS/S3、配布・deployには変更を加えない。

### 22.5 変更箇所と再利用の対応

| ファイル | 変更理由・保持する既存実装 |
| --- | --- |
| `api/sendai_coordinate_routes.py`・`api/sendai_coordinate_access.py` | 通常座標入力の安全な入口と既存旅程→Candidate変換、有限な地上アクセスreview。探索は既存practical/shared v2の呼出しのみ |
| `api/gtfs_route_backend.py`・`api/route_engine.py`・`api/app/route_endpoint.py` | 元の近傍候補計算を共用、明示同意の共通入力、実Policyが既にquoteした結果の維持。東京の探索・通常運賃のdecoratorは保持 |
| `api/app/sendai_runtime.py`・`api/sendai_practical_network.py` | 開発opt-inと重複graphの遅延構築、既存networkの許可具体便集合によるbus限定。元Adapter・時計・駅リンク・Policyは保持 |
| `lib/core/city_profile.dart`・`lib/services/fare_policy_preferences.dart`・`lib/pages/fare_policy_settings_page.dart` | debug opt-in時だけ既存運賃設定に本人所持passを追加。通常運賃の既定、東京選択肢、通常構成の保存keyは保持 |
| `lib/pages/home_page.dart`・`lib/pages/map_picker_page.dart`・`lib/providers/route_search_provider.dart` | 既存通常画面・地図Picker・providerへ開発選択、同意、仙台の初期地図位置を接続。新検索画面や停留所一覧は作らない |
| `lib/services/route_search_service.dart`・`lib/models/route_models.dart` | 通常 `/route` の既存モデルへ時計根拠・元ID・FareQuoteを保持し、仙台へ東京鉄道ID解決を適用しない。予定モデルの日本時間を明示し、東京の解決呼出し・日時処理は保持 |
| `lib/widgets/route_card.dart`・`lib/widgets/route_detail_widgets.dart`・`lib/pages/route_detail_page.dart` | 既存カード/詳細で到着目安・未実測徒歩/乗換・本人所持条件を表示。予定モデルへ未接続Realtime開始を出さない |
| `api/tests/test_sendai_normal_coordinates.py`・`api/tests/fixtures/sendai_subway/normal_coordinate_cases_20261017.json` | 新座標境界6回帰と固定5条件。既存raw oracle・元便witness・旧ID契約を正解基準として再利用 |
| `test/sendai_normal_result_test.dart`・`test/fixtures/sendai_normal_result.json`・`integration_test/sendai_normal_chrome_test.dart` | 共通結果の保持/欠落拒否、通常RouteSearchPageの実操作と旧フォームとは別のChrome回帰 |
| `scripts/serve_sendai_normal_local.py`・`scripts/check_sendai_normal_http.py`・`scripts/benchmark_sendai_normal_coordinates.py`・`scripts/sendai_normal_places_fixture.py`・`.github/workflows/sendai-normal-coordinates.yml` | localhost開発起動、実HTTP比較、同条件性能測定、CIのPlaces上流fixture、変更部分の実データgate。デプロイ工程は追加しない |

`docs/sendai-shared-network-design.md` は本節の実装結果・検証・制約を追記する。第21節の承認路線review、manifest、8,142具体便・467pattern・2,127 bus pole、22方向リンクと運行期間のデータは変更しない。

### 22.6 検証済み実装と成功CI

接続境界の実装は [`6b4e7e3ef0b3295121df17adbe8e074e73572ba5`](https://github.com/kaeruko/tobus_go/commit/6b4e7e3ef0b3295121df17adbe8e074e73572ba5)、共通UI/契約の接続は [`9e22e97d40fa1cdee10251c336444fd092172334`](https://github.com/kaeruko/tobus_go/commit/9e22e97d40fa1cdee10251c336444fd092172334)。HTTP fixture・focus・旧capabilities metadata・地図始点の詳細検査を経て、日本時間の詳細再検索まで確認した最終実装は [`1f645e911086c8ddcbc26ba637db6746f2fe76a6`](https://github.com/kaeruko/tobus_go/commit/1f645e911086c8ddcbc26ba637db6746f2fe76a6)。

| 成功した実行 | 確認した結果 |
| --- | --- |
| [通常CI #39046157369](https://github.com/kaeruko/tobus_go/actions/runs/39046157369) | `1f645e91`・completed/success、全7ジョブ成功。Python API912件（450.788秒）、Flutter662件（新3件含む）、共通SearchCore v2 Python 3.11/3.12、Windows、東京/仙台Android・iOS buildとidentity/Firebase分離、repository safety。Dart解析エラー0、非致命的lint100件 |
| [通常座標・実データ/Chrome #39046157376](https://github.com/kaeruko/tobus_go/actions/runs/39046157376) | 同じSHA・completed/success。新6 Python回帰30.903秒、独立raw oracleの5条件・元具体便witness・実通常HTTP/旧ID wire一致、乗車証/同意/未承認座標・日付境界、同条件性能比較、通常RouteSearchPageのPlaces候補→検索→5候補カード/詳細、MapPicker選択/確定、11/19 09:00を保持する詳細再検索picker、同じserver上の既存一括IDフォーム4経路 |
| [既存固定4経路Chrome #39034453664](https://github.com/kaeruko/tobus_go/actions/runs/39034453664) | `9e22e97d`・completed/success。元の固定4経路用form/API/入力/期待値を変更せず確認済み。その後の変更は通常座標UI・開発serverの表示metadataとその検査で、旧固定testと元reviewは保持 |

実HTTPの成功markerは `NORMAL_SENDAI_REAL_HTTP_OK`。通常画面Chromeはrouting responseをmockせず、上流Places fixtureとMap描画面fixtureの検証限界は22.3節のとおり。期間末日11/30は09:38着、10/25・11/22・12/1・期間前は拒否し、pass未選択の通常運賃経路や不正な敬老選択を無料成功へ読み替えない。有効な本人の乗車証所持は利用者による前提・明示選択であり、実所持をオンライン認証したという意味ではない。新しい全路線監査や旧112組gateを別途繰り返さず、今回の境界と通常CIを検査した。

最終の成功記録コミットは本書だけを変更し、上記の検証済みコード・テスト・データを保持する。本番公開は行わない。一般住所からの広い歩行接続、実Googleサービスのキー付き疎通、現場確認、通常運賃backendの上限/性能、未確認事業者・駅接続・市外部分区間・特別ダイヤと次版は残課題である。

## 23. 東京・仙台の徒歩アクセス処理を共通化（2026-10-18）

### 23.1 既存挙動を維持する抽出

開始main `a028dbf847d527a622f82f35c64bb889de305664`、通常CI [39047429833](https://github.com/kaeruko/tobus_go/actions/runs/39047429833) と通常座標/Chrome [39046157376](https://github.com/kaeruko/tobus_go/actions/runs/39046157376) は成功済み。開始時の未マージPR・進行中CIは0件だった。本段階は徒歩処理の共通化であり、対応路線・停留所・乗換拠点・徒歩許可範囲を追加する工程ではない。

`api/walking_access.py` にHaversine距離、元の列挙順を保つ距離候補、同距離先着のnearest、GTFSの距離/ID順、徒歩換算、徒歩表示集計、方向別地上review照合を集約する。`api/toei_engine.py`・`api/tokyo_route_engine.py`・`api/gtfs_route_backend.py`・`api/sendai_coordinate_routes.py` はこの処理と既存 `WalkStep` を使う。`api/sendai_coordinate_access.py` は既存の許可設定と長町南の地上reviewデータを保持し、polygon判定やendpoint生成の都市別実装を持たない。graph辺の実経過時間は既存共通 `reviewed_walk_time.py` をそのまま使い、review済み例外と証明対象の実装を維持する。

東京の空間indexの候補順・空の場合の元graph照合・駅filter・同距離先着、徒歩の距離切捨て/丸め順、先頭徒歩への合算、80m/分と最低1分/costの適用順を保持する。共通GTFSの候補距離→具体ID順、整数表示、レビュー済み明示徒歩分数も保持する。仙台では既存の600m候補調査範囲を徒歩許可半径として扱わず、0.01mの座標同一性か個別の方向別地上reviewを要求する。

長町南2番 `7111_10` の既存polygon・原GTFS版・公式のりば図SHA・往復を別々に記載した説明・推定1分/8mを変更しない。8mから時間を再推定せず、公式実測値として扱わない。反対側・他の標柱・建物内へ拡張しない。既存22方向のbus/subwayリンクと地下鉄線間の標準時間/余裕は変更しない。

### 23.2 表示・無料条件・回帰

APIの徒歩は既存共通 `WalkStep.to_mapping()` と徒歩集計へ接続し、仙台の `planning_details`（具体ID、予定時計、標準時間と余裕、根拠SHA、`physical_walk_meters=null`、未実測・未保証）を維持する。未知の実歩行距離を実測0mと表示せず、Flutter側の既存Candidate/StepSeg・RouteCard/RouteDetailPageをそのまま使う。Flutterソース・検索画面の追加/改作は行わない。

8,142具体便・467pattern・2,127 bus pole、乗降制限、無料scope、本人の有効な乗車証所持と明示選択/同意、通常運賃不明、敬老非無料、市外89便の除外、10/25・11/22の除外と11/30末日は従来どおり。SearchCore v2・GTFS Adapter・運賃Policy・駅レビューは変更しない。

ローカルPython 3.12で徒歩関連31件が成功した（新共通境界8件と既存23件、23.387秒）。既存5 ODの通常座標APIは独立raw oracleと具体便witnessに一致し、徒歩全fieldを変更前fixtureと照合した。到着目安は順に附属小→東仙台09:38、霞の目→泉中央2番11:06、仙台5番→泉岳10:48、霞の目→芦口11:07、長町南の確認済み待合歩道→長町駅西口09:24のまま。同一プロセスで未変更mainの座標Adapterとも照合し、5 Candidateは全項目一致した。

全応答の固定hashは、既存input_versionがreview内frozensetの日付reprに依存し、別プロセスでは変わるため回帰基準にできなかった。探索の期待値や実データを変更せず、変更前に採取した全徒歩Stepを `normal_coordinate_parity_20261017.json` へ保存する。新テストの未知距離・方向・曖昧標柱・未確認近接地点の負例と、既存oracleの5実経路・運賃/同意/日付負例を維持する。input_version生成の安定化は本段階には含めない。

新共通module・東京入口・既存徒歩helperの変更も通常座標workflowの対象とし、同じ既存実データ/HTTP/Chrome gateを再利用する。実Places/Maps上流は第22節と同じCI契約fixtureであり、外部サービスの実疎通・現場の徒歩安全性まで認定しない。性能・GitHub Actionsの確定結果と実装SHAは次項へ追記する。

一般地点からの徒歩根拠の拡張・現場確認・実Googleサービス・通常運賃backendの既存上限等は第22節の残課題のまま。本番公開、AWS/S3、Firebase、アプリID、配布・deploy操作は行わない。

### 23.3 既存証明契約の維持

最初の共通化 `e76861a8fd0bd6cd87978dd0f10d92c93b5a95c9` の通常CI [39050860721](https://github.com/kaeruko/tobus_go/actions/runs/39050860721) では、Windowsの既存静的time証明が `unreviewed_transition_implementation contract_index=7` を検出した。既存共通 `walk_edge_elapsed_minutes` 内の距離換算も新helper呼出しへ置き換えたため、証明対象のASTが変わっていた。徒歩の31差分回帰は成功していたが、このCIを成功として扱わない。

`9136b02fb7a4b30fc1cd52c96e526c87d744bb51` で不要な `reviewed_walk_time.py` の変更全体を元mainのblob `dcb08364c20f9ca59ff663e239e5bd0e42bfb05a` に戻した。既存helperは元から都市共通であり、座標の距離候補/徒歩表示の抽出に変更は不要だった。証明ゲートの期待AST・判断条件・入力・経路期待値は変更せず、旧AST SHA256 `b5fe6b98356e9c1f70720418e8b874381a0acfac2f5d39278b6b599235548380` との一致と徒歩25件の再成功を確認した。座標アクセスの新共通化は保持する。

### 23.4 最終の成功CI・実データ・性能

検証済み実装は [`9136b02fb7a4b30fc1cd52c96e526c87d744bb51`](https://github.com/kaeruko/tobus_go/commit/9136b02fb7a4b30fc1cd52c96e526c87d744bb51)。初回の証明契約違反を修正したこの同一SHAで、次の2 workflowの `completed/success` を確認した。

| 成功した実行 | 確認した範囲 |
| --- | --- |
| [通常CI #39051058234](https://github.com/kaeruko/tobus_go/actions/runs/39051058234) | 全7ジョブ成功。Python API920件（650.916秒）、Windows277件（54.408秒）、共通SearchCore Python 3.11/3.12各89件とLambda image import、Flutter analyze/unit・東京/仙台Android/iOS build・identity/Firebase分離。解析errorは0、非致命的lint100件は前段と同じ |
| [通常座標・実データ/Chrome #39051058208](https://github.com/kaeruko/tobus_go/actions/runs/39051058208) | 差分31件（30.460秒）、既存独立raw oracleの5 OD/具体便witness、通常HTTP/旧ID旅程一致と負例、性能測定、通常RouteSearchPageの5経路・Places候補/MapPicker契約・カード/詳細・日本時間再検索、既存IDフォーム4経路がすべて成功 |

実HTTPの成功markerは `NORMAL_SENDAI_REAL_HTTP_OK`。通常画面Chromeは16:54:04 UTC、既存ID Chromeは17:02:50 UTCに `All tests passed.` となった。Places/Map描画面のfixture範囲は第22節と同じで、実外部Googleサービスへの疎通成功に読み替えない。review済み9徒歩Stepの全fieldと5経路の元期待到着を維持した。

同じbenchmark・同じ3 OD/日付/3乗車/180分・各3回のLinux Python3.12実測を示す。ASGI/TestClientの通常HTTP契約を含み、外部通信・Places応答・画面描画の所要ではない。

| 同条件の測定 | 旧ID入口 | 共通化後の通常座標入口 |
| --- | ---: | ---: |
| 起動 | 6.055秒 | 6.179秒 |
| 最大RSS | 370,128 KiB | 369,924 KiB |
| bus→rail→泉中央2番poleの中央値 | 1.933秒 | 2.126秒 |
| 仙台5番pole→rail→busの中央値 | 3.600秒 | 3.467秒 |
| bus→rail→busの中央値 | 1.944秒 | 1.955秒 |

第22.4節の共通化前の通常入口は起動6.267秒・371,128 KiB・同じ3 ODの中央値2.150/3.570/1.962秒。今回の測定に明確な増加は観測されなかった。runner・GC等を統制した速度向上の証明や全ODの時間上限は主張しない。新しいgraph・cache・探索器による性能調整は行っていない。

この後の成功記録コミットは本書と共通設計書だけを変更し、検証済み実装の全コード・fixture・workflow・路線/駅レビューを保持する。公開可能範囲の拡張や本番公開は行わない。

## 24. 一般住所・施設座標の幾何学的徒歩アクセス（2026-10-18）

### 24.1 継承する明示接続と新しい推定範囲

開始mainは `744b8c9a893d969c31ce8e4436d524949f89cf30`。未マージPR・進行中CIは0件、同mainの通常CI [39052251826](https://github.com/kaeruko/tobus_go/actions/runs/39052251826) は成功していた。第22〜23節は当時の実装・検証記録として保持する。開発opt-in・本人の有効ふれあい乗車証所持/明示選択・推定モデルへの明示同意は従来どおりで、公開runtimeへの自動適用はない。

同一標柱座標と長町南の方向別reviewは、元のendpoint辞書をそのまま優先する。具体ID・根拠・明示徒歩1分/8m・既存5 ODの徒歩Step全fieldを一般推定で上書きしない。明示地点の曖昧な標柱やreview重複は依然拒否し、例外を捕捉して一般推定へ切り替えない。

明示地点に該当しない一般座標だけ、市内完結承認便が使う具体bus poleへのHaversine距離から徒歩を推定する。地下鉄駅中心・出入口・ホームを新しい候補にしない。一般座標→bus poleのアクセスと、既存22方向のbus/subway乗換を別の責務として保持する。反対側の道路・河川・建物出口・駅出入口の通行可能性は判定できない。一般地点を出入口や通行確認済みリンクとして登録しない。

`basis=haversine_80m_per_minute_estimate`、元の具体ID/feed版、未丸めの幾何距離、80m/分の切上げ時間、整数表示距離を保持する。`physical_walk_meters=null`、未実測・接続未保証・経路未確認を明記し、公式経路図のSHAを推定徒歩の証拠に転用しない。表示には既存WalkStep/カード/詳細の推定noticeを使用し、製品Flutterソースは変更しない。

### 24.2 候補評価・再利用・上限

共通 `nearby_stops` の距離→具体ID順を使い、一般地点の出発側は原GTFSのpickup許可、到着側はdropoff許可で別々に候補を作る。初期評価範囲は600m・各6件であり、仙台の最適値・徒歩可能範囲ではない。eligible件数・選択ID・上限により未比較となる全IDをmetaに残し、600m外も比較済みとは主張しない。従来の明示地点にはこの一般候補フィルタをかけない。たとえば泉中央の乗車専用標柱は、既存の確認済み地下鉄アクセスの終点にもなり得る。個々のバス乗降制限は従来のgraphが保持する。

最大36組を既存 `search_practical_subway → search_network → search_labels` で比較する。日付別networkの構築部分を抽出し、同じnetwork/日付窓/bus_onlyに限って1リクエスト内で再利用する。新しい探索器・枝刈り・永続cache・別backendは追加しない。通常GTFS batchの時計profile制限を迂回せず、既存の地下鉄推定時計・元便復元・provenance・Policyを保持する。

GTFS座標backendの既存の完成旅程比較を `coordinate_pair_objective` へ抽出して共用する。最早到着は目的地への徒歩を加えた到着→既存planning cost→乗物到着→両端の候補順、少乗換は乗換数→既存planning cost→最終到着→乗物到着→候補順を維持する。出発前の徒歩を発車可能時計へ、到着後の徒歩を最終到着・総時間へ一度だけ加える。最大3乗車・全行程180分・各探索max_visited=100,000・リクエスト全体15秒を維持し、構築後にも残deadlineを既存探索へ渡す。

候補比較の完了は選択された具体endpoint組の範囲に限る。`all_geographic_candidates_compared=false` と限定された最適性scopeを返す。deadline/max_visited等で失敗した場合は候補を返さず、同一の元例外・reason・core診断に完了組数/未比較組/構築数を付記してHTTP 503へ渡す。通常運賃側の既存503を無料成功へ読み替えない。一般アクセスで両端が同じ具体poleになる組はゼロ乗車の分類を診断に残し、無料の徒歩経路や便の循環を作らない。

`walking_access.py` のHaversine/候補/徒歩分数/距離丸め/集計、GTFSの完成旅程比較、既存の実データnetwork・SearchCore・時計serializer・WalkStepを再利用する。`reviewed_walk_time.py` と静的証明対象の徒歩遷移・証明ゲートは変更しない。8,142便・467pattern・2,127 bus pole・22方向リンク・市外89便除外・原GTFS時計/運行日/乗降・通常運賃不明と追加支払0円・敬老非無料の条件も変更しない。

### 24.3 先に固定した独立期待値と負例の分類

施設の代表座標は[太白区役所](https://geoshape.ex.nii.ac.jp/city/resource/04104A1989.html) `(38.224395,140.877212)` と[若林区役所](https://geoshape.ex.nii.ac.jp/city/resource/04103A1989.html) `(38.244180,140.900748)` を使用する。代表点は実測出入口を意味しない。標柱を数mずらした正例ではなく、実在施設の代表座標で徒歩時間が発生する条件を使う。変更後APIへ問い合わせる前に、元GTFS/CP932の独立layer scanと独立の幾何距離/80m分換算で次を固定した。日付はすべて2026-11-19、出発09:00、最大3乗車/180分。

| 新OD | 比較する候補組 | 独立期待最終到着 | 確認する意味 |
| --- | ---: | --- | --- |
| 若林区役所代表点→太白区役所代表点 | 6×6=36 | 10:04 | 両端とも一般地点。バス＋地下鉄＋両端徒歩 |
| 太白区役所代表点→泉中央の既存具体pole `1085_12` | 6×1=6 | 09:46 | 最寄りの乗車pole `7111_51` の原時刻表最終到着11:26より、少し遠い候補が早い |
| 霞の目の既存具体pole `5227_10`→太白区役所代表点 | 1×6=6 | 11:00 | 目的地までの徒歩を含む比較・バス＋地下鉄 |

fixtureは各候補の具体ID/距離/徒歩分、rawで成立する組/不成立組/最終到着を保持する。期待値を製品応答のコピーから作らない。選ばれた具体便・停車順・乗降・時計・既存乗換は独立raw witnessでも検査する。従来5 ODの09:38/11:06/10:48/11:07/09:24と徒歩Step全fieldは保持する。

従来422だった「標柱の数m近傍」「病院付近の未review地点」「反対側を含み得る近接座標」は、一般推定候補として許可し、review済みとは表示しない。元の負例 `(38.275854,140.876702)` は原CSVと独立距離計算でeligible9→選択6、病院付近 `(38.2319,140.8893)` はeligible15→選択6、外側 `(38.2907,140.9997)` はeligible0→候補なしと個別に固定する。長町南7番の正確な座標は従来どおり別ID `7111_11`。承認外の沼田/高橋poleを候補へ追加せず、近傍に承認poleが存在しない場合は共通GTFS入口と同じ200/候補なしとなる。曖昧な同一座標・review重複、同意なし、不正pass、未承認日、徒歩で未確認の日境界へ入る入力は拒否を維持する。逆方向reviewを推定で捏造しない。

合成負例には具体ID/同名別方向・乗降専用・両端の許可候補なし・0/80/80.001/600mの換算・半径外・便への乗り遅れ・出発徒歩の日境界・目的地徒歩による順位逆転・少乗換/既存cost順・明示接続と一般候補の重複・候補上限/未比較ID・max_visited/deadline時の元例外保持を含めた。河川/道路横断を自動判定できるというテストや主張は行わない。

### 24.4 検証・性能の記録

ローカルPython3.12で、既存徒歩/東京/5 ODの31件と初期一般接続9件の計40件が成功した（28.948秒）。施設3 ODの独立raw期待値・具体便witness・構築1回と未承認日/候補なしの追加実データ2件も成功した。構築共有なしに候補ペアごとにnetworkを作る案は採用しない。36組は1構築・36既存探索、6組は1構築・6既存探索となる。

`benchmark_sendai_general_coordinates.py` は同一runnerで開始mainと変更後コードを別プロセスで実行し、固定3 OD＋上表3 ODを同じ原GTFS/時刻/上限/各3回で比較する。network構築数・探索回数/時間・通常HTTP契約を含む所要・最大RSSを記録する。旧mainの一般座標は422であり、その拒否時間を変更後の成功検索の性能ベースラインとは扱わない。固定3 ODだけが前後の同じ成功動作の比較になる。

実HTTP、Places候補→既存カード/詳細、review済み地点および一般地点のMapPicker確定、旧IDフォーム4経路、通常CI全7ジョブは既存workflowで検証する。Google Places上流とMaps描画面は従来と同じCI fixtureであり、実Googleサービス・実地図タイル/ヒットテスト・現場での歩行疎通を認定しない。GitHub Actionsの最終SHA・URL・確定測定値は完了後に本項へ追記する。本番公開、Firebase、AWS/S3、本番API、アプリID、ストア、deployは変更しない。

初回実装 `dac58a6659cf56afbd0d8934730486059da01d1b` の実データrun [39054824284](https://github.com/kaeruko/tobus_go/actions/runs/39054824284) は、46差分回帰・実HTTP8 ODを成功したが、続く前後性能比較で `time_limit_sec`・HTTP 503となり停止した。直前の実HTTPの36組比較も14.861秒であり、15秒の既存上限に近かった。このrunを通常画面Chromeの成功根拠にはしない。

network構築は既に1回だったが、各組で約22万行の元stop_timesから最大時計を再走査し、同じnetworkの入力versionも再計算していた。最大時計と入力versionの同じ計算をrequest-local metadataへ保持し、36組の各計算を1回にする。元の日時窓計算式・version生成式・時計・比較・候補6件・36組・3乗車/180分・15秒・max_visitedを変更しない。元の失敗ログ・例外は上記runに保持し、benchmarkも今後は各sampleの測定と失敗HTTP本文を即座に残してから停止する。
