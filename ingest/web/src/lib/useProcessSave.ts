// Save = queue a write (POST), then poll until planner-sync has written the
// file into the vault (applied) or refused it (conflict / failed).

import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchWrite, saveProcess, type WriteStatus } from './api';

export type SaveState =
  | { kind: 'idle' }
  | { kind: 'sending' }
  | { kind: WriteStatus; error: string | null }
  | { kind: 'error'; error: string };

const POLL_MS = 3000;
const POLL_LIMIT = 60; // ~3 min — planner-sync ticks every 60 s

export function useProcessSave(slug: string, onApplied: () => void) {
  const [state, setState] = useState<SaveState>({ kind: 'idle' });
  const timer = useRef<number | null>(null);

  const stop = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  }, []);
  useEffect(() => {
    if (slug) setState({ kind: 'idle' });
    return stop;
  }, [slug, stop]);

  const save = useCallback(
    async (xml: string, baseHash: string) => {
      stop();
      setState({ kind: 'sending' });
      try {
        const write = await saveProcess(slug, xml, baseHash);
        setState({ kind: 'queued', error: null });
        let polls = 0;
        const poll = async () => {
          const w = await fetchWrite(slug, write.id).catch(() => null);
          if (w && w.status !== 'queued') {
            setState({ kind: w.status, error: w.error });
            if (w.status === 'applied') onApplied();
            return;
          }
          if (++polls < POLL_LIMIT) timer.current = window.setTimeout(poll, POLL_MS);
        };
        timer.current = window.setTimeout(poll, POLL_MS);
      } catch (e) {
        setState({ kind: 'error', error: e instanceof Error ? e.message : String(e) });
      }
    },
    [slug, onApplied, stop],
  );

  const reset = useCallback(() => {
    stop();
    setState({ kind: 'idle' });
  }, [stop]);

  return { state, save, reset };
}
