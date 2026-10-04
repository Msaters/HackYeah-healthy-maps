from pydantic import BaseModel

class GeocodeResult(BaseModel):
    label: str
    lat: float
    lon: float
    type: str | None = None
    osm_id: str | int | None = None
    distance_m: float | None = None

class GeocodeSearchResponse(BaseModel):
    query: str
    results: list[GeocodeResult]
    warning: str | None = None

class GeocodeReverseResponse(BaseModel):
    lat: float
    lon: float
    label: str
    results: list[GeocodeResult] = []
    warning: str | None = None
