from fastapi import APIRouter, Query
from ..services import places_client

router = APIRouter(prefix="", tags=["places"])

@router.get("/autocomplete")
async def autocomplete(q: str = Query(..., min_length=1)):
    return await places_client.autocomplete(q)

@router.get("/details")
async def details(place_id: str = Query(...)):
    return await places_client.details(place_id)
