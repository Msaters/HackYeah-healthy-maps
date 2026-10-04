from fastapi import APIRouter

from app.core.store import store
from app.schemas.auth import DemoLoginResponse


router = APIRouter(tags=["auth"])


@router.post("/auth/demo", response_model=DemoLoginResponse)
def auth_demo():
    return {
        "token": "demo-token-not-used",
        "user": store.get_user(),
    }
