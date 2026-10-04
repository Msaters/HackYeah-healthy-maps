// src/components/profile/IntegrationsSection.tsx
import { useState } from 'react';
import { Apple, Plug } from 'lucide-react';

// Logo Google jako mały inline SVG (lucide nie ma logotypów marek)
function GoogleIcon({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

// KONFIGURACJA DOSTAWCÓW: chcesz dodać Garmin? Dopisz obiekt i gotowe.
const PROVIDERS = [
  { id: 'apple',  name: 'Apple Health', desc: 'Kroki i treningi z iPhone / Apple Watch' },
  { id: 'google', name: 'Google Fit',   desc: 'Kroki i aktywność z Androida' },
];

export default function IntegrationsSection() {
  // PROTOTYP: stan połączeń tylko lokalnie (bez backendu i OAuth)
  const [connected, setConnected] = useState<Record<string, boolean>>({
    apple: true,   // dla efektu demo: Apple "już połączone"
    google: false,
  });

  const toggle = (id: string) => setConnected((c) => ({ ...c, [id]: !c[id] }));

  return (
    <section className="rounded-2xl bg-white p-4 shadow">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="flex items-center gap-2 font-semibold text-gray-700">
          <Plug size={18} className="text-violet-600" /> Integracje
        </h2>
        <span className="rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-bold text-violet-600">
          MAKIETA
        </span>
      </div>

      {/* Uczciwa notka dla sędziów/zespołu */}
      <p className="mb-2 text-xs text-gray-500">
        Miejsce gotowe na prawdziwe OAuth – w kolejnej wersji podłączymy tu API
        Apple Health i Google Fit (endpointy trafią do <code>src/api/client.ts</code>).
      </p>

      <div className="divide-y divide-gray-100">
        {PROVIDERS.map((p) => (
          <div key={p.id} className="flex items-center gap-3 py-3">
            {/* Kafel z logo marki */}
            <span
              className={`rounded-xl p-2 ${
                p.id === 'apple' ? 'bg-black text-white' : 'border border-gray-200 bg-white'
              }`}
            >
              {p.id === 'apple' ? <Apple size={22} fill="currentColor" /> : <GoogleIcon />}
            </span>

            <span className="flex-1">
              <span className="block text-sm font-semibold text-gray-700">{p.name}</span>
              <span className="block text-xs text-gray-500">{p.desc}</span>
            </span>

            {/* Przycisk-toggle: w makiecie tylko klika, w przyszłości odpali OAuth */}
            <button
              onClick={() => toggle(p.id)}
              className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors ${
                connected[p.id]
                  ? 'bg-green-100 text-green-700'
                  : 'bg-gray-800 text-white hover:bg-gray-700'
              }`}
            >
              <span className={`h-2 w-2 rounded-full ${connected[p.id] ? 'bg-green-500' : 'bg-gray-400'}`} />
              {connected[p.id] ? 'Połączono' : 'Połącz'}
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}