import { CalendarDays, Flame } from 'lucide-react';

// PROTOTYP: zmyślone dane – później podmienimy na prawdziwe z backendu
const DAYS = [
  { label: 'Pn', count: 0 },  { label: 'Wt', count: 7 },  { label: 'Śr', count: 3 },
  { label: 'Cz', count: 3 },  { label: 'Pt', count: 14 }, { label: 'So', count: 10 },
  { label: 'Nd', count: 12 }, { label: 'Pn', count: 10 }, { label: 'Wt', count: 15 },
  { label: 'Śr', count: 17 }, { label: 'Cz', count: 12 }, { label: 'Pt', count: 10 },
  { label: 'So', count: 14 }, { label: 'Nd', count: 10 },
];

// Liczy serię od KOŃCA: ile dni z rzędu (od dziś) użytkownik coś zrobił
function currentStreak(): number {
  let streak = 0;
  for (let i = DAYS.length - 1; i >= 0; i--) {
    if (DAYS[i].count > 0) streak++;
    else break;
  }
  return streak;
}

export default function StreakCalendar() {
  return (
    <section className="rounded-2xl bg-white p-4 shadow">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-2 font-semibold text-gray-700">
          <CalendarDays className="text-orange-500" /> Ostatnie 14 dni
        </h2>
        <span className="flex items-center gap-1 rounded-full bg-orange-100 px-3 py-1 text-sm font-bold text-orange-600">
          <Flame size={16} fill="currentColor" /> {currentStreak()} dni z rzędu
        </span>
      </div>

      <div className="grid grid-cols-7 gap-2">
        {DAYS.map((d, i) => (
          <div key={i} className="flex flex-col items-center gap-1">
            <div className="relative flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
              {d.count > 0 ? (
                <>
                  <Flame className="text-orange-500" size={20} fill="currentColor" />
                  {/* badge z liczbą (jak na Twoim mockupie) */}
                  <span className="absolute -right-1.5 -top-1.5 rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                    {d.count}
                  </span>
                </>
              ) : (
                <span className="text-xs text-gray-300">–</span>
              )}
            </div>
            <span className="text-[10px] text-gray-500">{d.label}</span>
          </div>
        ))}
      </div>
    </section>
  );
}