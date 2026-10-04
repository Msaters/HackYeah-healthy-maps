"""Pydantic schemas.

Route-slider API models (``/api/routes``) live in ``route.py`` and are re-exported here, so
``from backend.app.schemas import RouteRequest`` keeps working. Demo frontend API models
(``/api/v1``) are in ``auth``, ``geocode``, ``map`` and ``user``.
"""
from backend.app.schemas.route import (  # noqa: F401
    AirQualityInfo,
    Coordinates,
    EnvironmentSummary,
    HealthAdvisory,
    RouteMetrics,
    RoutePosition,
    RouteRequest,
    RouteResponse,
    UserProfile,
    WeatherInfo,
)
