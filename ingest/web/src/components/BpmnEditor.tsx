// BPMN 2.0 editor (bpmn-js Modeler) for one vault process. Lanes get a badge
// with the project's status / health / pressure; clicking it opens the same
// side sheet as the map. Saving queues a write that planner-sync commits.

import 'bpmn-js/dist/assets/diagram-js.css';
import 'bpmn-js/dist/assets/bpmn-js.css';
import 'bpmn-js/dist/assets/bpmn-font/css/bpmn-embedded.css';
import Modeler from 'bpmn-js/lib/Modeler';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import type { MapNode, ProcessDetail } from '@/lib/api';
import { laneBadge, SAVE_MESSAGE } from '@/lib/bpmn';
import { useProcessSave } from '@/lib/useProcessSave';
import { cn } from '@/lib/utils';
import { STATUS_DOT } from './status';

interface Lane {
  type: string;
  businessObject: { name?: string };
}
interface Overlays {
  add(el: Lane, type: string, o: { position: { top: number; left: number }; html: HTMLElement }): string;
  clear(): void;
}
interface ElementRegistry {
  filter(fn: (e: Lane) => boolean): Lane[];
}
interface Canvas {
  zoom(mode: 'fit-viewport'): void;
  scroll(delta: { dx: number; dy: number }): void;
}

/** Fit, then move right so the tool palette doesn't cover the lane labels. */
const PALETTE_GAP = 64;

interface Props {
  process: ProcessDetail;
  nodes: Map<string, MapNode>;
  onSelect: (id: string) => void;
  /** Refetch the process (and map) from the API — after a save or to resolve a conflict. */
  onRefresh: () => void;
}

function span(className: string, text: string): HTMLSpanElement {
  const el = document.createElement('span');
  el.className = className;
  el.textContent = text;
  return el;
}

function badgeElement(name: string, nodes: Map<string, MapNode>, onSelect: (id: string) => void): HTMLElement {
  const b = laneBadge(name, nodes);
  const el = document.createElement('button');
  el.type = 'button';
  el.className = cn(
    'flex items-center gap-1 rounded border bg-white px-1.5 py-0.5 font-mono text-[11px] text-neutral-700 shadow-sm',
    b.nodeId ? 'cursor-pointer hover:border-neutral-500' : 'cursor-default border-dashed text-neutral-400',
  );
  el.title = b.nodeId ? `${b.nodeId}: kliknij, by zobaczyć szczegóły` : `${name}: brak takiego węzła w vaulcie`;
  if (b.status) el.append(span(cn('inline-block size-2 rounded-full', STATUS_DOT[b.status] ?? 'bg-dormant'), ''));
  el.append(span('', b.label));
  if (b.health) el.append(span('', b.health));
  if (b.pressure) el.append(span(b.pressure >= 50 ? 'font-bold text-bad' : 'font-bold', String(b.pressure)));
  if (b.breaks) el.append(span('text-warn', `⚠${b.breaks}`));
  if (b.nodeId) el.onclick = () => onSelect(b.nodeId as string);
  return el;
}

export function BpmnEditor({ process, nodes, onSelect, onRefresh }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const modeler = useRef<Modeler | null>(null);
  const [isDirty, setDirty] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [imported, setImported] = useState(0);
  const { state, save, reset } = useProcessSave(process.slug, onRefresh);

  useEffect(() => {
    const m = new Modeler({ container: container.current as HTMLDivElement });
    m.on('commandStack.changed', () => setDirty(true));
    modeler.current = m;
    return () => m.destroy();
  }, []);

  const decorate = useCallback(() => {
    const m = modeler.current;
    if (!m) return;
    const overlays = m.get<Overlays>('overlays');
    overlays.clear();
    for (const lane of m.get<ElementRegistry>('elementRegistry').filter((e) => e.type === 'bpmn:Lane'))
      overlays.add(lane, 'mapa', {
        position: { top: 6, left: 38 }, // just right of the lane's name strip
        html: badgeElement(lane.businessObject.name ?? '', nodes, onSelect),
      });
  }, [nodes, onSelect]);

  // Import only when the vault copy changes — a map refresh must not wipe edits.
  useEffect(() => {
    const m = modeler.current;
    if (!m || !process.bpmn_xml) return;
    setImportError(null);
    m.importXML(process.bpmn_xml)
      .then(() => {
        const canvas = m.get<Canvas>('canvas');
        canvas.zoom('fit-viewport');
        canvas.scroll({ dx: PALETTE_GAP, dy: 0 });
        setDirty(false);
        reset();
        setImported((n) => n + 1);
      })
      .catch((e: Error) => setImportError(e.message));
  }, [process.bpmn_xml, reset]);

  useEffect(() => {
    if (imported) decorate();
  }, [imported, decorate]);

  const onSave = async () => {
    const m = modeler.current;
    if (!m || !process.bpmn_hash) return;
    const { xml } = await m.saveXML({ format: true });
    if (xml) await save(xml, process.bpmn_hash);
  };

  const canSave = isDirty && !!process.bpmn_hash && state.kind !== 'sending' && state.kind !== 'queued';
  const message =
    state.kind === 'idle' || state.kind === 'sending'
      ? null
      : `${state.kind === 'error' ? 'Błąd zapisu.' : SAVE_MESSAGE[state.kind]}${state.error ? ` (${state.error})` : ''}`;

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="flex items-center gap-3">
        <Button size="sm" disabled={!canSave} onClick={onSave}>
          {state.kind === 'sending' ? 'Wysyłam…' : 'Zapisz do vaulta'}
        </Button>
        {isDirty && state.kind === 'idle' && <span className="text-xs text-warn">niezapisane zmiany</span>}
        {state.kind === 'conflict' && (
          <Button size="sm" variant="outline" onClick={onRefresh}>
            Wczytaj z vaulta
          </Button>
        )}
        {message && (
          <span
            className={cn(
              'text-xs',
              state.kind === 'applied' ? 'text-good' : state.kind === 'queued' ? 'text-muted-foreground' : 'text-bad',
            )}
          >
            {message}
          </span>
        )}
      </div>
      {!process.bpmn_xml && <p className="text-sm text-bad">Brak pliku diagramu w vaulcie ({process.path}).</p>}
      {importError && <p className="text-sm text-bad">Nie udało się wczytać diagramu: {importError}</p>}
      <div ref={container} className="min-h-0 flex-1 rounded-md border bg-white" />
    </div>
  );
}
