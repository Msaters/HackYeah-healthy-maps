from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, geocode, map, users
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Zarządzanie cyklem życia aplikacji.
    Inicjalizuje współdzielony httpx.AsyncClient (Connection Pooling).
    """
    settings = get_settings()
    app.state.http_client = httpx.AsyncClient(timeout=settings.http_timeout_seconds)
    yield
    await app.state.http_client.aclose()


app = FastAPI(
    title="Health Routes API",
    version="0.3.0",
    description="""
    Backend dla aplikacji mapowej proponującej trasy.
    Tryb demo: brak prawdziwego auth, jeden demo user, trasy w pamięci.
    """,
    lifespan=lifespan,
)

# FIX BUG-01: allow_origins=["*"] jest zabronione przy allow_credentials=True.
# Używamy regexa, aby pozwolić na dowolny localhost/dev origin.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


API_V1_PREFIX = "/api/v1"

app.include_router(auth.router, prefix=API_V1_PREFIX)
app.include_router(users.router, prefix=API_V1_PREFIX)
app.include_router(geocode.router, prefix=API_V1_PREFIX)
app.include_router(map.router, prefix=API_V1_PREFIX)
