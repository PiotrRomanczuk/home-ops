// Why a project ranks where it does: every part of the pressure score
// (pressure-model.ts), so the ranking is never a black box.

import type { PressureRow } from '@/lib/api';

function Line({ label, detail, points }: { label: string; detail: string; points: number }) {
  return (
    <div className="flex items-baseline gap-2 py-0.5">
      <span className="w-20 shrink-0 text-muted-foreground">{label}</span>
      <span className="grow truncate" title={detail}>
        {detail || '—'}
      </span>
      <span className="font-mono tabular-nums">{points ? `+${Math.round(points * 10) / 10}` : '0'}</span>
    </div>
  );
}

export function PressureBreakdown({ row }: { row: PressureRow }) {
  const { tasks, pain, gaps, issues, runtime } = row.parts;
  const runtimeFlags = [
    runtime.errorPatterns ? `${runtime.errorPatterns} wzorce błędów / 24 h` : '',
    runtime.ciFailed ? 'CI czerwone' : '',
    runtime.down ? 'deploy DOWN' : '',
  ].filter(Boolean);
  return (
    <div className="space-y-1 text-xs">
      <Line
        label="Zadania"
        detail={`🔴 ${tasks.red} · 💰 ${tasks.money} · inne klasy ${tasks.other} · bez klasy ${tasks.unclassed}`}
        points={tasks.points}
      />
      <Line label="Pain points" detail={pain.n ? `${pain.n} otwartych` : ''} points={pain.points} />
      <Line
        label="Luki"
        detail={
          gaps.hasBlueprint
            ? `${gaps.n} otwartych${gaps.ids.length ? `: ${gaps.ids.join(', ')}` : ''}`
            : 'brak blueprintu'
        }
        points={gaps.points}
      />
      <Line
        label="Issues"
        detail={issues.open ? `${issues.open} otwartych, ${issues.bugs} z etykietą bug` : ''}
        points={issues.points}
      />
      <Line label="Runtime" detail={runtimeFlags.join(' · ')} points={runtime.points} />
      <div className="mt-2 border-t pt-2 font-mono tabular-nums">
        {row.base} baza × {row.blast} blast × {row.statusWeight} status = <b className="text-foreground">{row.score}</b>
      </div>
    </div>
  );
}
