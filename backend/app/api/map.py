from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.api.dependencies import get_current_user
from app.core.store import store
from app.schemas.map import MapPlanRequest, MapPlanResponse
from app.services import route_engine


router = APIRouter(tags=["map"])


@router.post("/map/plan", response_model=MapPlanResponse)
def plan_route(
    payload: MapPlanRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    response, routes_cache = route_engine.plan_routes(
        payload=payload,
        user=user,
    )

    store.set_routes(routes_cache)
    return response


@router.get("/map/routes/{route_id}/geojson")
def get_route_geojson(route_id: str):
    geojson = store.get_route_geojson(route_id)

    if geojson is None:
        raise HTTPException(status_code=404, detail="Route not found")

    return JSONResponse(content=geojson, media_type="application/geo+json")
