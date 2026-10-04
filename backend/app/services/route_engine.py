from typing import Any
from uuid import uuid4

from backend.app.schemas.map import MapPlanRequest, MapPlanResponse, RouteSummary
from backend.app.schemas.user import HealthGoal

def _make_bbox(o_lat, o_lon, d_lat, d_lon):
    return [min(o_lon, d_lon), min(o_lat, d_lat), max(o_lon, d_lon), max(o_lat, d_lat)]

def _make_geojson(coords, props):
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": props}]
    }

def plan_routes(payload: MapPlanRequest, user: dict[str, Any]) -> tuple[MapPlanResponse, dict[str, dict[str, Any]]]:
    """
    Inteligentny Mock Route Engine.
    Reaguje na wybrany tryb (walk/bike) oraz budżet czasowy (time_budget).
    """
    bbox = _make_bbox(payload.origin.lat, payload.origin.lon, payload.destination.lat, payload.destination.lon)
    line_coords = [[payload.origin.lon, payload.origin.lat], [payload.destination.lon, payload.destination.lat]]

    routes = []
    routes_cache = {}

    # 1. Trasa Najszybsza (Zależy od modes)
    fastest_id = f"route_fastest_{uuid4().hex[:8]}"
    
    # Domyślnie zakładamy, że najszybsza to transit/bike jeśli dostępne, inaczej walk
    f_mode = "walk"
    f_dist = 1200
    f_dur = 22
    f_steps = 1450
    f_cal = 110
    
    if "bike" in payload.modes:
        f_mode = "bike"
        f_dist = 3500
        f_dur = 14
        f_steps = 0  # Rower = 0 kroków
        f_cal = 150
    elif "transit" in payload.modes:
        f_mode = "transit"
        f_dist = 4000
        f_dur = 18
        f_steps = 400 # dojście na przystanek
        f_cal = 40

    f_warnings = []
    if payload.time_budget_minutes is not None and f_dur > payload.time_budget_minutes:
        f_warnings.append(f"Przekracza budżet czasowy o {f_dur - payload.time_budget_minutes} min.")

    f_geojson = _make_geojson(line_coords, {"mode": f_mode, "distance_m": f_dist, "duration_min": f_dur})
    
    routes.append(RouteSummary(
        route_id=fastest_id, kind="fastest", label="Najszybsza",
        duration_min=f_dur, steps=f_steps, calories=f_cal, bbox=bbox, warnings=f_warnings
    ))
    routes_cache[fastest_id] = {"kind": "fastest", "geojson": f_geojson}


    # 2. Trasa Zdrowa (Zawsze piesza/rowerowa, maksymalizująca kroki)
    healthy_id = f"route_healthy_{uuid4().hex[:8]}"
    
    h_mode = "walk"
    h_dist = 3900
    h_dur = 45
    h_steps = 5200
    h_cal = 390
    
    if "bike" in payload.modes:
        h_mode = "bike"
        h_dist = 8000 # Długa trasa rowerowa przez parki
        h_dur = 35
        h_steps = 0
        h_cal = 450

    h_warnings = []
    if payload.time_budget_minutes is not None and h_dur > payload.time_budget_minutes:
        h_warnings.append(f"Przekracza budżet czasowy o {h_dur - payload.time_budget_minutes} min.")

    h_geojson = _make_geojson(line_coords, {"mode": h_mode, "distance_m": h_dist, "duration_min": h_dur})

    routes.append(RouteSummary(
        route_id=healthy_id, kind="healthy", label="Zdrowa (Maksymalizacja Ruchu)",
        duration_min=h_dur, steps=h_steps, calories=h_cal, bbox=bbox, warnings=h_warnings
    ))
    routes_cache[healthy_id] = {"kind": "healthy", "geojson": h_geojson}

    # Wybór domyślnej trasy
    selected = healthy_id
    if payload.time_budget_minutes is not None and h_dur > payload.time_budget_minutes and f_dur <= payload.time_budget_minutes:
        selected = fastest_id # Jeśli zdrowa nie mieści się w czasie, wybierz najszybszą

    response = MapPlanResponse(
        plan_id=f"plan_{uuid4().hex[:8]}", bbox=bbox, routes=routes,
        selected_route_id=selected, alerts=[], user_goal=HealthGoal(**user["goal"])
    )

    return response, routes_cache
