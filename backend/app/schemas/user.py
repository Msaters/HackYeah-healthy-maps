from pydantic import BaseModel, Field

class HealthGoal(BaseModel):
    target_steps: int = Field(default=10000, ge=0)
    target_calories: int = Field(default=500, ge=0)
    prefer_green_routes: bool = Field(default=True)

class User(BaseModel):
    id: str
    email: str
    name: str
    weight_kg: float = Field(ge=0)
    height_cm: float = Field(ge=0)
    goal: HealthGoal

class GoalUpdate(BaseModel):
    target_steps: int | None = Field(default=None, ge=0)
    target_calories: int | None = Field(default=None, ge=0)
    prefer_green_routes: bool | None = None

class GoalUpdateResponse(BaseModel):
    ok: bool
    user: User
