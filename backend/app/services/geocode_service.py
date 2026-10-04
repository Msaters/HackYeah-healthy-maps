import json
from typing import Any
import httpx

from backend.app.core.config import get_settings
from backend.app.schemas.geocode import (
    GeocodeResult,
    GeocodeReverseResponse,
    GeocodeSearchResponse,
)

def _build_label(props: dict[str, Any]) -> str:
    street = props.get("street")
    housenumber = props.get("housenumber")
    if street and housenumber:
        street = f"{street} {housenumber}"

    parts = [props.get("name"), street, props.get("postcode"), props.get("city")]
    label = ", ".join([str(part) for part in parts if part])
    return label or props.get("osm_value") or props.get("type") or "Nieznana lokalizacja"

def _feature_to_result(feature: dict[str, Any], include_distance: bool = False) -> GeocodeResult | None:
    geometry = feature.get("geometry", {})
    coordinates = geometry.get("coordinates", [])
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None

    try:
        lon = float(coordinates[0])
        lat = float(coordinates[1])
    except (TypeError, ValueError):
        return None

    props = feature.get("properties", {}) or {}
    distance_m: float | None = None
    if include_distance and props.get("distance") is not None:
        try: distance_m = float(props["distance"])
        except (TypeError, ValueError): pass

    return GeocodeResult(
        label=_build_label(props), lat=lat, lon=lon,
        type=props.get("type") or props.get("osm_value"),
        osm_id=props.get("osm_id"), distance_m=distance_m,
    )

async def search(q: str, limit: int, client: httpx.AsyncClient) -> GeocodeSearchResponse:
    settings = get_settings()
    params = {"q": q, "limit": limit, "lang": "default"}

    try:
        response = await client.get(settings.photon_search_url, params=params)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError:
        return GeocodeSearchResponse(query=q, results=[], warning="API Photon niedostępne (błąd sieci/statusu).")
    except json.JSONDecodeError:
        # FIX BUG-02: Zabezpieczenie przed śmieciowym JSON-em (np. HTML przy 200 OK)
        return GeocodeSearchResponse(query=q, results=[], warning="API Photon zwróciło niepoprawny format danych.")

    results = [r for f in data.get("features", []) if (r := _feature_to_result(f)) is not None]
    return GeocodeSearchResponse(query=q, results=results)

async def reverse(lat: float, lon: float, client: httpx.AsyncClient) -> GeocodeReverseResponse:
    settings = get_settings()
    fallback_label = f"{lat:.5f}, {lon:.5f}"
    params = {"lat": lat, "lon": lon}

    try:
        response = await client.get(settings.photon_reverse_url, params=params)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError:
        return GeocodeReverseResponse(lat=lat, lon=lon, label=fallback_label, warning="API Photon niedostępne.")
    except json.JSONDecodeError:
        return GeocodeReverseResponse(lat=lat, lon=lon, label=fallback_label, warning="API Photon zwróciło niepoprawny format.")

    results = [r for f in data.get("features", []) if (r := _feature_to_result(f, True)) is not None]
    label = results[0].label if results else fallback_label
    return GeocodeReverseResponse(lat=lat, lon=lon, label=label, results=results)
