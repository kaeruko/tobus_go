# Dockerfile
FROM python:3.11-slim

# Lambdaの標準ディレクトリ
WORKDIR /var/task

# 1. ライブラリをインストール
# (api/requirements.txt ではなく、直下の requirements.txt を指す)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. プログラムとデータをコピー
# (api/ フォルダではなく、今あるファイルをすべてコピー)
COPY . .

# 3. 実行コマンド
# (api.server ではなく server になります)
CMD ["server.handler"]