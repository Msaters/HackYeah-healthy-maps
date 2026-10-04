import httpx
from fastapi import APIRouter, Depends, Query

from backend.app.api.dependencies import get_http_client
from backend.app.schemas.geocode import GeocodeReverseResponse, GeocodeSearchResponse
from backend.app.services import geocode_service


router = APIRouter(tags=["geocode"])


@router.get("/geocode/search", response_model=GeocodeSearchResponse)
async def geocode_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(5, ge=1, le=10),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    return await geocode_service.search(q=q, limit=limit, client=client)


@router.get("/geocode/reverse", response_model=GeocodeReverseResponse)
async def geocode_reverse(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    return await geocode_service.reverse(lat=lat, lon=lon, client=client)
