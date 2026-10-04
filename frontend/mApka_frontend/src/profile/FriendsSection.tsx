import { UserPlus, Users } from 'lucide-react';

// PROTOTYP: backend NIE będzie miał znajomych – to "klej" emocjonalny UI
const FRIENDS = [
  { name: 'Kasia', steps: 9120,  color: 'bg-pink-200 text-pink-800' },
  { name: 'Marek', steps: 7450,  color: 'bg-blue-200 text-blue-800' },
  { name: 'Ola',   steps: 11030, color: 'bg-green-200 text-green-800' },
  { name: 'Tomek', steps: 3200,  color: 'bg-amber-200 text-amber-800' },
];

export default function FriendsSection() {
  return (
    <section className="rounded-2xl bg-white p-4 shadow">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-2 font-semibold text-gray-700">
          <Users className="text-violet-600" /> Znajomi
        </h2>
        <span className="rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-bold text-violet-600">
          PROTOTYP – wkrótce
        </span>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {FRIENDS.map((f) => (
          <div key={f.name} className="flex flex-col items-center gap-1">
            {/* Awatar z inicjału – zero zewnętrznych obrazków */}
            <div className={`flex h-14 w-14 items-center justify-center rounded-full text-xl font-bold ${f.color}`}>
              {f.name[0]}
            </div>
            <span className="text-xs font-semibold text-gray-700">{f.name}</span>
            <span className="text-[10px] text-gray-500">{f.steps.toLocaleString('pl-PL')} kroków</span>
          </div>
        ))}

        {/* Karta-zaproszenie (zachęta do growth) */}
        <div className="col-span-4 flex items-center justify-center gap-2 rounded-xl border-2 border-dashed border-gray-300 py-3 text-sm text-gray-500">
          <UserPlus size={16} /> Zaproś znajomych i rywalizujcie o kroki!
        </div>
      </div>
    </section>
  );
}