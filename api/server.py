from mangum import Mangum
from app.app_factory import create_app

# Lambdaで動かすなら "lambda" モードが適切です（S3からのデータ取得等が有効になるため）
app = create_app("lambda")

# これが必要です。Dockerfileの CMD [ "server.handler" ] はここを見ています。
handler = Mangum(app)