from typing import Any

import httpx
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.core.store import store

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    """
    Fake auth dependency. Zawsze zwraca demo usera.
    """
    return store.get_user()


async def get_http_client(request: Request) -> httpx.AsyncClient:
    """
    Zwraca współdzieloną instancję httpx.AsyncClient z app.state.
    """
    return request.app.state.http_client
