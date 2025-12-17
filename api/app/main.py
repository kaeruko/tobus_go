from mangum import Mangum
from app.app_factory import create_app

app = create_app("lambda")
handler = Mangum(app, api_gateway_base_path="/default")