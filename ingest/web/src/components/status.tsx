// Small shared visuals: status colours (same as the console's --p-* tokens)
// and the pressure badge used on map nodes, the table and the side sheet.

import { cn } from '@/lib/utils';

export const STATUS_BORDER: Record<string, string> = {
  hot: 'border-l-hot',
  warm: 'border-l-warm',
  stalled: 'border-l-stalled',
  dormant: 'border-l-dormant',
};

export const STATUS_DOT: Record<string, string> = {
  hot: 'bg-hot',
  warm: 'bg-warm',
  stalled: 'bg-stalled',
  dormant: 'bg-dormant',
};

export function StatusDot({ status, className }: { status: string | null; className?: string }) {
  return (
    <span
      className={cn('inline-block size-2 shrink-0 rounded-full', STATUS_DOT[status ?? 'dormant'], className)}
      title={status ?? 'brak statusu'}
    />
  );
}

/** ≥ 50 red, ≥ 15 amber, > 0 muted, 0 / null → nothing. */
export function PressureBadge({ value, className }: { value: number | null; className?: string }) {
  if (!value) return null;
  const tone =
    value >= 50 ? 'bg-bad/20 text-bad' : value >= 15 ? 'bg-warn/20 text-warn' : 'bg-muted text-muted-foreground';
  return (
    <span
      className={cn('rounded px-1.5 py-px font-mono text-[11px] font-semibold tabular-nums', tone, className)}
      title="Presja (wynik z /api/pressure)"
    >
      {value}
    </span>
  );
}
