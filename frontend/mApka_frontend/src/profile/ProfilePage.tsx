import { useState } from 'react';
import { Footprints, User } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import ProgressBar from '../profile/ProgressBar';
import ProgressRing from '../profile/ProgressRing';
import StreakCalendar from '../profile/StreakCalendar';
import FriendsSection from '../profile/FriendsSection';
import IntegrationsSection from '../profile/IntegrationsSection';
import ClayFrame from './ClayFrame';
import gearIcon from '../assets/pictures/Ustawienia.png';
import tloJpg from '../assets/pictures/tlo.jpg';

export default function ProfilePage() {
  const user = useAppStore((s) => s.user);
  const goal = user?.goal.target_steps ?? 10000;
  const [steps, setSteps] = useState(7450);

  return (
    // 📦 1. NAJWIĘKSZE PUDEŁKO: Cały ekran z tłem JPG
    <div
      className="min-h-[100dvh] overflow-y-auto pb-24 relative"
      style={{
        backgroundImage: `url(${tloJpg})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        backgroundAttachment: 'fixed',
      }}
    >
      {/* 🌫️ Mgiełka przyciemniająca tło (leży płasko na ekranie) */}
      <div className="absolute inset-0 bg-black/10 pointer-events-none" />

      {/* ⚙️ Zębatka – jest "fixed", więc unosi się nad wszystkim, niezależnie od scrollowania */}
      <button
        title="Ustawienia"
        onClick={() => console.log('[PROFIL] kliknięto Ustawienia (makieta)')}
        className="fixed right-4 top-4 z-[1100] transition-transform duration-300 hover:rotate-45"
      >
        <img src={gearIcon} alt="Ustawienia" className="h-12 w-12 drop-shadow-lg" />
      </button>

      {/* 📦 2. PUDEŁKO NA TREŚĆ: Wyśrodkowane, z odpowiednimi odstępami, nad mgiełką (z-10) */}
      <div className="relative z-10 mx-auto flex max-w-3xl flex-col gap-6 p-4 pt-20">
        
        {/* pt-20 (padding-top) dodałem, żeby zębatka nie nachodziła na nagłówek profilu */}

        {/* 1️⃣ Nagłówek */}
        <ClayFrame className="flex items-center gap-4 px-6 py-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-violet-200">
            <User size={32} className="text-violet-700" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-800">{user?.name ?? 'Gość'}</h1>
            <p className="text-sm text-gray-500">{user?.email ?? 'wróć do mapy i zaloguj się jako demo'}</p>
            <div className="mt-1 flex gap-2 text-[11px] text-gray-600">
              <span className="rounded-full bg-white/70 px-2 py-0.5">⚖️ {user?.weight_kg ?? '–'} kg</span>
              <span className="rounded-full bg-white/70 px-2 py-0.5">📏 {user?.height_cm ?? '–'} cm</span>
            </div>
          </div>
        </ClayFrame>

        {/* 2️⃣ Dzisiejszy postęp */}
        <ClayFrame className="flex flex-col items-center gap-4 px-6 py-6">
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
        </ClayFrame>

        <StreakCalendar />
        <FriendsSection />
        <IntegrationsSection />

      </div>
    </div>   
  );
}