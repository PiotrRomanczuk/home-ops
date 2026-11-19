import { Panel } from '@xyflow/react';
import { STATUS_DOT } from './status';

/** Map key, pinned to the canvas corner. */
export function Legend() {
  return (
    <Panel
      position="top-left"
      className="space-y-1.5 rounded-md border bg-card/90 px-3 py-2 font-mono text-[11px] text-muted-foreground"
    >
      <div className="flex items-center gap-3">
        {Object.entries(STATUS_DOT).map(([status, dot]) => (
          <span key={status} className="flex items-center gap-1">
            <span className={`inline-block size-2 rounded-full ${dot}`} />
            {status}
          </span>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1">
          <span className="inline-block h-0.5 w-5 bg-warn" /> zależy od
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-0.5 w-5 border-t-2 border-dashed border-warm" /> zasila
        </span>
        <span className="text-warn">⚠ n</span> = ilu padnie razem z nim
      </div>
    </Panel>
  );
}
