from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field
from app.schemas.user import HealthGoal

class PointIn(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    label: str | None = None

class MapOptions(BaseModel):
    include_geojson: bool = False
    layers: list[Literal["air", "weather", "warnings"]] = []

class MapPlanRequest(BaseModel):
    origin: PointIn
    destination: PointIn
    depart_at: datetime | None = None
    time_budget_minutes: int | None = Field(default=None, ge=0)
    target_arrival_time: datetime | None = None
    modes: list[Literal["walk", "bike", "transit"]] = ["walk", "bike", "transit"]
    options: MapOptions = MapOptions()

class RouteSummary(BaseModel):
    route_id: str
    kind: Literal["fastest", "healthy", "balanced"]
    label: str
    duration_min: int = Field(ge=0)
    steps: int = Field(ge=0)
    calories: int = Field(ge=0)
    bbox: list[float] = Field(min_length=4, max_length=4)
    warnings: list[str] = []

class MapPlanResponse(BaseModel):
    plan_id: str
    bbox: list[float] = Field(min_length=4, max_length=4)
    routes: list[RouteSummary]
    selected_route_id: str | None = None
    alerts: list[str] = []
    user_goal: HealthGoal
