// Side sheet for whatever is selected on the map or in the pressure table:
// facts from the vault, relations, "if it goes down", pressure breakdown.

import { Badge } from '@/components/ui/badge';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import type { MapResponse, PressureRow } from '@/lib/api';
import { impactOf, relationsOf } from '@/lib/graph';
import { PressureBreakdown } from './PressureBreakdown';
import { PressureBadge, StatusDot } from './status';

interface Props {
  map: MapResponse;
  pressure: PressureRow[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  onOpenProcess: (slug: string) => void;
}

function Chips({ title, ids, onSelect }: { title: string; ids: string[]; onSelect: (id: string) => void }) {
  if (!ids.length) return null;
  return (
    <section className="space-y-1.5">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
      <div className="flex flex-wrap gap-1.5">
        {ids.map((id) => (
          <button key={id} type="button" onClick={() => onSelect(id)}>
            <Badge variant="outline" className="cursor-pointer font-mono hover:bg-muted">
              {id}
            </Badge>
          </button>
        ))}
      </div>
    </section>
  );
}

export function NodeSheet({ map, pressure, selected, onSelect, onOpenProcess }: Props) {
  const node = map.nodes.find((n) => n.id === selected);
  const isHost = !!selected?.startsWith('host:');
  const row = pressure.find((p) => p.slug.toLowerCase() === selected);
  const rel = selected ? relationsOf(map, selected) : null;
  const impact = selected ? [...impactOf(map, selected)].filter((id) => id !== selected) : [];
  const breaks = isHost ? impact : (node?.dependents ?? []);
  const processes = map.processes.filter((p) => selected && p.lanes.includes(selected));
  const title = node?.label ?? selected?.replace(/^(host|group):/, '') ?? '';

  return (
    <Sheet
      modal={false}
      open={!!selected && !selected.startsWith('group:')}
      onOpenChange={(open) => !open && onSelect(null)}
    >
      <SheetContent
        showOverlay={false}
        // clicks on the map change the selection instead of closing the panel
        onInteractOutside={(e) => e.preventDefault()}
        className="w-full overflow-y-auto sm:max-w-md"
      >
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2 font-mono">
            {node?.kind === 'project' && <StatusDot status={node.status} />}
            {title}
            <span>{node?.health}</span>
          </SheetTitle>
          <SheetDescription>
            {isHost ? 'Host' : node?.kind === 'external' ? 'Usługa zewnętrzna (bez notatki w vaulcie)' : node?.summary}
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-5 px-4 pb-6">
          {node?.kind === 'project' && (
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant="secondary">{node.status ?? 'brak statusu'}</Badge>
              {node.verdict && <Badge variant="secondary">{node.verdict}</Badge>}
              {node.stream && <Badge variant="secondary">{node.stream}</Badge>}
              {node.hosts.map((h) => (
                <Badge key={h} variant="outline" className="font-mono">
                  {h}
                </Badge>
              ))}
              <PressureBadge value={node.pressure} />
            </div>
          )}
          <Chips title="Jeśli padnie — przestaje działać" ids={breaks} onSelect={onSelect} />
          {rel && <Chips title="Zależy od" ids={rel.dependsOn} onSelect={onSelect} />}
          {rel && <Chips title="Zasila" ids={rel.feeds} onSelect={onSelect} />}
          {rel && <Chips title="Dostaje dane od" ids={rel.fedBy} onSelect={onSelect} />}
          {processes.length > 0 && (
            <section className="space-y-1.5">
              <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Procesy (BPMN)</h3>
              <ul className="space-y-0.5 text-sm">
                {processes.map((p) => (
                  <li key={p.slug}>
                    <button
                      type="button"
                      className="text-primary underline-offset-4 hover:underline"
                      onClick={() => onOpenProcess(p.slug)}
                    >
                      {p.title}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {row && (
            <section className="space-y-1.5">
              <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Presja</h3>
              <PressureBreakdown row={row} />
            </section>
          )}
          {node?.kind === 'project' && (
            <a
              className="inline-block text-sm text-primary underline-offset-4 hover:underline"
              href={`obsidian://open?vault=MainCV-Planner&file=${encodeURIComponent(node.id)}`}
            >
              Otwórz notatkę w Obsidianie →
            </a>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
