// src/profile/ProgressRing.tsx
import { useId } from 'react';
import clayRing from '../assets/pictures/Kolo_postepu_pelne.png';

// 🎨 PALETA FILTRÓW – tutaj kręcisz kolorami całego pierścienia:
const TRACK_FILTER = 'grayscale(1) brightness(1.55)';        // niewypełniony tor (jasnoszary)
const NORMAL_FILTER = 'none';                                // zwykły kolor gliny (fiolet)
const DONE_FILTER = 'hue-rotate(150deg) saturate(1.3)';      // po 100% → zieleń

interface Props {
  current: number;
  goal: number;
  size?: number;
}

export default function ClayProgressRing({ current, goal, size = 220 }: Props) {
  const maskId = useId().replace(/:/g, '');

  const rawPercent = Math.round((current / goal) * 100);
  const displayPercent = Math.min(999, rawPercent);
  const progress = Math.min(1, Math.max(0, current / goal));
  const goalDone = rawPercent >= 100; //  przełącznik koloru po 100%

  const strokeWidth = size * 0.18;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - progress);

  const overGoal = current > goal ? current - goal : 0;

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <defs>
          <mask id={maskId}>
            <rect width={size} height={size} fill="black" />
            <circle
              cx={size / 2} cy={size / 2} r={radius}
              fill="none" stroke="white"
              strokeWidth={strokeWidth} strokeLinecap="round"
              strokeDasharray={circumference} strokeDashoffset={offset}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
              style={{ transition: 'stroke-dashoffset 0.7s ease' }}
            />
          </mask>
        </defs>

        {/* WARSTWA 1: NIEWYPEŁNIONY TOR – inny kolor (szara glina) */}
        <image
          href={clayRing} width={size} height={size}
          style={{ filter: TRACK_FILTER }}
        />

        {/* WARSTWA 2: WYPEŁNIENIE – fiolet, a po 100% płynnie ZIELEŃ */}
        <image
          href={clayRing} width={size} height={size}
          mask={`url(#${maskId})`}
          style={{
            filter: goalDone ? DONE_FILTER : NORMAL_FILTER,
            opacity: progress === 0 ? 0 : 1,
            transition: 'filter 0.7s ease, opacity 0.3s ease',
          }}
        />
      </svg>

      {/* Tekst w środku */}
      <div className="absolute inset-0 flex flex-col items-center justify-center px-6 text-center">
        <span className="text-xs text-gray-500">Dzisiaj:</span>
        <span className="text-3xl font-bold tabular-nums text-gray-800">
          {current.toLocaleString('pl-PL')}
        </span>
        <span className="text-xs text-gray-500">z {goal.toLocaleString('pl-PL')} kroków</span>
        <span
          className={`mt-1 text-lg font-extrabold tabular-nums ${
            goalDone ? 'text-green-600' : 'text-violet-600'
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