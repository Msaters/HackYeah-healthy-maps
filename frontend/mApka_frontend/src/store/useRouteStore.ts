// src/store/useRouteStore.ts — stan planera tras (osobny od useAppStore)
import { create } from 'zustand';
import { planRoutes, type LatLon, type RoutesResponse } from '../api/routes';

const TZ = 'Europe/Warsaw';

/** Offset "+02:00" of Europe/Warsaw at the given instant, computed via Intl. */
function warsawOffset(at: Date): string {
  const dtf = new Intl.DateTimeFormat('en-US', {
    timeZone: TZ, hourCycle: 'h23',
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
  const p = Object.fromEntries(dtf.formatToParts(at).map((x) => [x.type, x.value]));
  const asUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
  const mins = Math.round((asUtc - Math.floor(at.getTime() / 1000) * 1000) / 60000);
  const sign = mins >= 0 ? '+' : '-';
  const a = Math.abs(mins);
  return `${sign}${String(Math.floor(a / 60)).padStart(2, '0')}:${String(a % 60).padStart(2, '0')}`;
}

function warsawParts(at: Date) {
  const dtf = new Intl.DateTimeFormat('en-CA', {
    timeZone: TZ, hourCycle: 'h23',
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  });
  const p = Object.fromEntries(dtf.formatToParts(at).map((x) => [x.type, x.value]));
  return { y: +p.year, mo: +p.month, d: +p.day, h: +p.hour, mi: +p.minute };
}

/** Wall-clock Warsaw date+time -> ISO string with offset (never "Z"). */
export function toWarsawIso(y: number, mo: number, d: number, h: number, mi: number): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  // Offset guess from noon of that day (DST switches happen at night)
  const guess = new Date(Date.UTC(y, mo - 1, d, 12, 0, 0));
  const off = warsawOffset(guess);
  return `${y}-${pad(mo)}-${pad(d)}T${pad(h)}:${pad(mi)}:00${off}`;
}

/** Default deadline: next full hour + 1h; after 18:00 -> tomorrow 08:30. Warsaw time. */
export function defaultDeadline(now: Date = new Date()): string {
  const n = warsawParts(now);
  if (n.h >= 18) {
    const t = new Date(Date.UTC(n.y, n.mo - 1, n.d + 1));
    return toWarsawIso(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate(), 8, 30);
  }
  const t = new Date(Date.UTC(n.y, n.mo - 1, n.d, n.h + 2, 0));
  return toWarsawIso(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate(), t.getUTCHours(), 0);
}

/** "HH:MM" of an ISO deadline (Warsaw wall clock as written). */
export const deadlineTime = (iso: string): string => iso.slice(11, 16);

/** Replace time-of-day, keeping the date: past times roll over to tomorrow. */
export function withTime(iso: string, hhmm: string, now: Date = new Date()): string {
  const [h, mi] = hhmm.split(':').map(Number);
  const n = warsawParts(now);
  let t = new Date(Date.UTC(n.y, n.mo - 1, n.d));
  if (h * 60 + mi <= n.h * 60 + n.mi + 5) t = new Date(Date.UTC(n.y, n.mo - 1, n.d + 1));
  void iso;
  return toWarsawIso(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate(), h, mi);
}

/** Human label for the deadline date: "dziś" / "jutro". */
export function deadlineDayLabel(iso: string, now: Date = new Date()): string {
  const n = warsawParts(now);
  const today = `${n.y}-${String(n.mo).padStart(2, '0')}-${String(n.d).padStart(2, '0')}`;
  return iso.slice(0, 10) === today ? 'dziś' : 'jutro';
}

type Status = 'idle' | 'loading' | 'error' | 'ok';

interface RouteState {
  status: Status;
  error: string | null;
  data: RoutesResponse | null;
  selectedIndex: number;
  deadline: string;
  hasBike: boolean;
  simulateSmog: boolean;

  setDeadlineTime: (hhmm: string) => void;
  setHasBike: (v: boolean) => void;
  setSimulateSmog: (v: boolean) => void;
  setSelectedIndex: (i: number) => void;
  plan: (
    origin: LatLon,
    dest: LatLon,
    user?: { weight_kg: number; height_cm: number } | null,
  ) => Promise<void>;
  clear: () => void;
}

let seq = 0;
let controller: AbortController | null = null;

export const useRouteStore = create<RouteState>((set, get) => ({
  status: 'idle',
  error: null,
  data: null,
  selectedIndex: 0,
  deadline: defaultDeadline(),
  hasBike: true,
  simulateSmog: false,

  setDeadlineTime: (hhmm) => set({ deadline: withTime(get().deadline, hhmm) }),
  setHasBike: (v) => set({ hasBike: v }),
  setSimulateSmog: (v) => set({ simulateSmog: v }),
  setSelectedIndex: (i) => set({ selectedIndex: i }),

  plan: async (origin, dest, user) => {
    const my = ++seq;
    controller?.abort();
    controller = new AbortController();
    const { signal } = controller;
    const s = get();
    set({ status: 'loading', error: null });
    try {
      const data = await planRoutes(
        {
          from: { lat: origin.lat, lon: origin.lon },
          to: { lat: dest.lat, lon: dest.lon },
          deadline: s.deadline,
          has_bike: s.hasBike,
          user_profile: user ? { weight_kg: user.weight_kg, height_m: user.height_cm / 100 } : undefined,
          lock_reason: s.simulateSmog ? 'smog' : null,
          buffer_min: 3,
        },
        signal,
      );
      if (my !== seq) return; // stale response
      const idx = Math.min(Math.max(data.default_index, 0), Math.max(data.positions.length - 1, 0));
      set({ status: 'ok', data, selectedIndex: idx, error: null });
    } catch (e) {
      if (my !== seq) return;
      set({ status: 'error', error: e instanceof Error ? e.message : 'Nieznany błąd', data: null });
    }
  },

  clear: () => {
    seq++;
    controller?.abort();
    set({ status: 'idle', error: null, data: null, selectedIndex: 0 });
  },
}));
