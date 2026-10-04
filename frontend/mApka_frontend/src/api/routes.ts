// src/api/routes.ts — POST /api/routes (planer tras: czas <-> ruch)
export const ROUTES_BASE = 'http://127.0.0.1:8000/api';

export interface LatLon {
  lat: number;
  lon: number;
}

export type LockReason = 'auto' | 'smog' | null;
export type AdvisoryLevel = 'SAFE' | 'CAUTION' | 'WARNING' | 'DANGER' | string;

export interface RoutesRequest {
  from: LatLon;
  to: LatLon;
  deadline: string; // ISO with offset
  has_bike: boolean;
  user_profile?: { weight_kg: number; height_m: number };
  lock_reason?: LockReason;
  buffer_min: number;
}

export interface PlaceRef {
  name: string;
  lat: number;
  lon: number;
}

export interface Leg {
  mode: string; // WALK | BICYCLE | TRAM | BUS | RAIL | ...
  duration: number; // seconds
  distance: number; // metres
  from: PlaceRef;
  to: PlaceRef;
  route: { shortName?: string | null } | null;
  legGeometry: { points: string };
  start?: unknown;
  end?: unknown;
}

export interface Advisory {
  level: AdvisoryLevel;
  badge: string;
  message: string;
  factors: unknown[];
  affected_legs: unknown[];
}

export interface PositionMetrics {
  duration_min: number;
  slack_min: number;
  active_kcal: number;
  steps: number;
  bike_duration_min: number;
  modes: string[];
}

export interface RoutePosition {
  s: number;
  locked: boolean;
  fallback: boolean;
  sources: string[];
  metrics: PositionMetrics;
  advisory: Advisory | null;
  itinerary: { start?: string; end?: string; duration: number; legs: Leg[] };
}

export interface Environment {
  overall_level: AdvisoryLevel;
  summary: string;
  air_quality?: unknown;
  weather?: unknown;
}

export interface RoutesResponse {
  positions: RoutePosition[];
  default_index: number;
  environment: Environment | null;
  warnings: string[];
  dropped: unknown[];
  baseline_min: number | null;
  lock_reason?: LockReason;
}

export async function planRoutes(req: RoutesRequest, signal?: AbortSignal): Promise<RoutesResponse> {
  let res: Response;
  try {
    res = await fetch(`${ROUTES_BASE}/routes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new Error('Nie można połączyć się z serwerem tras');
  }
  if (res.status === 502 || res.status === 503) {
    throw new Error('Planer tras jest chwilowo niedostępny — spróbuj za chwilę.');
  }
  if (!res.ok) {
    let detail = `Błąd serwera (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch { /* no JSON body */ }
    throw new Error(detail);
  }
  return (await res.json()) as RoutesResponse;
}
