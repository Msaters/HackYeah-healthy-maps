// src/components/RoutePanel.tsx — panel planera: godzina, rower, smog, suwak czas <-> ruch, karta trasy
import { useState } from 'react';
import { ChevronDown, ChevronUp, Loader2, RefreshCw, Route as RouteIcon } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { useRouteStore, deadlineDayLabel, deadlineTime } from '../store/useRouteStore';
import { modeStyle } from './routeStyle';

const LEVEL_STYLE: Record<string, string> = {
  SAFE: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  CAUTION: 'bg-amber-50 text-amber-800 border-amber-200',
  WARNING: 'bg-orange-50 text-orange-800 border-orange-200',
  DANGER: 'bg-red-50 text-red-800 border-red-200',
};
const levelClass = (l: string | undefined) => LEVEL_STYLE[l ?? 'SAFE'] ?? LEVEL_STYLE.CAUTION;

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`min-h-10 rounded-xl border px-2.5 text-xs font-semibold whitespace-nowrap transition-colors md:text-sm ${
        checked ? 'border-violet-600 bg-violet-600 text-white' : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
      }`}
    >
      {label}
    </button>
  );
}

const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'));
const MINUTES = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, '0'));
const selectCls = 'min-h-10 rounded-xl border border-gray-200 bg-white px-1.5 text-sm font-semibold text-gray-800';

export default function RoutePanel() {
  const origin = useAppStore((s) => s.origin);
  const destination = useAppStore((s) => s.destination);
  const user = useAppStore((s) => s.user);
  const r = useRouteStore();
  const [open, setOpen] = useState(true);

  const ready = !!origin && !!destination;
  const run = () => {
    if (origin && destination) void r.plan(origin, destination, user);
  };

  const positions = r.data?.positions ?? [];
  const sel = positions[r.selectedIndex];
  const env = r.data?.environment;

  return (
    <section
      aria-label="Planer tras"
      className="absolute right-2 bottom-[84px] left-2 z-[1000] flex max-h-[48dvh] flex-col overflow-hidden rounded-2xl bg-white shadow-xl md:top-4 md:right-4 md:bottom-auto md:left-auto md:max-h-[calc(100dvh-110px)] md:w-96"
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex min-h-9 items-center justify-between gap-2 px-4 py-1.5 text-left"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2 text-base font-bold text-gray-800">
          <RouteIcon size={18} className="text-violet-600" /> Dojedź na czas, ruszaj się po drodze
        </span>
        {open ? <ChevronDown size={18} /> : <ChevronUp size={18} />}
      </button>

      {open && (
        <div className="flex flex-col gap-2 overflow-y-auto px-4 pb-3 md:gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-gray-700 md:text-sm">Na miejscu o</span>
            <select
              aria-label="Godzina przyjazdu"
              value={deadlineTime(r.deadline).slice(0, 2)}
              onChange={(e) => r.setDeadlineTime(`${e.target.value}:${deadlineTime(r.deadline).slice(3, 5)}`)}
              className={selectCls}
            >
              {HOURS.map((h) => <option key={h}>{h}</option>)}
            </select>
            <span className="-mx-1 font-bold">:</span>
            <select
              aria-label="Minuta przyjazdu"
              value={MINUTES.includes(deadlineTime(r.deadline).slice(3, 5)) ? deadlineTime(r.deadline).slice(3, 5) : '00'}
              onChange={(e) => r.setDeadlineTime(`${deadlineTime(r.deadline).slice(0, 2)}:${e.target.value}`)}
              className={selectCls}
            >
              {MINUTES.map((m) => <option key={m}>{m}</option>)}
            </select>
            <span className="text-xs text-gray-500">({deadlineDayLabel(r.deadline)})</span>
          </div>

          <div className="flex gap-2">
            <Toggle checked={r.hasBike} onChange={r.setHasBike} label="🚲 Mam rower" />
            <Toggle checked={r.simulateSmog} onChange={r.setSimulateSmog} label="🌫️ Symuluj smog" />
            <button
              type="button"
              disabled={!ready || r.status === 'loading'}
              onClick={run}
              className="flex min-h-10 flex-1 items-center justify-center gap-1 rounded-xl bg-violet-600 px-2 text-xs font-bold text-white shadow transition-colors hover:bg-violet-700 disabled:cursor-not-allowed disabled:bg-gray-300 md:text-sm"
            >
              {r.status === 'loading' ? <Loader2 size={16} className="animate-spin" /> : <RouteIcon size={16} />}
              Wyznacz trasę
            </button>
          </div>
          {!ready && <p className="text-xs text-gray-500">Ustaw START i CEL, klikając w mapę.</p>}

          {r.status === 'loading' && (
            <p role="status" className="flex items-center gap-2 text-sm text-gray-600">
              <Loader2 size={16} className="animate-spin text-violet-600" /> Szukam tras…
            </p>
          )}

          {r.status === 'error' && (
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              <p>{r.error}</p>
              <button
                type="button"
                onClick={run}
                disabled={!ready}
                className="mt-2 flex min-h-10 items-center gap-1 rounded-lg bg-red-600 px-3 font-semibold text-white"
              >
                <RefreshCw size={16} /> Spróbuj ponownie
              </button>
            </div>
          )}

          {r.status === 'ok' && env && (
            <p className={`rounded-xl border px-3 py-1.5 text-xs md:p-3 md:text-sm ${levelClass(env.overall_level)}`}>{env.summary}</p>
          )}

          {r.status === 'ok' && positions.length === 0 && (
            <p className="rounded-xl bg-gray-50 p-3 text-sm text-gray-700">
              Nie znaleźliśmy trasy, która zdąży na czas. Spróbuj późniejszej godziny.
            </p>
          )}

          {r.status === 'ok' && sel && (
            <>
              <div>
                <div className="mb-1 flex justify-between text-xs font-semibold text-gray-600">
                  <span>⏱️ Szybciej</span>
                  <span>Więcej ruchu 💪</span>
                </div>
                <input
                  type="range"
                  aria-label="Czas lub ruch"
                  min={0}
                  max={Math.max(positions.length - 1, 0)}
                  step={1}
                  value={r.selectedIndex}
                  disabled={positions.length < 2}
                  onChange={(e) => r.setSelectedIndex(Number(e.target.value))}
                  className="h-6 w-full accent-violet-600"
                />
              </div>

              <article className="rounded-2xl border border-violet-100 bg-violet-50/60 p-2.5 md:p-3" data-testid="route-card">
                <div className="flex items-baseline justify-between gap-2">
                  <p className="text-2xl font-extrabold text-gray-900">
                    {Math.round(sel.metrics.duration_min)} <span className="text-base font-bold">min</span>
                  </p>
                  <p className="text-right text-sm font-semibold text-emerald-700">
                    Zdążysz z zapasem {Math.round(sel.metrics.slack_min)} min
                  </p>
                </div>
                <div className="mt-1.5 flex gap-2 text-sm font-semibold text-gray-800">
                  <span className="rounded-lg bg-white px-2 py-1 shadow-sm">🔥 ~{Math.round(sel.metrics.active_kcal)} kcal</span>
                  {sel.metrics.steps > 0 && (
                    <span className="rounded-lg bg-white px-2 py-1 shadow-sm">👣 ~{sel.metrics.steps.toLocaleString('pl-PL')} kroków</span>
                  )}
                </div>
                <ul className="mt-1.5 flex flex-wrap gap-1.5">
                  {sel.itinerary.legs.map((leg, i) => {
                    const st = modeStyle(leg.mode);
                    return (
                      <li
                        key={i}
                        className="flex items-center gap-1 rounded-full bg-white px-2 py-1 text-xs font-semibold text-gray-700 shadow-sm"
                      >
                        <span className="h-2 w-2 rounded-full" style={{ background: st.color }} />
                        {st.icon} {leg.route?.shortName ?? st.label} · {Math.max(1, Math.round(leg.duration / 60))}′
                      </li>
                    );
                  })}
                </ul>
                {sel.fallback && (
                  <p className="mt-2 rounded-lg bg-sky-50 px-2 py-1 text-xs font-semibold text-sky-800">
                    🛟 Bezpieczna alternatywa
                  </p>
                )}
                {sel.advisory && sel.advisory.level !== 'SAFE' && (
                  <p className={`mt-2 rounded-xl border p-2 text-xs ${levelClass(sel.advisory.level)}`}>
                    <b>{sel.advisory.badge}</b> — {sel.advisory.message}
                  </p>
                )}
              </article>
            </>
          )}
        </div>
      )}
    </section>
  );
}
