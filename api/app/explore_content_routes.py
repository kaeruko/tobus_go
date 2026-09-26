from fastapi import HTTPException, Query
from fastapi.responses import Response

from .services.explore_editorial_content import (
    ExploreContentError,
    ExploreContentNotFoundError,
    load_content,
    load_image,
)


def register_explore_content_routes(app) -> None:
    def runtime_mode() -> str:
        mode = getattr(app.state, "runtime_mode", None)
        if not isinstance(mode, str) or not mode:
            raise RuntimeError("app.state.runtime_mode is not configured")
        return mode

    def city_key() -> str:
        city = getattr(app.state, "city_key", None)
        if not isinstance(city, str) or not city:
            raise RuntimeError("app.state.city_key is not configured")
        return city

    @app.get("/explore/content")
    async def explore_content():
        try:
            return load_content(mode=runtime_mode(), city=city_key())
        except ExploreContentNotFoundError as error:
            raise HTTPException(
                503,
                detail={
                    "code": "explore_content_unavailable",
                    "message": str(error),
                },
            ) from error
        except ExploreContentError as error:
            raise HTTPException(
                500,
                detail={
                    "code": "explore_content_invalid",
                    "message": str(error),
                },
            ) from error

    @app.get("/explore/content/image")
    async def explore_content_image(file: str = Query(...)):
        try:
            content, media_type = load_image(
                mode=runtime_mode(),
                city=city_key(),
                filename=file,
            )
        except ExploreContentNotFoundError as error:
            raise HTTPException(
                404,
                detail={
                    "code": "explore_content_image_not_found",
                    "message": str(error),
                },
            ) from error
        except ExploreContentError as error:
            raise HTTPException(
                400,
                detail={
                    "code": "explore_content_image_invalid",
                    "message": str(error),
                },
            ) from error

        return Response(
            content=content,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )
