// Claude sessions on the day's clock: one lane per project, one bar per
// session (first → last event), coloured by host — the Mac is the human's own
// work, elitedesk runs the headless agents. Legend + lane labels carry
// identity; hovering a bar names the session, clicking selects it.

import { useState } from 'react';
import { clock, fmtMin, type JournalSession, type Lane } from '@/lib/journal';
import { cn } from '@/lib/utils';

interface Props {
  lanes: Lane[];
  selected: string | null;
  onSelect: (sessionId: string) => void;
}

const W = 960;
const ROW = 22;
const BAR = 12;
const x = (min: number) => (min / 1440) * W;
const HOST_FILL: Record<string, string> = { mac: 'fill-host-mac', elitedesk: 'fill-host-elitedesk' };

function Legend() {
  return (
    <div className="flex gap-4 text-xs text-muted-foreground">
      {[
        ['bg-host-mac', 'Mac (Ty)'],
        ['bg-host-elitedesk', 'uwh (agenty nocne)'],
      ].map(([cls, label]) => (
        <span key={label} className="flex items-center gap-1.5">
          <span className={cn('inline-block size-2.5 rounded-sm', cls)} />
          {label}
        </span>
      ))}
    </div>
  );
}

export function SessionLanes({ lanes, selected, onSelect }: Props) {
  const [hover, setHover] = useState<JournalSession | null>(null);
  if (!lanes.length) return <p className="text-sm text-muted-foreground">Tego dnia nie było sesji Claude.</p>;
  const height = lanes.length * ROW + 16;
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-medium">Sesje Claude w ciągu dnia</h3>
        <Legend />
      </div>
      <div className="flex gap-3">
        <ul className="w-56 shrink-0 font-mono text-xs">
          {lanes.map((l) => (
            <li key={l.project} className="flex h-[22px] items-center justify-between gap-2">
              <span className="truncate text-foreground" title={l.project}>
                {l.project}
              </span>
              <span className="shrink-0 whitespace-nowrap text-muted-foreground">{fmtMin(l.activeMin)}</span>
            </li>
          ))}
        </ul>
        <svg viewBox={`0 0 ${W} ${height}`} className="block h-auto min-w-0 flex-1" role="img" aria-label="Oś dnia">
          {[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => (
            <g key={h}>
              <line x1={x(h * 60)} x2={x(h * 60)} y1={0} y2={height - 14} className="stroke-border/60" />
              <text x={x(h * 60) + 2} y={height - 3} className="fill-muted-foreground font-mono text-[10px]">
                {String(h).padStart(2, '0')}
              </text>
            </g>
          ))}
          {lanes.map((l, row) =>
            l.segments.map(({ session: s, from, to }) => (
              // biome-ignore lint/a11y/useSemanticElements: an SVG bar can't be a <button>; role + keys make it one
              <rect
                key={`${s.host}:${s.session_id}`}
                x={x(from)}
                y={row * ROW + (ROW - BAR) / 2}
                width={Math.max(3, x(to) - x(from))}
                height={BAR}
                rx={2}
                className={cn(
                  'cursor-pointer stroke-card stroke-2',
                  HOST_FILL[s.host] ?? 'fill-muted-foreground',
                  selected && selected !== s.session_id && 'opacity-40',
                )}
                role="button"
                tabIndex={0}
                aria-label={`${s.title ?? s.session_id.slice(0, 8)} (${s.host})`}
                onMouseEnter={() => setHover(s)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(s)}
                onBlur={() => setHover(null)}
                onClick={() => onSelect(s.session_id)}
                onKeyDown={(e) => {
                  if (e.key !== 'Enter' && e.key !== ' ') return;
                  e.preventDefault();
                  onSelect(s.session_id);
                }}
              />
            )),
          )}
        </svg>
      </div>
      <p className="mt-1 h-4 truncate font-mono text-xs text-muted-foreground">
        {hover &&
          `${clock(hover.first_ts)}–${clock(hover.last_ts)} · ${hover.title ?? hover.session_id.slice(0, 8)} · ${hover.host} · ${hover.prompts_day} promptów · ${fmtMin(hover.active_min)}`}
      </p>
    </div>
  );
}
