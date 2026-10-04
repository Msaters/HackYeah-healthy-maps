"""Route planning service wrapping optimizer.slider_select, preset caching, and health advisories."""
import datetime
import json
import logging
from typing import Dict, Any, Optional, List, Tuple

from backend.app.config import get_settings
from backend.app.schemas import UserProfile
from backend.app.environment import get_environmental_context
from optimizer.genome import decode, encode_anchor
from optimizer.slider_select import plan_route_slider

logger = logging.getLogger(__name__)

_SLIDER_CACHE: Dict[str, Dict[str, Any]] = {}


def make_fallback_slider(variant: str = "bike", n: int = 7) -> Dict[str, Any]:
    """Generate a valid fallback slider.json document if pre-computed files are missing."""
    anchor_x = encode_anchor(variant)
    ticks = []
    for i in range(n):
        s = i / max(n - 1, 1)
        x = anchor_x.copy()
        if variant == "bike":
            x[1] = max(0.0, 0.9 - s * 0.7)
            x[8] = 0.1 if s < 0.3 else (0.5 if s < 0.7 else 0.9)
            x[9] = 0.1 if s < 0.4 else 0.9
        else:
            x[0] = max(0.1, 0.9 - s * 0.7)
            x[10] = min(1.0, s * 0.9)

        query = decode(x, variant)
        ticks.append({
            "s": round(s, 4),
            "u": round(s, 4),
            "index": i,
            "modes": query.get("modes"),
            "preferences": query.get("preferences"),
            "metrics": {},
        })

    return {
        "meta": {
            "variant": variant,
            "n": n,
            "source": "fallback_generator",
        },
        "ticks": ticks,
    }


def get_slider(variant: str = "bike") -> Dict[str, Any]:
    """Load and cache slider.json presets for 'bike' or 'walk'."""
    variant = "bike" if variant == "bike" else "walk"
    if variant in _SLIDER_CACHE:
        return _SLIDER_CACHE[variant]

    settings = get_settings()
    slider_path = settings.slider_bike_path if variant == "bike" else settings.slider_walk_path

    if slider_path.exists():
        try:
            with open(slider_path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            logger.info("Loaded slider preset from %s", slider_path)
            _SLIDER_CACHE[variant] = doc
            return doc
        except Exception as exc:
            logger.warning("Failed to read %s: %s; falling back to generated presets", slider_path, exc)

    fallback = make_fallback_slider(variant=variant, n=7)
    _SLIDER_CACHE[variant] = fallback
    return fallback


def clear_slider_cache() -> None:
    """Clear cached slider presets (useful for tests)."""
    _SLIDER_CACHE.clear()


def evaluate_health_advisory(
    positions: List[Dict[str, Any]],
    env_context: Optional[Dict[str, Any]] = None,
    manual_lock_reason: Optional[str] = None,
    limit_min: float = 15.0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Evaluates health and environmental risks for all candidate positions.
    Applies the transparent Advisory Nudge model (all routes remain selectable, locked = False).
    """
    env_context = env_context or {}
    station = env_context.get("station") or {}
    station_name = station.get("name", "Kraków")
    station_id = station.get("id", 400)
    distance_km = station.get("distance_km", 1.0)

    aqi = env_context.get("air_quality") or {}
    pm10 = aqi.get("pm10", 25.0)
    pm25 = aqi.get("pm25", 15.0)
    index_name = aqi.get("index_name", "Dobry")

    weather = env_context.get("weather") or {}
    temp_c = weather.get("temperature_c", 15.0)
    rain_mm = weather.get("rain_mm", 0.0)
    precip_mm = weather.get("precipitation_mm", 0.0)
    wind_kmh = weather.get("wind_kmh", 10.0)
    condition = weather.get("condition", "Bezchmurnie")
    weather_code = weather.get("weather_code", 0)

    # Determine environmental severity
    is_smog = manual_lock_reason == "smog" or pm10 > 50.0 or index_name in ("Zły", "Bardzo zły", "Dostateczny")
    is_severe_smog = pm10 > 80.0 or index_name == "Bardzo zły"
    is_rain = manual_lock_reason == "weather" or rain_mm > 0.5 or precip_mm > 0.8
    is_severe_weather = rain_mm > 3.5 or weather_code in (95, 96, 99)

    # Build top-level environment summary
    if is_severe_smog or is_severe_weather:
        overall_level = "DANGER"
        summary = f"Alarm smogowy lub trudne warunki: PM10 = {pm10:.0f} µg/m³, {condition}"
    elif is_smog or is_rain:
        overall_level = "WARNING"
        summary = f"Podwyższone stężenie pyłów ({pm10:.0f} µg/m³) lub opady ({condition})"
    else:
        overall_level = "SAFE"
        summary = f"Dobre warunki atmosferyczne: czyste powietrze ({index_name}) i brak opadów."

    env_summary = {
        "overall_level": overall_level,
        "summary": summary,
        "air_quality": {
            "station_name": station_name,
            "station_id": station_id,
            "distance_km": distance_km,
            "index_name": index_name,
            "pm10": pm10,
            "pm25": pm25,
        },
        "weather": {
            "temperature_c": temp_c,
            "rain_mm": rain_mm,
            "precipitation_mm": precip_mm,
            "condition": condition,
            "wind_kmh": wind_kmh,
        },
    }

    # Evaluate each position
    for pos in positions:
        itinerary = pos.get("itinerary") or {}
        legs = itinerary.get("legs") or []

        bike_sec = sum(leg.get("duration", 0) for leg in legs if leg.get("mode") == "BICYCLE")
        bike_min = round(bike_sec / 60.0, 1)

        metrics = pos.setdefault("metrics", {})
        metrics["bike_duration_min"] = bike_min

        # In advisory model, keep route selectable
        pos["locked"] = False
        pos["lock_note"] = None

        if bike_min == 0:
            # Transit or pure walk
            level = "SAFE"
            badge = "Czysty przejazd" if (is_smog or is_rain) else "Rekomendowana"
            msg = (
                "Trasa w pojeździe (tramwaj/autobus) minimalizuje kontakt ze smogiem i opadami."
                if (is_smog or is_rain)
                else "Optymalny czas dojazdu komunikacją miejską."
            )
            factors = []
            affected_legs = []
        else:
            # Bicycle used
            if is_severe_smog or is_severe_weather:
                level = "DANGER"
                badge = "Bardzo wysokie ryzyko"
                msg = f"Warunki niebezpieczne dla aktywności ({condition}, PM10: {pm10:.0f} µg/m³). Odradzany przejazd rowerem."
                factors = [
                    f"Stacja {station_name}: PM10 = {pm10:.0f} µg/m³"
                    if is_severe_smog
                    else f"Trudne warunki pogodowe: {condition}"
                ]
                affected_legs = ["BICYCLE"]
            elif is_smog or is_rain:
                if bike_min <= limit_min:
                    level = "MODERATE"
                    badge = "Krótka ekspozycja"
                    msg = f"Dojazd rowerem ({bike_min:.0f} min) mieści się w bezpiecznym limicie 15 min mimo gorszych warunków."
                    factors = [f"Czas jazdy na rowerze: {bike_min:.0f} min (poniżej limitu {limit_min:.0f} min)"]
                    affected_legs = ["BICYCLE"]
                else:
                    level = "WARNING"
                    badge = "Wysoka ekspozycja"
                    msg = (
                        f"{bike_min:.0f} min jazdy rowerem w strefie smogu ({pm10:.0f} µg/m³, {station_name}). "
                        "Zalecany tramwaj lub krótszy odcinek."
                    )
                    factors = [
                        f"Czas jazdy na rowerze ({bike_min:.0f} min) przekracza próg {limit_min:.0f} min",
                        f"Stacja {station_name}: PM10 = {pm10:.0f} µg/m³",
                    ]
                    affected_legs = ["BICYCLE"]
            else:
                level = "SAFE"
                badge = "Dobre warunki"
                msg = f"Czyste powietrze ({station_name}) i brak opadów — optymalne warunki na trening rowerowy."
                factors = []
                affected_legs = []

        pos["advisory"] = {
            "level": level,
            "badge": badge,
            "message": msg,
            "factors": factors,
            "affected_legs": affected_legs,
        }

    return positions, env_summary


def evaluate_outdoor_exposure(
    positions: List[Dict[str, Any]],
    lock_reason: Optional[str],
    limit_min: float = 15.0,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Applies the outdoor exposure rule (15 min cycling threshold) to route positions.
    Retained for backward compatibility.
    """
    extra_warnings: List[str] = []
    any_locked = False

    for pos in positions:
        itinerary = pos.get("itinerary") or {}
        legs = itinerary.get("legs") or []

        bike_sec = sum(leg.get("duration", 0) for leg in legs if leg.get("mode") == "BICYCLE")
        bike_min = round(bike_sec / 60.0, 1)

        metrics = pos.setdefault("metrics", {})
        metrics["bike_duration_min"] = bike_min

        if not lock_reason:
            pos["locked"] = False
            pos["lock_note"] = None
            continue

        modes = metrics.get("modes") or []
        is_fallback = pos.get("fallback", False) or ("BICYCLE" not in modes)

        if is_fallback:
            pos["locked"] = False
            pos["lock_note"] = None
        elif bike_min > limit_min:
            pos["locked"] = True
            pos["lock_note"] = (
                f"Zablokowano ({lock_reason}): czas jazdy rowerem ({bike_min:.0f} min) "
                f"przekracza dopuszczalny limit {limit_min:.0f} min."
            )
            any_locked = True
        else:
            pos["locked"] = False
            pos["lock_note"] = None

    if lock_reason and any_locked:
        extra_warnings.append(
            f"Aktywny alert ({lock_reason}): trasy rowerowe powyżej {limit_min:.0f} min "
            "zostały zablokowane ze względów bezpieczeństwa."
        )

    return positions, extra_warnings


async def plan_routes(
    origin: Dict[str, float],
    destination: Dict[str, float],
    deadline: str,
    has_bike: bool = True,
    user_profile: Optional[UserProfile] = None,
    lock_reason: Optional[str] = None,
    buffer_min: float = 3.0,
    client: Optional[Any] = None,
    http_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute route planning, fetch environmental context, and apply health advisories."""
    settings = get_settings()
    variant = "bike" if has_bike else "walk"
    slider = get_slider(variant)

    weight = user_profile.weight_kg if user_profile else 70.0
    height = user_profile.height_m if user_profile else 1.75
    walk_speed = user_profile.walk_speed_mps if user_profile else None
    bike_speed = user_profile.bike_speed_mps if user_profile else None

    # 1. Fetch environmental context in background/cache (<1ms when cached)
    env_context = await get_environmental_context(
        lat=origin["lat"],
        lon=origin["lon"],
        deadline_iso=deadline,
        client=http_client,
    )

    # 2. Call OTP route slider engine
    rs = plan_route_slider(
        slider=slider,
        origin=origin,
        destination=destination,
        deadline=deadline,
        url=settings.otp_url,
        buffer_min=buffer_min,
        lock_reason=None,  # We handle locking via advisory nudge
        walk_speed=walk_speed,
        bike_speed=bike_speed,
        weight=weight,
        height=height,
        client=client,
    )

    # 3. Post-process with health advisories
    positions, env_summary = evaluate_health_advisory(
        positions=rs.get("positions", []),
        env_context=env_context,
        manual_lock_reason=lock_reason,
        limit_min=settings.outdoor_exposure_limit_min,
    )
    rs["positions"] = positions
    rs["environment"] = env_summary

    # 4. Smart default: default_index targets the safest position (SAFE or MODERATE)
    if positions:
        safe_indices = [
            i for i, p in enumerate(positions)
            if p.get("advisory", {}).get("level") in ("SAFE", "MODERATE")
        ]
        if safe_indices:
            # Pick first safe (or the one closest to s=0 / transit)
            rs["default_index"] = safe_indices[0]

    return rs
