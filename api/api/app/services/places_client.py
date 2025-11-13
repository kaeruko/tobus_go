import httpx
from ..core import settings
async def autocomplete(q: str, language: str = "ja"):
    params = {"input": q, "language": language, "key": settings.PLACES_KEY}
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(f"{settings.BASE_URL}/autocomplete/json", params=params)
    return r.json()
async def details(place_id: str, language: str = "ja"):
    params = {"place_id": place_id, "language": language, "fields": "geometry,name", "key": settings.PLACES_KEY}
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(f"{settings.BASE_URL}/details/json", params=params)
    return r.json()
