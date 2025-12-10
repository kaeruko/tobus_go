# これ重要！AWS公式のLambda用イメージを使う
FROM public.ecr.aws/lambda/python:3.11

# 1. ライブラリをインストール
# Lambda用イメージでは ${LAMBDA_TASK_ROOT} (/var/task) に置く決まりがあります
COPY requirements.txt ${LAMBDA_TASK_ROOT}
RUN pip install -r requirements.txt

# 2. プログラムとデータをコピー
COPY . ${LAMBDA_TASK_ROOT}

# 3. 実行コマンド
# Lambda用イメージなら、これで正しく server.py の handler を呼んでくれます
CMD [ "server.handler" ]