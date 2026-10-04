"""FastAPI application for Aktywny Kraków route slider API with environmental health advisories."""
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import auth, geocode, map as map_api, users
from backend.app.config import get_settings
from backend.app.core.config import get_settings as get_v1_settings
from backend.app.schemas import RouteRequest, RouteResponse
from backend.app.service import plan_routes

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Shared httpx client for the /api/v1 demo routers (geocoding)."""
    # Photon (komoot) rejects requests without a User-Agent (403).
    app.state.http_client = httpx.AsyncClient(
        timeout=get_v1_settings().http_timeout_seconds,
        headers={"User-Agent": "AktywnyKrakow/1.0 (HackYeah 2026)"},
    )
    yield
    await app.state.http_client.aclose()


app = FastAPI(
    title="Aktywny Kraków - Route Slider API",
    description="Multi-modal Pareto route planning API with real-time environmental health advisories (GIOŚ & Open-Meteo).",
    version="1.1.0",
    lifespan=lifespan,
)

# CORS middleware for local frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Demo frontend API (auth, profile, geocoding, map plan) used by frontend/mApka_frontend.
API_V1_PREFIX = "/api/v1"
for router in (auth.router, users.router, geocode.router, map_api.router):
    app.include_router(router, prefix=API_V1_PREFIX)


@app.get("/api/health", tags=["system"])
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "otp_url": settings.otp_url}


@app.post("/api/routes", response_model=RouteResponse, tags=["routing"])
async def get_routes(request: RouteRequest):
    """
    Compute health-aware multi-modal route options for Kraków.
    Returns an ordered set of Pareto slider positions (fastest to most active),
    incorporating real-time GIOŚ air quality, Open-Meteo weather forecasts,
    transparent health advisories, and polyline geometry for frontend rendering.
    """
    origin = {"lat": request.from_loc.lat, "lon": request.from_loc.lon}
    destination = {"lat": request.to_loc.lat, "lon": request.to_loc.lon}
    deadline_iso = request.deadline.isoformat()

    try:
        rs = await plan_routes(
            origin=origin,
            destination=destination,
            deadline=deadline_iso,
            has_bike=request.has_bike,
            user_profile=request.user_profile,
            lock_reason=request.lock_reason,
            buffer_min=request.buffer_min,
        )
    except Exception as exc:
        logger.error("Failed to plan routes: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Route planning failed: {exc}",
        )

    # If all OTP requests failed, inform client
    n_req = rs.get("n_requests", 0)
    dropped = rs.get("dropped") or {}
    if n_req > 0 and dropped.get("error", 0) == n_req:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenTripPlanner service is unreachable or returned errors for all queries.",
        )

    return RouteResponse.model_validate(rs)
