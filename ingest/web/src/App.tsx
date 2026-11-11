// Mapa — the planner vault's project map as views: ecosystem (UML-component
// style), infrastructure (UML-deployment style) and the pressure queue.
// The vault is the source of truth; nothing here edits it.

import { useQuery } from '@tanstack/react-query';
import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { GraphCanvas } from '@/components/GraphCanvas';
import { NodeSheet } from '@/components/NodeSheet';
import { PressureTable } from '@/components/PressureTable';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { fetchMap, fetchPressure } from '@/lib/api';
import { ecosystemSpec, impactOf, infraSpec, visibleIds } from '@/lib/graph';

// bpmn-js (~600 kB) loads only when the Procesy tab is opened.
const ProcessesView = lazy(() => import('@/components/ProcessesView').then((m) => ({ default: m.ProcessesView })));

const VIEWS = [
  { id: 'ekosystem', label: 'Ekosystem' },
  { id: 'infrastruktura', label: 'Infrastruktura' },
  { id: 'procesy', label: 'Procesy' },
  { id: 'presja', label: 'Presja' },
] as const;
type View = (typeof VIEWS)[number]['id'];

const readView = (): View => VIEWS.find((v) => `#${v.id}` === window.location.hash)?.id ?? 'ekosystem';

export function App() {
  const [view, setView] = useState<View>(readView);
  const [showQuiet, setShowQuiet] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [processSlug, setProcessSlug] = useState<string | null>(null);
  const mapQ = useQuery({ queryKey: ['map'], queryFn: fetchMap, refetchInterval: 60_000 });
  const pressureQ = useQuery({ queryKey: ['pressure'], queryFn: fetchPressure, refetchInterval: 60_000 });
  const map = mapQ.data;

  useEffect(() => window.history.replaceState(null, '', `#${view}`), [view]);

  const spec = useMemo(() => {
    if (!map || view === 'presja' || view === 'procesy') return null;
    return view === 'infrastruktura' ? infraSpec(map, showQuiet) : ecosystemSpec(map, showQuiet);
  }, [map, view, showQuiet]);
  const highlight = useMemo(() => (map && selected ? impactOf(map, selected) : null), [map, selected]);
  const rows = useMemo(
    () => (pressureQ.data?.projects ?? []).filter((r) => showQuiet || r.status !== 'dormant'),
    [pressureQ.data, showQuiet],
  );
  const counts = map && {
    shown: visibleIds(map, showQuiet).size,
    processes: map.processes.length,
  };
  const error = mapQ.error ?? pressureQ.error;

  return (
    <div className="flex h-dvh flex-col bg-background font-sans text-foreground">
      <header className="flex h-12 shrink-0 items-center gap-4 border-b px-4">
        <a href="/" className="font-mono text-sm text-muted-foreground hover:text-foreground" title="Wróć do konsoli">
          ← home-ops
        </a>
        <h1 className="font-mono text-sm font-semibold">Mapa</h1>
        <Tabs value={view} onValueChange={(v) => setView(v as View)}>
          <TabsList>
            {VIEWS.map((v) => (
              <TabsTrigger key={v.id} value={v.id}>
                {v.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          <Switch id="show-quiet" checked={showQuiet} onCheckedChange={setShowQuiet} />
          <label htmlFor="show-quiet" className="cursor-pointer">
            uśpione i archiwalne
          </label>
        </div>
        {counts && (
          <span className="hidden font-mono text-xs text-muted-foreground md:inline">
            {counts.shown} węzłów · {counts.processes} procesów
          </span>
        )}
      </header>
      <main className="relative min-h-0 flex-1">
        {error && <div className="p-6 text-sm text-bad">Nie udało się pobrać danych: {String(error)}</div>}
        {!error && !map && <div className="p-6 text-sm text-muted-foreground">Ładuję mapę…</div>}
        {spec && <GraphCanvas spec={spec} selected={selected} highlight={highlight} onSelect={setSelected} />}
        {map && view === 'procesy' && (
          <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Ładuję edytor BPMN…</div>}>
            <ProcessesView map={map} slug={processSlug} onOpen={setProcessSlug} onSelect={setSelected} />
          </Suspense>
        )}
        {view === 'presja' && (
          <div className="h-full overflow-auto px-4 py-3">
            <p className="mb-3 max-w-3xl text-xs text-muted-foreground">
              Podpowiedź do kolejki, nie decyzja: wynik = baza (zadania wg klas §8, pain points, luki z blueprintów,
              issues, błędy / CI / deploy) × blast (ilu zależy) × waga statusu. Decyduje QUEUE.md.
            </p>
            <PressureTable rows={rows} selected={selected} onSelect={setSelected} />
          </div>
        )}
      </main>
      {map && (
        <NodeSheet
          map={map}
          pressure={pressureQ.data?.projects ?? []}
          selected={selected}
          onSelect={setSelected}
          onOpenProcess={(slug) => {
            setProcessSlug(slug);
            setView('procesy');
          }}
        />
      )}
    </div>
  );
}
