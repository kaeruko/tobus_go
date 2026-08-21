import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


StartupHandler = Callable[[FastAPI, str], Awaitable[None]]


def _configured_backend_city() -> str:
    key = os.getenv("APP_CITY", "tokyo")
    if key not in ("tokyo", "nagoya", "sendai"):
        raise RuntimeError(
            f'Unsupported APP_CITY="{key}". Expected one of: tokyo, nagoya, sendai'
        )
    return key


def install_city_isolation(app: FastAPI, city: str) -> None:
    if city not in ("tokyo", "nagoya", "sendai"):
        raise ValueError(f"unsupported backend city: {city!r}")

    @app.middleware("http")
    async def reject_cross_city_request(request: Request, call_next):
        requested_city = request.headers.get("X-App-City")
        if requested_city is not None and requested_city != city:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": {
                        "code": "city_mismatch",
                        "message": (
                            "Client/backend city mismatch: "
                            f"client={requested_city!r}, backend={city!r}"
                        ),
                    }
                },
            )
        return await call_next(request)


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

    from .fare_routes import register_fare_routes

    app = FastAPI(title=title)
    app.state.city_key = city

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_city_isolation(app, city)

    @app.on_event("startup")
    async def _startup() -> None:
        await startup(app, mode)

    for register in route_registrars:
        register(app)
    register_fare_routes(app)
    return app
