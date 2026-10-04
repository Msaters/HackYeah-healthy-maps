// src/api/client.ts
import type { MapPlanResponse, TransportMode, User } from '../store/useAppStore';
import { logger } from '../utils/logger';

const BASE_URL = 'http://127.0.0.1:8000/api/v1';

// --- Geocoding (§4, §5) ---
export interface GeocodeResult {
  label: string;
  lat: number;
  lon: number;
  type: string | null;
  osm_id: number | string | null;
  distance_m: number | null;
}
export interface GeocodeResponse {
  query: string;
  results: GeocodeResult[];
  warning: string | null;
}
export interface ReverseGeocodeResponse extends GeocodeResponse {
  lat: number;
  lon: number;
  label: string;
}

// --- Plan (§6) ---
export interface PlanRequest {
  origin: { lat: number; lon: number; label?: string | null };
  destination: { lat: number; lon: number; label?: string | null };
  modes: TransportMode[];
  time_budget_minutes: number | null;
}

// --- GeoJSON (§7) – typ minimalny, wystarczający do rysowania ---
export interface RouteFeatureCollection {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    geometry: { type: string; coordinates: number[][] };
    properties: { mode?: string; distance_m?: number; duration_min?: number };
  }>;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const method = options?.method ?? 'GET';
  logger.api(`➡️ ${method} ${path}`, options?.body ?? '');

  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        // 🚨 FORBIDDEN: bez nagłówka Authorization (kontrakt!)
        ...(options?.headers ?? {}),
      },
    });
  } catch {
    logger.error(`🔌 ${method} ${path} → brak połączenia z serwerem`);
    throw new Error('Brak połączenia z serwerem.');
  }

  if (!res.ok) {
    // FastAPI przy błędzie zwraca { "detail": "..." } (§10) – wyciągamy to!
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body.detail) detail = String(body.detail);
    } catch { /* response bez JSON – trudno, zostaje statusText */ }
    logger.error(`❌ ${method} ${path} → HTTP ${res.status}: ${detail}`);
    throw new Error(detail);
  }

  const data = (await res.json()) as T;
  logger.api(`✅ ${method} ${path} → HTTP ${res.status}`, data);
  return data;
}

export const api = {
  loginDemo: () =>
    request<{ token: string; user: User }>('/auth/demo', { method: 'POST', body: '{}' }),
  getMe: () => request<User>('/me'),
  patchGoal: (body: Partial<HealthGoalBody>) =>
    request<{ ok: boolean; user: User }>('/me/goal', {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  geocodeSearch: (q: string, limit = 5) =>
    request<GeocodeResponse>(`/geocode/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  geocodeReverse: (lat: number, lon: number) =>
    request<ReverseGeocodeResponse>(`/geocode/reverse?lat=${lat}&lon=${lon}`),
  planRoute: (body: PlanRequest) =>
    request<MapPlanResponse>('/map/plan', { method: 'POST', body: JSON.stringify(body) }),
  routeGeoJson: (routeId: string) =>
    request<RouteFeatureCollection>(`/map/routes/${routeId}/geojson`),
};

// pomocniczy typ dla PATCH /me/goal
interface HealthGoalBody {
  target_steps: number;
  target_calories: number;
  prefer_green_routes: boolean;
}