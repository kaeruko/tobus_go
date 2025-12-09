# Dockerfile

# 軽量なPython 3.11を使用
FROM python:3.11-slim

# 作業ディレクトリを作成
WORKDIR /app

# 1. ライブラリのインストール
# キャッシュを効かせるために先にrequirementsだけコピーする
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. ソースコードをコピー
COPY api/ ./api/

# 3. データをコピー
# ここがポイント！ローカルでダウンロード済みのデータをイメージの中に埋め込む
COPY data/ ./data/

# 4. パスを通す
# これがないと api フォルダ内の import initialize_data などでエラーになる場合がある
ENV PYTHONPATH=/app/api

# 5. Lambda起動コマンド
CMD ["api.server.handler"]