# みつける掲載コンテンツ

このディレクトリが「みつける」に表示する開発者編集コンテンツの正本です。

## ローカルCMS

初回だけStreamlitを入れます。

```powershell
python -m pip install -r scripts/requirements_explore_cms.txt
```

リポジトリ直下から起動します。

```powershell
python -m streamlit run scripts/explore_cms.py
```

CMSでは停留所名を検索して、通る系統（例: 上23）を選びます。
同じ停留所名・同じ系統に含まれる上り/下りのBusstopPoleはまとめて同じ掲載内容になります。
写真は一度に複数選択して追加でき、各写真に日本語・英語のキャプションを個別に設定できます。
複数写真の保存はまとめて検証され、途中で失敗した場合は新しく追加しようとした写真を残しません。

対象BusstopPoleの解決には次だけを使います。

- `odpt_BusstopPole.json` の `dc:title`
- `odpt_BusroutePattern.json` の `odpt:busroute`
- `odpt_BusroutePattern.json` の `odpt:busstopPoleOrder`

`odpt:note` は停留所の同定に使いません。

## CSVを直接編集する場合

`spots.csv` の形式は次です。

```csv
stop_name,route_id,comment,comment_en,image,caption,caption_en
押上駅前,odpt.Busroute:Toei.Ue23,スカイツリーが近い,Tokyo Skytree is nearby,oshiage_01.jpg,駅前から見たスカイツリー,Tokyo Skytree from the bus stop
押上駅前,odpt.Busroute:Toei.Ue23,,,oshiage_02.jpg,夕方,Evening view
```

- 1画像につきCSV 1行です。
- 同じ `stop_name + route_id` に複数画像を付ける場合は行を増やします。
- `comment` / `comment_en` は同じ `stop_name + route_id` で各1種類だけにしてください。2行目以降は空欄でも構いません。
- `comment_en` / `caption_en` は任意です。空欄の場合、英語UIでは日本語へ自動フォールバックせず、その編集文・キャプションを表示しません。
- 写真は `images/` に置きます。
- 対応画像形式は `.jpg` / `.jpeg` / `.png` / `.webp` です。
- 公開時に `stop_name + route_id` をODPTマスタへ完全一致させ、該当するBusstopPole IDすべてへ展開します。
- 0件一致や、別のCSVエントリ同士で同じBusstopPoleを取り合う場合はエラーで停止します。

## 公開

CMSの「S3へ公開」ボタン、または次を使います。

```powershell
python scripts/publish_explore_content.py
```

スクリプトはCSV・ODPTマスタ・画像をすべて検証してから、画像を先にS3へ送り、最後に `spots.json` を更新します。検証に失敗した場合はS3を変更しません。
