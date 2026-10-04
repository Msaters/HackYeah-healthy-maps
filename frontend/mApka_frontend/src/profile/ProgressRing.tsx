interface Props {
  current: number;
  goal: number;
  size?: number;
  strokeWidth?: number;
}

export default function ProgressRing({ current, goal, size = 190, strokeWidth = 16 }: Props) {
  // PRAWDZIWY procent (bez limitu) – steruje kolorem i nadwyżką
  const rawPercent = Math.round((current / goal) * 100);

  // 🎯 LICZNIK W ŚRODKU – rośnie aż do 999%, wyżej pokazuje "999%+"
  const displayPercent = Math.min(999, rawPercent);

  // RYSOWANIE KOŁA – clamp 0..1 (obwód SVG nie może się "przewinąć")
  const progress = Math.min(1, Math.max(0, current / goal));

  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - progress);

  const overGoal = current > goal ? current - goal : 0;

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#e5e7eb" strokeWidth={strokeWidth} />
        <circle
          cx={size / 2} cy={size / 2} r={radius} fill="none"
          stroke={rawPercent >= 100 ? '#16a34a' : '#8b5cf6'}
          strokeWidth={strokeWidth} strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 0.7s ease, stroke 0.7s ease' }}
        />
      </svg>

      <div className="absolute inset-0 flex flex-col items-center justify-center px-4 text-center">
        <span className="text-xs text-gray-500">Dzisiaj:</span>
        {/* tabular-nums = cyfry mają stałą szerokość, więc tekst nie "skacze" przy zmianach */}
        <span className="text-3xl font-bold tabular-nums text-gray-800">
          {current.toLocaleString('pl-PL')}
        </span>
        <span className="text-xs text-gray-500">z {goal.toLocaleString('pl-PL')} kroków</span>

        {/* 🚀 LICZNIK PROCENT – rośnie do 999% */}
        <span
          className={`mt-1 text-lg font-extrabold tabular-nums ${
            rawPercent >= 100 ? 'text-green-600' : 'text-violet-600'
          }`}
        >
          {displayPercent}%{rawPercent > 999 ? '+' : ''}
        </span>

        {overGoal > 0 && (
          <span className="mt-1 text-[10px] font-semibold text-green-600">
            🎉 +{overGoal.toLocaleString('pl-PL')}
          </span>
        )}
      </div>
    </div>
  );
}