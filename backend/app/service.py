"""Route planning service wrapping optimizer.slider_select and preset caching."""
import datetime
import json
import logging
from typing import Dict, Any, Optional, List, Tuple

from backend.app.config import get_settings
from backend.app.schemas import UserProfile
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


def evaluate_outdoor_exposure(
    positions: List[Dict[str, Any]],
    lock_reason: Optional[str],
    limit_min: float = 15.0,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Applies the outdoor exposure rule (15 min cycling threshold) to route positions.
    - Computes metrics['bike_duration_min'] for every position.
    - If lock_reason is present and bike_duration_min > limit_min -> position is locked.
    - If bike_duration_min <= limit_min or mode is transit/walk -> unlocked.
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

        # If it's a fallback or pure transit/walk without bicycle, keep it unlocked
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
            # Short cycling trip (<= 15 min): permitted even under lock_reason!
            pos["locked"] = False
            pos["lock_note"] = None

    if lock_reason and any_locked:
        extra_warnings.append(
            f"Aktywny alert ({lock_reason}): trasy rowerowe powyżej {limit_min:.0f} min "
            "zostały zablokowane ze względów bezpieczeństwa."
        )

    return positions, extra_warnings


def plan_routes(
    origin: Dict[str, float],
    destination: Dict[str, float],
    deadline: str,
    has_bike: bool = True,
    user_profile: Optional[UserProfile] = None,
    lock_reason: Optional[str] = None,
    buffer_min: float = 3.0,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute route planning and apply exposure safety rules."""
    settings = get_settings()
    variant = "bike" if has_bike else "walk"
    slider = get_slider(variant)

    weight = user_profile.weight_kg if user_profile else 70.0
    height = user_profile.height_m if user_profile else 1.75
    walk_speed = user_profile.walk_speed_mps if user_profile else None
    bike_speed = user_profile.bike_speed_mps if user_profile else None

    # Call the proven optimizer.slider_select engine
    rs = plan_route_slider(
        slider=slider,
        origin=origin,
        destination=destination,
        deadline=deadline,
        url=settings.otp_url,
        buffer_min=buffer_min,
        lock_reason=lock_reason,
        walk_speed=walk_speed,
        bike_speed=bike_speed,
        weight=weight,
        height=height,
        client=client,
    )

    # Post-process with the 15-minute exposure rule
    updated_positions, extra_warnings = evaluate_outdoor_exposure(
        positions=rs.get("positions", []),
        lock_reason=lock_reason,
        limit_min=settings.outdoor_exposure_limit_min,
    )
    rs["positions"] = updated_positions
    warnings = rs.setdefault("warnings", [])
    warnings.extend(extra_warnings)

    # Guarantee default_index points to an unlocked position
    positions = rs.get("positions", [])
    if positions:
        curr_default = rs.get("default_index", 0)
        if curr_default < len(positions) and positions[curr_default].get("locked"):
            # find first unlocked
            unlocked_idx = next((i for i, p in enumerate(positions) if not p.get("locked")), 0)
            rs["default_index"] = unlocked_idx

    return rs
