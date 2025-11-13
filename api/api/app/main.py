from fastapi import FastAPI
from .routers import places as places_router
app = FastAPI(title="toei-places-proxy")
app.include_router(places_router.router)
@app.get("/healthz")
async def healthz():
    return {"ok": True}
