import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


StartupHandler = Callable[[FastAPI, str], Awaitable[None]]


def _configured_backend_city() -> str:
    key = os.getenv("APP_CITY", "tokyo")
    if key not in ("tokyo", "nagoya", "sendai"):
        raise RuntimeError(
            f'Unsupported APP_CITY="{key}". Expected one of: tokyo, nagoya, sendai'
        )
    return key


def create_app(mode: str) -> FastAPI:
    city = _configured_backend_city()

    if city == "tokyo":
        from .routes import register_routes
        from .runtime import setup_on_startup
        from .train_routes import register_train_routes

        startup: StartupHandler = setup_on_startup
        route_registrars = (register_routes, register_train_routes)
        title = "Toei Route API"
    elif city == "nagoya":
        from .nagoya_routes import register_nagoya_routes
        from .nagoya_runtime import setup_nagoya_on_startup

        startup = setup_nagoya_on_startup
        route_registrars = (register_nagoya_routes,)
        title = "Nagoya Route API"
    else:
        # The Flutter profile exists so common UI capabilities can be designed
        # ahead of the backend. Do not silently serve Tokyo for Sendai.
        raise RuntimeError("Sendai backend is not implemented yet")

    app = FastAPI(title=title)
    app.state.city_key = city

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _startup() -> None:
        await startup(app, mode)

    for register in route_registrars:
        register(app)
    return app
