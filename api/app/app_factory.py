from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .runtime import setup_on_startup
from .routes import register_routes
from .train_routes import register_train_routes


def create_app(mode: str) -> FastAPI:
    app = FastAPI(title="Toei Route API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _startup() -> None:
        await setup_on_startup(app, mode)

    register_routes(app)
    register_train_routes(app)
    return app
