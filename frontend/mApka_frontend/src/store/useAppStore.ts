// src/store/useAppStore.ts
import { create } from 'zustand';
import { logger } from '../utils/logger';

// ===== TYPY 1:1 Z KONTRAKTEM (docs/BACKEND_CONTRACT.md) =====
// snake_case CELOWO – kontrakt §1 zabrania kamelowania pól z backendu!

export interface HealthGoal {
  target_steps: number;
  target_calories: number;
  prefer_green_routes: boolean;
}

export interface User {
  id: string;
  email: string;
  name: string;
  weight_kg: number;
  height_cm: number;
  goal: HealthGoal; // 🚨 NAPRAWA BUGA: cel jest zagnieżdżony w "goal"
}

export type RouteKind = 'fastest' | 'healthy' | 'balanced';
export type TransportMode = 'walk' | 'bike' | 'transit';

export interface RouteSummary {
  route_id: string;      // (nie "id"!)
  kind: RouteKind;       // (nie "type"!)
  label: string;
  duration_min: number;  // (nie "duration_minutes"!)
  steps: number;
  calories: number;
  bbox: number[];        // [min_lon, min_lat, max_lon, max_lat]
  warnings: string[];
}

export interface MapPlanResponse {
  plan_id: string;
  bbox: number[];
  routes: RouteSummary[];
  selected_route_id: string | null; // null → fallback routes[0]
  alerts: string[];
  user_goal: HealthGoal;
}

export interface GeoPoint {
  lat: number;
  lon: number;
  label?: string | null; // czytelna nazwa (z geocode/reverse)
}

interface AppState {
    view: 'map' | 'profile';
setView: (v: 'map' | 'profile') => void;
  user: User | null;
  origin: GeoPoint | null;
  destination: GeoPoint | null;
  modes: TransportMode[];          // do requestu POST /map/plan
  timeBudgetMinutes: number | null; // "AI agent" / budżet czasu
  plan: MapPlanResponse | null;
  selectedRouteId: string | null;
  routeGeoJsonCache: Record<string, unknown>;
  mapClickTarget: 'origin' | 'destination' | null;
  

  setUser: (u: User | null) => void;
  setOrigin: (p: GeoPoint | null) => void;
  setDestination: (p: GeoPoint | null) => void;
  setMapClickTarget: (t: 'origin' | 'destination' | null) => void;
  toggleMode: (m: TransportMode) => void;
  setTimeBudgetMinutes: (m: number | null) => void;
  setPlan: (p: MapPlanResponse) => void;
  setSelectedRouteId: (id: string) => void;
  addGeoJsonToCache: (routeId: string, geoJson: unknown) => void;
}

export const useAppStore = create<AppState>((set) => ({
  user: null,
  origin: null,
  destination: null,
  modes: ['walk', 'bike'],
  timeBudgetMinutes: null,
  plan: null,
  selectedRouteId: null,
  routeGeoJsonCache: {},
  mapClickTarget: null,
  view: 'map',
setView: (v) => { logger.store(`🧭 view → ${v}`); set({ view: v }); },

  setUser: (u) => { logger.store('👤 setUser', u); set({ user: u }); },

  // Wymóg A (State Clearing): zmiana punktu = sprzątanie planu i cache
  setOrigin: (p) => {
    logger.store('✏️ setOrigin + 🧹 czyszczenie planu', p);
    set({ origin: p, plan: null, selectedRouteId: null, routeGeoJsonCache: {} });
  },
  setDestination: (p) => {
    logger.store('✏️ setDestination + 🧹 czyszczenie planu', p);
    set({ destination: p, plan: null, selectedRouteId: null, routeGeoJsonCache: {} });
  },

  setMapClickTarget: (t) => {
    logger.store(`🚦 mapClickTarget → ${t ?? 'null'}`);
    set({ mapClickTarget: t });
  },

  toggleMode: (m) =>
    set((s) => ({
      modes: s.modes.includes(m) ? s.modes.filter((x) => x !== m) : [...s.modes, m],
    })),

  setTimeBudgetMinutes: (m) => set({ timeBudgetMinutes: m }),

  // Wymóg B (Auto-Select): backend decyduje; null → pierwsza trasa
  setPlan: (p) => {
    const fallback = p.selected_route_id ?? p.routes[0]?.route_id ?? null;
    logger.store('🗺️ setPlan, auto-select:', fallback);
    set({ plan: p, selectedRouteId: fallback });
  },

  setSelectedRouteId: (id) => {
    logger.store('🎯 setSelectedRouteId (klik użytkownika):', id);
    set({ selectedRouteId: id });
  },

  addGeoJsonToCache: (routeId, geoJson) => {
    logger.store(`💾 cache GeoJSON: ${routeId}`);
    set((s) => ({ routeGeoJsonCache: { ...s.routeGeoJsonCache, [routeId]: geoJson } }));
  },
}));