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
