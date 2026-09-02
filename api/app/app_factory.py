import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


StartupHandler = Callable[[FastAPI, str], Awaitable[None]]
_SUPPORTED_BACKEND_CITIES = ("tokyo", "nagoya", "sendai", "yokohama")


def _configured_backend_city() -> str:
    key = os.getenv("APP_CITY", "tokyo")
    if key not in _SUPPORTED_BACKEND_CITIES:
        raise RuntimeError(
            f'Unsupported APP_CITY="{key}". '
            f"Expected one of: {', '.join(_SUPPORTED_BACKEND_CITIES)}"
        )
    return key


def install_city_isolation(app: FastAPI, city: str) -> None:
    if city not in _SUPPORTED_BACKEND_CITIES:
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
        from .tokyo_runtime_fast import setup_on_startup
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
    elif city == "sendai":
        from .sendai_routes import register_sendai_routes
        from .sendai_runtime import setup_sendai_on_startup

        startup = setup_sendai_on_startup
        route_registrars = (register_sendai_routes,)
        title = "Sendai Route API"
    elif city == "yokohama":
        from .yokohama_routes import register_yokohama_routes
        from .yokohama_runtime import setup_yokohama_on_startup

        startup = setup_yokohama_on_startup
        route_registrars = (register_yokohama_routes,)
        title = "Yokohama Route API"
    else:
        raise RuntimeError(f"unreachable backend city branch: {city!r}")

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
        if city == "tokyo":
            from .runtime import refresh_realtime_bus_positions
            from .services.tokyo_realtime_provider import TokyoRealtimeProvider

            app.state.realtime_provider = TokyoRealtimeProvider(
                app.state.TM,
                refresh_realtime_bus_positions,
            )

    @app.get("/warmup")
    async def warmup() -> dict[str, str]:
        # ASGI startup finishes before requests are served. Reaching this route
        # therefore guarantees that this backend instance has completed its
        # city runtime initialization without invoking Places or route search.
        return {"status": "ready", "city": city}

    for register in route_registrars:
        register(app)
    register_fare_routes(app)
    return app
