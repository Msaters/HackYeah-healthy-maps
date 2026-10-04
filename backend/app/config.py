import os
from pathlib import Path
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

class Settings(BaseModel):
    otp_url: str = Field(
        default_factory=lambda: os.getenv("OTP_URL", "http://localhost:8080/otp/gtfs/v1")
    )
    slider_bike_path: Path = Field(
        default_factory=lambda: REPO_ROOT / os.getenv("SLIDER_BIKE_PATH", "optimizer/out/quick_bike/slider.json")
    )
    slider_walk_path: Path = Field(
        default_factory=lambda: REPO_ROOT / os.getenv("SLIDER_WALK_PATH", "optimizer/out/quick_walk/slider.json")
    )
    outdoor_exposure_limit_min: float = Field(
        default_factory=lambda: float(os.getenv("OUTDOOR_EXPOSURE_LIMIT_MIN", "15.0"))
    )
    default_buffer_min: float = Field(
        default_factory=lambda: float(os.getenv("DEFAULT_BUFFER_MIN", "3.0"))
    )
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "*",
    ]

_settings = Settings()

def get_settings() -> Settings:
    return _settings
