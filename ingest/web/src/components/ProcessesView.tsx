// "Procesy" — BPMN process notes from the vault (2-Obszary/mapy/procesy):
// a list on the left, the selected diagram in the bpmn-js editor on the right.

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle } from 'lucide-react';
import { useCallback, useMemo } from 'react';
import { fetchProcess, type MapResponse } from '@/lib/api';
import { cn } from '@/lib/utils';
import { BpmnEditor } from './BpmnEditor';

interface Props {
  map: MapResponse;
  slug: string | null;
  onOpen: (slug: string) => void;
  onSelect: (id: string) => void;
}

export function ProcessesView({ map, slug, onOpen, onSelect }: Props) {
  const current = slug ?? map.processes[0]?.slug ?? null;
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ['process', current],
    queryFn: () => fetchProcess(current as string),
    enabled: !!current,
  });
  const nodes = useMemo(() => new Map(map.nodes.map((n) => [n.id, n])), [map.nodes]);
  const onRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['process', current] });
    queryClient.invalidateQueries({ queryKey: ['map'] });
  }, [queryClient, current]);

  if (!map.processes.length)
    return (
      <p className="p-6 text-sm text-muted-foreground">
        Brak procesów. Dodaj notatkę <code>type: process</code> z plikiem <code>.bpmn</code> w
        <code> 2-Obszary/mapy/procesy/</code>.
      </p>
    );

  const p = detail.data;
  return (
    <div className="flex h-full min-h-0">
      <nav className="w-60 shrink-0 space-y-1 overflow-y-auto border-r p-3">
        {map.processes.map((proc) => (
          <button
            key={proc.slug}
            type="button"
            onClick={() => onOpen(proc.slug)}
            className={cn(
              'w-full rounded-md px-2.5 py-2 text-left text-sm hover:bg-muted',
              proc.slug === current && 'bg-muted text-foreground',
            )}
          >
            <div className="flex items-center gap-1.5">
              <span className="truncate">{proc.title}</span>
              {proc.warnings.length > 0 && <AlertTriangle className="ml-auto size-3.5 shrink-0 text-warn" />}
            </div>
            <div className="font-mono text-[11px] text-muted-foreground">{proc.lanes.length} torów</div>
          </button>
        ))}
      </nav>
      <section className="flex min-w-0 flex-1 flex-col gap-2 p-3">
        {detail.isLoading && <p className="text-sm text-muted-foreground">Wczytuję diagram…</p>}
        {detail.error && <p className="text-sm text-bad">{String(detail.error)}</p>}
        {p && (
          <>
            <header className="space-y-1">
              <h2 className="font-mono text-sm font-semibold">{p.title}</h2>
              <p className="text-xs text-muted-foreground">
                {[p.summary, p.trigger && `wyzwalacz: ${p.trigger}`, p.schedule].filter(Boolean).join(' · ')}
              </p>
              {p.warnings.map((w) => (
                <p key={w} className="flex items-center gap-1.5 text-xs text-warn">
                  <AlertTriangle className="size-3.5" /> {w}
                </p>
              ))}
            </header>
            <BpmnEditor process={p} nodes={nodes} onSelect={onSelect} onRefresh={onRefresh} />
          </>
        )}
      </section>
    </div>
  );
}
