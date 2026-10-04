import { useState } from 'react';
import { Footprints, User } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import ProgressBar from '../profile/ProgressBar';
import ProgressRing from '../profile/ProgressRing';
import StreakCalendar from '../profile/StreakCalendar';
import FriendsSection from '../profile/FriendsSection';
import IntegrationsSection from '../profile/IntegrationsSection';


export default function ProfilePage() {
  const user = useAppStore((s) => s.user);
  const goal = user?.goal.target_steps ?? 10000;
  const [steps, setSteps] = useState(7450); // PROTOTYP: suwak symuluje dane z Apple Health

  return (
    <div className="min-h-[100dvh] overflow-y-auto bg-gray-100 pb-24">
      <div className="mx-auto flex max-w-3xl flex-col gap-4 p-4">

        {/* Nagłówek z danymi usera ze store'a */}
        <header className="flex items-center gap-4 rounded-2xl bg-white p-4 shadow">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-violet-200">
            <User size={32} className="text-violet-700" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-800">{user?.name ?? 'Gość'}</h1>
            <p className="text-sm text-gray-500">{user?.email ?? 'wróć do mapy i zaloguj się jako demo'}</p>
            <div className="mt-1 flex gap-2 text-[11px] text-gray-600">
              <span className="rounded-full bg-gray-100 px-2 py-0.5">⚖️ {user?.weight_kg ?? '–'} kg</span>
              <span className="rounded-full bg-gray-100 px-2 py-0.5">📏 {user?.height_cm ?? '–'} cm</span>
            </div>
          </div>
        </header>

        {/* Dzisiejszy postęp: pierścień + pasek + SUWAK-SYMULATOR */}
        <section className="flex flex-col items-center gap-4 rounded-2xl bg-white p-4 shadow">
          <h2 className="flex items-center gap-2 self-start font-semibold text-gray-700">
            <Footprints className="text-violet-600" /> Dzisiejszy postęp
          </h2>

          <ProgressRing current={steps} goal={goal} />
          <div className="w-full"><ProgressBar current={steps} goal={goal} /></div>

          <div className="w-full">
            <label className="text-xs text-gray-500">🎚️ Symulator kroków (pociągnij i patrz, jak się wypełnia):</label>
            <input
              type="range" min={0} max={60000} step={250} value={steps}
              onChange={(e) => setSteps(Number(e.target.value))}
              className="w-full accent-violet-600"
            />
          </div>
        </section>

        <StreakCalendar />
        <FriendsSection />
        <IntegrationsSection />

      </div>
    </div>
  );
}