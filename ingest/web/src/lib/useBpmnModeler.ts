// The bpmn-js Modeler for one process, plus the bookkeeping that keeps editor
// and vault in step: which vault version the editor derives from (`base`, sent
// as base_hash on save), whether there are unsaved edits, and what to do when a
// new vault copy arrives (see decideImport).

import Modeler from 'bpmn-js/lib/Modeler';
import { type RefObject, useCallback, useEffect, useRef, useState } from 'react';
import { decideImport, sha256Hex } from './bpmnSync';

interface Canvas {
  zoom(mode: 'fit-viewport'): void;
  scroll(delta: { dx: number; dy: number }): void;
}

/** Fit, then move right so the tool palette doesn't cover the lane labels. */
const PALETTE_GAP = 64;

interface Copy {
  xml: string;
  hash: string;
}

export function useBpmnModeler(
  container: RefObject<HTMLDivElement | null>,
  copy: { xml: string | null; hash: string | null },
  onLoaded: () => void,
) {
  const modeler = useRef<Modeler | null>(null);
  const base = useRef<string | null>(null);
  const seen = useRef<string | null>(null);
  const dirtyRef = useRef(false);
  const edits = useRef(0);
  const wantReload = useRef(false);
  const [isDirty, setIsDirty] = useState(false);
  const [pending, setPending] = useState<Copy | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [imported, setImported] = useState(0);

  const markDirty = useCallback((value: boolean) => {
    dirtyRef.current = value;
    setIsDirty(value);
  }, []);

  useEffect(() => {
    const m = new Modeler({ container: container.current as HTMLDivElement });
    m.on('commandStack.changed', () => {
      edits.current += 1;
      markDirty(true);
    });
    modeler.current = m;
    return () => {
      m.destroy();
      modeler.current = null;
      seen.current = null;
      base.current = null;
    };
  }, [container, markDirty]);

  const load = useCallback(
    (c: Copy) => {
      const m = modeler.current;
      if (!m) return;
      setImportError(null);
      m.importXML(c.xml)
        .then(() => {
          const canvas = m.get<Canvas>('canvas');
          canvas.zoom('fit-viewport');
          canvas.scroll({ dx: PALETTE_GAP, dy: 0 });
          base.current = c.hash;
          wantReload.current = false;
          setPending(null);
          markDirty(false);
          onLoaded();
          setImported((n) => n + 1);
        })
        .catch((e: Error) => setImportError(e.message));
    },
    [markDirty, onLoaded],
  );

  // A vault copy arrived (first load, Obsidian edit, our own save coming back).
  useEffect(() => {
    if (!modeler.current || !copy.xml || !copy.hash) return;
    const c = { xml: copy.xml, hash: copy.hash };
    const action = decideImport({
      incoming: c.hash,
      seen: seen.current,
      base: base.current,
      isDirty: dirtyRef.current,
    });
    seen.current = c.hash;
    if (action === 'import' || (action === 'ask' && wantReload.current)) load(c);
    else if (action === 'ask') setPending(c);
  }, [copy.xml, copy.hash, load]);

  /** Drop unsaved edits for the vault copy: the one we are holding back, or the next one to arrive. */
  const reload = useCallback(
    (refetch: () => void) => {
      if (pending) return load(pending);
      wantReload.current = true;
      refetch();
    },
    [pending, load],
  );

  /** Our save reached the vault: it is now the base. Edits made while it was queued stay unsaved. */
  const markSaved = useCallback(
    async (xml: string, editsAtSave: number) => {
      base.current = await sha256Hex(xml);
      if (edits.current === editsAtSave) markDirty(false);
    },
    [markDirty],
  );

  return {
    modeler,
    isDirty,
    pending,
    importError,
    imported,
    reload,
    markSaved,
    snapshot: () => ({ baseHash: base.current, edits: edits.current }),
  };
}
