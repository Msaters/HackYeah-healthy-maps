from typing import Any

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import get_current_user
from backend.app.core.store import store
from backend.app.schemas.user import GoalUpdate, GoalUpdateResponse, User


router = APIRouter(tags=["users"])


@router.get("/me", response_model=User)
def get_me(user: dict[str, Any] = Depends(get_current_user)):
    return user


@router.patch("/me/goal", response_model=GoalUpdateResponse)
def update_my_goal(
    payload: GoalUpdate,
    user: dict[str, Any] = Depends(get_current_user),
):
    update_data = payload.model_dump(exclude_unset=True)
    updated_user = store.update_user_goal(update_data)

    return {
        "ok": True,
        "user": updated_user,
    }
