// One measure across the day's 24 hours as thin bars (single series → no
// legend; the title names it). Hovering an hour column shows its value; hours
// with no samples (Mac asleep) stay empty and say so.

import { useState } from 'react';

interface Props {
  title: string;
  values: (number | null)[];
  format: (v: number) => string;
  max?: number;
}

const W = 480;
const H = 72;
const COL = W / 24;
const BAR = COL - 4;

/** Bar with 2px-rounded top, square at the baseline. */
function barPath(x: number, y: number, h: number): string {
  const r = Math.min(2, h);
  return `M${x},${H} V${y + r} Q${x},${y} ${x + r},${y} H${x + BAR - r} Q${x + BAR},${y} ${x + BAR},${y + r} V${H} Z`;
}

export function HourChart({ title, values, format, max }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const top = max ?? Math.max(1, ...values.map((v) => v ?? 0));
  const hv = hover === null ? undefined : values[hover];
  return (
    <figure className="min-w-0 flex-1 rounded-lg border bg-card p-3">
      <figcaption className="mb-2 flex items-baseline justify-between text-xs">
        <span className="font-medium text-foreground">{title}</span>
        <span className="font-mono text-muted-foreground">
          {hover === null
            ? `max ${format(Math.max(0, ...values.map((v) => v ?? 0)))}`
            : `${String(hover).padStart(2, '0')}:00 · ${hv == null ? 'uśpiony' : format(hv)}`}
        </span>
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H + 14}`}
        className="block h-auto w-full"
        role="img"
        aria-label={title}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          setHover(Math.min(23, Math.max(0, Math.floor(((e.clientX - r.left) / r.width) * 24))));
        }}
      >
        <line x1={0} x2={W} y1={H + 0.5} y2={H + 0.5} className="stroke-border" />
        {values.map((v, i) => {
          const h = v ? Math.max(1, (v / top) * (H - 4)) : 0;
          const x = i * COL + 2;
          return (
            // biome-ignore lint/suspicious/noArrayIndexKey: the index is the hour
            <g key={i}>
              <title>{`${String(i).padStart(2, '0')}:00 · ${v == null ? 'uśpiony' : format(v)}`}</title>
              <rect x={i * COL} y={0} width={COL} height={H} className="fill-transparent" />
              {h > 0 && <path d={barPath(x, H - h, h)} className={hover === i ? 'fill-foreground' : 'fill-primary'} />}
            </g>
          );
        })}
        {[0, 6, 12, 18].map((hr) => (
          <text key={hr} x={hr * COL + 2} y={H + 12} className="fill-muted-foreground font-mono text-[9px]">
            {String(hr).padStart(2, '0')}
          </text>
        ))}
      </svg>
    </figure>
  );
}
