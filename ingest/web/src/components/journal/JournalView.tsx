// "Dziennik" — one day of the Mac in one place: the local model's note, what
// was done with Claude (per project, per session, down to each prompt) and
// what ran on the machine. Data: GET /api/journal/day (migration 032).

import { useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { fetchJournal, fmtMin, type JournalDay, lanes, shiftDay, summarySections, today } from '@/lib/journal';
import { HourChart } from './HourChart';
import { ProcessPanel } from './ProcessPanel';
import { SessionLanes } from './SessionLanes';
import { SessionTable } from './SessionTable';

const DAY_LABEL = new Intl.DateTimeFormat('pl-PL', { weekday: 'long', day: 'numeric', month: 'long' });

function Tile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="min-w-32 flex-1 rounded-lg border bg-card px-3 py-2">
      <div className="font-mono text-2xl tabular-nums">{value}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

function Summary({ j }: { j: JournalDay }) {
  const sections = summarySections(j.journal?.summary_md ?? null);
  if (!sections.length)
    return (
      <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
        Podsumowanie dnia powstaje o 21:30 (lokalny model w Ollamie na Macu).
      </p>
    );
  return (
    <div className="grid gap-3 rounded-lg border bg-card p-3 md:grid-cols-2">
      {sections.map((s) => (
        <section key={s.title}>
          <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{s.title}</h3>
          <ul className="space-y-1 text-sm">
            {s.lines.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </section>
      ))}
      <p className="font-mono text-[11px] text-muted-foreground md:col-span-2">{j.journal?.model}</p>
    </div>
  );
}

export function JournalView() {
  const [day, setDay] = useState(today);
  const [selected, setSelected] = useState<string | null>(null);
  const q = useQuery({ queryKey: ['journal', day], queryFn: () => fetchJournal(day), refetchInterval: 60_000 });
  const j = q.data;
  const dayLanes = useMemo(() => lanes(j?.claude.sessions ?? [], day), [j, day]);
  const hourly = (key: 'cpu' | 'gpu') => j?.hours.map((h) => (h.samples ? (h[key] ?? 0) : null)) ?? [];
  const net = j?.hours.map((h) => (h.samples ? (h.rx_mb ?? 0) + (h.tx_mb ?? 0) : null)) ?? [];
  const isToday = day === today();
  const goTo = (d: string) => {
    setDay(d);
    setSelected(null);
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 px-4 py-3">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon" onClick={() => goTo(shiftDay(day, -1))} aria-label="Poprzedni dzień">
          <ChevronLeft />
        </Button>
        <h2 className="min-w-56 text-center text-sm font-medium">{DAY_LABEL.format(new Date(`${day}T12:00:00Z`))}</h2>
        <Button
          variant="ghost"
          size="icon"
          disabled={isToday}
          onClick={() => goTo(shiftDay(day, 1))}
          aria-label="Następny dzień"
        >
          <ChevronRight />
        </Button>
        {!isToday && (
          <Button variant="outline" size="sm" onClick={() => goTo(today())}>
            dziś
          </Button>
        )}
      </div>
      {q.error && <p className="text-sm text-bad">Nie udało się pobrać dziennika: {String(q.error)}</p>}
      {!j && !q.error && <p className="text-sm text-muted-foreground">Ładuję dzień…</p>}
      {j && (
        <>
          <div className="flex flex-wrap gap-3">
            <Tile label="aktywnie z Claude (Mac)" value={fmtMin(j.claude.totals.active_min)} />
            <Tile label="sesje / prompty" value={`${j.claude.totals.sessions} / ${j.claude.totals.prompts}`} />
            <Tile label="PR-y (wszystkie hosty)" value={j.claude.prs.length} />
            <Tile label="błędy narzędzi" value={j.claude.totals.errors} />
            <Tile label="Mac nie spał" value={fmtMin(j.awake_min)} />
          </div>
          <Summary j={j} />
          <SessionLanes lanes={dayLanes} day={day} selected={selected} onSelect={setSelected} />
          <div className="rounded-lg border bg-card">
            <SessionTable sessions={j.claude.sessions} day={day} selected={selected} onSelect={setSelected} />
          </div>
          <div className="flex flex-col gap-3 md:flex-row">
            <HourChart title="CPU (średnio, %)" values={hourly('cpu')} max={100} format={(v) => `${v.toFixed(0)}%`} />
            <HourChart title="GPU (średnio, %)" values={hourly('gpu')} max={100} format={(v) => `${v.toFixed(0)}%`} />
            <HourChart title="Sieć (MB)" values={net} format={(v) => `${v.toFixed(0)} MB`} />
          </div>
          <ProcessPanel day={j} />
        </>
      )}
    </div>
  );
}
