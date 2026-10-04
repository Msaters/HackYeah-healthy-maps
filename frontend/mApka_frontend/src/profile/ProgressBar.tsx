interface Props {
  current: number;
  goal: number;
}

export default function ProgressBar({ current, goal }: Props) {
  // PROCENT DO WYŚWIETLENIA – bez clampu, może być 150%, 200% itd.
  const percent = Math.round((current / goal) * 100);

  // SZEROKOŚĆ PASKA – clamp, żeby nie wylał się z kontenera
  const widthPercent = Math.min(100, Math.max(0, percent));

  const overGoal = current > goal ? current - goal : 0;

  return (
    <div className="w-full">
      <div className="mb-1 flex justify-between text-xs text-gray-600">
        <span>
          Dzisiaj: <b>{current.toLocaleString('pl-PL')}</b> kroków
        </span>
        <span>Cel: {goal.toLocaleString('pl-PL')}</span>
      </div>

      <div className="h-4 w-full overflow-hidden rounded-full bg-gray-200">
        <div
          className="h-full rounded-full bg-gradient-to-r from-violet-500 to-green-500 transition-all duration-700"
          style={{ width: `${widthPercent}%` }}
        />
      </div>

      <div className="mt-1 flex items-center justify-between text-xs">
        {/* PROCENT PRAWDZIWY – może być >100 */}
        <span
          className={`font-bold ${
            percent >= 100 ? 'text-green-600' : 'text-gray-700'
          }`}
        >
          {percent}%
        </span>

        {/* KOMUNIKAT "NADWYŻKI" – motywacyjny boost */}
        {overGoal > 0 && (
          <span className="rounded-full bg-green-100 px-2 py-0.5 font-semibold text-green-700">
            🎉 +{overGoal.toLocaleString('pl-PL')} ponad cel!
          </span>
        )}
      </div>
    </div>
  );
}