# みつける掲載コンテンツ

このディレクトリが「みつける」に表示する開発者編集コンテンツの正本です。

- `spots.csv` を編集します。
- 写真は `images/` に置きます。
- 1画像につきCSV 1行です。
- 同じ `stop_id` に複数画像を付ける場合は行を増やします。
- `comment` は同じ `stop_id` で1種類だけにしてください。2行目以降は空欄でも構いません。
- `image` を指定したら、そのファイルが `images/` に存在する必要があります。
- 対応画像形式は `.jpg` / `.jpeg` / `.png` / `.webp` です。

例:

```csv
stop_id,comment,image,caption
odpt.BusstopPole:Toei.Example,川沿いを歩くと気持ちいい。,example_01.jpg,バス停から川へ向かう道
odpt.BusstopPole:Toei.Example,,example_02.jpg,夕方の川沿い
```

公開はリポジトリ直下から次を実行します。

```powershell
python scripts/publish_explore_content.py
```

スクリプトはCSVと画像をすべて検証してから、画像を先にS3へ送り、最後に `spots.json` を更新します。検証に失敗した場合はS3を変更しません。
