"""Pydantic schemas for the route slider API with environmental health advisories."""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict


class Coordinates(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees")


class UserProfile(BaseModel):
    weight_kg: float = Field(default=70.0, ge=30.0, le=300.0, description="User body weight in kg")
    height_m: float = Field(default=1.75, ge=1.0, le=2.5, description="User height in meters")
    walk_speed_mps: Optional[float] = Field(default=None, ge=0.5, le=3.0, description="Walking speed in m/s")
    bike_speed_mps: Optional[float] = Field(default=None, ge=1.0, le=15.0, description="Bicycle speed in m/s")


class RouteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_loc: Coordinates = Field(..., alias="from", description="Origin coordinates")
    to_loc: Coordinates = Field(..., alias="to", description="Destination coordinates")
    deadline: datetime = Field(..., description="Target arrival deadline with timezone")
    has_bike: bool = Field(default=True, description="Whether the user has a bicycle")
    user_profile: Optional[UserProfile] = Field(default=None, description="Optional physical profile for MET calculation")
    lock_reason: Optional[str] = Field(default=None, description="Manual lock reason or 'auto' for automated GIOŚ/Meteo detection")
    buffer_min: float = Field(default=3.0, ge=0.0, le=60.0, description="Arrival buffer in minutes")

    @field_validator("deadline")
    @classmethod
    def validate_deadline_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("deadline must include a timezone offset (e.g. +02:00 or Z)")
        return v


class RouteMetrics(BaseModel):
    duration_min: float
    slack_min: Optional[float] = 0.0
    active_kcal: float
    steps: int = 0
    bike_duration_min: float = 0.0
    modes: List[str] = []


class HealthAdvisory(BaseModel):
    level: str = Field(default="SAFE", description="Risk level: SAFE, MODERATE, WARNING, DANGER")
    badge: str = Field(default="Rekomendowana", description="Short UI badge label")
    message: str = Field(default="", description="Explanatory health rationale")
    factors: List[str] = Field(default_factory=list, description="Specific triggers (e.g. smog, rain)")
    affected_legs: List[str] = Field(default_factory=list, description="Transport modes affected, e.g. ['BICYCLE']")


class AirQualityInfo(BaseModel):
    station_name: str
    station_id: int
    distance_km: float
    index_name: str
    pm10: float
    pm25: float


class WeatherInfo(BaseModel):
    temperature_c: float
    rain_mm: float
    precipitation_mm: float
    condition: str
    wind_kmh: float


class EnvironmentSummary(BaseModel):
    overall_level: str = Field(default="SAFE", description="SAFE, MODERATE, WARNING, DANGER")
    summary: str = Field(default="Dobre warunki atmosferyczne", description="One-line summary for UI banner")
    air_quality: Optional[AirQualityInfo] = None
    weather: Optional[WeatherInfo] = None


class RoutePosition(BaseModel):
    s: float = Field(..., ge=0.0, le=1.0, description="Slider position from 0 (fastest) to 1 (most active)")
    locked: bool = Field(default=False, description="Kept false in advisory model so user retains agency")
    lock_note: Optional[str] = Field(default=None, description="Legacy/optional note")
    fallback: bool = Field(default=False, description="Whether this is a safe public transit/walk fallback")
    sources: List[str] = Field(default_factory=list, description="Source tags (ticks/anchor/walk)")
    metrics: RouteMetrics
    advisory: Optional[HealthAdvisory] = Field(default=None, description="Environmental health risk assessment")
    itinerary: Dict[str, Any] = Field(..., description="Raw OTP itinerary with legs and legGeometry")


class RouteResponse(BaseModel):
    baseline_min: Optional[float] = None
    default_index: int = 0
    lock_reason: Optional[str] = None
    environment: Optional[EnvironmentSummary] = None
    positions: List[RoutePosition] = []
    warnings: List[str] = []
    otp_stats: Optional[Dict[str, int]] = None
    dropped: Optional[Dict[str, int]] = None
    n_requests: Optional[int] = None
